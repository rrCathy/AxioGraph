"""Rule-based detection of theorem-like environments. No LLM, no model.

Reads line-level font + geometry from the PDF text layer and classifies the
classical math-writing environments (定理/定义/证明/例/引理/...). The signals
were measured on the corpus (2026-11-15):

- 代数学方法: environment headers use NotoSansCJKjp-Black (+TeXGyreHeros-Bold
  for latin), proof marks NotoSansCJKjp-Medium; body prose is FandolSong.
- 群论与Galois理论: headers use FandolSong-Bold; the proof mark is plain
  FandolKai/FandolSong (no weight signal) -> short-line text rule.
- 简明复分析 has a HiddenHorzOCR fake text layer (no fonts at all) and 代数拓扑
  is English: both fall through to the text+geometry rule.

The detection is a DERIVATION: it never touches build_layout output or
LAYOUT_VERSION, costs ~70 ms per uncached page and is memoised in-process.
"""

from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict

import pymupdf as fitz

_KIND_OF = {
    "定理": "theorem", "定义": "definition", "引理": "lemma",
    "命题": "proposition", "推论": "corollary", "例子": "example",
    "例": "example", "注记": "remark", "注": "remark", "评注": "remark",
    "约定": "convention", "记号": "notation", "问题": "problem",
    "警告": "warning", "练习": "exercise", "习题": "exercise",
    "Theorem": "theorem", "Definition": "definition", "Lemma": "lemma",
    "Proposition": "proposition", "Corollary": "corollary",
    "Example": "example", "Remark": "remark", "Notation": "notation",
    "Conventions": "convention", "Convention": "convention",
    "Question": "problem", "Warning": "warning", "Exercise": "exercise",
}
_ZH_HEADS = "|".join(sorted((k for k in _KIND_OF if k.isascii() is False),
                            key=len, reverse=True))
_EN_HEADS = "|".join(sorted((k for k in _KIND_OF if k.isascii()),
                            key=len, reverse=True))
_HEAD_RE = re.compile(
    r"^(?:" + _ZH_HEADS + r"|" + _EN_HEADS + r")"
    r"\s*([0-9]+(?:\.[0-9]+)*)?")
_BOLD_CJK_RE = re.compile(
    r"(?:CJK|Fandol|Noto|SimHei|SourceHan|SourceHanSerif|WenQuanYi|FZ[KS])"
    r"[A-Za-z0-9]*-(?:Black|Bold|Heavy|Medium)")
_KAI_RE = re.compile(r"(?:Kai|Kaiti)", re.I)
# After an unnumbered head word, the next character must be one of these (or
# end-of-line) -- "定义域是...", "定理告诉我们...", "注意", "例如" are prose,
# and a line STARTING with "问题), ..." is a wrapped sentence, not a header.
_NUMLESS_OK = set("．.。;，,，(（")
_DOTS_RE = re.compile(r"(?:\.\s*){6,}")     # table-of-contents leader dots
_HEADER_TOP = 40.0      # y above this is running head / page number


def _classify_head(text: str):
    """(kind, label, number, title) if the line STARTS a theorem-like env."""
    if _DOTS_RE.search(text):
        return None                        # TOC entry "习题. . . . . 100"
    m = _HEAD_RE.match(text)
    if not m:
        return None
    num = m.group(1)
    head = text[: m.end() - len(num or "")].rstrip()
    kind = _KIND_OF.get(head)
    if kind is None:
        return None
    if not num:
        nxt = text[m.end(): m.end() + 1]
        if nxt and nxt not in _NUMLESS_OK:
            return None                    # "定义域", "定理告诉我们", "例如"
    title = None
    tm = re.match(r"\s*[（(]([^（）()]{1,80})[）)]", text[m.end():])
    if tm:                                 # bracketed name right after number
        title = tm.group(1).strip()
    return kind, head, num, title


def _is_proof_mark(text: str, fonts: set[str], flush: bool) -> bool:
    if text.startswith("Proof"):
        return True                        # "Proof." / "Proof of Theorem 1"
    if not text.startswith("证明"):
        return False
    if any(_BOLD_CJK_RE.search(f) for f in fonts):
        return True
    if any(_KAI_RE.search(f) for f in fonts):
        return True
    # 群论书 has no weight signal for 证明: a bare short mark at the margin.
    return flush and len(text) <= 6


