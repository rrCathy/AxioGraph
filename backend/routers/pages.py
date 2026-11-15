"""Page-level workbench API: original page, editable text, OCR hand-off."""
from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel

from database import get_db
import page_service as ps
import page_extractor as pe
import vision as vo

router = APIRouter(prefix="/api/books", tags=["pages"])


class TextUpdate(BaseModel):
    text: str
    status: str = "reviewed"


class OcrResult(BaseModel):
    text: str
    confidence: float = 0.0


def _require_book(book_id: str):
    conn = get_db()
    row = conn.execute("SELECT id, title FROM books WHERE id = ?", (book_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Book not found")
    return row


@router.post("/{book_id}/import-pages")
def import_pages_for_book(book_id: str, dry_run: bool = False):
    """(Re)build the per-page text index. dry_run reports the effect without
    writing: raw text/blocks/status are overwritten, corrected text is kept."""
    _require_book(book_id)
    path = ps.pdf_path(book_id)
    if not path.exists():
        raise HTTPException(404, f"PDF missing: {path.name}")
    if dry_run:
        import pymupdf as fitz
        doc = fitz.open(str(path))
        count = len(doc)
        doc.close()
        conn = get_db()
        edited = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE book_id = ? AND text_corrected IS NOT NULL",
            (book_id,),
        ).fetchone()[0]
        conn.close()
        return {"ok": True, "dry_run": True, "page_count": count,
                "edited_pages_preserved": edited}
    count = ps.import_pages(book_id, path)
    return {"ok": True, "page_count": count}


@router.get("/{book_id}/pages")
def list_pages(book_id: str):
    _require_book(book_id)
    return {"pages": ps.list_pages(book_id)}


@router.get("/{book_id}/pages/{page_no}")
def get_page(book_id: str, page_no: int):
    page = ps.get_page(book_id, page_no)
    if not page:
        raise HTTPException(404, "Page not found or not imported")
    # Warm the next two pages in a single background worker so sequential
    # flipping never waits for recognition again.
    ps.prefetch_layout(book_id, [page_no + 1, page_no + 2])
    return page


@router.get("/{book_id}/pages/{page_no}/meta")
def get_page_meta(book_id: str, page_no: int):
    """Page geometry only — never triggers layout recognition. The frontend
    uses this to show the original page before the slow text extraction."""
    meta = ps.get_page_meta(book_id, page_no)
    if not meta:
        raise HTTPException(404, "Page not found or not imported")
    return meta


@router.put("/{book_id}/pages/{page_no}")
def update_page(book_id: str, page_no: int, body: TextUpdate):
    if not ps.save_page_text(book_id, page_no, body.text, body.status):
        raise HTTPException(404, "Page not found")
    return {"ok": True, "status": body.status}


@router.post("/{book_id}/pages/{page_no}/ocr")
def accept_ocr(book_id: str, page_no: int, body: OcrResult):
    """Frontend Tesseract result. Low confidence or empty text falls back to
    manual entry by keeping the page in bad_page state."""
    text = body.text.strip()
    usable = bool(text) and body.confidence >= 55
    status = "ocr" if usable else "bad_page"
    if not ps.save_page_text(book_id, page_no, text, status, body.confidence or None):
        raise HTTPException(404, "Page not found")
    return {"ok": True, "status": status, "needs_manual": not usable}


@router.get("/{book_id}/pages/{page_no}/layout")
def get_page_layout(book_id: str, page_no: int, include_figure: bool = False):
    """Typed layout blocks (heading/table/formula/figure) with bboxes."""
    layout = ps.ensure_layout(book_id, page_no)
    if layout is None:
        raise HTTPException(404, "Page not found or layout unavailable")
    return {**layout,
            "layout_text": ps.render_layout_text(layout, include_figure)}


@router.post("/{book_id}/relayout")
def relayout(book_id: str):
    """Discard cached layouts so the next read re-derives them from the PDF."""
    _require_book(book_id)
    ps.clear_layout(book_id)
    return {"ok": True}


@router.post("/{book_id}/pages/{page_no}/vision-ocr")
def vision_ocr(book_id: str, page_no: int,
               x_task_id: str | None = Header(default=None)):
    """Server-side vision-model transcription for scanned pages.

    X-Task-Id enables cooperative cancellation while the model is busy; a
    failed/empty transcription leaves the page untouched (manual entry path).
    """
    task_id = x_task_id or None
    if task_id:
        pe.register_task(task_id)
    try:
        result = vo.ocr_page(book_id, page_no, task_id)
    except Exception:
        pe.clear_task(task_id)
        raise
    if not result.get("ok") and not result.get("cancelled") \
            and result.get("error") == "page not found":
        pe.clear_task(task_id)
        raise HTTPException(404, "Page not found or PDF missing")
    return result


@router.get("/{book_id}/pages/{page_no}/render")
def render_page(book_id: str, page_no: int, zoom: float = 1.3):
    rendered = ps.render_page(book_id, page_no, min(max(zoom, 0.5), 3.0))
    if not rendered:
        raise HTTPException(404, "Page not found or PDF missing")
    data, _, _ = rendered
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})
