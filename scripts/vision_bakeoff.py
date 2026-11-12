"""Vision OCR bake-off: compare candidate FreeLLMAPI vision models on real
scanned pages (bad_page from the DB).

Usage (backend deps required):
    cd backend && python ../scripts/vision_bakeoff.py

Writes docs/sop/vision-ocr-bakeoff.md.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pymupdf as fitz  # noqa: E402

from config import settings  # noqa: E402
from services.llm import FreeAPIProvider  # noqa: E402
from vision import OCR_PROMPT, _confidence  # noqa: E402

MODELS = ["nemotron-parse-2.0", "glm-4.6v-flash", "llama-3.2-90b-vision"]
# nemotron-parse-2.0 rejects max_tokens=8192 upstream (NVIDIA NIM 400).
MODEL_MAX_TOKENS = {
    "nemotron-parse-2.0": 4096,
    "glm-4.6v-flash": 8192,
    "llama-3.2-90b-vision": 4096,
}
ZOOM = 2.0
GAP_SECONDS = 30      # spacing: the free aggregator rate-limits hard
RETRY_WAIT = 60       # cool-down before the single 429 retry
MAX_CHARS = 400       # preview length per model


def call_with_retry(provider, prompt, data, model) -> str:
    for attempt in (1, 2):
        try:
            return provider.chat_vision(prompt, data, model=model,
                                        max_tokens=MODEL_MAX_TOKENS[model])
        except Exception as e:
            rate_limited = "429" in str(e) or "rate" in str(e).lower()
            if attempt == 2 or not rate_limited:
                raise
            print(f"  429 on {model}, cooling down {RETRY_WAIT}s ...", flush=True)
            time.sleep(RETRY_WAIT)


def pick_pages(limit=2) -> list[dict]:
    import sqlite3
    conn = sqlite3.connect(str(settings.sqlite_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT book_id, page_no FROM pages
           WHERE status = 'bad_page' ORDER BY book_id, page_no LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def render(book_id: str, page_no: int):
    path = settings.data_dir / "books" / f"{book_id}.pdf"
    doc = fitz.open(str(path))
    page = doc[page_no - 1]
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
    data = pix.tobytes("png")
    w, h = pix.width, pix.height
    doc.close()
    return data, w, h


def main() -> int:
    pages = pick_pages()
    if not pages:
        print("no bad_page rows found")
        return 1
    page_labels = ", ".join(f"{p['book_id'][:8]} p{p['page_no']}" for p in pages)
    lines = [
        "# 视觉 OCR 模型实测（bake-off）",
        "",
        f"- 日期：{time.strftime('%Y-%m-%d %H:%M')}",
        f"- 端点：{settings.freeapi_base_url}",
        f"- 页面：{page_labels}",
        f"- 渲染：zoom={ZOOM}",
        "",
        "| 模型 | 页 | 耗时 | 字符数 | 启发式置信 | 判定 |",
        "|------|----|------|--------|------------|------|",
    ]
    for model in MODELS:
        provider = FreeAPIProvider(
            settings.freeapi_api_key, settings.freeapi_base_url, settings.freeapi_model
        )
        for p in pages:
            data, w, h = render(p["book_id"], p["page_no"])
            t0 = time.time()
            try:
                text = call_with_retry(provider, OCR_PROMPT, data, model)
                elapsed = time.time() - t0
                text = (text or "").strip()
                conf = _confidence(text, w, h, ZOOM)
                verdict = "usable" if conf >= 55 else "bad"
                lines.append(
                    f"| {model} | p{p['page_no']} | {elapsed:.1f}s | {len(text)} | {conf} | {verdict} |"
                )
                lines += ["", f"<details><summary>{model} · p{p['page_no']} 输出预览</summary>",
                          "", "```", text[:MAX_CHARS], "```", ""]
            except Exception as e:
                elapsed = time.time() - t0
                lines.append(f"| {model} | p{p['page_no']} | {elapsed:.1f}s | ERR | ERR | {type(e).__name__}: {str(e)[:120]} |")
                lines += ["", f"<details><summary>{model} · p{p['page_no']} 错误</summary>", "",
                          "```", str(e)[:400], "```", ""]
            time.sleep(GAP_SECONDS)
    out = ROOT / "docs" / "sop" / "vision-ocr-bakeoff.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(l for l in lines if l.startswith("|")))
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
