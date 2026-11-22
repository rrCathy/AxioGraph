"""Section-scoped context for selection Q&A.

"这一小节" is resolved from the confirmed/bookmarked TOC (toc_full): the
finest entry whose pdf_page covers the current page, ending at the next entry
of the same or a shallower level. When the structure is not confirmed, fall
back to the layout heading on the page, then to the neighbouring pages.

The text is gathered from the pages table (text_corrected first, then
text_raw) — never from OCR output written back by the model, never from the
layout cache — so the context always reflects what the user can see and edit.
"""
from __future__ import annotations

from database import get_db

MAX_CONTEXT_CHARS = 5000
MAX_SECTION_PAGES = 40


def _toc_section(book_id: str, page_no: int, total: int) -> dict | None:
    """Finest TOC entry covering page_no → {title, start, end}."""
    import book_structure as bs
    st = bs.get_structure(book_id) or {}
    toc = st.get("toc_full") or st.get("toc") or []
    entries = []
    for i, it in enumerate(toc):
        p = it.get("pdf_page")
        if p is None:
            continue
        entries.append({"order": i, "pdf_page": int(p), "level": int(it.get("level") or 1),
                        "title": (it.get("title") or "").strip()})
    if not entries:
        return None
    entries.sort(key=lambda e: (e["pdf_page"], e["order"]))
    current = None
    for e in entries:
        if e["pdf_page"] <= page_no:
            current = e
        else:
            break
    if current is None:
        return None
    end = total
    for e in entries:
        if e["pdf_page"] > current["pdf_page"] and e["level"] <= current["level"]:
            end = e["pdf_page"] - 1
            break
    if end < current["pdf_page"]:
        end = current["pdf_page"]
    # A level-1 chapter entry would drag in the whole chapter; cap the span.
    if end - current["pdf_page"] + 1 > MAX_SECTION_PAGES:
        end = current["pdf_page"] + MAX_SECTION_PAGES - 1
    return {"title": current["title"], "start": current["pdf_page"], "end": end,
            "source": "toc"}


def _layout_section(conn, book_id: str, page_no: int) -> dict | None:
    """Nearest heading on the page → its section name (cached layout only,
    never triggers recognition — context building must stay fast)."""
    row = conn.execute(
        "SELECT layout_json FROM pages WHERE book_id = ? AND page_no = ?",
        (book_id, page_no),
    ).fetchone()
    if not row or not row["layout_json"]:
        return None
    import json
    try:
        layout = json.loads(row["layout_json"])
    except Exception:
        return None
    blocks = layout.get("blocks") or []
    section = None
    for b in blocks:
        if b.get("type") == "H":
            section = (b.get("text") or b.get("section") or "").strip() or section
        elif b.get("section"):
            section = b["section"]
    if not section:
        return None
    return {"title": section, "start": page_no, "end": page_no, "source": "layout"}


def _page_texts(conn, book_id: str, start: int, end: int) -> list[tuple[int, str]]:
    rows = conn.execute(
        """SELECT page_no, COALESCE(text_corrected, text_raw, '') AS text
           FROM pages WHERE book_id = ? AND page_no BETWEEN ? AND ?""",
        (book_id, start, end),
    ).fetchall()
    return [(r["page_no"], (r["text"] or "").strip()) for r in rows
            if (r["text"] or "").strip()]


def build_section_context(book_id: str, page_no: int) -> dict:
    """Return {title, source, start, end, text, pages_used, chars}."""
    conn = get_db()
    total_row = conn.execute(
        "SELECT COALESCE(MAX(page_no), page_no) AS t FROM pages WHERE book_id = ?",
        (book_id,)).fetchone()
    total = (total_row["t"] if total_row else page_no) or page_no

    section = _toc_section(book_id, page_no, total) \
        or _layout_section(conn, book_id, page_no) \
        or {"title": "", "start": max(1, page_no - 1), "end": min(total, page_no + 1),
            "source": "neighbours"}

    pairs = _page_texts(conn, book_id, section["start"], section["end"])
    conn.close()
    if not pairs:
        pairs = [(page_no, "")]
    # Keep whole pages, nearest to the current page first, until the budget
    # runs out; then re-sort for reading order.
    pairs.sort(key=lambda p: (abs(p[0] - page_no), p[0]))
    kept: list[tuple[int, str]] = []
    budget = MAX_CONTEXT_CHARS
    for pno, text in pairs:
        if budget <= 0:
            break
        kept.append((pno, text[:budget]))
        budget -= len(text) + 2
    kept.sort(key=lambda p: p[0])
    body = "\n\n".join(f"[p{pno}]\n{text}" for pno, text in kept)
    return {
        "title": section["title"],
        "source": section["source"],
        "start": section["start"],
        "end": section["end"],
        "pages_used": [p for p, _ in kept],
        "text": body,
        "chars": len(body),
    }
