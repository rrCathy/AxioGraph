import asyncio
import logging
import shutil
import traceback
import sys
from pathlib import Path
from typing import Any
from lightrag import LightRAG, QueryParam

logger = logging.getLogger("axiograph.lightrag")

_data_dir: Path | None = None
_llm_func: Any = None
_embed_func: Any = None
_instances: dict[str, LightRAG] = {}


def init(data_dir: Path, llm_model_func, embedding_func):
    global _data_dir, _llm_func, _embed_func
    _data_dir = data_dir
    _llm_func = llm_model_func
    _embed_func = embedding_func
    logger.info("LightRAG bridge initialized")


def _create_instance(book_id: str) -> LightRAG:
    working_dir = str(_data_dir / "lightrag" / book_id)
    Path(working_dir).mkdir(parents=True, exist_ok=True)
    return LightRAG(
        working_dir=working_dir,
        llm_model_func=_llm_func,
        embedding_func=_embed_func,
        addon_params={
            "language": "Chinese",
            "chunker": {
                "chunk_token_size": 1000,
                "recursive_character": {
                    "separators": ["\n\n", "\n", "。", "！", "？", " ", ".", "!", "?"]
                },
            },
        },
    )


def _find_node_name(nodes: list[dict], node_id: str) -> str | None:
    for n in nodes:
        if n["id"] == node_id:
            return n["name"]
    return None


def ingest(book_id: str, nodes: list[dict], edges: list[dict],
           chapters: list[dict]):
    entities = []
    for n in nodes:
        entities.append({
            "entity_name": n["name"],
            "entity_type": n["entity_type"],
            "description": n.get("content", ""),
            "source_id": book_id,
            "file_path": f"{book_id}/{n.get('chapter', 'unknown')}",
        })

    relationships = []
    for e in edges:
        src_name = _find_node_name(nodes, e["source_id"])
        tgt_name = _find_node_name(nodes, e["target_id"])
        if src_name and tgt_name:
            relationships.append({
                "src_id": src_name,
                "tgt_id": tgt_name,
                "description": e.get("description", ""),
                "keywords": e["relation_type"].lower(),
                "weight": 1.0,
                "source_id": book_id,
                "file_path": f"{book_id}/relations",
            })

    chunks = []
    for ch in chapters:
        if ch.get("content", "").strip():
            chunks.append({
                "content": ch["content"],
                "source_id": book_id,
                "file_path": f"{book_id}/{ch.get('title', 'untitled')}",
            })

    custom_kg = {
        "chunks": chunks,
        "entities": entities,
        "relationships": relationships,
    }

    logger.info(
        "Ingesting book %s into LightRAG: %d entities, %d relations, %d chunks",
        book_id, len(entities), len(relationships), len(chunks),
    )

    async def _do_ingest():
        rag = _create_instance(book_id)
        await rag.initialize_storages()
        await rag.ainsert_custom_kg(custom_kg)
        _instances[book_id] = rag

    try:
        asyncio.run(_do_ingest())
    except Exception:
        logger.error("LightRAG ingest failed for book %s:\n%s", book_id, traceback.format_exc())
        print(f"[LightRAG] Ingest failed for {book_id}:", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise
    logger.info("LightRAG ingest complete for book %s", book_id)


async def query(book_id: str, question: str, *,
                mode: str = "hybrid", stream: bool = False,
                conversation_history: list[dict] | None = None,
                only_need_context: bool = False) -> str | None:
    rag = _instances.get(book_id)
    if not rag:
        logger.warning("No LightRAG instance for book %s", book_id)
        return None
    return await rag.aquery(
        question,
        param=QueryParam(
            mode=mode,
            stream=stream,
            conversation_history=conversation_history or [],
            only_need_context=only_need_context,
        ),
    )


def delete_book(book_id: str):
    rag = _instances.pop(book_id, None)
    if rag:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(rag.finalize_storages())
        else:
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                rag.finalize_storages(), loop
            )
            future.result(timeout=10)
    wd = _data_dir / "lightrag" / book_id
    if wd.exists():
        shutil.rmtree(wd, ignore_errors=True)
    logger.info("LightRAG resources cleaned for book %s", book_id)


def shutdown():
    for book_id in list(_instances.keys()):
        delete_book(book_id)
    logger.info("LightRAG bridge shut down")
