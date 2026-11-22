"""Promote / relations / selection Q&A endpoints.

All writes here are human-triggered: the AI never writes to the graph, it only
suggests relations which the user ticks off. Promote writes are undoable for
8 seconds through the shared action_log.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from database import get_db
import graph_store as gs
import section_context as sc

router = APIRouter(tags=["enrich"])


class RelationIn(BaseModel):
    target_id: str
    relation_type: str = "DEPENDS_ON"
    description: str = ""


class PromoteRequest(BaseModel):
    entity_type: str
    name: str
    content: str
    quote: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    relations: list[RelationIn] = []


class EdgeRequest(BaseModel):
    book_id: str
    source_id: str
    target_id: str
    relation_type: str = "DEPENDS_ON"
    description: str = ""


class SuggestRequest(BaseModel):
    name: str
    entity_type: str
    content: str
    limit: int = 8


class AskSectionRequest(BaseModel):
    question: str
    selection: str = ""
    page_no: int


def _require_book(book_id: str):
    conn = get_db()
    row = conn.execute("SELECT id FROM books WHERE id = ?", (book_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Book not found")


# ── Promote: selection / environment → graph node ───────────────────────────

@router.post("/api/books/{book_id}/nodes/promote")
def promote(book_id: str, body: PromoteRequest):
    """Direct human promotion into the graph (no candidate queue)."""
    _require_book(book_id)
    result = gs.promote_node(
        book_id, body.entity_type, body.name, body.content,
        body.quote, body.page_start, body.page_end,
        [r.model_dump() for r in body.relations],
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "promote failed"))
    return result


@router.post("/api/promote/{token}/undo")
def undo_promote(token: str):
    if not gs.undo_promote(token):
        raise HTTPException(410, "Undo expired or already applied")
    return {"ok": True}


# ── Manual relations ────────────────────────────────────────────────────────

@router.post("/api/graph/edges")
def create_edge(body: EdgeRequest):
    result = gs.add_edge(body.book_id, body.source_id, body.target_id,
                         body.relation_type, body.description)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "edge rejected"))
    return result


@router.delete("/api/graph/edges/{edge_id}")
def remove_edge(edge_id: int):
    if not gs.delete_edge(edge_id):
        raise HTTPException(404, "Edge not found")
    return {"ok": True}


@router.get("/api/books/{book_id}/relation-targets")
def relation_targets(book_id: str, exclude: str | None = None):
    """Confirmed nodes as candidate relation endpoints."""
    _require_book(book_id)
    return {"nodes": gs.list_nodes_for_relation(book_id, exclude)}


# ── AI relation suggestion (advisory only) ──────────────────────────────────

_SUGGEST_SYSTEM = """你是数学知识图谱助手。给你一个新的数学条目和若干已有节点，判断新条目与已有节点之间成立的关系。
只允许这些关系类型：DEPENDS_ON（新条目依赖于目标）、GENERALIZES（新条目推广目标）、PROVES（新条目证明目标）、BUILDS_ON（新条目建立在目标之上）、EXAMPLE_OF（新条目是目标的例子）。
**只连直接关系，禁止传递性推理**：若新条目依赖 A、A 依赖 B，绝不要再给新条目依赖 B——间接的传递关系会让图谱变成蛛网。只提取数学上一步可达的直接依赖。
只输出 JSON 数组，不要输出其他文字。每项格式：{"target_id": "...", "relation_type": "...", "note": "一句话理由"}。
没有可靠关系时输出 []。宁缺毋滥，不要凭空联想。"""


@router.post("/api/books/{book_id}/relations/suggest")
def suggest_relations(book_id: str, body: SuggestRequest):
    """LLM proposes relations to existing confirmed nodes. Never writes.

    FreeLLMAPI can 429 or time out; the endpoint degrades to an empty list so
    the promote dialog keeps working offline.
    """
    _require_book(book_id)
    targets = gs.list_nodes_for_relation(book_id, limit=120)
    if not targets:
        return {"relations": [], "targets": 0}
    from services.llm import get_llm

    lines = [f'- id={t["id"]} [{t["entity_type"]}] {t["name"]}' for t in targets]
    user = (
        f'新条目：[{body.entity_type}] {body.name}\n'
        f'内容：{body.content[:1200]}\n\n'
        f'已有节点：\n' + "\n".join(lines)
    )
    try:
        llm = get_llm("extraction")
        raw = llm.chat(
            [{"role": "system", "content": _SUGGEST_SYSTEM},
             {"role": "user", "content": user}],
            temperature=0.2, max_tokens=800,
        )
    except Exception:
        return {"relations": [], "targets": len(targets), "degraded": True}
    try:
        import json_repair
        data = json_repair.loads(raw)
    except Exception:
        data = []
    valid = {t["id"]: t for t in targets}
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        tid = str(item.get("target_id", ""))
        if tid not in valid:
            continue
        rel = str(item.get("relation_type", "")).upper()
        if rel not in gs.VALID_RELATION_TYPES:
            continue
        out.append({
            "target_id": tid,
            "target_name": valid[tid]["name"],
            "relation_type": rel,
            "note": str(item.get("note", ""))[:200],
        })
        if len(out) >= max(1, min(body.limit, 12)):
            break
    return {"relations": out, "targets": len(targets)}


# ── Selection Q&A with section context ──────────────────────────────────────

_ASK_SYSTEM = """你是数学助教。根据提供的教材小节内容回答用户问题。
要求：引用条目时给出名称或页码；公式用 $...$ 包裹；内容不足时明确说明而不是编造。
用中文回答。"""


@router.post("/api/books/{book_id}/ask-section")
def ask_section(book_id: str, body: AskSectionRequest):
    """Answer a question with the current section auto-filled as context.

    The record is stored on the page (qa_records) — history only, never a
    graph node.
    """
    _require_book(book_id)
    if not (body.question or "").strip():
        raise HTTPException(400, "question is required")
    ctx = sc.build_section_context(book_id, body.page_no)
    from services.llm import get_llm

    label = f'p{ctx["start"]}–p{ctx["end"]}'
    header = f'小节：{ctx["title"] or label}（{ctx["chars"]} 字）\n'
    question_block = ""
    if body.selection.strip():
        question_block = f'用户划选的原文：\n"""\n{body.selection.strip()[:1500]}\n"""\n\n'
    prompt = (
        header
        + f'小节正文：\n{ctx["text"][:6000]}\n\n'
        + question_block
        + f'问题：{body.question.strip()}'
    )
    try:
        llm = get_llm("chat")
        answer = llm.chat(
            [{"role": "system", "content": _ASK_SYSTEM},
             {"role": "user", "content": prompt}],
            temperature=0.4, max_tokens=2048,
        )
    except Exception as e:
        raise HTTPException(502, f"LLM unavailable: {type(e).__name__}: {str(e)[:160]}")

    qa_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        """INSERT INTO qa_records
           (id, book_id, page_no, question, selection, answer, section_title, context_pages)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (qa_id, book_id, body.page_no, body.question.strip()[:2000],
         body.selection.strip()[:2000], answer,
         f'{ctx["title"] or ""} p{ctx["start"]}-p{ctx["end"]}'.strip(),
         json.dumps(ctx["pages_used"])),
    )
    conn.commit()
    conn.close()
    return {
        "id": qa_id,
        "answer": answer,
        "section": {"title": ctx["title"], "source": ctx["source"],
                    "start": ctx["start"], "end": ctx["end"],
                    "chars": ctx["chars"], "pages_used": ctx["pages_used"]},
    }


