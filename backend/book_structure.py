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
        items.append({"level": max(1, min(3, level)), "title": title,
                      "book_page": page, "pdf_page": None})
    return items


def parse_toc_page(book_id: str, page_no: int) -> dict:
    """Manually designated TOC page → vision-parsed entries (not saved)."""
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
        "title": (meta.get("title") or "").strip() or None,
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
            {"level": max(1, min(3, int(lvl))), "title": str(title).strip(),
             "book_page": None, "pdf_page": int(page)}
            for lvl, title, page in toc_raw if str(title).strip()
        ]
        doc.close()
    else:
        # Locate the TOC page: text-layer hit first, then vision probes.
        toc_page_no = None
        scan = range(1, min(MAX_TOC_SCAN_PAGES, n_pages) + 1)
        for page_no in scan:
            rendered = ps.render_page(book_id, page_no, zoom=1.0)
            page = doc[page_no - 1]
            text = page.get_text("text") or ""
            if _looks_like_toc_page(text) and ps.text_quality(text) >= 0.55:
                toc_page_no = page_no
                break
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

    # Cover fallback for title/author when metadata is empty.
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
        items.append({"level": max(1, min(3, level)), "title": title,
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
    for idx, it in enumerate(toc):
        pdf_page = int(it["pdf_page"])
        nxt = toc[idx + 1]["pdf_page"] if idx + 1 < len(toc) else None
        page_end = max(pdf_page, int(nxt) - 1) if nxt and int(nxt) > pdf_page else pdf_page
        conn.execute(
            """INSERT INTO graph_nodes
               (id, book_id, entity_type, name, content, chapter, metadata,
                page_start, page_end, review_status, source_quote, created_by)
               VALUES (?, ?, 'CHAPTER', ?, '', ?, ?, ?, 'confirmed', NULL, 'human')""",
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
    return {"ok": True, "chapters_created": created}
