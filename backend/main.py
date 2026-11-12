from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from routers import books, graph, chat, pages, workbench, structure

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
app.include_router(pages.router)
app.include_router(workbench.router)
app.include_router(structure.router)


@app.on_event("startup")
async def on_startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/health/llm")
async def llm_health():
    """Probe configured LLM endpoints with a hard time bound.

    A dead or unreachable model server must not turn a health check into a hang.
    Both probes run concurrently, each capped at 12 seconds.
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
            return await asyncio.wait_for(asyncio.to_thread(probe, task), timeout=12)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "probe timed out after 12s"}

    tasks = ["extraction", "chat"]
    results = dict(zip(tasks, await asyncio.gather(*(bounded(t) for t in tasks))))
    return {"llm": results}
