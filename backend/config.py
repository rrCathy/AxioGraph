from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    data_dir: Path = Path(__file__).parent.parent / "data"
    sqlite_path: str = ""

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen3:14b"

    freeapi_base_url: str = "http://127.0.0.1:31415/v1"
    freeapi_api_key: str = ""
    freeapi_model: str = "auto"
    freeapi_embedding_model: str = "auto"
    freeapi_embedding_dim: int = 1024

    glm_api_key: str = ""
    glm_model: str = "glm-4.7-flash"

    extraction_model: str = "ollama"
    chat_model: str = "deepseek"

    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.sqlite_path:
            self.sqlite_path = str(self.data_dir / "axiograph.db")
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
