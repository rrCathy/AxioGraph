"""Page-level workbench API: original page, editable text, OCR hand-off."""
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from database import get_db
import page_service as ps

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
def import_pages_for_book(book_id: str):
    """(Re)build the per-page text index for an already uploaded PDF."""
    _require_book(book_id)
    path = ps.pdf_path(book_id)
    if not path.exists():
        raise HTTPException(404, f"PDF missing: {path.name}")
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
    return page


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


@router.get("/{book_id}/pages/{page_no}/render")
def render_page(book_id: str, page_no: int, zoom: float = 1.3):
    rendered = ps.render_page(book_id, page_no, min(max(zoom, 0.5), 3.0))
    if not rendered:
        raise HTTPException(404, "Page not found or PDF missing")
    data, _, _ = rendered
    return Response(content=data, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})
