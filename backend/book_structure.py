"""Book structure recognition: title / author / TOC → chapter graph nodes.

TOC sources, in priority order:
  1. Embedded PDF bookmarks (PyMuPDF get_toc) — exact, no LLM needed.
  2. TOC pages located in the first ~20 pages and parsed by the vision model
     (text-layer hit first; scanned TOC pages go straight to vision).
  3. Manual entry / editing in the frontend.

The "book page → PDF page" offset is detected by matching chapter titles
against the page text layer (excluding pages that look like the TOC itself).
The whole structure is stored as one JSON row in book_structure and can be
re-detected / edited / confirmed at any time.
"""
import json
import logging
import re
import uuid

import pymupdf as fitz

from database import get_db
from graph_store import sync_book_counts
import page_service as ps
from services.llm import get_llm

log = logging.getLogger("axiograph.structure")

TOC_PAGE_PATTERNS = re.compile(
    r"^\s*(目\s*录|目次|Contents|CONTENTS|Table of Contents)\s*$", re.M
)
MAX_TOC_SCAN_PAGES = 20
MAX_VISION_TOC_PROBES = 6

TOC_ANCHOR_RE = re.compile(r"^\s*(目\s*录|目\s*次|contents|table of contents)\s*$", re.I)
_NUM_ONLY_RE = re.compile(r"^\d{1,4}$")
_DOTTED_NO_RE = re.compile(r"^\d{1,3}(?:\.\d{1,2}){1,2}$")
_LEAD_NO_SP_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,2}){0,2})\s+(.*\S)")
_LEAD_NO_GLUE_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,2}){1,2})([^\d.\s].*)$")
_TAIL_PAGE_RE = re.compile(r"^(.*\S)\s+(\d{1,4})$")
_DOTS_RE = re.compile(r"(?:\.\s*){3,}|[.·…]{4,}")


def _strip_dots(s: str) -> str:
    s = _DOTS_RE.sub(" ", s)
    return s.strip(" .·…").strip()


def _page_toc_text(page) -> str:
    """Text of a TOC page with two-column layouts re-sequenced: plain text
    mode merges left/right columns line by line, scrambling the entry
    stream. Line bboxes are regrouped into columns by x."""
    try:
        d = page.get_text("dict")
        mid = page.rect.width / 2
        left, right = [], []
        for b in d.get("blocks", []):
            for l in b.get("lines", []):
                text = "".join(s["text"] for s in l.get("spans", [])).strip()
                if not text:
                    continue
                (left if l["bbox"][0] < mid - 15 else right).append((l["bbox"][1], text))
        dot_re = re.compile(r"(?:\.\s*){3,}|[.\u00b7\u2026]{4,}")
        left_dots = sum(1 for _, t in left if dot_re.search(t))
        right_dots = sum(1 for _, t in right if dot_re.search(t))
        # A right-aligned page-number column is NOT a second column: regroup
        # only when both sides carry their own dot-leader entries.
        if left_dots >= 2 and right_dots >= 2:
            left.sort(key=lambda t: t[0])
            right.sort(key=lambda t: t[0])
            return "\n".join(t for _, t in left) + "\n" + "\n".join(t for _, t in right)
    except Exception:
        pass
    return page.get_text("text") or ""


