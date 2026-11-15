#!/usr/bin/env python3
"""Engine-level formula recognition benchmark on IM2LATEX-100K.

Unlike scripts/bench_formula.py (which locates formulas on real arXiv PDFs),
this one feeds *clean, ground-truthed formula images* directly to a formula
engine — measuring the engine itself, with zero localization error.

Data sources:
- Primary: HuggingFace mirror yuntian-deng/im2latex-100k, test split parquet
  (downloaded via hf-mirror.com to data/bench_im2latex/test.parquet).
  6,810 rows (the subset of the original 10,355 whose rendering succeeded),
  columns: formula (tokenized LaTeX), filename, image {bytes,path}.
- Original: Zenodo record 56198 (arXiv:1609.04938), harvardnlp im2latex-100k.

im2latex renders each formula alone on an A4 page; images are cropped to the
ink bounding box before recognition, matching what the workbench does with
PDF formula regions.

Usage::

    python scripts/bench_im2latex.py --engine pix2tex --limit 150
    python scripts/bench_im2latex.py --engine texify   --limit 150 --json out.json
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DATA = ROOT / "data" / "bench_im2latex"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402

from bench_formula import score_pair  # noqa: E402  (shared normalization / scoring)


def crop_white(img: np.ndarray, pad: int = 16) -> np.ndarray:
    """im2latex renders formulas on A4 pages; trim the blank margins."""
    gray = img.mean(axis=2)
    mask = gray < 245
    if not mask.any():
        return img
    ys, xs = np.where(mask)
    y0, y1 = max(0, int(ys.min()) - pad), min(img.shape[0], int(ys.max()) + pad)
    x0, x1 = max(0, int(xs.min()) - pad), min(img.shape[1], int(xs.max()) + pad)
    return img[y0:y1, x0:x1]


class Pix2TexEngine:
    """The project's current engine: pix2tex ONNX (rapid-latex-ocr)."""

    def __init__(self):
        import local_recognize as LR
        self._eng = LR.latex_engine()
        self.name = "pix2tex"

    def __call__(self, img: np.ndarray) -> str:
        import page_layout as PL
        latex, _ = self._eng(img)
        return PL._tidy_latex(str(latex).strip())


class TexifyEngine:
    """VikP/texify (312M, donut-swin encoder + mBART decoder), CPU float32.

    The repo ships a custom `VariableDonutImageProcessor` that transformers 5.x
    cannot auto-load, so preprocessing is inlined here, replicating its config:
    fit the image within 420x420 keeping aspect ratio (white canvas), then
    normalize with ImageNet mean/std.
    """

    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    MAX_SIZE = 420

    def __init__(self, device: str = "cpu"):
        import torch
        from transformers import AutoTokenizer, VisionEncoderDecoderModel
        self.name = "texify"
        self.torch = torch
        self.device = device
        self.model = VisionEncoderDecoderModel.from_pretrained(
            str(ROOT / "backend" / "models" / "texify"), torch_dtype=torch.float32)
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(ROOT / "backend" / "models" / "texify"))
        self.model.eval().to(device)
        self._start = self.model.config.decoder_start_token_id
        self._unk = self.tokenizer.unk_token_id

    def _prepare(self, img: np.ndarray):
        from PIL import Image
        h, w = img.shape[:2]
        scale = min(self.MAX_SIZE / h, self.MAX_SIZE / w, 1.0)
        nh, nw = max(1, round(h * scale)), max(1, round(w * scale))
        resized = Image.fromarray(img.astype(np.uint8)).resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (self.MAX_SIZE, self.MAX_SIZE), (255, 255, 255))
        canvas.paste(resized, ((self.MAX_SIZE - nw) // 2, (self.MAX_SIZE - nh) // 2))
        x = np.asarray(canvas, dtype=np.float32) / 255.0
        x = (x - self.MEAN) / self.STD
        x = np.transpose(x, (2, 0, 1))[None]  # 1x3xHxW
        return self.torch.from_numpy(x)

    def __call__(self, img: np.ndarray) -> str:
        pixel_values = self._prepare(img).to(self.device)
        with self.torch.inference_mode():
            ids = self.model.generate(
                pixel_values=pixel_values,
                decoder_start_token_id=self._start,
                max_new_tokens=1024,
                bad_words_ids=[[self._unk]],
            )
        return self.tokenizer.batch_decode(ids, skip_special_tokens=True)[0].strip()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["pix2tex", "texify"], required=True)
    ap.add_argument("--limit", type=int, default=150)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args()

    import pandas as pd
    df = pd.read_parquet(DATA / "test.parquet")
    rows = df.iloc[args.offset:args.offset + args.limit]
    print(f"loaded {len(rows)} test formulas (offset {args.offset})")

    engine = Pix2TexEngine() if args.engine == "pix2tex" else TexifyEngine()
    from PIL import Image

    results, errors = [], Counter()
    t0 = time.time()
    for i, row in enumerate(rows.itertuples(index=False)):
        try:
            pil = Image.open(io.BytesIO(row.image["bytes"])).convert("RGB")
            img = crop_white(np.asarray(pil))
            pred = engine(img)
        except Exception as exc:  # engine crash: keep benchmark alive
            pred = f"[ERROR {type(exc).__name__}]"
            errors[type(exc).__name__] += 1
        r = score_pair(row.formula, pred)
        r.update({"filename": row.filename})
        results.append(r)
        if (i + 1) % 25 == 0 or i + 1 == len(rows):
            el = time.time() - t0
            done = i + 1
            ok = [x for x in results if not x["pred"].startswith("[ERROR")]
            print(f"  {done}/{len(rows)}  mean_f1="
                  f"{sum(x['f1'] for x in ok)/max(1,len(ok)):.4f}  "
                  f"({el:.0f}s, {el/done:.1f}s/it, err={len(results)-len(ok)})")

    ok = [x for x in results if not x["pred"].startswith("[ERROR")]
    n = len(ok)
    summary = {
        "engine": engine.name, "sampled": len(rows), "scored": n,
        "engine_errors": dict(errors),
        "exact": round(sum(r["exact"] for r in ok) / n, 4) if n else 0,
        "f1": round(sum(r["f1"] for r in ok) / n, 4) if n else 0,
        "sim": round(sum(r["sim"] for r in ok) / n, 4) if n else 0,
        "ge90": round(sum(r["f1"] >= 0.90 for r in ok) / n, 4) if n else 0,
        "ge95": round(sum(r["f1"] >= 0.95 for r in ok) / n, 4) if n else 0,
    }
    print("\nSUMMARY", json.dumps(summary, ensure_ascii=False))
    worst = sorted(ok, key=lambda x: x["f1"])[:5]
    for w in worst:
        print(f"  f1={w['f1']:.2f}")
        print(f"    truth: {w['truth'][:90]}")
        print(f"    pred : {w['pred'][:90]}")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"summary": summary, "results": results}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print("wrote", args.json)


if __name__ == "__main__":
    main()
