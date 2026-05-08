"""Application configuration sourced from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for backend, model, and processing behavior."""

    backend: str = "local"
    backend_opts: dict[str, Any] = {"root": "/data"}

    dropzone: str = "/dropzone"
    organized: str = "/organized"
    quarantine: str = "/quarantine"
    state_db: Path = Path("/data/state.db")

    ollama_api_key: SecretStr = SecretStr("")
    ollama_base_url: str = "https://ollama.com"
    model: str = "gpt-oss:120b-cloud"

    dry_run: bool = False
    max_depth: int = 4
    extract_max_bytes: int = 8192
    ocr_enabled: bool = False
    log_level: str = "INFO"
    poll_interval_seconds: float = 1.0

    model_config = SettingsConfigDict(env_nested_delimiter="__", extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance.

    Returns:
        Settings: Cached settings object.
    """
    return Settings()
