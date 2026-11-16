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
    "公理": "axiom", "猜想": "conjecture", "断言": "claim",
    "事实": "fact", "假设": "assumption", "原理": "principle",
    "定义–定理": "theorem", "定义-定理": "theorem",   # en-dash / hyphen
    "Theorem": "theorem", "Definition": "definition", "Lemma": "lemma",
    "Proposition": "proposition", "Corollary": "corollary",
    "Example": "example", "Remark": "remark", "Notation": "notation",
    "Conventions": "convention", "Convention": "convention",
    "Question": "problem", "Warning": "warning", "Exercise": "exercise",
    "Axiom": "axiom", "Conjecture": "conjecture", "Claim": "claim",
    "Fact": "fact", "Assumption": "assumption", "Principle": "principle",
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
# Hei (black) faces carry the bold look with a -Regular suffix (代数学方法
# appendix axiom rows: FandolHei-Regular). Only explicit Hei names, never
# Song/Kai body faces.
_HEI_RE = re.compile(r"(?:FandolHei|SimHei)")
_KAI_RE = re.compile(r"(?:Kai|Kaiti)", re.I)
# After an unnumbered head word, the next character must be one of these (or
# end-of-line) -- "定义域是...", "定理告诉我们...", "注意", "例如" are prose,
# and a line STARTING with "问题), ..." is a wrapped sentence, not a header.
# No comma: "假设，我们就有" is a wrapped sentence, never a header.
_NUMLESS_OK = set("．.。;(（")
_LETTER_NUM_RE = re.compile(r"^([A-Z]\.\d+(?:\.\d+)*)\s*([^\s:：]{1,24})")
# Appendix style 'A.1 外延公理: ...' -- the number comes FIRST and the env
# word sits inside the title. Only environment words of >=2 chars qualify, so
# a title like 分离公理模式 maps to axiom via the contained word 公理.
_LETTER_WORDS = tuple(sorted(
    (w for w in _KIND_OF if not w.isascii() and len(w) >= 2),
    key=len, reverse=True))
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
        if nxt in "(（":
            inner = re.match(r"[（(]([^（）()]{1,80})[）)]", text[m.end():])
            # "假设(2) 成立" cites an item number in prose; a titled
            # environment has words inside the brackets ("断言(GY, ψY)").
            if inner and re.fullmatch(r"\d+(?:\.\d+)*", inner.group(1).strip()):
                return None
    title = None
    tm = re.match(r"\s*[（(]([^（）()]{1,80})[）)]", text[m.end():])
    if tm:                                 # bracketed name right after number
        title = tm.group(1).strip()
    return kind, head, num, title


def _classify_letter_num(text: str):
    """'A.1 外延公理: ...' appendix rows: number FIRST, env word in the title.

    Returns (kind, label, number, title) or None. The caller additionally
    requires a bold/hei row, so in-prose references never qualify.
    """
    m = _LETTER_NUM_RE.match(text)
    if not m:
        return None
    num, title = m.group(1), m.group(2)
    kind = None
    label = None
    for w in _LETTER_WORDS:                # longest word wins
        if w in title:
            kind = _KIND_OF[w]
            label = w
            break
    if kind is None:
        return None
    rest = text[m.end():]
    if rest and rest[0] not in ":：,，":   # title must end at a separator
        return None
    return kind, label, num, title


