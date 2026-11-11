import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.llm import get_llm

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    question: str
    book_id: str | None = None


QA_SYSTEM_PROMPT = """You are a mathematics tutor with access to a knowledge graph of mathematical concepts.
Answer the user's question based on the provided context of mathematical definitions, theorems, and concepts.
Cite specific theorems or definitions when relevant.
If the context is insufficient, say so clearly.

IMPORTANT: Wrap ALL math formulas in $...$ (inline) or $$...$$ (display block). For example: $x^2 + 1$ or $$e^{i\pi} + 1 = 0$$

Context from knowledge graph:
{context}"""


def _build_fallback_response(question: str, book_id: str | None) -> dict:
    """Fallback when no LightRAG instance or no context found."""
    try:
        from graph_store import get_context_for_qa
        context_nodes = get_context_for_qa(question, book_id, limit=15)
        if not context_nodes:
            return {
                "answer": "No relevant mathematical concepts found in the knowledge graph. Please import a math book first.",
                "references": [],
            }

        context_text = "\n\n".join(
            f"[{n['entity_type']}] {n['name']}\n{n.get('content', '')[:800]}"
            for n in context_nodes
        )

        llm = get_llm("chat")
        messages = [
            {"role": "system", "content": QA_SYSTEM_PROMPT.replace("{context}", context_text)},
            {"role": "user", "content": question},
        ]
        answer = llm.chat(messages, temperature=0.5, max_tokens=2048)
        references = [
            {"id": n["id"], "type": n["entity_type"], "name": n["name"]}
            for n in context_nodes[:8]
        ]
        return {"answer": answer, "references": references}
    except Exception as e:
        return {"answer": f"Error: {str(e)}", "references": []}


@router.post("/ask")
async def ask_question(req: ChatRequest):
    if not req.book_id:
        return {
            "answer": "Please select a book first.",
            "references": [],
        }

    try:
        from lightrag_bridge import query as lightrag_query
        answer = await lightrag_query(
            req.book_id, req.question,
            mode="hybrid",
        )
    except Exception as e:
        answer = None

    if answer is None:
        return _build_fallback_response(req.question, req.book_id)

    return {"answer": answer, "references": []}


@router.post("/ask/stream")
async def ask_stream(req: ChatRequest):
    if not req.book_id:
        async def empty():
            yield "data: Please select a book first.\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    async def generate():
        try:
            from lightrag_bridge import query as lightrag_query
            result = await lightrag_query(
                req.book_id, req.question,
                mode="hybrid", stream=True,
            )
            if result:
                yield f"data: {result}\n\n"
            else:
                fb = _build_fallback_response(req.question, req.book_id)
                yield f"data: {fb['answer']}\n\n"
                yield f"data: __REFS__{json.dumps(fb['references'])}\n\n"
        except Exception as e:
            yield f"data: [Error: {str(e)}]\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