@router.get("/api/books/{book_id}/pages/{page_no}/qa")
def list_page_qa(book_id: str, page_no: int):
    conn = get_db()
    rows = conn.execute(
        """SELECT id, question, selection, answer, section_title, context_pages, created_at
           FROM qa_records WHERE book_id = ? AND page_no = ?
           ORDER BY created_at DESC, rowid DESC""",
        (book_id, page_no),
    ).fetchall()
    conn.close()
    return {"records": [dict(r) for r in rows]}


@router.delete("/api/qa/{qa_id}")
def delete_qa(qa_id: str):
    conn = get_db()
    cur = conn.execute("DELETE FROM qa_records WHERE id = ?", (qa_id,))
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "QA record not found")
    return {"ok": True}


# ── AI auto-flow: read page → ai_pending → human review ─────────────────────

class AiReadRequest(BaseModel):
    page_no: int


class AiReviewRequest(BaseModel):
    accept: bool
    note: str = ""
    edits: dict | None = None


@router.post("/api/books/{book_id}/ai-read")
def ai_read(book_id: str, body: AiReadRequest):
    """Manual "已读" trigger: extract this page's entities as ai_pending."""
    _require_book(book_id)
    import ai_flow
    try:
        return ai_flow.read_page(book_id, body.page_no)
    except Exception as e:
        raise HTTPException(502, f"AI extraction failed: {type(e).__name__}: {str(e)[:160]}")


@router.get("/api/books/{book_id}/ai-review")
def ai_review_list(book_id: str):
    """The review queue: every ai_pending node and edge for this book."""
    _require_book(book_id)
    import ai_flow
    return ai_flow.list_pending(book_id)


@router.get("/api/books/{book_id}/ai-jobs")
def ai_jobs_list(book_id: str):
    _require_book(book_id)
    import ai_flow
    return {"jobs": ai_flow.list_jobs(book_id)}


@router.post("/api/ai/nodes/{node_id}/review")
def ai_review_node(node_id: str, body: AiReviewRequest):
    """✓ confirm (with optional edits) / ✗ rework; 3rd ✗ drops the node."""
    import ai_flow
    result = ai_flow.review_node(node_id, body.accept, body.note, body.edits)
    if not result.get("ok"):
        raise HTTPException(404 if "not found" in result.get("error", "") else 400,
                            result.get("error", "review failed"))
    return result


@router.post("/api/ai/edges/{edge_id}/review")
def ai_review_edge(edge_id: int, body: AiReviewRequest):
    import ai_flow
    result = ai_flow.review_edge(edge_id, body.accept, body.note)
    if not result.get("ok"):
        raise HTTPException(404 if "not found" in result.get("error", "") else 400,
                            result.get("error", "review failed"))
    return result


# ── Recycle bin: soft-deleted graph items ───────────────────────────────────

class RestoreRequest(BaseModel):
    node_ids: list[str] = []


@router.get("/api/books/{book_id}/recycle")
def recycle_list(book_id: str):
    _require_book(book_id)
    return gs.list_recycle(book_id)


@router.post("/api/recycle/restore")
def recycle_restore(body: RestoreRequest):
    """Undo of a delete — bring nodes (and their cascade edges) back."""
    return gs.restore_nodes(body.node_ids)


@router.post("/api/recycle/purge")
def recycle_purge(body: RestoreRequest):
    """Hard delete from the recycle bin: gone for good."""
    return gs.purge_nodes(body.node_ids)


@router.post("/api/books/{book_id}/recycle/purge-all")
def recycle_purge_all(book_id: str):
    _require_book(book_id)
    return gs.purge_all(book_id)


@router.get("/api/books/{book_id}/tag-list")
def tag_list_endpoint(book_id: str):
    """Labels in use for this book, grouped — filter chips + suggestions."""
    return gs.tag_list(book_id)
