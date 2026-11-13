"""Structured page layout — LOCAL recognition, no cloud calls.

Pipeline per page:
  1. ONNX layout model (pymupdf.layout, bundled weights) predicts semantic
     regions with bboxes: section-header / text / formula / picture / table.
  2. If the page is a scanned bitmap (or the text layer is garbage), re-read
     it with local RapidOCR instead of trusting the embedded OCR text layer.
  3. Text lines (from the text layer or OCR) are assigned to regions by their
     centre point, yielding typed blocks that carry a real page position.

The old pymupdf4llm Markdown path is kept ONLY as a fallback when the layout
model is unavailable. Figure blocks are excluded from the LLM input by default.
"""
import json
import re

import pymupdf as fitz

from page_service import pdf_path, text_quality
import local_recognize as LR

FORMULA_NO_RE = re.compile(r"\(\s*(\d+)\.\s*(\d+)\s*\)")
FORMULA_REF_RE = re.compile(
    r"(?:式|公式|等式|equation|eq\.?|Eq\.?)\s*\(\s*(\d+)\.\s*(\d+)\s*\)", re.I)
# Embedded TeX math fonts: lines using them carry inline mathematics even
# when the layout model labels the region as plain text.
MATH_FONT_RE = re.compile(
    r"CMMI|CMSY|CMEX|MSAM|MSBM|LMMath|EUFM|EUSM|Symbol|MathDesign|"
    r"CambriaMath|Cambria.?Math|TeX.?Gyre.?Math|STIX|XITSMath", re.I)
CONTROL_RE = re.compile(r"[\ufffd\uE000-\uF8FF\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = CONTROL_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _span_rows(page) -> list[dict]:
    rows = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line.get("spans", [])).strip()
            if not text:
                continue
            rows.append({
                "text": text,
                "bbox": [round(v, 1) for v in line["bbox"]],
                "size": round(max((s["size"] for s in line.get("spans", [])), default=0), 1),
                "math": any(MATH_FONT_RE.search(str(s.get("font", "")))
                            for s in line.get("spans", [])),
            })
    return rows


def _center_in(inner: list[float], outer: list[float], pad: float = 3.0) -> bool:
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return (outer[0] - pad <= cx <= outer[2] + pad
            and outer[1] - pad <= cy <= outer[3] + pad)


