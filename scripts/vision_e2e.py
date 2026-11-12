"""One-off: prove vision OCR end-to-end on a REAL scanned page.

Tries every online vision model with generous spacing (the free aggregator
rate-limits hard). Writes a result log; exits 0 on first success.
"""
import base64
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pymupdf as fitz  # noqa: E402
import httpx  # noqa: E402
from openai import OpenAI  # noqa: E402

from config import settings  # noqa: E402
from vision import OCR_PROMPT  # noqa: E402

BOOK = "323fea46-176b-4300-a080-45724eb0cb29"  # real scanned book
PAGE = 13
MODELS = [
    ("glm-4.6v-flash", 8192),
    ("llama-3.2-90b-vision", 4096),
    ("nemotron-parse-2.0", 4096),
    ("moondream-3.1-9b-a2b", 4096),
    ("llava-1.5-7b", 4096),
]
GAP = 45
LOG = ROOT / "docs" / "sop" / "vision-e2e.log"


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    log(f"rendering {BOOK[:8]} p{PAGE} at zoom 2.0")
    doc = fitz.open(str(ROOT / "data" / "books" / f"{BOOK}.pdf"))
    pix = doc[PAGE - 1].get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
    data = pix.tobytes("png")
    w, h = pix.width, pix.height
    doc.close()
    log(f"png {len(data) // 1024} KB ({w}x{h})")

    client = OpenAI(
        api_key=settings.freeapi_api_key,
        base_url=settings.freeapi_base_url,
        http_client=httpx.Client(trust_env=False, timeout=httpx.Timeout(180.0, connect=3.0)),
        max_retries=0,
    )
    b64 = base64.b64encode(data).decode()

    for round_no in (1, 2):
        for model, max_tokens in MODELS:
            try:
                t0 = time.time()
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": OCR_PROMPT},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
                    ]}],
                    temperature=0.1, max_tokens=max_tokens,
                )
                elapsed = time.time() - t0
                text = (resp.choices[0].message.content or "").strip()
                usage = resp.usage
                log(f"SUCCESS {model} in {elapsed:.1f}s | chars={len(text)} | "
                    f"total_tokens={usage.total_tokens if usage else '?'} | finish={resp.choices[0].finish_reason}")
                log("---- transcription preview ----")
                for chunk in [text[i:i + 800] for i in range(0, min(len(text), 1600), 800)]:
                    log(chunk)
                log(f"WINNER={model}")
                return 0
            except Exception as e:
                log(f"FAIL {model} ({time.time() - t0:.1f}s): {type(e).__name__}: {str(e)[:160]}")
            time.sleep(GAP)
        log(f"round {round_no} done, cooling 90s before next round")
        time.sleep(90)
    log("ALL MODELS FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
