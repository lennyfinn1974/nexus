"""Typed configuration for Nexus using Pydantic BaseSettings.
All environment variables are optional -- defaults are provided for a local dev setup.
The Settings object is instantiated once at startup and injected wherever needed.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    host: str = Field("127.0.0.1", env="HOST")
    port: int = Field(8080, env="PORT")

    # Database
    database_url: str = Field("postgresql+asyncpg://localhost/nexus", env="DATABASE_URL")
    db_path: Path = Field(
        default_factory=lambda: Path(__file__).parents[3] / "data" / "nexus.db", env="DB_PATH"
    )  # legacy, used by migration script

    # Model endpoints
    ollama_base_url: str = Field("http://localhost:11434", env="OLLAMA_BASE_URL")
    ollama_model: str = Field("llama3.1", env="OLLAMA_MODEL")
    anthropic_api_key: str | None = Field(None, env="ANTHROPIC_API_KEY")
    claude_model: str = Field("claude-3-5-sonnet-20240620", env="CLAUDE_MODEL")

    # Misc
    max_research_tasks: int = Field(5, env="MAX_RESEARCH_TASKS")
    persona_tone: str = Field("balanced", env="PERSONA_TONE")

    # Tool calling mode
    tool_calling_mode: str = Field("native", env="TOOL_CALLING_MODE")

    @field_validator("persona_tone")
    @classmethod
    def _check_tone(cls, v: str) -> str:
        allowed = {"balanced", "professional", "casual", "technical"}
        if v not in allowed:
            raise ValueError(f"persona_tone must be one of {allowed}")
        return v

    @field_validator("tool_calling_mode")
    @classmethod
    def _check_tool_mode(cls, v: str) -> str:
        allowed = {"native", "legacy"}
        if v not in allowed:
            raise ValueError(f"tool_calling_mode must be one of {allowed}")
        return v

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# Export a singleton for easy import elsewhere
settings = Settings()
