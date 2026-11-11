import hashlib
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
        timeout = httpx.Timeout(30.0, connect=3.0)
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


def get_embedding_func():
    """Embedding function for LightRAG, backed by FreeLLMAPI.

    Falls back to a deterministic hash embedding when no API key is configured.
    """
    import numpy as np
    from lightrag.utils import wrap_embedding_func_with_attrs
    from config import settings

    if settings.freeapi_api_key:

        @wrap_embedding_func_with_attrs(
            embedding_dim=settings.freeapi_embedding_dim,
            max_token_size=8192,
            model_name=settings.freeapi_embedding_model,
        )
        async def embedding_func(texts: list[str]) -> np.ndarray:
            client = _make_client(
                settings.freeapi_api_key,
                settings.freeapi_base_url,
                async_client=True,
            )
            response = await client.embeddings.create(
                model=settings.freeapi_embedding_model,
                input=texts,
                encoding_format="float",
            )
            return np.array([dp.embedding for dp in response.data])

        return embedding_func

    @wrap_embedding_func_with_attrs(
        embedding_dim=256,
        max_token_size=8192,
        model_name="hash-embedding",
    )
    async def fallback(texts: list[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), 256), dtype=np.float32)
        for i, text in enumerate(texts):
            for j in range(256):
                h = hashlib.md5(f"{j}:{text}".encode()).digest()
                vecs[i, j] = (h[0] / 255.0) * 2 - 1
            norm = np.linalg.norm(vecs[i])
            if norm > 0:
                vecs[i] /= norm
        return vecs

    return fallback
