"""Local, offline page recognition (no cloud, no rate limits).

Two ONNX engines that ship with the installed packages:
  * pymupdf.layout.DocumentLayoutAnalyzer — layout regions with semantic
    labels (section-header / text / formula / picture / table / page-header).
    Its 16 ONNX weights are bundled in the wheel; nothing to download.
  * rapidocr_onnxruntime — OCR for pages whose text layer is unusable.

Both are process-wide singletons (model init is expensive).
"""
import threading

import pymupdf as fitz

_layout_model = None
_ocr_engine = None
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
