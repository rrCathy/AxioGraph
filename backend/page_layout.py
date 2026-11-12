"""Structured page layout: hierarchy, position, figure exclusion, formula blocks.

Replaces the flat text dump with typed blocks so the LLM receives the page's
structure instead of a one-dimensional string. Uses PyMuPDF's official
pymupdf4llm Markdown output (hierarchy / tables / picture text) plus
PyMuPDF geometry (span bboxes, embedded-image boxes).

Nothing here guesses chapter structure by hand: Markdown markers and vector /
image geometry are the only signals.
"""
import json
import re

import pymupdf as fitz
import pymupdf4llm

from page_service import pdf_path, text_quality

# Math-dense line signal (used only to TYPE a block, never to invent content).
MATH_RE = re.compile(
    r"[=≤≥≠∫∂∑∏≃≅∈→↦√±×∩∪⊂⊃]|\$|\bif\b|\bfor all\b|\\frac|\\int|"
    r"\bdx\b|\bdy\b|\bdz\b"
)
FORMULA_NO_RE = re.compile(r"\(\s*(\d+)\.\s*(\d+)\s*\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
NOISE_RE = re.compile(r"[\ufffd\uE000-\uF8FF]{2,}|[□■]{2,}")
# A prose sentence starts with one of these; it is not a formula even if it
# contains an arrow or an equals sign.
PROSE_START_RE = re.compile(
    r"^(Let|For|Define|We|If|Then|Suppose|The|In|By|Since|Write|Note|Recall|"
    r"Consider|Given|Assume|Hence|Thus|Moreover|It|This|As|When|While)\b",
    re.I,
)


def _is_formula_line(text: str) -> bool:
    """Type a line as FORMULA only when it is math-dense and not a sentence."""
    if PROSE_START_RE.search(text):
        return False
    hits = len(MATH_RE.findall(text))
    return hits >= 2 and len(text) <= 220


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _cluster_image_boxes(page, pad=6.0, min_size=25.0) -> list[fitz.Rect]:
    """Schematic figures are drawn as many 1x1 px line images, not vector
    paths and not one picture. Cluster overlapping/adjacent line boxes into
    figure rectangles (union-find on padded rects)."""
    boxes = []
    for info in page.get_image_info():
        if info["width"] <= 4 or info["height"] <= 4:
            boxes.append(fitz.Rect(info["bbox"]))
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


def _span_rows(page) -> list[dict]:
    """Line-level text with bbox and font size — the position source."""
    rows = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line.get("spans", [])).strip()
            if not text:
                continue
            spans = line.get("spans", [])
            rows.append({
                "text": text,
                "bbox": [round(v, 1) for v in line["bbox"]],
                "size": round(max((s["size"] for s in spans), default=0), 1),
            })
    return rows


def _parse_markdown(md: str) -> list[dict]:
    """Typed blocks from standard Markdown markers (no bespoke heuristics)."""
    blocks: list[dict] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i].strip()
        if not raw:
            i += 1
            continue
        if raw.startswith("<!-- Start of picture text"):
            buf, i = [], i + 1
            while i < len(lines) and "End of picture text" not in lines[i]:
                buf.append(lines[i])
                i += 1
            i += 1
            text = _clean(" ".join(buf))
            if text:
                toks = [t for t in re.split(r"\s+", text) if t]
                short_ratio = (sum(1 for t in toks if len(t) <= 3) / len(toks)) if toks else 0
                # Numbered display equation -> FORMULA; a pile of 1-3 char
                # labels (f g h / c_x c_w) -> FIGURE.
                if FORMULA_NO_RE.search(text):
                    kind = "FORMULA"
                elif short_ratio > 0.5:
                    kind = "FIGURE"
                else:
                    kind = "FORMULA" if _is_formula_line(text) else "FIGURE"
                blocks.append({"type": kind, "text": text,
                               "origin": "picture-text"})
            continue
        m = HEADING_RE.match(raw)
        if m:
            blocks.append({"type": "H", "level": len(m.group(1)),
                           "text": _clean(m.group(2)), "origin": "markdown"})
            i += 1
            continue
        if raw.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            blocks.append({"type": "TABLE", "text": "\n".join(rows),
                           "origin": "markdown"})
            continue
        para = [raw]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or nxt.startswith(("#", "|", "<!--")):
                break
            para.append(nxt)
            i += 1
        text = _clean(" ".join(para))
        if not text:
            continue
        if len(text) <= 2:  # stray page numbers / single letters
            blocks.append({"type": "NOISE", "text": text, "origin": "markdown"})
        else:
            blocks.append({"type": "FORMULA" if _is_formula_line(text) else "P",
                           "text": text, "origin": "markdown"})
    return blocks


def _attach_bbox(blocks: list[dict], rows: list[dict]) -> None:
    """Best-effort position for each block: match its opening text to a line."""
    for b in blocks:
        key = re.sub(r"\s+", "", b["text"].split("|")[0])[:14].lower()
        if not key:
            continue
        for r in rows:
            if key and key[:10] in re.sub(r"\s+", "", r["text"]).lower():
                b["bbox"] = r["bbox"]
                b["font_size"] = r["size"]
                break


