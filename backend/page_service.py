"""Page-level PDF access.

PyMuPDF is the single source of truth for both the rendered page image and the
extracted text (with bounding boxes). The frontend never parses the PDF itself,
so the original page and the editable text can never drift apart.
"""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf as fitz

import env_service
from config import settings
from database import get_db

_SUSPICIOUS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd\uE000-\uF8FF]")
_DOT_LEADER = re.compile(r"[0OＯ.．·…]{4,}")
BAD_PAGE_QUALITY = 0.55
MIN_CHARS = 40


def pdf_path(book_id: str) -> Path:
    return settings.data_dir / "books" / f"{book_id}.pdf"


def text_quality(text: str) -> float:
    """Heuristic score in [0, 1] for how trustworthy the text layer is."""
    if not text or not text.strip():
        return 0.0
    n = len(text)
    penalty = min(0.5, len(_SUSPICIOUS.findall(text)) / n * 10)
    penalty += min(0.6, len(_DOT_LEADER.findall(text)) * 0.06)
    if n < 80:
        penalty += 0.3
    return round(max(0.0, 1.0 - penalty), 3)


def _blocks(page) -> list[dict]:
    out = []
    for block in page.get_text("dict").get("blocks", []):
        if "lines" not in block:
            continue
        text = "\n".join(
            "".join(span["text"] for span in line["spans"])
            for line in block["lines"]
        ).strip()
        if not text:
            continue
        x0, y0, x1, y1 = block["bbox"]
        out.append({
            "x0": round(x0, 1), "y0": round(y0, 1),
            "x1": round(x1, 1), "y1": round(y1, 1),
            "text": text,
        })
    return out


def import_pages(book_id: str, filepath: str | Path) -> int:
    """Extract text + bboxes for every page and populate the pages table."""
    doc = fitz.open(str(filepath))
    conn = get_db()
    rows = []
    for i, page in enumerate(doc):
        blocks = _blocks(page)
        text = "\n".join(b["text"] for b in blocks)
        quality = text_quality(text)
        status = "bad_page" if (quality < BAD_PAGE_QUALITY or len(text) < MIN_CHARS) else "extracted"
        rows.append((
            book_id, i + 1, text, None, json.dumps(blocks, ensure_ascii=False),
            len(text), quality, status, None,
        ))
    doc.close()
    conn.executemany(
        """INSERT INTO pages
           (book_id, page_no, text_raw, text_corrected, blocks_json,
            char_count, quality, status, ocr_confidence)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(book_id, page_no) DO UPDATE SET
             text_raw = excluded.text_raw,
             blocks_json = excluded.blocks_json,
             char_count = excluded.char_count,
             quality = excluded.quality,
             status = excluded.status,
             layout_json = NULL,
             layout_text = NULL,
             updated_at = CURRENT_TIMESTAMP""",
        rows,
    )
    conn.execute("UPDATE books SET chunk_total = ? WHERE id = ?", (len(rows), book_id))
    conn.commit()
    conn.close()
    return len(rows)


