from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # FreeLLMAPI is the only supported provider. .env may still contain keys
    # for retired providers; ignore them instead of failing validation.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    data_dir: Path = Path(__file__).parent.parent / "data"
    sqlite_path: str = ""

    freeapi_base_url: str = "http://127.0.0.1:31415/v1"
    freeapi_api_key: str = ""
    freeapi_model: str = "auto"
    freeapi_vision_model: str = ""
    freeapi_embedding_model: str = "auto"
    freeapi_embedding_dim: int = 1024

    # Local formula-to-LaTeX engine: "texify" (VikP/texify, 312M, best token
    # F1 on im2latex-100K) or "pix2tex" (rapid-latex-ocr ONNX, the old engine).
    # Both run fully offline on CPU; weights live under backend/models/.
    formula_engine: str = "texify"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.sqlite_path:
            self.sqlite_path = str(self.data_dir / "axiograph.db")
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
