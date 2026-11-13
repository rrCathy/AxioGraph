"""Local, offline page recognition (no cloud, no rate limits).

Three ONNX engines:
  * pymupdf.layout.DocumentLayoutAnalyzer — layout regions with semantic
    labels (section-header / text / formula / picture / table / page-header).
    Its 16 ONNX weights are bundled in the wheel; nothing to download.
  * rapidocr_onnxruntime — OCR for pages whose text layer is unusable.
  * rapid_latex_ocr (RapidLaTeXOCR) — formula images -> LaTeX. Weights live in
    backend/models/latexocr/ (gitignored); without them the pipeline still
    works, formulas just keep their OCR characters.

All three are process-wide singletons (model init is expensive).
"""
import re
import threading
from pathlib import Path

import pymupdf as fitz

LATEX_DIR = Path(__file__).resolve().parent / "models" / "latexocr"
LATEX_FILES = ("encoder.onnx", "decoder.onnx", "image_resizer.onnx", "tokenizer.json")

_layout_model = None
_ocr_engine = None
_latex_engine = None
_lock = threading.Lock()

# Layout label -> our block type. Anything unknown is treated as prose.
LABEL_MAP = {
    "section-header": "H",
    "title": "H",
    "text": "P",
    "list-item": "P",
    "caption": "P",
    "footnote": "P",
    "formula": "FORMULA",
    "table": "TABLE",
    "picture": "FIGURE",
    "figure": "FIGURE",
    "page-header": "NOISE",
    "page-footer": "NOISE",
    "page-number": "NOISE",
}


def layout_model():
    global _layout_model
    with _lock:
        if _layout_model is None:
            from pymupdf.layout.DocumentLayoutAnalyzer import get_model
            _layout_model = get_model(n_workers=1)
    return _layout_model


def ocr_engine():
    global _ocr_engine
    with _lock:
        if _ocr_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
    return _ocr_engine


def detect_layout(page) -> list[dict]:
    """Return semantic regions in PDF points: [{bbox, label}, ...]."""
    try:
        raw = layout_model().predict(page)
    except Exception:
        return []
    out = []
    for row in raw or []:
        if len(row) < 5:
            continue
        out.append({"bbox": [round(float(v), 1) for v in row[:4]],
                    "label": str(row[4])})
    return out


def ocr_page(page, zoom: float = 2.0) -> list[dict]:
    """OCR the rendered page; bboxes are converted back to PDF points."""
    import numpy as np

    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )[:, :, :3]
    res, _ = ocr_engine()(img)
    out = []
    for box, text, score in res or []:
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        out.append({
            "bbox": [round(min(xs) / zoom, 1), round(min(ys) / zoom, 1),
                     round(max(xs) / zoom, 1), round(max(ys) / zoom, 1)],
            "text": str(text).strip(),
            "score": float(score),
        })
    return [r for r in out if r["text"]]


def latex_available() -> bool:
    """Formula-to-LaTeX works only when the weights are on disk."""
    return all((LATEX_DIR / f).exists() for f in LATEX_FILES)


def latex_engine():
    global _latex_engine
    if not latex_available():
        return None
    with _lock:
        if _latex_engine is None:
            from rapid_latex_ocr import LaTeXOCR
            _latex_engine = LaTeXOCR(
                image_resizer_path=LATEX_DIR / "image_resizer.onnx",
                encoder_path=LATEX_DIR / "encoder.onnx",
                decoder_path=LATEX_DIR / "decoder.onnx",
                tokenizer_json=LATEX_DIR / "tokenizer.json",
            )
    return _latex_engine


# --- Formula output sanity -------------------------------------------------
# Layout-model misfires (arrow-diagram labels, stray lines) produce LaTeX
# full of garbage tokens; real formulas never contain these.
_EMPTY_STRUCT = re.compile(
    r"\\[dt]?frac\s*\{\s*\}\s*\{\s*\}"      # \frac{}{}  empty fraction
    r"|\\sqrt\s*\{\s*\}"                     # \sqrt{}    empty root
    r"|[_^]\s*\{\s*\}"                       # _{} ^{}    empty script
)
_WHITESPACE_CMD = re.compile(r"\\qquad|\\quad|\\;|\\:|\\,|\\!|\\ ")
_NO_MATH_CMD = re.compile(
    r"\\nonumber|\\label\s*\{[^}]*\}|\\tag\s*\{[^}]*\}|\\text\s*\{[^}]*\}"
    r"|\\mathrm\s*\{[^}]*\}|\\mathbf\s*\{[^}]*\}|\\mbox\s*\{[^}]*\}"
)


def latex_valid(latex: str) -> bool:
    """A recognized LaTeX string is trustworthy only if it still carries
    mathematical structure after stripping whitespace/annotation noise."""
    if not latex:
        return False
    if "\\nonumber" in latex:
        return False
    if _EMPTY_STRUCT.search(latex):
        return False
    # A bare equation number "(1.5)" read off a margin is not a formula.
    stripped = latex.replace("\\,", "").replace("\\ ", "").strip()
    if re.fullmatch(r"\(?\s*\d+\s*\.\s*\d+\s*\)?", stripped):
        return False
    core = _WHITESPACE_CMD.sub("", latex)
    core = _NO_MATH_CMD.sub("", core)
    core = re.sub(r"\\(left|right)[.{[|]?", "", core)
    core = re.sub(r"\\[a-zA-Z]+", "", core)          # command names
    core = re.sub(r"[{}~$&]", "", core)
    return len(core.strip()) >= 4
