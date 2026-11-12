"""Book structure endpoints: detect / edit / confirm TOC → chapter nodes."""
import uuid

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

import book_structure as bs
import page_extractor as pe

router = APIRouter(tags=["structure"])


class StructureData(BaseModel):
    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    offset: float | None = None
    source: str | None = None
    toc: list[dict] = []


class TocPageRequest(BaseModel):
    page_no: int


def _require_book(book_id: str):
    from database import get_db
    conn = get_db()
    row = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Book not found")


@router.get("/api/books/{book_id}/structure")
def get_structure(book_id: str):
    _require_book(book_id)
    st = bs.get_structure(book_id)
    if st is None:
        return {"title": None, "author": None, "publisher": None, "offset": None,
                "source": None, "toc": [], "confirmed": False}
    return st


@router.post("/api/books/{book_id}/structure/detect")
def detect_structure(book_id: str, x_task_id: str | None = Header(default=None)):
    _require_book(book_id)
    task_id = x_task_id or str(uuid.uuid4())
    pe.register_task(task_id)
    try:
        result = bs.detect_structure(book_id, task_id)
        if result.get("cancelled"):
            return {"cancelled": True, "task_id": task_id}
        return {"ok": True, "task_id": task_id, **result}
    except Exception as e:
        raise HTTPException(500, f"structure detection failed: {str(e)[:200]}")
    finally:
        pe.clear_task(task_id)


@router.post("/api/books/{book_id}/structure")
def save_structure(book_id: str, body: StructureData):
    _require_book(book_id)
    bs.save_structure(book_id, body.model_dump())
    return bs.get_structure(book_id)


@router.post("/api/books/{book_id}/structure/confirm")
def confirm_structure(book_id: str):
    _require_book(book_id)
    try:
        return bs.confirm_structure(book_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/books/{book_id}/structure/toc-page")
def parse_toc_page(book_id: str, body: TocPageRequest):
    _require_book(book_id)
    try:
        return bs.parse_toc_page(book_id, body.page_no)
    except Exception as e:
        raise HTTPException(500, f"TOC page parse failed: {str(e)[:200]}")
