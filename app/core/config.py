"""
CS2 Instant Alert — Application Configuration.

Centralized configuration via Pydantic Settings.
All values are loaded from environment variables with .env file support.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: two levels up from app/core/config.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class AppSettings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Application ───
    app_name: str = "cs2-instant-alert"
    version: str = "1.0.0"
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = False
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    app_secret_key: SecretStr = Field(default=SecretStr("change-me"))

    # ─── Database ───
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "cs2_alert"
    database_user: str = "cs2_alert"
    database_password: SecretStr = Field(default=SecretStr("change-me"))
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # ─── Redis ───
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: SecretStr | None = None
    redis_url_override: str | None = Field(default=None, alias="REDIS_URL")

    # ─── Telegram ───
    telegram_bot_token: SecretStr = Field(default=SecretStr(""))
    telegram_admin_ids: list[int] = Field(default_factory=list)
    admin_telegram_id: int | None = None

    @field_validator("telegram_admin_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | list[int]) -> list[int]:
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    # ─── Steam ───
    steam_web_api_key: SecretStr = Field(default=SecretStr(""))
    steam_anonymous_login: bool = True
    steam_username: str | None = None
    steam_password: SecretStr | None = None

    # ─── Pushover ───
    pushover_app_token: SecretStr | None = None
    pushover_default_user_key: str | None = None

    # ─── ntfy ───
    ntfy_base_url: str = "https://ntfy.sh"
    ntfy_default_topic: str = "cs2-updates"

    # ─── Discord ───
    discord_webhook_url: str | None = None

    # ─── Email ───
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_address: str | None = None
    smtp_use_tls: bool = True

    # ─── Translation (DeepL) ───
    deepl_api_key: SecretStr | None = None

    # ─── AI Analysis (Gemini) ───
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"

    # ─── API ───
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_workers: int = 1

    # ─── Encryption ───
    encryption_key: SecretStr | None = None

    # ─── Monitoring ───
    steam_check_interval_seconds: int = 5
    steam_race_mode_interval_seconds: int = 2
    steam_race_mode_duration_minutes: int = 30

    # ─── Derived Properties ───

    @property
    def database_url(self) -> str:
        """Async PostgreSQL connection string."""
        password = self.database_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.database_user}:{password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    @property
    def database_url_sync(self) -> str:
        """Synchronous PostgreSQL connection string (for Alembic)."""
        password = self.database_password.get_secret_value()
        return (
            f"postgresql://{self.database_user}:{password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    @property
    def redis_url(self) -> str:
        """Redis connection string. Prefers REDIS_URL env var (Upstash/Fly.io)."""
        if self.redis_url_override:
            return self.redis_url_override
        password_part = ""
        if self.redis_password:
            password_part = f":{self.redis_password.get_secret_value()}@"
        return f"redis://{password_part}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Singleton settings instance. Cached after first call."""
    return AppSettings()