def _local_toc_items(text: str, max_ch: int = 0) -> tuple[list[dict], int]:
    """Parse a text-layer TOC page WITHOUT any model.

    LaTeX-style TOCs come out of the text layer as a token stream — entry
    number line, title line(s), dot-leader line, page-number line (or the
    whole entry on one line) — which a small state machine reassembles.
    `max_ch` carries the highest plausible chapter number across multi-page
    TOCs and is returned updated. Returns ([], max_ch) when the page does
    not parse as a TOC (fewer than 5 entries) so callers can fall back.
    """
    lines = [l.strip() for l in (text or "").splitlines()]
    start = next((i for i, l in enumerate(lines) if TOC_ANCHOR_RE.match(l)), -1)
    tokens = lines[start + 1:] if start >= 0 else lines
    if start < 0:
        # No "目录" heading: only treat the page as a TOC when dot leaders and
        # bare page numbers are abundant (multi-page TOC continuations).
        dots = sum(1 for l in tokens if _DOTS_RE.search(l))
        nums = sum(1 for l in tokens if _NUM_ONLY_RE.match(l))
        tail_nums = sum(1 for l in tokens
                        if not _NUM_ONLY_RE.match(l) and _TAIL_PAGE_RE.match(_strip_dots(l)))
        if dots < 3 or (nums < 5 and tail_nums < 5):
            return [], max_ch

    entries: list[dict] = []
    cur_no, cur_title = "", []
    # max_ch (parameter) = highest plausible chapter number seen so far;
    # it guards "60 阶的单群" / "238" style junk and carries across pages.

    def plausible_no(no: str) -> bool:
        head = int(no.split(".")[0])
        if head > 200:
            return False
        if "." not in no:
            return head <= max_ch + 1        # chapters run 1, 2, 3, ...
        return head <= max_ch + 1            # sections live in a known chapter

    prev_page = 0

    def finish(page_no: int | None):
        nonlocal cur_no, cur_title, prev_page
        title = _strip_dots(" ".join(t for t in cur_title if t))
        # TOC page numbers are monotonically increasing; a wild backwards
        # jump marks a stray line caught by the state machine.
        if title and page_no and page_no <= 5000 and page_no >= prev_page * 0.5:
            level = min(3, cur_no.count(".") + 1) if cur_no else 1
            entries.append({"level": level, "no": cur_no or None, "title": title,
                            "book_page": page_no, "pdf_page": None})
            if page_no > prev_page:
                prev_page = page_no
        cur_no, cur_title = "", []

    for raw in tokens:
        line = _strip_dots(raw.strip())
        if not line:
            continue
        if _NUM_ONLY_RE.match(line):               # bare integer (incl. dots+number lines)
            if cur_no and cur_title:
                finish(int(line))                  # page number completes it
            elif not cur_no and plausible_no(line):
                max_ch = max(max_ch, int(line))
                cur_no = line                      # bare chapter number
            continue                               # stray number: page junk
        if _DOTTED_NO_RE.match(line) and plausible_no(line):
            finish(None)                           # "1.1" / "2.7.4" alone
            max_ch = max(max_ch, int(line.split(".")[0]))
            cur_no, cur_title = line, []
            continue
        clean = line
        tail_page = None
        pm = _TAIL_PAGE_RE.match(clean)
        if pm and (len(pm.group(2)) <= 3 or int(pm.group(2)) <= 500):
            tail_page = int(pm.group(2))
            clean = _strip_dots(pm.group(1))
            if not clean:
                continue
        m = _LEAD_NO_SP_RE.match(clean) or _LEAD_NO_GLUE_RE.match(clean)
        if m and plausible_no(m.group(1)):
            finish(None)                           # unfinished entry: drop
            cur_no, cur_title = m.group(1), [m.group(2)]
            max_ch = max(max_ch, int(m.group(1).split(".")[0]))
        elif cur_no:
            cur_title.append(clean)
        elif tail_page is None:
            continue                               # prose outside entries
        else:
            cur_title.append(clean)                # unnumbered entry title
        if tail_page is not None:
            finish(tail_page)                      # entry closed on same line
    finish(None)
    return (entries if len(entries) >= 5 else []), max_ch


def _cover_meta_from_text(text: str) -> dict:
    """Heuristic cover/flyleaf metadata from the first text page: first
    non-empty line is the title; a short pure-Chinese line among the first
    few lines is the author. Local-only fallback when PDF metadata is empty."""
    out: dict = {}
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s or TOC_ANCHOR_RE.match(s):
            continue
        if "title" not in out and 2 <= len(s) <= 40 and not s.isdigit():
            out["title"] = s
            continue
        if "author" not in out and re.fullmatch(r"[\u4e00-\u9fff·]{2,6}", s):
            out["author"] = s
        if len(out) == 2:
            break
    return out

