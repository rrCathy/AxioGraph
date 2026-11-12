import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from config import settings
from database import get_db
from pathlib import Path
import page_service as ps

router = APIRouter(prefix="/api/books", tags=["books"])


class BookResponse(BaseModel):
    id: str
    title: str
    filename: str
    language: str
    status: str
    progress: int = 0
    node_count: int = 0
    edge_count: int = 0
    chunk_total: int = 0
    chunk_done: int = 0
    created_at: str = ""


@router.post("/upload")
async def upload_book(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")

    book_id = str(uuid.uuid4())
    save_dir = settings.data_dir / "books"
    save_dir.mkdir(exist_ok=True)
    filepath = save_dir / f"{book_id}.pdf"

    content = await file.read()
    filepath.write_bytes(content)

    title = file.filename.replace(".pdf", "").replace("_", " ").strip()

    conn = get_db()
    conn.execute(
        "INSERT INTO books (id, title, filename, status) VALUES (?, ?, ?, 'importing')",
        (book_id, title, file.filename)
    )
    conn.commit()
    conn.close()

    # Page-level workflow: import text + bounding boxes only. No LLM call,
    # no whole-book extraction. The human decides which 1-3 pages to analyze.
    page_count = 0
    try:
        page_count = ps.import_pages(book_id, filepath)
        status = "ready"
    except Exception as e:
        status = f"error: page import failed: {str(e)[:160]}"

    conn = get_db()
    conn.execute("UPDATE books SET status = ? WHERE id = ?", (status, book_id))
    conn.commit()
    conn.close()

    return {"id": book_id, "title": title, "status": status, "page_count": page_count}


@router.get("/")
def list_books():
    conn = get_db()
    rows = conn.execute("SELECT * FROM books ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/{book_id}")
def get_book(book_id: str):
    conn = get_db()
    book = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    conn.close()
    if not book:
        raise HTTPException(404, "Book not found")
    return dict(book)


@router.get("/{book_id}/status")
def get_status(book_id: str):
    conn = get_db()
    book = conn.execute(
        "SELECT status, progress, node_count, edge_count, chunk_total, chunk_done "
        "FROM books WHERE id = ?",
        (book_id,),
    ).fetchone()
    conn.close()
    if not book:
        raise HTTPException(404, "Book not found")
    return {
        "status": book["status"],
        "progress": book["progress"],
        "node_count": book["node_count"],
        "edge_count": book["edge_count"],
        "chunk_total": book["chunk_total"],
        "chunk_done": book["chunk_done"],
        "elapsed": 0,
        "eta": 0,
    }


@router.delete("/{book_id}")
def delete_book(book_id: str):
    conn = get_db()
    # action_log has no FK to books — clean it explicitly; everything else
    # cascades, but delete the big tables explicitly for clarity.
    conn.execute("DELETE FROM action_log WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM graph_edges WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM graph_nodes WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM candidates WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM pages WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM chapters WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM book_structure WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    return {"ok": True}
