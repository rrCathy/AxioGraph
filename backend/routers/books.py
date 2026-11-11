import uuid
import threading
import time
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from database import get_db
from parser import parse_pdf, detect_language
from extractor import extract_from_chapters
from graph_store import save_nodes_and_edges
from config import settings
from pathlib import Path

router = APIRouter(prefix="/api/books", tags=["books"])

_progress: dict[str, dict] = {}
_pause_events: dict[str, threading.Event] = {}
_cancel_events: dict[str, threading.Event] = {}


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


def _check_llm():
    """Quick check if the extraction LLM is reachable. Returns (ok, error_msg)."""
    try:
        from services.llm import get_llm
        llm = get_llm("extraction")
        resp = llm.chat([{"role": "user", "content": "Say 1"}], temperature=0, max_tokens=2)
        if not resp or not resp.strip():
            return (False, "LLM returned empty response — model may be overloaded")
        return (True, None)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate" in msg.lower() or "访问量过大" in msg:
            return (False, "LLM rate limited — try again in a minute")
        if "401" in msg or "403" in msg or "auth" in msg.lower():
            return (False, "Invalid LLM API key — check backend/.env")
        if "connect" in msg.lower() or "timed out" in msg.lower() or "timeout" in msg.lower():
            return (False, "Cannot reach the configured LLM server — check "
                           "EXTRACTION_MODEL / base URL in backend/.env and whether "
                           "the local model service is running")
        return (False, f"{type(e).__name__}: {msg[:180]}")