VISION_TOC_PROMPT = """这是一本书的目录页图片。请逐条解析目录条目。
规则：
1. 每条输出：level（1=章，2=节，3=小节，按缩进与编号判断）、title（条目文字，保持原文语言）、book_page（目录中标注的书页码整数；没有页码填 null）。
2. 忽略页眉、页脚、页码行本身的装饰点线。
3. 只输出严格 JSON 数组，不要任何解释：
[{"level": 1, "title": "...", "book_page": 1}]"""

VISION_TOC_PROBE_PROMPT = """这是数学书的一页图片。判断它是否是目录页（Contents/目录）。
若不是目录页，只输出 []。
若是目录页，逐条解析条目并输出严格 JSON 数组：
[{"level": 1, "title": "...", "book_page": 1}]
level：1=章，2=节，3=小节；book_page 为目录中标注的书页码（没有则 null）。"""

VISION_META_PROMPT = """这是数学书的封面或扉页图片。请提取书名、作者、出版社。
只输出严格 JSON：{"title": "...", "author": "...", "publisher": "..."}
提取不到的字段填 null。书名保持原文语言，不要翻译。"""


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "")).lower()


_JUNK_TITLE = re.compile(
    r"\.(dvi|tex|pdf|docx?)$|^unsaved|^untitled|^document$|^unknown$|^\d+$",
    re.I,
)
_NONCHAPTER_TITLE = re.compile(
    r"^(contents|目录|目次|index|索引|cover|封面|halftitle|titlepage)$"
)


def _clean_meta_title(raw: str | None) -> str | None:
    title = (raw or "").strip()
    if not title or _JUNK_TITLE.search(title):
        return None
    return title


def _parse_json_array(response: str) -> list:
    """Strict JSON array (or {\"items\": [...]}) with json-repair fallback."""
    if not response or not response.strip():
        return []
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "",
                  response.strip(), flags=re.I | re.M).strip()
    candidates = []
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        candidates.append(match.group())
    candidates.append(text)
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return [x for x in data["items"] if isinstance(x, dict)]
    try:
        import json_repair
        data = json_repair.loads(text)
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except Exception:
        log.exception("json-repair failed on structure output")
    return []