def list_pages(book_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT page_no, char_count, quality, status, ocr_confidence,
                  (text_corrected IS NOT NULL) AS edited
           FROM pages WHERE book_id = ? ORDER BY page_no""",
        (book_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _page_geometry(book_id: str, page_no: int) -> tuple[float, float] | None:
    """PDF point size of one page. Cheap: opens the PDF, never recognizes."""
    path = pdf_path(book_id)
    if not path.exists():
        return None
    try:
        doc = fitz.open(str(path))
        try:
            if 0 <= page_no - 1 < len(doc):
                r = doc[page_no - 1].rect
                return r.width, r.height
        finally:
            doc.close()
    except Exception:
        return None


def get_page_meta(book_id: str, page_no: int) -> dict | None:
    """Lightweight page shell: geometry + status, with NO layout recognition.

    The workbench renders the original page image as soon as this returns;
    the extracted text follows later from get_page()/ensure_layout(). Keeping
    the two apart means a 3-16 s recognition pass no longer blanks the page.
    """
    conn = get_db()
    row = conn.execute(
        "SELECT status, quality FROM pages WHERE book_id = ? AND page_no = ?",
        (book_id, page_no),
    ).fetchone()
    conn.close()
    if not row:
        return None
    out: dict = {"page_no": page_no, "status": row["status"],
                 "quality": row["quality"]}
    geom = _page_geometry(book_id, page_no)
    if geom:
        out["page_width"], out["page_height"] = geom
    return out


def get_page(book_id: str, page_no: int) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM pages WHERE book_id = ? AND page_no = ?", (book_id, page_no)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["blocks"] = json.loads(d.pop("blocks_json") or "[]")
    layout = ensure_layout(book_id, page_no)
    d.pop("layout_json", None)
    d["layout"] = layout
    d["layout_text"] = render_layout_text(layout) if layout else (d.get("text_corrected") or d.get("text_raw") or "")
    d["page_kind"] = layout["page_kind"] if layout else "text_layer"
    d["needs_vision"] = bool(layout["needs_vision"]) if layout else False
    d["text"] = d.get("text_corrected") or d.get("text_raw") or ""
    d["text_raw_present"] = bool(d.get("text_raw"))
    # Rule-based theorem-environment detection (definition/theorem/proof/...).
    # A derivation with its own memo cache -- never touches ensure_layout,
    # costs ~70 ms on an uncached page and 0 ms once seen this session.
    d["environments"] = env_service.detect_environments(
        book_id, page_no, d["blocks"])
    # PDF point dimensions, so the frontend can overlay block bboxes on the
    # rendered page image using simple percentages.
    geom = _page_geometry(book_id, page_no)
    if geom:
        d["page_width"], d["page_height"] = geom
    return d


# --- Adjacent-page prefetch -------------------------------------------------
# A fresh page costs 3-16 s (ONNX layout + per-formula LaTeX OCR, plus a full
# RapidOCR pass on fragmented pages). Sequential reading is the common case,
# so compute the next two pages in ONE background worker; the foreground
# request never waits for them, and cached pages are skipped entirely.
_prefetch_lock = threading.Lock()
_prefetch_queued: set[tuple[str, int]] = set()
_prefetch_pool = ThreadPoolExecutor(max_workers=1,
                                    thread_name_prefix="layout-prefetch")


def prefetch_layout(book_id: str, page_nos: list[int]) -> None:
    pages = [n for n in page_nos if n > 0]
    if not pages:
        return
    import page_layout as L  # local import: page_layout imports this module
    conn = get_db()
    rows = conn.execute(
        "SELECT page_no, layout_json FROM pages WHERE book_id = ? "
        "AND page_no IN (%s)" % ",".join("?" * len(pages)),
        (book_id, *pages),
    ).fetchall()
    conn.close()
    for row in rows:
        cached = None
        if row["layout_json"]:
            try:
                cached = json.loads(row["layout_json"])
            except (ValueError, TypeError):
                pass
        if cached and cached.get("version") == L.LAYOUT_VERSION:
            continue
        key = (book_id, row["page_no"])

        def _run(k=key, b=book_id, p=row["page_no"]):
            try:
                ensure_layout(b, p)
            except Exception:
                pass
            finally:
                with _prefetch_lock:
                    _prefetch_queued.discard(k)

        with _prefetch_lock:
            if key in _prefetch_queued:
                continue
            _prefetch_queued.add(key)
        _prefetch_pool.submit(_run)


def ensure_layout(book_id: str, page_no: int) -> dict | None:
    """Lazily build and cache the typed layout for one page. Layout is derived
    from the PDF, so it never depends on a possibly-edited flat text dump.
    Cached layouts from older pipeline versions are rebuilt transparently."""
    import page_layout as L  # local import: page_layout imports this module

    conn = get_db()
    row = conn.execute(
        "SELECT layout_json FROM pages WHERE book_id = ? AND page_no = ?",
        (book_id, page_no),
    ).fetchone()
    conn.close()
    if not row:
        return None
    if row["layout_json"]:
        try:
            cached = json.loads(row["layout_json"])
            if cached.get("version") == L.LAYOUT_VERSION:
                return cached
        except (ValueError, TypeError):
            pass
    try:
        layout = L.build_layout(book_id, page_no)
        layout_json, layout_text = L.to_storage(layout)
    except Exception:
        return None
    conn = get_db()
    conn.execute(
        """UPDATE pages SET layout_json = ?, layout_text = ?, page_kind = ?,
                            needs_vision = ?
           WHERE book_id = ? AND page_no = ?""",
        (layout_json, layout_text, layout["page_kind"], int(layout["needs_vision"]),
         book_id, page_no),
    )
    conn.commit()
    conn.close()
    return layout


def render_layout_text(layout: dict, include_figure: bool = False) -> str:
    import page_layout as L
    return L.render_layout_text(layout, include_figure)


def clear_layout(book_id: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE pages SET layout_json = NULL, layout_text = NULL WHERE book_id = ?",
        (book_id,),
    )
    conn.commit()
    conn.close()


def save_page_text(book_id: str, page_no: int, text: str,
                   status: str, confidence: float | None = None) -> bool:
    conn = get_db()
    cur = conn.execute(
        """UPDATE pages SET text_corrected = ?, status = ?, ocr_confidence = ?,
                            updated_at = CURRENT_TIMESTAMP
           WHERE book_id = ? AND page_no = ?""",
        (text, status, confidence, book_id, page_no),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def render_page(book_id: str, page_no: int, zoom: float = 1.3) -> tuple[bytes, int, int] | None:
    path = pdf_path(book_id)
    if not path.exists():
        return None
    doc = fitz.open(str(path))
    if page_no < 1 or page_no > len(doc):
        doc.close()
        return None
    pix = doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    data = pix.tobytes("png")
    w, h = pix.width, pix.height
    doc.close()
    return data, w, h


def window_text(book_id: str, start: int, end: int) -> str:
    """Text of an inclusive page window as TYPED BLOCKS.

    Structured layout is preferred: headings, tables, formulas and (excluded)
    figure labels. Pages manually corrected by a human still win, because the
    human's text is authoritative over any re-derivation.
    """
    conn = get_db()
    rows = conn.execute(
        """SELECT page_no, COALESCE(text_corrected, text_raw, '') AS text,
                  text_corrected IS NOT NULL AS edited, layout_text
           FROM pages WHERE book_id = ? AND page_no BETWEEN ? AND ?
           ORDER BY page_no""",
        (book_id, start, end),
    ).fetchall()
    conn.close()

    out = []
    for r in rows:
        if r["edited"]:
            body = "[EDITED] " + r["text"]
        elif r["layout_text"]:
            body = r["layout_text"]
        else:
            layout = ensure_layout(book_id, r["page_no"])
            body = render_layout_text(layout) if layout else r["text"]
        if body.strip():
            out.append(f"[p{r['page_no']}]\n{body}")
    return "\n\n".join(out)
