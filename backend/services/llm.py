from abc import ABC, abstractmethod
import httpx
from openai import OpenAI, AsyncOpenAI


def _is_local(base_url: str) -> bool:
    return "127.0.0.1" in base_url or "localhost" in base_url


def _make_client(api_key: str, base_url: str, *, async_client: bool = False):
    """Build an OpenAI-compatible client.

    Loopback endpoints (the local model server, Ollama) must bypass the ambient
    HTTP_PROXY/HTTPS_PROXY: httpx otherwise sends 127.0.0.1 requests through a
    proxy that never answers, so a dead local service hangs every LLM call for
    ~9s. Local clients also fail fast (3s connect, no retries); remote APIs keep
    the system proxy and a generous read timeout for long extraction prompts.
    """
    if _is_local(base_url):
        timeout = httpx.Timeout(30.0, connect=3.0)
        http_client = (
            httpx.AsyncClient(trust_env=False, timeout=timeout)
            if async_client
            else httpx.Client(trust_env=False, timeout=timeout)
        )
        cls = AsyncOpenAI if async_client else OpenAI
        return cls(api_key=api_key, base_url=base_url,
                   http_client=http_client, max_retries=0)
    cls = AsyncOpenAI if async_client else OpenAI
    return cls(api_key=api_key, base_url=base_url, timeout=120.0, max_retries=2)


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> str:
        pass


class OpenAIProvider(LLMProvider):
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


class OllamaProvider(LLMProvider):
    def __init__(self, host: str, model: str):
        self.client = _make_client("ollama", f"{host}/v1")
        self.model = model

    def chat(self, messages: list[dict], **kwargs) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        return resp.choices[0].message.content or ""


class GLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self.client = _make_client(api_key, "https://open.bigmodel.cn/api/paas/v4")
        self.model = model

    def chat(self, messages: list[dict], **kwargs) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.3),
            max_tokens=kwargs.get("max_tokens", 4096),
            extra_body={"thinking": {"type": "disabled"}},
        )
        return resp.choices[0].message.content or ""


def get_llm(task: str = "extraction") -> LLMProvider:
    """Get LLM provider based on task and settings."""
    from config import settings

    if task == "extraction":
        model_choice = settings.extraction_model
    else:
        model_choice = settings.chat_model

    if model_choice == "freeapi":
        return OpenAIProvider(
            settings.freeapi_api_key,
            settings.freeapi_base_url,
            settings.freeapi_model,
        )
    elif model_choice == "ollama":
        return OllamaProvider(settings.ollama_host, settings.ollama_model)
    elif model_choice == "deepseek":
        return OpenAIProvider(
            settings.deepseek_api_key or "sk-placeholder",
            "https://api.deepseek.com",
            settings.deepseek_model,
        )
    elif model_choice == "glm":
        return GLMProvider(
            settings.glm_api_key or "sk-placeholder",
            settings.glm_model,
        )
    else:
        return OpenAIProvider(
            settings.openai_api_key or "sk-placeholder",
            settings.openai_base_url,
            settings.openai_model,
        )


def get_embedding_func():
    """Return an embedding function compatible with LightRAG.

    Uses OpenAI-compatible embedding API by default.
    Set EMBEDDING_API_KEY, EMBEDDING_BASE_URL, EMBEDDING_MODEL in .env.
    Falls back to a deterministic hash-based embedding if no API key is set.
    """
    import numpy as np
    from lightrag.utils import wrap_embedding_func_with_attrs
    from config import settings

    if settings.embedding_api_key:

        @wrap_embedding_func_with_attrs(
            embedding_dim=settings.embedding_dim,
            max_token_size=8192,
            model_name=settings.embedding_model,
        )
        async def embedding_func(texts: list[str]) -> np.ndarray:
            client = _make_client(
                settings.embedding_api_key,
                settings.embedding_base_url,
                async_client=True,
            )
            response = await client.embeddings.create(
                model=settings.embedding_model,
                input=texts,
                encoding_format="float",
            )
            return np.array([dp.embedding for dp in response.data])

        return embedding_func
    else:
        import hashlib

        @wrap_embedding_func_with_attrs(
            embedding_dim=256,
            max_token_size=8192,
            model_name="hash-embedding",
        )
        async def embedding_func(texts: list[str]) -> np.ndarray:
            """Deterministic hash-based fallback embedding."""
            vecs = np.zeros((len(texts), 256), dtype=np.float32)
            for i, text in enumerate(texts):
                for j in range(256):
                    h = hashlib.md5(f"{j}:{text}".encode()).digest()
                    vecs[i, j] = (h[0] / 255.0) * 2 - 1
                norm = np.linalg.norm(vecs[i])
                if norm > 0:
                    vecs[i] /= norm
            return vecs

        return embedding_func
