"""Runtime configuration, read once from environment variables.

Secrets never appear in code or logs. Copy ``.env.example`` to ``.env`` for
local development; on Hugging Face Spaces set the same names as Space secrets.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Typed view over the environment with safe defaults."""

    def __init__(self) -> None:
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "").strip()
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
        self.gemini_base_url: str = os.getenv(
            "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")
        self.request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "40"))
        self.max_document_chars: int = int(os.getenv("MAX_DOCUMENT_CHARS", "60000"))
        self.rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "30"))
        self.cache_size: int = int(os.getenv("ANALYSIS_CACHE_SIZE", "128"))
        self.static_dir: str = os.getenv("STATIC_DIR", "static").strip()
        self.allowed_origins: list[str] = [
            origin.strip()
            for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(
                ","
            )
            if origin.strip()
        ]

    @property
    def ai_enabled(self) -> bool:
        """True when a Gemini key is configured; otherwise the app runs in demo mode."""
        return bool(self.gemini_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
