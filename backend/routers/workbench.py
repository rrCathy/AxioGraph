"""Human-in-the-loop workbench endpoints."""
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
import uuid

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
def extract(book_id: str, body: ExtractRequest,
            x_task_id: str | None = Header(default=None)):
    _require_book(book_id)
    task_id = x_task_id or str(uuid.uuid4())
    pe.register_task(task_id)
    try:
        return pe.extract_window(book_id, body.start, body.end, task_id)
    except ValueError as e:
        pe.clear_task(task_id)
        raise HTTPException(400, str(e))
    except Exception:
        pe.clear_task(task_id)
        raise


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
           ORDER BY name LIMIT 500""",
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
    result = pe.reject_candidate(candidate_id)
    if not result.get("ok"):
        raise HTTPException(404, "Pending candidate not found")
    return result


@router.post("/api/candidates/{candidate_id}/merge")
def merge(candidate_id: str, body: MergeRequest):
    result = pe.merge_candidate(candidate_id, body.node_id)
    if not result.get("ok"):
        raise HTTPException(404, "Pending candidate or target node not found")
    return {**result, "merged_into": body.node_id}


@router.get("/api/candidates/{candidate_id}/preview")
def preview(candidate_id: str):
    result = pe.preview_candidate(candidate_id)
    if result is None:
        raise HTTPException(404, "Candidate not found")
    return result


@router.post("/api/actions/{token}/undo")
def undo(token: str):
    if not pe.undo_action(token):
        raise HTTPException(410, "Undo expired or already applied")
    return {"ok": True}


@router.post("/api/tasks/{task_id}/cancel")
def cancel(task_id: str):
    return {"ok": pe.cancel_task(task_id), "cancelled": True}


@router.delete("/api/books/{book_id}/confirmed-nodes")
def clear_confirmed_nodes(book_id: str):
    _require_book(book_id)
    conn = get_db()
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM graph_nodes WHERE book_id = ? AND review_status = 'confirmed'",
        (book_id,),
    )]
    for node_id in ids:
        conn.execute("DELETE FROM graph_edges WHERE source_id = ? OR target_id = ?",
                     (node_id, node_id))
    conn.execute("DELETE FROM graph_nodes WHERE book_id = ? AND review_status = 'confirmed'",
                 (book_id,))
    from graph_store import sync_book_counts
    sync_book_counts(conn, book_id)
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": len(ids)}
