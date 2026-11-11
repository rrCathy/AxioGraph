from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from graph_store import get_graph_for_book, get_node_detail, update_node, delete_node, search_nodes

router = APIRouter(prefix="/api/graph", tags=["graph"])


class NodeUpdate(BaseModel):
    name: str
    content: str


class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "zh"


@router.get("/{book_id}")
def get_graph(book_id: str):
    data = get_graph_for_book(book_id)
    return data


@router.get("/node/{node_id}")
def get_node(node_id: str):
    node = get_node_detail(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    return node


@router.put("/node/{node_id}")
def update_node_endpoint(node_id: str, body: NodeUpdate):
    update_node(node_id, body.name, body.content)
    return {"ok": True}


@router.delete("/node/{node_id}")
def delete_node_endpoint(node_id: str):
    delete_node(node_id)
    return {"ok": True}


@router.get("/search/{book_id}")
def search_in_book(book_id: str, q: str = ""):
    if not q:
        return []
    return search_nodes(q, book_id)


@router.post("/translate")
def translate_text(req: TranslateRequest):
    """Translate text using the configured LLM, preserving math formulas."""
    from services.llm import get_llm

    lang_name = "Chinese (简体中文)" if req.target_lang == "zh" else req.target_lang
    system_prompt = (
        f"You are a translation assistant. Translate the following text to {lang_name}.\n"
        "CRITICAL: Preserve ALL math formulas wrapped in $...$ or $$...$$ exactly as-is — do NOT modify, "
        "translate, or reformat them. Only translate the surrounding natural language text.\n"
        "Also preserve Markdown formatting (bold, italic, lists, headings) in the output."
    )

    llm = get_llm("chat")
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": req.text},
    ]
    translated = llm.chat(messages, temperature=0.3, max_tokens=8192)
    return {"translated": translated, "original": req.text}
