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
CONTROL_RE = re.compile(r"[\ufffd\uE000-\uF8FF\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
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
        else:
            blocks.append({"type": "P", "text": r["text"], "bbox": list(r["bbox"]),
                           "origin": "ungrouped", "_y": y})
    for b in blocks:
        b.pop("_y", None)
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
            blocks = [{"type": "P", "text": raw, "origin": "text-layer"}]
    else:
        blocks.extend(_group_leftovers([r for i, r in enumerate(rows) if i not in used]))

    # Figure boxes: predicted picture regions + line-image clusters.
    figure_boxes = [fitz.Rect(b["bbox"]) for b in blocks if b["type"] == "FIGURE"]
    for r in _cluster_image_boxes(page):
        if not any(fb.intersects(r) for fb in figure_boxes):
            figure_boxes.append(r)

    numbers, name_map, named = _formula_anchors(rows)
    for b in blocks:
        numbers.extend(f"({a}.{c})" for a, c in FORMULA_NO_RE.findall(b["text"]))
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
        "page_no": page_no,
        "page_kind": page_kind,
        "text_source": text_source,
        # Only a full-page bitmap still needs human/vision verification:
        # formula characters are now read by local OCR, but NOT converted to
        # LaTeX, so the UI must still ask for a human check.
        "needs_vision": bool(full_bitmap),
        "text_quality": quality,
        "layout_regions": regions,
        "figure_boxes": [[round(v, 1) for v in r] for r in figure_boxes],
        "figure_labels": [b["text"] for b in blocks if b["type"] == "FIGURE"],
        "formula_numbers": numbers,
        "formula_name_map": name_map,
        "named_formulas": named,
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
            out.append("[FORMULA] " + b["text"])
        elif t == "FIGURE":
            out.append("[FIGURE] " + b["text"])
        else:
            out.append("[P] " + b["text"])
    return "\n\n".join(out)


def to_storage(layout: dict, include_figure: bool = False) -> tuple[str, str]:
    return (json.dumps(layout, ensure_ascii=False),
            render_layout_text(layout, include_figure))