def _cluster_image_boxes(page, pad=6.0, min_size=25.0) -> list[fitz.Rect]:
    """Complement the layout model: schematic frames drawn as 1x1 px line
    images are clustered into figure rectangles (union-find on padded rects)."""
    boxes = [fitz.Rect(i["bbox"]) for i in page.get_image_info()
             if i["width"] <= 4 or i["height"] <= 4]
    if not boxes:
        return []
    parent = list(range(len(boxes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(boxes)):
        ri = boxes[i] + (-pad, -pad, pad, pad)
        for j in range(i + 1, len(boxes)):
            if ri.intersects(boxes[j] + (-pad, -pad, pad, pad)):
                parent[find(j)] = find(i)
    groups: dict[int, fitz.Rect] = {}
    for i, b in enumerate(boxes):
        root = find(i)
        groups[root] = groups.get(root, fitz.Rect(b)) | b
    return [r for r in groups.values() if r.width >= min_size and r.height >= min_size]


def _group_leftovers(rows: list[dict]) -> list[dict]:
    """Lines outside any predicted region: group by y into prose blocks."""
    blocks = []
    for r in sorted(rows, key=lambda x: (x["bbox"][1], x["bbox"][0])):
        y = r["bbox"][1]
        if blocks and abs(y - blocks[-1]["_y"]) <= 6:
            b = blocks[-1]
            b["text"] += " " + r["text"]
            b["bbox"] = [min(b["bbox"][0], r["bbox"][0]), min(b["bbox"][1], r["bbox"][1]),
                         max(b["bbox"][2], r["bbox"][2]), max(b["bbox"][3], r["bbox"][3])]
            b["_math"] = b.get("_math", False) or bool(r.get("math"))
        else:
            blocks.append({"type": "P", "text": r["text"], "bbox": list(r["bbox"]),
                           "origin": "ungrouped", "_y": y,
                           "_math": bool(r.get("math"))})
    for b in blocks:
        b.pop("_y", None)
        if b.pop("_math", False):
            b["has_math"] = True
    return blocks


def _formula_anchors(rows: list[dict]) -> tuple[list[str], dict[str, str], list[str]]:
    """Equation numbers + names paired in reading order (line-level, not
    Markdown blocks, which regroup lines and break the pairing)."""
    name_re = re.compile(r"([\u4e00-\u9fffA-Za-z]{2,12})\s*公式")
    numbers: list[str] = []
    name_map: dict[str, str] = {}
    named: list[str] = []
    current = ""
    for r in rows:
        m = name_re.search(r["text"])
        if m and not any(c in m.group(1) for c in "这该三个些上述下列"):
            current = m.group(1) + " 公式"
            named.append(current)
        for a, b in FORMULA_NO_RE.findall(r["text"]):
            n = f"({a}.{b})"
            numbers.append(n)
            if current:
                name_map[n] = current
    return list(dict.fromkeys(numbers)), name_map, list(dict.fromkeys(named))


def _looks_mathish(text: str) -> bool:
    """Heuristic: does this line plausibly carry mathematics? Used to demote
    layout-model 'formula' misfires (diagram labels like "d' , e or f d d")
    back to prose."""
    if re.search(r"[=^_∑∫∏→←↔⇒≤≥±×÷∈∀∃√∥∂∇≡≈≠]", text):
        return True
    if FORMULA_NO_RE.search(text):
        return True
    words = re.findall(r"[A-Za-z]+", text)
    if not words:
        return True  # pure symbols / digits
    # English filler words ("d', e or f d d" — arrow-diagram labels) betray
    # prose; a genuine formula line is symbols or bare identifiers.
    if any(w.lower() in ("or", "and", "of", "the", "to", "is", "for", "where",
                         "with", "we", "if") for w in words):
        return False
    singles = sum(1 for w in words if len(w) == 1)
    return len(words) >= 2 and singles / len(words) >= 0.6


LAYOUT_VERSION = 3


def build_layout(book_id: str, page_no: int) -> dict:
    path = pdf_path(book_id)
    doc = fitz.open(str(path))
    if page_no < 1 or page_no > len(doc):
        doc.close()
        raise ValueError("page out of range")
    page = doc[page_no - 1]

    regions = LR.detect_layout(page)
    spans = _span_rows(page)
    raw = "\n".join(r["text"] for r in spans)
    quality = text_quality(raw)

    page_area = page.rect.get_area()
    full_bitmap = any(
        fitz.Rect(i["bbox"]).get_area() > 0.7 * page_area
        for i in page.get_image_info()
        if i["width"] > 400 and i["height"] > 400
    )
    garbled = bool(raw) and len(CONTROL_RE.findall(raw)) / len(raw) > 0.02
    needs_ocr = bool(full_bitmap or garbled or (quality < 0.55 and raw.strip()))

    if needs_ocr:
        try:
            rows = [{"text": r["text"], "bbox": r["bbox"], "size": 0}
                    for r in LR.ocr_page(page)]
            text_source = "rapidocr"
        except Exception:
            rows, text_source = spans, "text_layer"
    else:
        rows, text_source = spans, "text_layer"

    # Assign lines to semantic regions.
    blocks: list[dict] = []
    used: set[int] = set()
    for reg in regions:
        kind = LR.LABEL_MAP.get(reg["label"], "P")
        inside = [(i, r) for i, r in enumerate(rows)
                  if _center_in(r["bbox"], reg["bbox"])]
        if not inside:
            continue
        used.update(i for i, _ in inside)
        inside.sort(key=lambda ir: (ir[1]["bbox"][1], ir[1]["bbox"][0]))
        text = _clean(" ".join(r["text"] for _, r in inside))
        if not text:
            continue
        b: dict = {"type": kind, "text": text, "bbox": reg["bbox"],
                   "origin": f"layout:{reg['label']}"}
        if kind == "H":
            b["level"] = 1 if reg["label"] == "title" else 2
        elif kind == "P":
            b["has_math"] = any(r.get("math") for _, r in inside)
        blocks.append(b)

    if not regions:
        # Fallback when the ONNX model is unavailable: Markdown markers.
        try:
            import pymupdf4llm
            md = pymupdf4llm.to_markdown(doc, pages=[page_no - 1], use_ocr=False)
            for line in md.splitlines():
                s = line.strip()
                if s.startswith("#"):
                    level = len(s) - len(s.lstrip("#"))
                    blocks.append({"type": "H", "level": level,
                                   "text": _clean(s.lstrip("#")), "origin": "markdown"})
                elif s.startswith("|"):
                    if blocks and blocks[-1]["type"] == "TABLE":
                        blocks[-1]["text"] += "\n" + s
                    else:
                        blocks.append({"type": "TABLE", "text": s, "origin": "markdown"})
                elif s and not s.startswith("<!--"):
                    blocks.append({"type": "P", "text": _clean(s), "origin": "markdown"})
        except Exception:
            pass
        if not blocks:
            # No model regions AND no markdown (e.g. a scanned page whose
            # bitmap confuses the layout model): never drop the OCR rows —
            # group every line into prose blocks so the page stays usable.
            blocks = _group_leftovers(rows)
    else:
        blocks.extend(_group_leftovers([r for i, r in enumerate(rows) if i not in used]))

    # Figure boxes: predicted picture regions + line-image clusters.
    figure_boxes = [fitz.Rect(b["bbox"]) for b in blocks if b["type"] == "FIGURE"]
    for r in _cluster_image_boxes(page):
        if not any(fb.intersects(r) for fb in figure_boxes):
            figure_boxes.append(r)

    # ---- structure: reading order (top-down, left-right; noise last)
    def _read_key(b: dict):
        bb = b.get("bbox") or [0, 0, 0, 0]
        return (bb[1], bb[0])

    core = [b for b in blocks if b["type"] != "NOISE"]
    noise = [b for b in blocks if b["type"] == "NOISE"]
    core.sort(key=_read_key)
    blocks = core + noise

    # ---- structure: every block records the heading it lives under
    section = ""
    for b in blocks:
        if b["type"] == "H":
            section = b["text"]
            b["section"] = ""
        else:
            b["section"] = section

    # ---- formulas: demote non-math misfires, then read real ones as LaTeX
    formula_total = 0
    for b in blocks:
        if b["type"] != "FORMULA":
            continue
        if not LR.latex_valid(b.get("latex") or "") and not _looks_mathish(b["text"]):
            b["type"] = "P"                      # diagram label / stray line
            b["origin"] += "->demoted"
            continue
        formula_total += 1

    latex_engine = LR.latex_engine()
    page_img = None
    if latex_engine is not None and formula_total:
        import numpy as np
        zoom = 2.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        page_img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n)[:, :, :3]
    formula_recognized = 0
    for b in blocks:
        if b["type"] != "FORMULA":
            continue
        b["latex"] = b.get("latex") or None
        if b["latex"]:
            b["latex_source"] = "latex-ocr"
            formula_recognized += 1
            continue
        if page_img is None or not b.get("bbox"):
            continue
        x0, y0, x1, y1 = b["bbox"]
        pad = 2.0
        zx0 = max(0, int((x0 - pad) * 2.0))
        zy0 = max(0, int((y0 - pad) * 2.0))
        zx1 = min(page_img.shape[1], int((x1 + pad) * 2.0))
        zy1 = min(page_img.shape[0], int((y1 + pad) * 2.0))
        if zx1 - zx0 < 8 or zy1 - zy0 < 8:
            continue
        try:
            latex, _ = latex_engine(page_img[zy0:zy1, zx0:zx1])
        except Exception:
            continue
        latex = str(latex).strip()
        if LR.latex_valid(latex):
            b["latex"] = latex
            b["latex_source"] = "latex-ocr"
            formula_recognized += 1

    # ---- equation numbers (positioned) + explicit prose references
    numbers, name_map, named = _formula_anchors(rows)
    formula_items: list[dict] = []
    formula_refs: list[dict] = []
    for idx, b in enumerate(blocks):
        text = b.get("text") or ""
        for a, c in FORMULA_NO_RE.findall(text):
            no = f"({a}.{c})"
            numbers.append(no)
            formula_items.append({"no": no, "block": idx,
                                  "bbox": b.get("bbox"),
                                  "where": "formula" if b["type"] == "FORMULA" else "prose"})
        for a, c in FORMULA_REF_RE.findall(text):
            formula_refs.append({"ref": f"({a}.{c})", "block": idx,
                                 "context": text[:90]})
    numbers = list(dict.fromkeys(numbers))

    if full_bitmap:
        page_kind = "scanned_ocr" if rows else "scanned_image"
    elif needs_ocr:
        # Clean text layer polluted by figure glyphs / low quality: re-read
        # locally, but this is not a full-page scan.
        page_kind = "mixed_ocr"
    elif quality < 0.55:
        page_kind = "low_quality_text"
    else:
        page_kind = "text_layer"

    doc.close()
    return {
        "version": LAYOUT_VERSION,
        "page_no": page_no,
        "page_kind": page_kind,
        "text_source": text_source,
        # Only a full-page bitmap still needs human/vision verification.
        # Display formulas now carry locally-recognized LaTeX (best effort,
        # human review still welcome); prose keeps its OCR/text characters.
        "needs_vision": bool(full_bitmap),
        "text_quality": quality,
        "layout_regions": regions,
        "figure_boxes": [[round(v, 1) for v in r] for r in figure_boxes],
        "figure_labels": [b["text"] for b in blocks if b["type"] == "FIGURE"],
        "formula_numbers": numbers,
        "formula_name_map": name_map,
        "named_formulas": named,
        "formula_items": formula_items,
        "formula_refs": formula_refs,
        "formula_recognized": formula_recognized,
        "formula_total": formula_total,
        "math_lines": sum(1 for b in blocks if b.get("has_math")),
        "blocks": blocks,
        "counts": {k: sum(1 for b in blocks if b["type"] == k)
                   for k in ("H", "TABLE", "P", "FORMULA", "FIGURE", "NOISE")},
    }


def render_layout_text(layout: dict, include_figure: bool = False) -> str:
    out = []
    for b in layout["blocks"]:
        t = b["type"]
        if t == "NOISE" or (t == "FIGURE" and not include_figure):
            continue
        if t == "H":
            out.append("#" * b.get("level", 2) + " " + b["text"])
        elif t == "TABLE":
            out.append("[TABLE]\n" + b["text"])
        elif t == "FORMULA":
            # LaTeX when the local formula OCR succeeded, OCR characters
            # otherwise — both editable by the human in the workbench.
            if b.get("latex"):
                out.append("$$" + b["latex"] + "$$")
            else:
                out.append("[FORMULA] " + b["text"])
        elif t == "FIGURE":
            out.append("[FIGURE] " + b["text"])
        else:
            out.append("[P] " + b["text"])
    return "\n\n".join(out)


def to_storage(layout: dict, include_figure: bool = False) -> tuple[str, str]:
    return (json.dumps(layout, ensure_ascii=False),
            render_layout_text(layout, include_figure))
