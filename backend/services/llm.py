import httpx
from openai import OpenAI, AsyncOpenAI


def _is_local(base_url: str) -> bool:
    return "127.0.0.1" in base_url or "localhost" in base_url


def _make_client(api_key: str, base_url: str, *, async_client: bool = False):
    """Build the FreeLLMAPI client.

    Loopback endpoints must bypass the ambient HTTP_PROXY/HTTPS_PROXY: httpx
    otherwise sends 127.0.0.1 requests through a proxy that never answers, so
    a dead local service hangs every call for ~9s. Local clients fail fast.
    """
    cls = AsyncOpenAI if async_client else OpenAI
    if _is_local(base_url):
        timeout = httpx.Timeout(180.0, connect=3.0)
        http_client = (
            httpx.AsyncClient(trust_env=False, timeout=timeout)
            if async_client
            else httpx.Client(trust_env=False, timeout=timeout)
        )
        return cls(api_key=api_key, base_url=base_url,
                   http_client=http_client, max_retries=0)
    return cls(api_key=api_key, base_url=base_url, timeout=120.0, max_retries=2)


class FreeAPIProvider:
    """The single LLM provider: an OpenAI-compatible FreeLLMAPI endpoint."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = _make_client(api_key, base_url)
        self.model = model

    def chat(self, messages: list[dict], **kwargs) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        return resp.choices[0].message.content or ""

    def chat_vision(self, prompt: str, png_bytes: bytes,
                    system: str | None = None,
                    model: str | None = None, **kwargs) -> str:
        """One-shot image + text call against a vision-capable model.

        `model` defaults to get_vision_model(); FreeLLMAPI routes text models
        by `self.model`, but image input needs an explicitly vision-capable id.
        """
        from services.llm import get_vision_model
        import base64

        data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode()
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        })
        resp = self.client.chat.completions.create(
            model=model or get_vision_model(),
            messages=messages,
            temperature=kwargs.get("temperature", 0.1),
            max_tokens=kwargs.get("max_tokens", 8192),
        )
        return resp.choices[0].message.content or ""


def get_llm(task: str = "extraction") -> FreeAPIProvider:
    """Return the FreeLLMAPI client.

    `task` is kept for call-site compatibility (extraction / chat / translate
    now share one endpoint); it no longer selects a provider.
    """
    from config import settings
    return FreeAPIProvider(
        settings.freeapi_api_key,
        settings.freeapi_base_url,
        settings.freeapi_model,
    )


def get_vision_model() -> str:
    """Model id used for image-input calls (page OCR, TOC parsing).

    Overridable via FREEAPI_VISION_MODEL in backend/.env; the default comes
    from the bake-off recorded in docs/sop/vision-ocr-bakeoff.md.
    """
    from config import settings
    return settings.freeapi_vision_model or "glm-4.6v-flash"