def build_layout(book_id: str, page_no: int) -> dict:
    """Build (and return) the typed layout of one page. Read-only w.r.t. pages."""
    path = pdf_path(book_id)
    doc = fitz.open(str(path))
    if page_no < 1 or page_no > len(doc):
        doc.close()
        raise ValueError("page out of range")
    page = doc[page_no - 1]

    md = pymupdf4llm.to_markdown(doc, pages=[page_no - 1], use_ocr=False)
    blocks = _parse_markdown(md)
    rows = _span_rows(page)
    figure_boxes = _cluster_image_boxes(page)
    _attach_bbox(blocks, rows)

    # Text that sits INSIDE a schematic figure is a label, not prose.
    # Figure glyphs are often non-printable in the embedded font; keep only
    # printable tokens and record the rest as unreadable marks.
    figure_labels: list[str] = []
    unreadable_labels = 0
    for r in rows:
        cx = (r["bbox"][0] + r["bbox"][2]) / 2
        cy = (r["bbox"][1] + r["bbox"][3]) / 2
        if not any(box.contains(fitz.Point(cx, cy)) for box in figure_boxes):
            continue
        cleaned = re.sub(r"[^\x20-\x7e\u00a1-\uffff]", "", r["text"]).strip()
        if cleaned and len(cleaned) <= 24 and re.search(r"[A-Za-z0-9\u4e00-\u9fff]", cleaned):
            figure_labels.append(cleaned)
        else:
            unreadable_labels += 1
    if figure_boxes:
        printables = [x for x in figure_labels if re.search(r"[A-Za-z0-9\u4e00-\u9fff]", x)]
        blocks.append({
            "type": "FIGURE",
            "text": " | ".join(printables) if printables
                    else f"图内符号（{unreadable_labels} 处不可读标记）",
            "origin": "image-geometry",
            "bbox": [round(v, 1) for v in figure_boxes[0]],
        })
    # A picture-text block made mostly of those labels is a figure caption,
    # not a formula (e.g. "f g h / c_x c_w").
    label_set = {re.sub(r"\s+", "", x).lower() for x in figure_labels}
    for b in blocks:
        if b["type"] == "FORMULA" and b.get("origin") == "picture-text" and label_set:
            toks = [t for t in re.split(r"\s+", b["text"]) if t]
            if toks and sum(1 for t in toks if re.sub(r"\W", "", t).lower() in label_set) / len(toks) > 0.5:
                b["type"] = "FIGURE"

    # Whole-page bitmap + an OCR text layer on top: the text is untrustworthy.
    page_area = page.rect.get_area()
    full_bitmap = any(
        fitz.Rect(i["bbox"]).get_area() > 0.7 * page_area
        for i in page.get_image_info()
        if i["width"] > 400 and i["height"] > 400
    )
    raw = "\n".join(r["text"] for r in rows)
    quality = text_quality(raw)
    if full_bitmap:
        page_kind = "scanned_ocr" if raw.strip() else "scanned_image"
        needs_vision = True
    elif quality < 0.55 and raw.strip():
        page_kind = "low_quality_text"
        needs_vision = True
    else:
        page_kind = "text_layer"
        needs_vision = False

    numbers = [f"({a}.{b})" for a, b in FORMULA_NO_RE.findall(raw)]
    # Anchors that the OCR layer mangled, e.g. "(0.7)" for (1.7).
    for b in blocks:
        numbers.extend(f"({a}.{c})" for a, c in FORMULA_NO_RE.findall(b["text"]))
    numbers = list(dict.fromkeys(numbers))

    # Pair equation numbers with the named formula heading that precedes them
    # in READING ORDER (span rows are authoritative; Markdown regroups lines).
    name_re = re.compile(r"([\u4e00-\u9fffA-Za-z]{2,12})\s*公式")
    name_by_number: dict[str, str] = {}
    named_seen: list[str] = []
    current_name = ""
    for r in rows:
        m = name_re.search(r["text"])
        if m and not any(c in m.group(1) for c in "这该三个些上述下列"):
            current_name = m.group(1) + " 公式"
            named_seen.append(current_name)
        for a, c in FORMULA_NO_RE.findall(r["text"]):
            if current_name:
                name_by_number[f"({a}.{c})"] = current_name

    doc.close()
    return {
        "page_no": page_no,
        "page_kind": page_kind,
        "needs_vision": needs_vision,
        "text_quality": quality,
        "figure_boxes": [[round(v, 1) for v in r] for r in figure_boxes],
        "figure_labels": figure_labels,
        "formula_numbers": numbers,
        "formula_name_map": name_by_number,
        "named_formulas": list(dict.fromkeys(named_seen)),
        "blocks": blocks,
        "counts": {k: sum(1 for b in blocks if b["type"] == k)
                   for k in ("H", "TABLE", "P", "FORMULA", "FIGURE", "NOISE")},
    }


def render_layout_text(layout: dict, include_figure: bool = False) -> str:
    """Human/LLM readable structured text. Figure labels are excluded by
    default — this is the 'selective extraction' the user asked for."""
    out = []
    for b in layout["blocks"]:
        t = b["type"]
        if t == "NOISE" or (t == "FIGURE" and not include_figure):
            continue
        if t == "H":
            out.append("#" * b.get("level", 1) + " " + b["text"])
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