def _process_book(book_id: str, filepath: str):
    """Background task: parse PDF and extract knowledge graph."""
    conn = get_db()
    start_time = time.time()
    pause_evt = threading.Event()
    pause_evt.set()  # not paused initially
    cancel_evt = threading.Event()
    _pause_events[book_id] = pause_evt
    _cancel_events[book_id] = cancel_evt
    try:
        conn.execute("UPDATE books SET status = 'checking' WHERE id = ?", (book_id,))
        conn.commit()

        llm_ok, llm_error = _check_llm()
        if not llm_ok:
            conn.execute(
                "UPDATE books SET status = ? WHERE id = ?",
                (f"error: {llm_error or 'LLM not reachable'}", book_id)
            )
            conn.commit()
            return

        conn.execute("UPDATE books SET status = 'parsing' WHERE id = ?", (book_id,))
        conn.commit()

        chapters = parse_pdf(filepath)

        # Select chapters with substantial content, including non-frontmatter ones
        # that were misclassified (common in Chinese math books).
        PREAMBLE_KEYWORDS = [
            'Contents', 'Preface', 'Introduction', 'Notation', 'Acknowledg',
            '前言', '导言', '序言', '目录', '概观', '符号', '致谢', '版权',
            'INTRODUCTION', 'CONTENTS', 'PREFACE',
        ]

        def _is_preamble(title: str) -> bool:
            t = title.strip()
            for kw in PREAMBLE_KEYWORDS:
                if t.startswith(kw) or t == kw:
                    return True
            return False

        MIN_CHAPTER_CHARS = 500

        body = [ch for ch in chapters if not ch.get("is_frontmatter", False)]
        front = [ch for ch in chapters if ch.get("is_frontmatter", False)]

        # Include substantial frontmatter chapters (often misclassified body chapters)
        front_substantial = [ch for ch in front
                             if len(ch.get("content", "")) >= MIN_CHAPTER_CHARS
                             and not _is_preamble(ch.get("title", ""))]

        body_qualified = [ch for ch in body if len(ch.get("content", "")) >= MIN_CHAPTER_CHARS]
        active_chapters = body_qualified + front_substantial
        skipped = len(chapters) - len(active_chapters)

        full_text = " ".join(ch["content"][:500] for ch in chapters[:3])
        language = detect_language(full_text)

        conn.execute(
            "UPDATE books SET language = ?, status = 'extracting' WHERE id = ?",
            (language, book_id)
        )
        conn.commit()

        saved_node_ids = set()

        def update_progress(done: int, total: int, nodes: int, edges: int):
            pct = int(done / total * 100) if total > 0 else 0
            elapsed = time.time() - start_time
            eta = (elapsed / done * (total - done)) if done > 0 else 0
            _progress[book_id] = {
                "chunk_done": done, "chunk_total": total,
                "node_count": nodes, "edge_count": edges,
                "pct": pct, "elapsed": elapsed, "eta": eta,
            }
            conn.execute(
                "UPDATE books SET progress = ?, node_count = ?, edge_count = ?, chunk_total = ?, chunk_done = ? WHERE id = ?",
                (pct, nodes, edges, total, done, book_id)
            )
            conn.commit()

        nodes, edges, stats = [], [], {}
        nodes, edges, stats = extract_from_chapters(
            active_chapters, book_id,
            progress_callback=update_progress,
            pause_event=pause_evt,
            cancel_event=cancel_evt,
        )

        if nodes:
            save_nodes_and_edges(nodes, edges, book_id)

            try:
                from lightrag_bridge import ingest
                ingest(book_id, nodes, edges, active_chapters)
            except Exception as e:
                import traceback, sys
                print(f"\n[LightRAG ERROR] Ingest failed for {book_id}: {e}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)

        if cancel_evt.is_set():
            status_msg = f"done (cancelled, {len(nodes)} nodes)" if nodes else "done (cancelled)"
        elif pause_evt and not pause_evt.is_set():
            status_msg = "paused"
        elif stats.get("failed_chunks", 0) > 0 and len(nodes) == 0:
            status_msg = f"error: LLM extraction failed all {stats['total_chunks']} chunks: {stats.get('first_error', '?')[:150]}"
        elif stats.get("failed_chunks", 0) > 0:
            status_msg = f"done ({stats['failed_chunks']}/{stats['total_chunks']} chunks failed)"
        elif len(nodes) == 0:
            status_msg = "done (no math content found)"
        else:
            status_msg = "done"
            if skipped > 0:
                status_msg += f" (skipped {skipped} insubstantial/preface chapters)"

        conn.execute("UPDATE books SET status = ? WHERE id = ?", (status_msg, book_id))
        conn.commit()
    except InterruptedError:
        pass
    except Exception as e:
        conn.execute(
            "UPDATE books SET status = ? WHERE id = ?",
            (f"error: {str(e)[:200]}", book_id)
        )
        conn.commit()
    finally:
        _progress.pop(book_id, None)
        _pause_events.pop(book_id, None)
        _cancel_events.pop(book_id, None)
        conn.close()


@router.post("/upload")
async def upload_book(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported in MVP")

    book_id = str(uuid.uuid4())
    save_dir = settings.data_dir / "books"
    save_dir.mkdir(exist_ok=True)
    filepath = save_dir / f"{book_id}.pdf"

    content = await file.read()
    filepath.write_bytes(content)

    title = file.filename.replace(".pdf", "").replace("_", " ").strip()

    conn = get_db()
    conn.execute(
        "INSERT INTO books (id, title, filename, status) VALUES (?, ?, ?, 'pending')",
        (book_id, title, file.filename)
    )
    conn.commit()
    conn.close()

    threading.Thread(target=_process_book, args=(book_id, str(filepath)), daemon=True).start()

    return {"id": book_id, "title": title, "status": "pending"}


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
    book = conn.execute("SELECT status, progress, node_count, edge_count, chunk_total, chunk_done FROM books WHERE id = ?", (book_id,)).fetchone()
    conn.close()
    if not book:
        raise HTTPException(404, "Book not found")
    live = _progress.get(book_id)
    return {
        "status": book["status"],
        "progress": live["pct"] if live else book["progress"],
        "node_count": live["node_count"] if live else book["node_count"],
        "edge_count": live["edge_count"] if live else book["edge_count"],
        "chunk_total": live["chunk_total"] if live else book["chunk_total"],
        "chunk_done": live["chunk_done"] if live else book["chunk_done"],
        "elapsed": live["elapsed"] if live else 0,
        "eta": live["eta"] if live else 0,
    }


@router.post("/{book_id}/pause")
def pause_extraction(book_id: str):
    evt = _pause_events.get(book_id)
    if not evt:
        raise HTTPException(404, "No active extraction found for this book")
    evt.clear()
    conn = get_db()
    conn.execute("UPDATE books SET status = 'paused' WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "paused": True}


@router.post("/{book_id}/resume")
def resume_extraction(book_id: str):
    evt = _pause_events.get(book_id)
    if not evt:
        raise HTTPException(404, "No active extraction found for this book")
    evt.set()
    conn = get_db()
    conn.execute("UPDATE books SET status = 'extracting' WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "paused": False}


@router.post("/{book_id}/cancel")
def cancel_extraction(book_id: str):
    evt = _cancel_events.get(book_id)
    if not evt:
        raise HTTPException(404, "No active extraction found for this book")
    evt.set()
    _pause_events.get(book_id, threading.Event()).set()
    return {"ok": True, "cancelled": True}


@router.delete("/{book_id}")
def delete_book(book_id: str):
    conn = get_db()
    conn.execute("DELETE FROM graph_edges WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM graph_nodes WHERE book_id = ?", (book_id,))
    conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
    conn.commit()
    conn.close()
    try:
        from lightrag_bridge import delete_book as lightrag_delete
        lightrag_delete(book_id)
    except Exception:
        pass
    return {"ok": True}