def _page_lines(page: fitz.Page) -> list[dict]:
    raw = page.get_text("rawdict")
    lines = []
    for blk in raw["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            chars: list[str] = []
            fonts: set[str] = set()
            bold_spans: list[str] = []
            for sp in ln["spans"]:
                f = sp["font"]
                fonts.add(f)
                sp_text = "".join(ch["c"] for ch in sp["chars"])
                chars.append(sp_text)
                if _BOLD_CJK_RE.search(f) or "Heros-Bold" in f:
                    bold_spans.append(sp_text)
            t = "".join(chars).strip()
            if t:
                lines.append({"text": t, "bbox": list(ln["bbox"]),
                              "fonts": fonts, "x0": ln["bbox"][0],
                              "bold_spans": bold_spans})
    lines.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
    body = [x for x in lines if x["bbox"][1] > _HEADER_TOP]
    # The margin x is the MODE of line starts, not the minimum: margin notes
    # and equation rows sit left of the text edge (Hatcher p16: notes at x0<50
    # pulled min() down and marked every real header indented).
    counts: dict[int, int] = {}
    for x in body:
        k = round(x["x0"])
        counts[k] = counts.get(k, 0) + 1
    left = min(counts, key=lambda k: (-counts[k], k)) if counts else 0.0
    for x in lines:
        x["flush"] = x["x0"] <= left + 1.5
    return lines


def detect_from_pdf(book_id: str, page_no: int) -> list[dict] | None:
    """Line-level detection from the PDF text layer; None if the page has
    no usable text layer (callers fall back to block-text matching)."""
    from page_service import pdf_path  # local import: page_service imports us

    path = pdf_path(book_id)
    if not path.exists():
        return None
    doc = fitz.open(str(path))
    try:
        if page_no < 1 or page_no > len(doc):
            return None
        page = doc[page_no - 1]
        if not page.get_text("text").strip():
            return None
        lines = _page_lines(page)
    finally:
        doc.close()

    heads: list[tuple[int, dict]] = []
    page_has_bold = any(x["bold_spans"] for x in lines)
    for i, ln in enumerate(lines):
        bold = any(_BOLD_CJK_RE.search(f) for f in ln["fonts"])
        if _is_proof_mark(ln["text"], ln["fonts"], ln["flush"]):
            heads.append((i, {"kind": "proof",
                              "label": "Proof" if ln["text"].startswith("Proof") else "证明",
                              "number": None, "title": None,
                              "signal": "font" if any(_BOLD_CJK_RE.search(f) for f in ln["fonts"]) else "text"}))
            continue
        cls = _classify_head(ln["text"])
        if not cls:
            continue
        kind, label, number, title = cls
        if bold:
            heads.append((i, {"kind": kind, "label": label, "number": number,
                              "title": title, "signal": "font"}))
        elif number and page_has_bold and not any(
                number in bs for bs in ln["bold_spans"]):
            # A numbered header on a page that USES bold type: the number
            # itself is set bold in every real header (TeXGyreHeros-Bold /
            # FandolSong-Bold), while the number in an in-prose reference
            # ("引理2.2.7 相当于说...", a flush-left continuation line) is
            # body type -> reject.
            continue
        elif number and not ln["flush"]:
            # No bold type on this page (OCR-re-laid-out books): fall back to
            # the 2-em paragraph-indent test.
            continue
        else:
            heads.append((i, {"kind": kind, "label": label, "number": number,
                              "title": title, "signal": "text"}))
    return _assemble(heads, lines)


def _assemble(heads, lines) -> list[dict]:
    out = []
    for j, (idx, meta) in enumerate(heads):
        end = heads[j + 1][0] if j + 1 < len(heads) else len(lines)
        seg = lines[idx:end]
        x0 = min(x["bbox"][0] for x in seg)
        y0 = min(x["bbox"][1] for x in seg)
        x1 = max(x["bbox"][2] for x in seg)
        y1 = max(x["bbox"][3] for x in seg)
        text = "\n".join(x["text"] for x in seg)
        out.append({**meta, "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
                    "text": text})
    return out


def detect_from_blocks(blocks: list[dict]) -> list[dict]:
    """Fallback for OCR pages without a text layer: match whole blocks."""
    out = []
    for bi, b in enumerate(blocks or []):
        text = (b.get("text") or "").strip()
        if not text:
            continue
        if _is_proof_mark(text, set(), True) and len(text) <= 8:
            out.append({"kind": "proof", "label": "证明", "number": None,
                        "title": None, "signal": "text", "bbox": b.get("bbox"),
                        "text": text, "block": bi})
            continue
        cls = _classify_head(text.splitlines()[0] if "\n" in text else text)
        if not cls:
            continue
        kind, label, number, title = cls
        out.append({"kind": kind, "label": label, "number": number,
                    "title": title, "signal": "text", "bbox": b.get("bbox"),
                    "text": text, "block": bi})
    return out


_cache_lock = threading.Lock()
_cache: OrderedDict[tuple[str, int], list[dict]] = OrderedDict()
_CACHE_MAX = 256


def detect_environments(book_id: str, page_no: int,
                        blocks: list[dict] | None = None) -> list[dict]:
    key = (book_id, page_no)
    envs = None
    with _cache_lock:                      # NB: Lock is NOT reentrant -- the
        hit = _cache.get(key)              # detection itself must run OUTSIDE
        if hit is not None:                # this block or the thread deadlocks.
            _cache.move_to_end(key)
            envs = hit
    if envs is None:
        envs = detect_from_pdf(book_id, page_no)
        if envs is None:
            envs = detect_from_blocks(blocks or [])
        with _cache_lock:
            _cache[key] = envs
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
    if not (envs and blocks):
        return envs
    # Map each environment to the overlapping blocks (fresh copies, so the
    # memoised entries stay unmapped and reusable with any block list).
    # Accept both shapes: row-level TextBlock (x0/y0/x1/y1) and layout
    # blocks (bbox).
    def _blk_rect(b):
        bb = b.get("bbox")
        if bb:
            return fitz.Rect(bb)
        if "x0" in b:
            return fitz.Rect(b["x0"], b["y0"], b["x1"], b["y1"])
        return None

    out = []
    for e in envs:
        e2 = dict(e)
        bb = e2.get("bbox")
        if bb:
            r = fitz.Rect(bb)
            e2["blocks"] = [i for i, b in enumerate(blocks)
                            if (br := _blk_rect(b)) is not None and r.intersects(br)]
        else:
            e2["blocks"] = []
        out.append(e2)
    return out
