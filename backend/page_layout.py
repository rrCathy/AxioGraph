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
# pix2tex renders an ellipsis as a run of \cdot commands.
_MANY_CDOT_RE = re.compile(r"(?:\\cdot\s*){2,}")
# A CJK connector ("并且/其中") inside an otherwise correct formula is read
# by pix2tex as a tiny \hat/\mathrm artifact. Drop just that fragment.
_CJK_CONNECTOR_ARTIFACT = re.compile(r"\{\\hat\{.*?\}\}\{\\mathrm\{.*?\}\}")
# CMEX brace glyphs leak into the text layer as bare "9" / "33" right before
# a formula. They mark a real TeX formula line, not a Chinese prose line.
_TEX_BRACE_FRAGMENT_RE = re.compile(r"(?:^|\s)(?:9|33)(?=[A-Za-z(])")
# TeX math PDFs encode radicals/braces/relations as isolated one-glyph text
# lines. A high share of those lines means the text layer is a pile of glyphs,
# not a readable transcript — no amount of line sorting will fix it.
_MATH_ORPHAN_RE = re.compile(
    r"[\u221a\u2a38\u2208\u21d2\u2243\u228a\u0338]|^[0-9]{1,2}$")
# TeX emits a display formula's big operator (⋂ / ∑ / ∫ ...) as its OWN
# one-glyph text line, a few points above the line carrying its limits. The
# layout model's formula region usually starts just below that glyph, so the
# operator misses _center_in() by a hair and lands in a stray "[P] ∩" block.
_BIGOP_RE = re.compile(r"^[\u2211\u220f\u222b\u2210\u2229\u222a\u22c2\u22c3\u2a00\u2a01\u2a02\u2a04\u2a06]$")


def _tidy_latex(latex: str) -> str:
    """Normalize the unambiguous, lossless cases in formula OCR output."""
    latex = _MANY_CDOT_RE.sub(r"\\cdots ", latex)
    latex = _CJK_CONNECTOR_ARTIFACT.sub(r"\\,", latex)
    # pix2tex pads short crops with long runs of non-breaking spaces. They are
    # pure decoder padding, never mathematical content, and they wreck the
    # editable text (and downstream token comparisons) if left in place.
    latex = re.sub(r"(?:~|\\,|\\;|\\:|\\ ){3,}", " ", latex)
    latex = re.sub(r"[~\s]+$", "", latex)
    return latex.strip()


