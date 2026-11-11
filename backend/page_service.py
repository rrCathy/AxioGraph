"""Page-level PDF access.

PyMuPDF is the single source of truth for both the rendered page image and the
extracted text (with bounding boxes). The frontend never parses the PDF itself,
so the original page and the editable text can never drift apart.
"""
import json
import re
from pathlib import Path

import pymupdf as fitz

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
    d["text"] = d.get("text_corrected") or d.get("text_raw") or ""
    d["text_raw_present"] = bool(d.get("text_raw"))
    # PDF point dimensions, so the frontend can overlay block bboxes on the
    # rendered page image using simple percentages.
    path = pdf_path(book_id)
    if path.exists():
        try:
            doc = fitz.open(str(path))
            if 0 <= page_no - 1 < len(doc):
                rect = doc[page_no - 1].rect
                d["page_width"], d["page_height"] = rect.width, rect.height
            doc.close()
        except Exception:
            pass
    return d


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
    """Text of an inclusive page window, using corrected text when available."""
    conn = get_db()
    rows = conn.execute(
        """SELECT page_no, COALESCE(text_corrected, text_raw, '') AS text
           FROM pages WHERE book_id = ? AND page_no BETWEEN ? AND ?
           ORDER BY page_no""",
        (book_id, start, end),
    ).fetchall()
    conn.close()
    return "\n\n".join(f"[p{r['page_no']}] {r['text']}" for r in rows if r["text"].strip())
