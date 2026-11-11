from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from routers import books, graph, chat

app = FastAPI(title="AxioGraph", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(books.router)
app.include_router(graph.router)
app.include_router(chat.router)


@app.on_event("startup")
async def on_startup():
    init_db()
    try:
        from config import settings
        from services.llm import get_llm, get_embedding_func
        from lightrag_bridge import init as lightrag_init

        def make_llm_func():
            async def llm_model_func(
                prompt, system_prompt=None, history_messages=None, **kwargs
            ) -> str:
                llm = get_llm("chat")
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                if history_messages:
                    for msg in history_messages:
                        messages.append(msg)
                messages.append({"role": "user", "content": prompt})
                return llm.chat(messages, temperature=0.5)
            return llm_model_func

        lightrag_init(
            data_dir=settings.data_dir,
            llm_model_func=make_llm_func(),
            embedding_func=get_embedding_func(),
        )
    except Exception:
        import logging
        logging.getLogger("axiograph").warning(
            "LightRAG init failed — chat will use fallback keyword search"
        )


@app.on_event("shutdown")
async def on_shutdown():
    try:
        from lightrag_bridge import shutdown as lightrag_shutdown
        lightrag_shutdown()
    except Exception:
        pass


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/health/llm")
async def llm_health():
    """Probe configured LLM endpoints with a hard time bound.

    A dead or unreachable model server must not turn a health check into a hang.
    Both probes run concurrently, each capped at 6 seconds.
    """
    import asyncio
    from services.llm import get_llm

    def probe(task: str) -> dict:
        try:
            llm = get_llm(task)
            resp = llm.chat(
                [{"role": "user", "content": "Say ok"}],
                temperature=0, max_tokens=10,
            )
            return {"ok": bool(resp and resp.strip()),
                    "model": getattr(llm, "model", "unknown")}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}

    async def bounded(task: str) -> dict:
        try:
            return await asyncio.wait_for(asyncio.to_thread(probe, task), timeout=6)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "probe timed out after 6s"}

    tasks = ["extraction", "chat"]
    results = dict(zip(tasks, await asyncio.gather(*(bounded(t) for t in tasks))))
    return {"llm": results}