def _clean(text: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    text = CONTROL_RE.sub(" ", text)
    # TeX radicals are separate glyphs; a run of them is one broken radical,
    # not a nested root. Collapse before whitespace normalization.
    text = re.sub(r"(?:\u221a\s*){2,}", "\u221a", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Limits of a big operator live on separate text rows; joining the rows
    # with a space used to leave "∩ _{E⊂N◁G} N" in the editable text.
    return re.sub(r"([\u2211\u220f\u222b\u2229\u222a\u22c2\u22c3])\s+(?=[_^]\{)",
                  r"\1", text)


def _line_text_with_scripts(line: dict) -> str:
    """Rebuild sub/superscripts from char size and baseline.

    TeX PDFs put indices in separate 5-7pt spans below (or above) the main
    baseline. Joining spans as plain text flattens `{v_i.w_j}_{1<=i<=m}` into
    `vi · wj 1⩽i⩽m`. Character bboxes still carry the structure, so restore
    it deterministically — no model, no guessing.
    """
    chars = []
    for s in line.get("spans", []):
        size = float(s.get("size") or 0)
        font = str(s.get("font", ""))
        for ch in s.get("chars", []):
            c = ch.get("c", "")
            if not c or c == "\n":
                continue
            b = ch.get("bbox") or (0, 0, 0, 0)
            chars.append((b[0], (b[1] + b[3]) / 2, size, font, c))
    if not chars:
        return ""
    size_counts: dict[float, int] = {}
    for ch in chars:
        k = round(ch[2], 1)
        size_counts[k] = size_counts.get(k, 0) + 1
    base_size = max(size_counts, key=size_counts.get)
    base_ys = sorted(ch[1] for ch in chars if abs(ch[2] - base_size) < 0.6)
    base_y = base_ys[len(base_ys) // 2] if base_ys else chars[0][1]

    out: list[str] = []
    sub: list[str] = []
    sup: list[str] = []
    for _x0, cy, size, font, c in sorted(chars, key=lambda t: t[0]):
        small = size < base_size * 0.82
        if small and cy > base_y + base_size * 0.12:
            sub.append(c)
            continue
        if small and cy < base_y - base_size * 0.12:
            sup.append(c)
            continue
        if sub:
            out.append("_{" + "".join(sub).strip() + "}")
            sub = []
        if sup:
            group = "".join(sup).strip()
            # A stacked condition like "1<=i<=m" sits ABOVE a brace but is a
            # subscript, not an exponent. Real exponents are short.
            kind = "_" if len(group) >= 3 and re.search(r"[\u2a7d\u2264\u2265<>,]", group) else "^"
            out.append(kind + "{" + group + "}")
            sup = []
        # CMEX's big summation operator has no Unicode mapping and leaks out
        # as the digit "7" in the text layer.
        if "CMEX" in font.upper() and c == "7":
            c = "\u2211"
        out.append(c)
    if sub:
        out.append("_{" + "".join(sub).strip() + "}")
    if sup:
        group = "".join(sup).strip()
        kind = "_" if len(group) >= 3 and re.search(r"[\u2a7d\u2264\u2265<>,]", group) else "^"
        out.append(kind + "{" + group + "}")
    return "".join(out)


def _span_rows(page) -> list[dict]:
    rows = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(
                "".join(ch.get("c", "") for ch in s.get("chars", []))
                for s in spans
            ).strip()
            if not text:
                continue
            rows.append({
                "text": text,
                "text_math": _line_text_with_scripts(line),
                "bbox": [round(v, 1) for v in line["bbox"]],
                "size": round(max((s.get("size", 0) for s in spans), default=0), 1),
                "math": any(MATH_FONT_RE.search(str(s.get("font", "")))
                            for s in spans),
            })
    return rows


def _center_in(inner: list[float], outer: list[float], pad: float = 3.0) -> bool:
    cx = (inner[0] + inner[2]) / 2
    cy = (inner[1] + inner[3]) / 2
    return (outer[0] - pad <= cx <= outer[2] + pad
            and outer[1] - pad <= cy <= outer[3] + pad)


def _attach_bigops(rows: list[dict], reg: dict, inside: list, used: set) -> list[float]:
    """Give a formula region back the one-glyph big operator above it.

    TeX puts ⋂/∑/∫ on a separate line whose centre falls just outside the
    ONNX formula box. Left alone it becomes an ungrouped "[P] ∩" block and the
    LaTeX crop loses the operator entirely. Only single-glyph operator lines
    are attached, so ordinary prose lines can never be pulled in.
    """
    if reg["label"] != "formula" or not inside:
        return reg["bbox"]
    rx0, ry0, rx1, ry1 = reg["bbox"]
    have = {i for i, _ in inside}
    box = fitz.Rect(reg["bbox"])
    for i, r in enumerate(rows):
        if i in have or i in used:
            continue
        if not _BIGOP_RE.match((r.get("text") or "").strip()):
            continue
        cx = (r["bbox"][0] + r["bbox"][2]) / 2
        cy = (r["bbox"][1] + r["bbox"][3]) / 2
        if rx0 - 12 <= cx <= rx1 + 12 and ry0 - 24 <= cy <= ry1 + 12:
            inside.append((i, r))
            box |= fitz.Rect(r["bbox"])
    return [round(v, 1) for v in box]


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
            b["text"] += " " + (r.get("text_math") or r["text"])
            b["bbox"] = [min(b["bbox"][0], r["bbox"][0]), min(b["bbox"][1], r["bbox"][1]),
                         max(b["bbox"][2], r["bbox"][2]), max(b["bbox"][3], r["bbox"][3])]
            b["_math"] = b.get("_math", False) or bool(r.get("math"))
        else:
            blocks.append({"type": "P", "text": r.get("text_math") or r["text"],
                           "bbox": list(r["bbox"]),
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


LAYOUT_VERSION = 12


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
    # A genuine scan is ONE image covering roughly the whole page. TeX-generated
    # PDFs instead carry stretched pattern/background tiles whose bbox can be
    # several times the page area; treating those as a full-page bitmap threw
    # away a perfectly good text layer and OCR destroyed all inline math.
    full_bitmap = any(
        0.7 * page_area <= fitz.Rect(i["bbox"]).get_area() <= 1.5 * page_area
        for i in page.get_image_info()
        if i["width"] > 400 and i["height"] > 400
    )
    garbled = bool(raw) and len(CONTROL_RE.findall(raw)) / len(raw) > 0.02
    # A readable text layer has a handful of short math lines; a fragmented
    # TeX layer has dozens ("√" on its own line, "9"/"33" brace glyphs,
    # superscript digits). Those pages must be read visually instead.
    math_orphans = sum(
        1 for r in spans
        if len(r["text"].strip()) <= 3 and r.get("math")
        and _MATH_ORPHAN_RE.search(r["text"].strip())
    )
    fragmented = len(spans) >= 20 and (
        math_orphans >= 20 and math_orphans / max(1, len(spans)) >= 0.25
    )
    needs_ocr = bool(full_bitmap or garbled or fragmented
                     or (quality < 0.55 and raw.strip()))

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
        box = _attach_bigops(rows, reg, inside, used)
        used.update(i for i, _ in inside)
        # Big braces, sub/superscripts and math glyphs sit on slightly different
        # baselines than the surrounding prose. Bin by visual row (~6pt) before
        # ordering left-to-right, or inline formulas get scrambled.
        mathy = any(r.get("math") for _, r in inside)
        inside.sort(key=lambda ir: (
            round(ir[1]["bbox"][1] / 6) if mathy else ir[1]["bbox"][1],
            ir[1]["bbox"][0],
        ))
        text = _clean(" ".join(r.get("text_math") or r["text"] for _, r in inside))
        if not text:
            continue
        b: dict = {"type": kind, "text": text, "bbox": box,
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
        # CJK prose is never a formula. The layout model often boxes a line
        # like "乘法满足分配律：对任意的 a1, a2 ..." because of the inline
        # symbols; feeding that bitmap to pix2tex produces hundreds of
        # hallucinated \hat tokens. But a set/display formula with just a
        # connector or two ("并且/其中") IS a formula — keep those, otherwise
        # their TeX brace fragments ("9P(x) : 33P,Q...") stay unreadable.
        txt = b.get("text") or ""
        if re.search(r"[\u4e00-\u9fff]", txt):
            cjk = len(re.findall(r"[\u4e00-\u9fff]", txt))
            # A couple of Han characters inside a display formula are usually
            # a condition or label ("H⊂G:子群"), not prose. The old rule
            # required a TeX brace-fragment marker, which exists only on
            # fragmented TeX PDFs — on a clean text layer it demoted EVERY
            # formula containing Chinese to [P] and skipped LaTeX OCR.
            han_ratio = cjk / max(1, len(txt))
            # Centered display formulas are short; Chinese prose lines span the
            # whole text column. The width test keeps this exemption narrow —
            # without it long "有重根 ⇔ ..." lines become FORMULA blocks that
            # texify cannot read (CJK inside the bitmap), which looks like a
            # coverage regression without gaining any LaTeX.
            bb = b.get("bbox") or [0, 0, 0, 0]
            centered = (bb[2] - bb[0]) <= 0.55 * page.rect.width
            # One or two Han characters are a label ("子群", "有限"); three or
            # more are usually a Chinese phrase inside a diagram caption,
            # which texify reliably mangles. Keep the exemption to labels.
            mathish = (cjk <= 2 and han_ratio <= 0.2 and centered
                       and _looks_mathish(txt))
            if cjk > 4 or (not _TEX_BRACE_FRAGMENT_RE.search(txt) and not mathish):
                b["type"] = "P"
                b["origin"] += "->prose"
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
        latex = _tidy_latex(str(latex).strip())
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
        # Only a genuine full-page bitmap still needs human/vision verification.
        # Display formulas carry locally recognized LaTeX (best effort, human
        # review welcome); prose keeps its text-layer/OCR characters.
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
            # Keep any Han characters the layout model swallowed into the
            # formula box ("其中/使得/证明"). They are prose, not math, and
            # dropping them silently costs character fidelity.
            if b.get("latex"):
                han = "".join(re.findall(r"[\u4e00-\u9fff]", b.get("text") or ""))
                out.append("$$" + b["latex"] + "$$" + (" " + han if han else ""))
            else:
                out.append("[FORMULA] " + b["text"])
        elif t == "FIGURE":
            out.append("[FIGURE] " + b["text"])
        else:
            out.append("[P] " + b["text"])
    return "\n".join(out)


def to_storage(layout: dict, include_figure: bool = False) -> tuple[str, str]:
    return (json.dumps(layout, ensure_ascii=False),
            render_layout_text(layout, include_figure))
