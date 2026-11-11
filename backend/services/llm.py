from abc import ABC, abstractmethod
from openai import OpenAI


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], **kwargs) -> str:
        pass


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, base_url: str, model: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
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
        self.client = OpenAI(base_url=f"{host}/v1", api_key="ollama")
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
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4",
        )
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
        from openai import AsyncOpenAI

        @wrap_embedding_func_with_attrs(
            embedding_dim=settings.embedding_dim,
            max_token_size=8192,
            model_name=settings.embedding_model,
        )
        async def embedding_func(texts: list[str]) -> np.ndarray:
            client = AsyncOpenAI(
                api_key=settings.embedding_api_key,
                base_url=settings.embedding_base_url,
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