def _parse_json_object(response: str) -> dict:
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "",
                  (response or "").strip(), flags=re.I | re.M).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        data = json.loads(match.group() if match else text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        try:
            import json_repair
            data = json_repair.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def get_structure(book_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT data_json, confirmed, updated_at FROM book_structure WHERE book_id = ?",
        (book_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = json.loads(row["data_json"])
    d["confirmed"] = bool(row["confirmed"])
    d["updated_at"] = row["updated_at"]
    return d


def save_structure(book_id: str, data: dict, confirmed: bool | None = None) -> None:
    conn = get_db()
    if confirmed is None:
        row = conn.execute(
            "SELECT confirmed FROM book_structure WHERE book_id = ?", (book_id,)
        ).fetchone()
        confirmed = bool(row["confirmed"]) if row else False
    conn.execute(
        """INSERT INTO book_structure (book_id, data_json, confirmed, updated_at)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(book_id) DO UPDATE SET data_json = excluded.data_json,
             confirmed = excluded.confirmed, updated_at = CURRENT_TIMESTAMP""",
        (book_id, json.dumps(data, ensure_ascii=False), int(confirmed)),
    )
    conn.commit()
    conn.close()


def _page_texts_from_db(book_id: str) -> dict[int, str]:
    conn = get_db()
    rows = conn.execute(
        """SELECT page_no, text_raw FROM pages
           WHERE book_id = ? AND COALESCE(text_raw, '') != ''
             AND COALESCE(quality, 0) >= 0.55
           ORDER BY page_no""",
        (book_id,),
    ).fetchall()
    conn.close()
    return {r["page_no"]: r["text_raw"] for r in rows}


def _looks_like_toc_page(text: str) -> bool:
    return bool(TOC_PAGE_PATTERNS.search(text or ""))


def _detect_offset(page_texts: dict[int, str], toc_items: list[dict]) -> tuple[float | None, int]:
    """Match chapter titles against page text to find (book_page → pdf_page) offset."""
    titles = [
        _norm(it["title"]) for it in toc_items
        if it.get("book_page") is not None and len(_norm(it.get("title", ""))) >= 4
    ]
    if not titles:
        return None, 0

    # Pages that contain many of the TOC titles are the TOC itself — exclude.
    toc_like = set()
    for page_no, text in page_texts.items():
        head = _norm(text[:3000])
        hits = sum(1 for t in titles if t in head)
        if hits >= 3:
            toc_like.add(page_no)

    offsets = []
    for it in toc_items:
        t = _norm(it.get("title", ""))
        if it.get("book_page") is None or len(t) < 4:
            continue
        for page_no, text in sorted(page_texts.items()):
            if page_no in toc_like:
                continue
            if t in _norm(text[:220]):
                offsets.append(page_no - it["book_page"])
                break
    if not offsets:
        return None, 0
    offsets.sort()
    median = offsets[len(offsets) // 2]
    return float(median), len(offsets)


def _vision_toc_items(book_id: str, page_no: int) -> list[dict]:
    rendered = ps.render_page(book_id, page_no, zoom=2.0)
    if not rendered:
        return []
    data, _, _ = rendered
    llm = get_llm("structure")
    response = llm.chat_vision(VISION_TOC_PROMPT, data, max_tokens=8192)
    items = []
    for it in _parse_json_array(response):
        title = str(it.get("title", "")).strip()
        if not title:
            continue
        page = it.get("book_page")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        try:
            level = int(it.get("level", 1))
        except (TypeError, ValueError):
            level = 1
        items.append({"level": max(1, min(3, level)), "no": None, "title": title,
                      "book_page": page, "pdf_page": None})
    return items


def parse_toc_page(book_id: str, page_no: int) -> dict:
    """Manually designated TOC page → parsed entries (not saved). Text-layer
    pages parse locally; vision is the fallback for scanned/odd layouts."""
    doc = fitz.open(str(ps.pdf_path(book_id)))
    if page_no < 1 or page_no > len(doc):
        doc.close()
        return {"ok": True, "page_no": page_no, "items": []}
    text = _page_toc_text(doc[page_no - 1])
    doc.close()
    items: list[dict] = []
    if ps.text_quality(text) >= 0.55:
        items, _ = _local_toc_items(text)
    if not items:
        items = _vision_toc_items(book_id, page_no)
    offset = (get_structure(book_id) or {}).get("offset")
    if offset is not None:
        for it in items:
            if it["book_page"] is not None:
                it["pdf_page"] = it["book_page"] + offset
    return {"ok": True, "page_no": page_no, "items": items}


def detect_structure(book_id: str, task_id: str | None = None) -> dict:
    """Full detection pass. Degrades gracefully: whatever is found is saved as
    an unconfirmed draft; vision failures never raise."""
    from page_extractor import is_cancelled

    path = ps.pdf_path(book_id)
    doc = fitz.open(str(path))
    n_pages = len(doc)
    meta = doc.metadata or {}

    result = {
        "title": _clean_meta_title(meta.get("title")),
        "author": (meta.get("author") or "").strip() or None,
        "publisher": None,
        "offset": None,
        "offset_confidence": 0,
        "source": None,
        "toc": [],
    }

    toc_raw = doc.get_toc(simple=True)  # [level, title, 1-based page]
    if toc_raw:
        result["source"] = "bookmark"
        result["toc"] = [
            {"level": max(1, min(3, int(lvl))), "no": None, "title": str(title).replace("\x00", "").strip(),
             "book_page": None, "pdf_page": int(page)}
            for lvl, title, page in toc_raw if str(title).replace("\x00", "").strip()
        ]
        doc.close()
    else:
        # Locate the TOC page. Text-layer pages parse locally first (no model,
        # immune to LLM rate limits); vision is only the last resort.
        toc_page_no = None
        toc_page_text = ""
        seen_ch = 0
        scan = range(1, min(MAX_TOC_SCAN_PAGES, n_pages) + 1)
        for page_no in scan:
            if is_cancelled(task_id):
                doc.close()
                return {"cancelled": True}
            page = doc[page_no - 1]
            text = _page_toc_text(page)
            if ps.text_quality(text) < 0.55:
                continue
            local, seen_ch = _local_toc_items(text, seen_ch)
            if local:
                toc_page_no, toc_page_text = page_no, text
                break
            if toc_page_no is None and _looks_like_toc_page(text):
                toc_page_no, toc_page_text = page_no, text
        if toc_page_no is None:
            # Scanned book: probe the first pages with the vision model.
            for page_no in scan:
                if is_cancelled(task_id):
                    doc.close()
                    return {"cancelled": True}
                try:
                    items = _vision_probe_toc_page(book_id, page_no)
                except Exception as e:
                    log.warning("vision TOC probe failed p%s: %s", page_no, e)
                    items = None
                if items:
                    toc_page_no = page_no
                    result["source"] = "vision"
                    result["toc"] = items
                    break
        else:
            local, seen_ch = _local_toc_items(toc_page_text, seen_ch)
            # TOCs usually span several pages: keep parsing while entries flow.
            page_no = toc_page_no
            while local and page_no - toc_page_no < 10 and page_no < n_pages:
                page_no += 1
                more, seen_ch = _local_toc_items(_page_toc_text(doc[page_no - 1]), seen_ch)
                if not more:
                    break
                local.extend(more)
            if len(local) >= 5:
                result["source"] = "text"
                result["toc"] = local
            else:
                result["source"] = "vision"
                try:
                    result["toc"] = _vision_toc_items(book_id, toc_page_no)
                except Exception as e:
                    log.warning("vision TOC parse failed p%s: %s", toc_page_no, e)
                    result["toc"] = []
        doc.close()

    if is_cancelled(task_id):
        return {"cancelled": True}

    # Offset detection against the page text layer.
    if result["toc"] and any(it.get("book_page") is not None for it in result["toc"]):
        page_texts = _page_texts_from_db(book_id)
        offset, confidence = _detect_offset(page_texts, result["toc"])
        result["offset"] = offset
        result["offset_confidence"] = confidence
        if offset is not None:
            for it in result["toc"]:
                if it["pdf_page"] is None and it["book_page"] is not None:
                    it["pdf_page"] = it["book_page"] + offset

    # Cover fallback for title/author when metadata is empty: try the first
    # page's text layer locally (no model) before spending a vision call.
    if not result["title"] or not result["author"]:
        try:
            first_doc = fitz.open(str(path))
            first_text = first_doc[0].get_text("text") if n_pages else ""
            first_doc.close()
        except Exception:
            first_text = ""
        local_meta = _cover_meta_from_text(first_text) if ps.text_quality(first_text) >= 0.55 else {}
        if not result["title"] and local_meta.get("title"):
            result["title"] = local_meta["title"]
            result["source"] = result["source"] or "text"
        if not result["author"] and local_meta.get("author"):
            result["author"] = local_meta["author"]
    if not result["title"] or not result["author"]:
        try:
            rendered = ps.render_page(book_id, 1, zoom=1.5)
            if rendered:
                llm = get_llm("structure")
                resp = llm.chat_vision(VISION_META_PROMPT, rendered[0], max_tokens=512)
                parsed = _parse_json_object(resp)
                if not result["title"] and parsed.get("title"):
                    result["title"] = str(parsed["title"]).strip()
                if not result["author"] and parsed.get("author"):
                    result["author"] = str(parsed["author"]).strip()
                if parsed.get("publisher"):
                    result["publisher"] = str(parsed["publisher"]).strip()
                if result["title"] or result["author"]:
                    result["source"] = result["source"] or "vision"
        except Exception as e:
            log.warning("vision cover meta failed for %s: %s", book_id, e)

    save_structure(book_id, result, confirmed=False)
    return {"ok": True, **result}


def _vision_probe_toc_page(book_id: str, page_no: int) -> list[dict] | None:
    """Vision probe: is this page a TOC? Returns items or None."""
    rendered = ps.render_page(book_id, page_no, zoom=2.0)
    if not rendered:
        return None
    llm = get_llm("structure")
    response = llm.chat_vision(VISION_TOC_PROBE_PROMPT, rendered[0], max_tokens=8192)
    if not response or not response.strip():
        return None
    items = []
    for it in _parse_json_array(response):
        title = str(it.get("title", "")).strip()
        if not title:
            continue
        page = it.get("book_page")
        try:
            page = int(page) if page is not None else None
        except (TypeError, ValueError):
            page = None
        try:
            level = int(it.get("level", 1))
        except (TypeError, ValueError):
            level = 1
        items.append({"level": max(1, min(3, level)), "no": None, "title": title,
                      "book_page": page, "pdf_page": None})
    return items or None


def confirm_structure(book_id: str) -> dict:
    """Write confirmed TOC entries into the graph as CHAPTER nodes.

    Re-runnable: previous toc-sourced CHAPTER nodes are replaced, so a
    re-confirm never duplicates. Edges attached to them cascade away.
    """
    st = get_structure(book_id)
    if not st:
        raise ValueError("no structure detected yet")
    toc = [it for it in (st.get("toc") or []) if it.get("pdf_page")]
    if not toc:
        raise ValueError("no TOC entries with a resolvable PDF page")

    conn = get_db()
    conn.execute(
        """DELETE FROM graph_edges WHERE source_id IN
             (SELECT id FROM graph_nodes WHERE book_id = ? AND entity_type = 'CHAPTER')
            OR target_id IN
             (SELECT id FROM graph_nodes WHERE book_id = ? AND entity_type = 'CHAPTER')""",
        (book_id, book_id),
    )
    conn.execute(
        "DELETE FROM graph_nodes WHERE book_id = ? AND entity_type = 'CHAPTER'",
        (book_id,),
    )
    created = 0
    skipped = 0
    for idx, it in enumerate(toc):
        pdf_page = int(it["pdf_page"])
        if not it.get("title") or _NONCHAPTER_TITLE.match(_norm(it["title"])):
            skipped += 1
            continue
        nxt = toc[idx + 1]["pdf_page"] if idx + 1 < len(toc) else None
        page_end = max(pdf_page, int(nxt) - 1) if nxt and int(nxt) > pdf_page else pdf_page
        conn.execute(
            """INSERT INTO graph_nodes
               (id, book_id, entity_type, name, content, chapter, metadata,
                page_start, page_end, review_status, source_quote, created_by)
               VALUES (?, ?, 'CHAPTER', ?, '', ?, ?, ?, ?, 'confirmed', NULL, 'human')""",
            (str(uuid.uuid4()), book_id, it["title"],
             f"p{pdf_page}-{page_end}",
             json.dumps({"source": "toc", "book_page": it.get("book_page"),
                         "level": it.get("level", 1)}, ensure_ascii=False),
             pdf_page, page_end),
        )
        created += 1
    sync_book_counts(conn, book_id)
    conn.commit()
    conn.close()
    save_structure(book_id, st, confirmed=True)
    return {"ok": True, "chapters_created": created, "skipped_nonchapter": skipped}
