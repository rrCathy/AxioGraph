#!/usr/bin/env python3
"""Theorem-environment detection benchmark with the author's LaTeX as truth.

Same setup as bench_aljabr.py: the AlJabr-1 repository ships `Al-jabr-1.pdf`
and the chapter .tex files of the SAME compile, so every
\\begin{definition}/\\begin{theorem}/\\begin{proof}/... block is human-written
ground truth for the rule-based detector in backend/env_service.py -- no
transcription needed.

Truth per environment:
  kind     the .tex env name, mapped onto env_service's kind vocabulary
  visible  the body text after the same command->Unicode mapping the PDF
           text layer has (bench_aljabr.visible), used to locate the page
Scoring (per located page, greedy one-to-one):
  hit            the detector produced an env whose text overlaps the truth
  kind_ok        the hit's kind matches the source env family
  coverage       truth-visible chars contained in the predicted env text;
                 low values mean the box was cut short, >1 mean prose was
                 swallowed past the body end
Continuation entries (cross-page bodies) count as hits of their kind but
are reported separately: the source block is one environment, the page
window may hold only its tail.

Localization uses only the PDF text layer (never OCR output), so a weak
recognizer cannot make the alignment look better.

Setup (once): same as bench_aljabr.py -- the AlJabr-1 tarball under
data/bench_aljabr/.

Usage:
  python scripts/bench_env.py --limit 120
  python scripts/bench_env.py --limit 400 --json data/bench_aljabr/env_result.json

NOTE: the repository PDF (445 pp) is NOT the same build as the workbench
copy (443 pp); the benchmark always reads the repository PDF.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
import bench_aljabr as BA  # noqa: E402  (visible(), SRC, PDF, locate, build_windows)
import env_service as E  # noqa: E402

PDF = BA.PDF

# .tex env name -> env_service kind. The repository uses shared numbering
# ([section] counters), so 'definition-theorem' is a theorem family.
KIND_MAP = {
    "definition": "definition", "theorem": "theorem", "lemma": "lemma",
    "proposition": "proposition", "corollary": "corollary",
    "example": "example", "remark": "remark", "proof": "proof",
    "hypothesis": "assumption", "conjecture": "conjecture",
    "convention": "convention", "exercise": "exercise",
    "definition-theorem": "theorem", "definition-proposition": "proposition",
}
ENV_RE = re.compile(
    r"\\begin\{(" + "|".join(sorted(KIND_MAP, key=len, reverse=True)) +
    r")\}(.*?)\\end\{\1\}", re.S)


def load_truth():
    truths = []
    files = sorted(BA.SRC.glob("chapter*.tex"),
                   key=lambda p: int(re.search(r"\d+", p.name).group()))
    for f in files:
        s = f.read_text(encoding="utf-8", errors="replace")
        for m in ENV_RE.finditer(s):
            tex_env, body = m.group(1), m.group(2).strip()
            v = BA.visible(body)
            if len(v) < 6:
                continue
            truths.append({
                "chapter": f.stem, "tex_env": tex_env,
                "kind": KIND_MAP[tex_env],
                "visible": v[:80],          # localization anchor
                "visible_len": len(v),
            })
    return truths


def coverage(truth_visible: str, pred_text: str) -> float:
    """Fraction of the truth's visible chars contained in the predicted env
    text (in order). ~1.0 = good boundary; <<1 cut short; the pred may carry
    MORE text (swallowed prose) -- overshoot is measured by len ratio."""
    pred = BA.visible(pred_text)
    if not pred or not truth_visible:
        return 0.0
    sm = SequenceMatcher(None, truth_visible, pred, autojunk=False)
    matched = sum(b.size for b in sm.get_matching_blocks())
    return matched / len(truth_visible)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=120,
                    help="max located truths to score")
    ap.add_argument("--threshold", type=float, default=0.45,
                    help="min char overlap for a hit")
    ap.add_argument("--json", type=str, default=None)
    args = ap.parse_args()

    if not PDF.exists():
        print(f"missing {PDF}; see bench_aljabr.py docstring for setup")
        return 1
    t0 = time.time()
    truths = load_truth()
    by_kind = Counter(t["kind"] for t in truths)
    print(f"source: {len(truths)} environments " +
          " ".join(f"{k}={n}" for k, n in by_kind.most_common()))
    import pymupdf as fitz
    doc = fitz.open(str(PDF))
    windows = BA.build_windows(doc)
    doc.close()
    # Locate the WHOLE truth set: scoring a page against a partial truth
    # subset would count that page's real-but-unscanned environments as
    # false positives.
    located, scanned = BA.locate(truths, windows, args.threshold,
                                 len(truths))
    print(f"located {len(located)} of {scanned} scanned truths "
          f"({len(located)/max(1,scanned):.3f}); source total {len(truths)} "
          f"in {time.time()-t0:.0f}s", flush=True)

    # patch pdf lookup so env_service reads the repository PDF (bench only)
    import page_service
    page_service.pdf_path = lambda book_id: PDF

    # group truths per page, then score each page's detection in one pass.
    # --limit now caps scored TRUTHS: keep whole pages so each page is
    # scored against its complete truth set.
    by_page_all = defaultdict(list)
    for t in located:
        by_page_all[t["page"]].append(t)
    by_page = {}
    budget = args.limit
    for pno in sorted(by_page_all):
        if budget <= 0:
            break
        by_page[pno] = by_page_all[pno]
        budget -= len(by_page_all[pno])

    # Detections of the scored pages AND their neighbours: locate() can land
    # a truth one page off (long bodies / repeated styles), and a cross-page
    # environment legitimately shows its tail on the next page. Matching
    # against the 3-page pool keeps the pairing honest.
    all_preds = {}
    for pno in sorted(by_page):
        for pg in (pno - 1, pno, pno + 1):
            if pg not in all_preds and pg >= 1:
                try:
                    all_preds[pg] = E.detect_from_pdf("bench-aljabr", pg) or []
                except Exception as ex:
                    print(f"  page {pg} detect failed: {ex}", flush=True)
                    all_preds[pg] = []

    rows = []
    used_pred_global: set[tuple[int, int]] = set()
    all_pred_ids = set()
    for pg, ps in all_preds.items():
        for pi in range(len(ps)):
            all_pred_ids.add((pg, pi))
    for k, (pno, ts) in enumerate(sorted(by_page.items()), 1):
        pool = [(pg, pi, p) for pg in (pno - 1, pno, pno + 1)
                for pi, p in enumerate(all_preds.get(pg, []))
                if (pg, pi) not in used_pred_global]
        # greedy one-to-one: prefer higher coverage, same kind slightly wins
        cands = []
        for ti, t in enumerate(ts):
            for pg, pi, p in pool:
                cov = coverage(t["visible"], p.get("text", ""))
                if cov < args.threshold:
                    continue
                kind_ok = p["kind"] == t["kind"]
                cands.append((cov + (0.05 if kind_ok else 0), cov, kind_ok,
                              ti, (pg, pi), p))
        cands.sort(key=lambda x: -x[0])
        used_t, used_p = set(), set()
        for _, cov, kind_ok, ti, pid, p in cands:
            if ti in used_t or pid in used_p:
                continue
            used_t.add(ti)
            used_p.add(pid)
            used_pred_global.add(pid)
            rows.append({
                "page": pno, "tex_env": ts[ti]["tex_env"], "kind": ts[ti]["kind"],
                "pred_kind": p["kind"], "kind_ok": kind_ok,
                "coverage": round(cov, 3),
                "continuation": bool(p.get("continuation")),
                "overshoot": round(
                    len(BA.visible(p.get("text", ""))) /
                    max(1, ts[ti]["visible_len"]), 2),
            })
        for ti in set(range(len(ts))) - used_t:
            rows.append({"page": pno, "tex_env": ts[ti]["tex_env"],
                         "kind": ts[ti]["kind"], "miss": True})
        if k % 20 == 0:
            print(f"  {k}/{len(by_page)} pages {time.time()-t0:.0f}s", flush=True)
    # unmatched detections count once each (global ids avoid the shared
    # neighbourhood pools being double-counted)
    for pg, pi in sorted(all_pred_ids - used_pred_global):
        rows.append({"page": pg, "pred_kind": all_preds[pg][pi]["kind"],
                     "fp": True,
                     "continuation": bool(all_preds[pg][pi].get("continuation"))})

    hits = [r for r in rows if r.get("coverage") is not None]
    misses = [r for r in rows if r.get("miss")]
    fps = [r for r in rows if r.get("fp")]
    n_tp, n_fn, n_fp = len(hits), len(misses), len(fps)
    prec = n_tp / max(1, n_tp + n_fp)
    rec = n_tp / max(1, n_tp + n_fn)
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    kind_ok = [r for r in hits if r["kind_ok"]]
    covs = [r["coverage"] for r in hits]

    print("\n=== SUMMARY (located subset, one-to-one) ===")
    print(f"scored truths {n_tp + n_fn}   hits {n_tp}   misses {n_fn}   "
          f"false positives {n_fp}")
    print(f"precision {prec:.4f}   recall {rec:.4f}   f1 {f1:.4f}")
    print(f"kind accuracy (on hits) {len(kind_ok)}/{n_tp} = "
          f"{len(kind_ok)/max(1,n_tp):.4f}")
    print(f"coverage mean {sum(covs)/max(1,len(covs)):.3f}   "
          f">=0.6 {sum(c >= .6 for c in covs)}/{len(covs)}   "
          f"==1.0 {sum(c >= .999 for c in covs)}/{len(covs)}")
    over = [r["overshoot"] for r in hits]
    print(f"overshoot mean {sum(over)/max(1,len(over)):.2f}   "
          f">1.5 (swallowed prose) {sum(o > 1.5 for o in over)}/{len(over)}")

    per = defaultdict(lambda: [0, 0, 0])     # kind -> tp, fn, fp
    for r in hits:
        per[r["kind"]][0] += 1
    for r in misses:
        per[r["kind"]][1] += 1
    for r in fps:
        per[r["pred_kind"]][2] += 1
    print("\nby kind:              tp  fn  fp   f1")
    for kind in sorted(per, key=lambda k: -sum(per[k])):
        tp, fn, fp = per[kind]
        p_ = tp / max(1, tp + fp)
        r_ = tp / max(1, tp + fn)
        f_ = 2 * p_ * r_ / max(1e-9, p_ + r_)
        print(f"  {kind:<12}      {tp:3} {fn:3} {fp:3}   {f_:.3f}")
    conts = [r for r in hits if r.get("continuation")]
    print(f"\nhits that are cross-page continuations: {len(conts)}")
    print(f"elapsed {time.time()-t0:.0f}s")
    if args.json:
        Path(args.json).write_text(
            json.dumps({"rows": rows}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
