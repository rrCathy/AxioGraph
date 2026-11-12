"""Vision-model OCR for scanned pages.

Replaces the tesseract.js main path for scans: the page is rendered server-side
and transcribed by a vision-capable FreeLLMAPI model. Confidence is a heuristic
composite (text sanity + character density) on the same 0-100 scale the
frontend tesseract path uses; <55 keeps the page in bad_page for manual entry.
"""
import logging

import page_service as ps
from services.llm import get_llm

log = logging.getLogger("axiograph.vision")

OCR_ZOOM = 2.0
CONFIDENCE_THRESHOLD = 55.0

OCR_PROMPT = """将这页数学书图像上的文字逐字转录为纯文本。
要求：
1. 按阅读顺序输出，保留段落与换行。
2. 数学公式用 LaTeX 记号，行内公式用 $...$ 包裹，不要改变记号本身。
3. 保留章节标题与定理/定义/例的编号。
4. 只输出页面上实际出现的文字：不要解释、不要 Markdown 标记、不要复述要求。
5. 纯页码的页眉页脚可省略。"""


def _confidence(text: str, width_px: int, height_px: int, zoom: float) -> float:
    """0-100 heuristic: text sanity (0-1) blended with character density.

    Density reference: a dense A4 textbook page at zoom=2 has roughly
    2000-5000 chars; a dense 32-open page fewer. 900 chars per square inch
    of paper maps to full marks — generous enough that a sparse but valid
    page (e.g. a chapter opener) can still pass.
    """
    base = ps.text_quality(text)  # 0-1, penalises control chars / dot leaders
    area_in2 = (width_px / zoom / 72.0) * (height_px / zoom / 72.0)
    density = len(text.strip()) / max(area_in2, 0.5)
    density_score = min(1.0, density / 900)
    return round(100 * (0.55 * base + 0.45 * density_score), 1)


def ocr_page(book_id: str, page_no: int, task_id: str | None = None) -> dict:
    from page_extractor import is_cancelled, clear_task

    rendered = ps.render_page(book_id, page_no, zoom=OCR_ZOOM)
    if not rendered:
        return {"ok": False, "needs_manual": True, "error": "page not found"}
    data, w, h = rendered

    try:
        llm = get_llm("vision")
        text = llm.chat_vision(OCR_PROMPT, data)
    except Exception as e:
        log.warning("vision OCR failed for %s p%s: %s", book_id, page_no, e)
        return {"ok": False, "needs_manual": True, "error": str(e)[:200]}

    # Cancelled while the model was busy: nothing is written, same semantics
    # as the page-extraction task path.
    if is_cancelled(task_id):
        clear_task(task_id)
        return {"cancelled": True, "needs_manual": False}

    text = (text or "").strip()
    if not text:
        clear_task(task_id)
        return {"ok": False, "needs_manual": True, "error": "empty transcription"}

    confidence = _confidence(text, w, h, OCR_ZOOM)
    usable = confidence >= CONFIDENCE_THRESHOLD
    status = "ocr" if usable else "bad_page"
    ps.save_page_text(book_id, page_no, text, status, confidence)
    clear_task(task_id)
    return {"ok": True, "status": status, "confidence": confidence,
            "char_count": len(text), "needs_manual": not usable}