def _is_proof_mark(text: str, fonts: set[str], flush: bool) -> bool:
    if text.startswith("Proof"):
        # TOC entries ('Proof of the zagier theorem   205') end with a page
        # number; real heads end with punctuation or continue in prose.
        if text.rstrip()[-1:].isdigit():
            return False
        return True                       # "Proof." / "Proof of Theorem 1"
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
                if _BOLD_CJK_RE.search(f) or _HEI_RE.search(f) or "Heros-Bold" in f:
                    bold_spans.append(sp_text)
            t = "".join(chars).strip()
            if t:
                lines.append({"text": t, "bbox": list(ln["bbox"]),
                              "fonts": fonts, "x0": ln["bbox"][0],
                              "size": max(sp["size"] for sp in ln["spans"]),
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
    # Right text edge: mode of line ends (for the QED-mark position test).
    rcounts: dict[int, int] = {}
    for x in body:
        k = round(x["bbox"][2])
        rcounts[k] = rcounts.get(k, 0) + 1
    right = min(rcounts, key=lambda k: (-rcounts[k], k)) if rcounts else 0.0
    for x in lines:
        x["flush"] = x["x0"] <= left + 1.5
    return lines, left, right


def _qed_marks(page: fitz.Page, right: float) -> list[float]:
    """Y positions of hollow-square QED marks. The symbol is pure vector
    art on this corpus -- four INDEPENDENT short stroke drawings (two
    horizontal, two vertical, ~6pt each) forming a small box near the
    right text edge; it never reaches the text layer. Short strokes are
    clustered spatially: a cluster of >=3 strokes spanning 3-12pt both
    ways near the right edge is a QED mark."""
    strokes = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return []
    for d in drawings:
        if d.get("fill"):
            continue
        r = d["rect"]
        if r.width > 12 or r.height > 12:
            continue
        if right and r.x1 < right - 30:
            continue
        strokes.append(((r.y0 + r.y1) / 2, (r.x0 + r.x1) / 2))
    # cluster by centre distance (the page has few strokes; O(n^2) is fine)
    clusters: list[list[tuple[float, float]]] = []
    for s in strokes:
        for c in clusters:
            if abs(s[0] - c[0][0]) <= 8 and abs(s[1] - c[0][1]) <= 8:
                c.append(s)
                break
        else:
            clusters.append([s])
    out = []
    for c in clusters:
        if len(c) < 3:
            continue
        ys = [p[0] for p in c]
        xs = [p[1] for p in c]
        if max(ys) - min(ys) <= 12 and max(xs) - min(xs) <= 12 \
                and max(ys) - min(ys) >= 3:
            out.append(round(sum(ys) / len(ys), 1))
    return sorted(set(out))


def _is_running_head(ln: dict) -> bool:
    """Running heads sit just below _HEADER_TOP in some books (Hatcher:
    y≈44, ALL-CAPS chapter title or a bare page number) -- a global
    _HEADER_TOP would eat 代数学方法's first axiom row at y=54."""
    y = ln["bbox"][1]
    if y <= _HEADER_TOP:
        return True
    if y > 60:
        return False
    t = ln["text"].strip()
    if not t:
        return True
    if t.isdigit():
        return True
    letters = [c for c in t if c.isascii() and c.isalpha()]
    return len(letters) >= 6 and all(c.isupper() for c in letters)


_book_qed_seen: dict[str, bool] = {}


_SECTION_HEAD_RE = re.compile(r"^\d+(?:\.\d+){0,3}(?:\s+\S{1,24})?[\s.。]*$")
_BACK_MATTER = {"参考文献", "索引", "附录", "后记", "致谢", "目录", "前言", "符号表"}


def _detect_single(book_id: str, page_no: int):
    """One-page detection. Returns (envs, open_tail) -- open_tail is the
    (kind, label) of an environment whose body runs past the page bottom,
    or None."""
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
        lines, left, right = _page_lines(page)
        qed_ys = _qed_marks(page, right)
        page_h = page.rect.height
    finally:
        doc.close()

    # A bare page number (群论: '39' near the foot) is not body text; it
    # poisoned the open-tail test (a digit never ends a sentence). Position
    # conditions are unreliable across books -- an isolated digit row is a
    # page number in practice, so drop it wherever it sits.
    lines = [ln for ln in lines
             if not (ln["text"].strip().isdigit()
                     and len(ln["text"].strip()) <= 4)]

    heads: list[tuple[int, dict]] = []
    page_has_bold = any(x["bold_spans"] for x in lines)
    for i, ln in enumerate(lines):
        if _is_running_head(ln):
            continue
        bold = any(_BOLD_CJK_RE.search(f) or _HEI_RE.search(f)
                   for f in ln["fonts"])
        if _is_proof_mark(ln["text"], ln["fonts"], ln["flush"]):
            heads.append((i, {"kind": "proof",
                              "label": "Proof" if ln["text"].startswith("Proof") else "证明",
                              "number": None, "title": None,
                              "signal": "font" if any(_BOLD_CJK_RE.search(f) for f in ln["fonts"]) else "text"}))
            continue
        cls = _classify_head(ln["text"])
        if not cls:
            # Appendix style 'A.1 外延公理: ...': number first, env word inside
            # the title. Only bold/hei rows qualify -- in-prose references to
            # '公理A.1 — A.9' are body type and (being mid-sentence) rarely
            # start a line with the bare number.
            letter = _classify_letter_num(ln["text"])
            if letter and bold:
                kind, label, number, title = letter
                heads.append((i, {"kind": kind, "label": label,
                                  "number": number, "title": title,
                                  "signal": "font"}))
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
            # A page that uses bold type sets its real unnumbered heads in
            # bold. A plain-type "公理."/"定义. ..." line is a wrapped
            # sentence; the exception is a bracketed title right after the
            # head ("断言(GY, ψY) 的唯一性: ..."), which is a genuine
            # in-proof claim even when not bolded.
            if not number and page_has_bold and not bold:
                nxt = ln["text"][len(label): len(label) + 1]
                if nxt not in "(（":
                    continue
            heads.append((i, {"kind": kind, "label": label, "number": number,
                              "title": title, "signal": "text"}))
    envs, open_tail = _assemble(heads, lines, qed_ys)
    if qed_ys:
        _book_qed_seen[book_id] = True

    # Continuation CANDIDATE rows: everything between the running head and
    # this page's first head. Whether they actually are a cross-page body
    # depends on the PREVIOUS page's open tail, decided by the caller (kept
    # out of the cache so a cold cache never cascades the whole prefix).
    first_head_idx = heads[0][0] if heads else len(lines)
    cont_rows = [ln for ln in lines[:first_head_idx]
                 if not _is_running_head(ln)]
    return envs, open_tail, cont_rows, left


def _detect_cached(book_id: str, page_no: int):
    """Memoised single-page detection -- NO recursion, so a cold cache
    costs one page, never the whole prefix."""
    key = (book_id, page_no)
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    res = _detect_single(book_id, page_no)
    with _cache_lock:
        _cache[key] = res
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return res


def _attach_continuation(book_id: str, page_no: int, res) -> list[dict] | None:
    """Build the final env list: base detection of this page +, when the
    previous page left an environment open, its continuation rows as a
    marked entry. Both pages come from the memoised base detection."""
    if res is None:
        return None
    envs, open_tail, cont_rows, left = res
    if page_no > 1 and cont_rows:
        prev = _detect_cached(book_id, page_no - 1)
        if prev and prev[1]:
            pkind, plabel, preason = prev[1]
            # Signal-less opens ('ends_open') rely on the continuation
            # guards below (flush first row, no section heading, page
            # numbers already filtered) to stay honest.
            # A leading section number row ('2.5') precedes the real
            # continuation when a new section opens mid-continuation -- skip
            # it instead of rejecting the whole continuation.
            rows = cont_rows
            while rows and _SECTION_HEAD_RE.match(rows[0]["text"].strip()):
                rows = rows[1:]
            # The first real continuation row must not be a section heading
            # and must start flush at the baseline; a new paragraph starts
            # ~2em in. Cap the length: half a page of "continuation" means
            # the previous page was not actually open.
            if (rows
                    and rows[0]["text"].strip() not in _BACK_MATTER
                    and not _SECTION_HEAD_RE.match(rows[0]["text"].strip())
                    and rows[0]["x0"] <= left + 5
                    and len(rows) <= 14):
                x0 = min(x["bbox"][0] for x in rows)
                y0 = min(x["bbox"][1] for x in rows)
                x1 = max(x["bbox"][2] for x in rows)
                y1 = max(x["bbox"][3] for x in rows)
                envs.insert(0, {
                    "kind": pkind, "label": plabel, "number": None,
                    "title": None, "signal": "text", "continuation": True,
                    "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
                    "text": "\n".join(x["text"] for x in rows),
                })
    return envs


def detect_from_pdf(book_id: str, page_no: int) -> list[dict] | None:
    """Line-level detection from the PDF text layer; None if the page has
    no usable text layer (callers fall back to block-text matching).
    Includes the continuation of an environment left open on the previous
    page (cross-page theorem/proof bodies)."""
    return _attach_continuation(book_id, page_no, _detect_cached(book_id, page_no))


def _has_body_font(ln: dict) -> bool:
    """Environment bodies in Chinese math books are set in Fang/Kai while
    running prose is Song -- the reliable end-of-environment signal for
    flush-left inline environments (引理 1.2.7 in 代数学方法)."""
    return any("Fang" in f or "Kai" in f for f in ln["fonts"])


def _is_prose_row(ln: dict) -> bool:
    """A running-prose row: Song type (possibly with Hei for emphasised
    words) and no Fang/Kai. Body rows are Fang/Kai, Hei bullet labels
    ('▷反身性'), or pure math -- none of those count as prose."""
    return (not _has_body_font(ln)
            and any("Song" in f for f in ln["fonts"]))


def _is_math_row(ln: dict) -> bool:
    """A display-formula row: no CJK face at all (CMMI/CMR/CMSY only)."""
    return not any(s in f for f in ln["fonts"]
                   for s in ("Fandol", "Noto", "CJK", "Song", "Hei", "Kai", "Fang"))


_SENT_END = set(".。？！;；:：")


def _ends_open(text: str) -> bool:
    """True when the row does NOT end a sentence -- the body was cut
    mid-sentence by the page break."""
    tail = text.rstrip()
    return not tail or tail[-1] not in _SENT_END


def _assemble(heads, lines, qed_ys: list[float]):
    """Cut each head-to-head segment down to the actual environment body.

    Returns (envs, open_tail): open_tail is (kind, label, reason) of the
    LAST environment when its body runs to the page bottom without a
    closing signal -- reason 'signal' (an indented-block or Fang/Kai body
    simply never closed) or 'ends_open' (no body signal at all; the last
    row does not end a sentence, so the text was likely cut mid-sentence).
    Proof segments close only at a QED mark; otherwise 'ends_open'.
    """
    # Body text size: mode of row sizes. A row set clearly larger is a
    # section heading ('4.2 同态和商群') and ENDS whatever segment it
    # appears in -- headings carry no env word, so the old head-to-head cut
    # swallowed them together with the prose that follows.
    sizes: dict[float, int] = {}
    for x in lines:
        s = round(x.get("size", 10.0), 1)
        sizes[s] = sizes.get(s, 0) + 1
    body_size = min(sizes, key=lambda k: (-sizes[k], k)) if sizes else 10.0

    out = []
    open_tail = None
    last = len(heads) - 1
    for j, (idx, meta) in enumerate(heads):
        end = heads[j + 1][0] if j + 1 < len(heads) else len(lines)
        seg = lines[idx:end]
        cut = len(seg)
        reason = None
        if meta["kind"] == "proof":
            # End of proof = the QED mark. Without one the segment keeps
            # the old head-to-head extent; it is left open (cross-page
            # proof) only when its last row does not even end a sentence
            # (books that DO use a QED mark never leave one out).
            below = [q for q in qed_ys if q >= seg[0]["bbox"][1] - 1]
            next_head_y = lines[end]["bbox"][1] if end < len(lines) else None
            qy = below[0] if below and (next_head_y is None
                                        or below[0] < next_head_y) else None
            if qy is None:
                if _ends_open(seg[-1]["text"] if seg else "."):
                    reason = "ends_open"
            else:
                for k in range(len(seg)):
                    if seg[k]["bbox"][3] >= qy - 1:
                        cut = k + 1          # the row carrying the mark
                        break
        elif len(seg) > 1:
            base = seg[0]["x0"]
            # (a) indented-block body (appendix axioms: head flush, body
            # rows at base+22, prose rows back at base). The indent must be
            # MODEST (<= base+40): a centred display row (base+100 and up)
            # also passes the lower bound and would masquerade as an
            # indented body while the real flush-left body rows get cut as
            # "prose back at the margin" (定义 4.3.7). Two rows required: a
            # single centred row fooled the old test.
            two_indented = (base + 15 <= seg[1]["x0"] <= base + 40) and (
                len(seg) < 3 or base + 15 <= seg[2]["x0"] <= base + 40)
            # (b) Fang/Kai body, flush left (inline 定义/引理 environments):
            # once any Fang/Kai row has been seen, the first running-prose
            # (plain Song) row ends the environment. Math-only rows and
            # body-font rows in between are skipped.
            if not two_indented:
                seen_body = False
                for k in range(1, len(seg)):
                    ln = seg[k]
                    if ln.get("size", body_size) >= body_size + 2.5:
                        cut = k              # section heading row
                        break
                    if _has_body_font(ln):
                        seen_body = True
                    elif seen_body and _is_prose_row(ln):
                        cut = k              # first running-prose row
                        break
            if two_indented:
                for k in range(1, len(seg)):
                    x = seg[k]["x0"]
                    if seg[k].get("size", body_size) >= body_size + 2.5:
                        cut = k              # section heading row
                        break
                    if x <= base + 2:
                        cut = k              # prose continuation row
                        break
                    if base + 8 <= x <= base + 26:  # ~2em paragraph start
                        nxt = seg[k + 1]["x0"] if k + 1 < len(seg) else base + 50
                        if nxt <= base + 2:
                            cut = k          # prose paragraph start
                            break
            # No closing signal found and the body runs to the page bottom:
            # cross-page environment. A body WITH a signal (indent / Fang-Kai)
            # that never closed is trustworthy; a signal-less Song body only
            # counts when the last row does not even end a sentence.
            if j == last and cut == len(seg):
                if two_indented or seen_body:
                    reason = "signal"
                elif _ends_open(seg[-1]["text"]):
                    reason = "ends_open"
        seg = seg[:cut]
        if j == last and reason is not None:
            open_tail = (meta["kind"], meta["label"], reason)
        x0 = min(x["bbox"][0] for x in seg)
        y0 = min(x["bbox"][1] for x in seg)
        x1 = max(x["bbox"][2] for x in seg)
        y1 = max(x["bbox"][3] for x in seg)
        text = "\n".join(x["text"] for x in seg)
        out.append({**meta, "bbox": [round(v, 1) for v in (x0, y0, x1, y1)],
                    "text": text})
    return out, open_tail


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
_cache: OrderedDict[tuple[str, int], tuple[list[dict], tuple | None]] = OrderedDict()
_CACHE_MAX = 256


def detect_environments(book_id: str, page_no: int,
                        blocks: list[dict] | None = None) -> list[dict]:
    envs = _attach_continuation(book_id, page_no, _detect_cached(book_id, page_no))
    if envs is None:
        envs = detect_from_blocks(blocks or [])   # no text layer; not cached
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
