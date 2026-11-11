"""Human-in-the-loop workbench endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
import page_extractor as pe

router = APIRouter(tags=["workbench"])


class ExtractRequest(BaseModel):
    start: int
    end: int


class ConfirmRequest(BaseModel):
    name: str | None = None
    quote: str | None = None


class MergeRequest(BaseModel):
    node_id: str


def _require_book(book_id: str):
    conn = get_db()
    row = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Book not found")


@router.post("/api/books/{book_id}/extract")
def extract(book_id: str, body: ExtractRequest):
    _require_book(book_id)
    try:
        return pe.extract_window(book_id, body.start, body.end)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/books/{book_id}/candidates")
def candidates(book_id: str, status: str = "pending"):
    _require_book(book_id)
    return {"candidates": pe.list_candidates(book_id, status)}


@router.get("/api/books/{book_id}/confirmed-nodes")
def confirmed_nodes(book_id: str, q: str = ""):
    _require_book(book_id)
    conn = get_db()
    rows = conn.execute(
        """SELECT id, name, entity_type, page_start, page_end FROM graph_nodes
           WHERE book_id = ? AND review_status = 'confirmed' AND name LIKE ?
           ORDER BY name LIMIT 100""",
        (book_id, f"%{q}%"),
    ).fetchall()
    conn.close()
    return {"nodes": [dict(r) for r in rows]}


@router.post("/api/candidates/{candidate_id}/confirm")
def confirm(candidate_id: str, body: ConfirmRequest | None = None):
    result = pe.confirm_candidate(candidate_id, body.name if body else None,
                                  body.quote if body else None)
    if result is None:
        raise HTTPException(404, "Candidate not found")
    return result


@router.post("/api/candidates/{candidate_id}/reject")
def reject(candidate_id: str):
    if not pe.reject_candidate(candidate_id):
        raise HTTPException(404, "Pending candidate not found")
    return {"ok": True}


@router.post("/api/candidates/{candidate_id}/merge")
def merge(candidate_id: str, body: MergeRequest):
    if not pe.merge_candidate(candidate_id, body.node_id):
        raise HTTPException(404, "Pending candidate or target node not found")
    return {"ok": True, "merged_into": body.node_id}
