"""Configuration loading: env vars + optional YAML overrides."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from videomemory.types import PipelineConfig


class Settings(BaseSettings):
    """App-level settings (env-driven, prefix VIDEOMEMORY_)."""

    data_dir: Path = Path("./data")
    log_level: str = "INFO"

    qdrant_url: str = "http://localhost:6333"
    qdrant_in_memory: bool = True  # default: qdrant-client local mode (file-backed, no server)
    ollama_url: str = "http://localhost:11434"

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    hf_token: str | None = None

    model_config = SettingsConfigDict(env_prefix="VIDEOMEMORY_", env_file=".env", extra="ignore")


def load_pipeline_config(path: Path | None = None) -> PipelineConfig:
    """Load PipelineConfig from YAML if provided, otherwise defaults."""
    if path is None:
        return PipelineConfig()
    data = yaml.safe_load(Path(path).read_text()) or {}
    return PipelineConfig(**data)


def get_settings() -> Settings:
    """Return cached Settings."""
    if not hasattr(get_settings, "_cache"):
        get_settings._cache = Settings()  # type: ignore[attr-defined]
    return get_settings._cache  # type: ignore[attr-defined]


def select_device(pref: str = "auto") -> str:
    """Pick the best available torch device, honoring the user preference."""
    if pref != "auto":
        return pref
    try:
        import torch

        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name, "")
    if not val:
        return default
    return val.lower() in ("1", "true", "yes", "on")
