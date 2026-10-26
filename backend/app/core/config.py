from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT = "dev-only-insecure-secret-change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPENDWISE_", env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_name: str = "SpendWise AI"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://spendwise:spendwise@localhost:5432/spendwise"
    redis_url: str | None = None

    jwt_secret: str = _INSECURE_DEFAULT
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=15, ge=1, le=120)
    refresh_token_days: int = Field(default=14, ge=1, le=90)

    # Fernet key (urlsafe base64, 32 bytes) used to encrypt user-supplied LLM API keys at rest.
    encryption_key: str = "x0tJ0vYb0E1y6WbqkqBkzvGJ1qvJ4gXr2J5cS3aLQpM="

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    cookie_secure: bool = False

    login_rate_limit_per_minute: int = Field(default=10, ge=1)
    max_page_size: int = Field(default=200, ge=1, le=1000)

    fx_url: str = "https://api.frankfurter.dev/v1/latest"
    amfi_url: str = "https://portal.amfiindia.com/spages/NAVAll.txt"
    mfapi_url: str = "https://api.mfapi.in/mf"
    gold_url: str = "https://api.gold-api.com/price/XAU"
    # Background worker cadence
    # Email notifications (optional). Without smtp_host, alerts are shown in the app only.
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    smtp_from: str = "SpendWise <no-reply@localhost>"
    app_url: str = "http://localhost:3000"
    digest_hours: int = Field(default=20, ge=1, le=168)
    morning_hour: int = Field(default=7, ge=0, le=23)  # money alerts after this local hour
    worker_heartbeat_path: str = "/tmp/spendwise-worker-heartbeat"  # noqa: S108 - tmpfs in Docker

    price_check_hours: int = Field(default=12, ge=1, le=168)
    fx_refresh_hours: int = Field(default=6, ge=1, le=48)

    @model_validator(mode="after")
    def _forbid_insecure_production(self) -> Settings:
        if self.environment == "production":
            if self.jwt_secret == _INSECURE_DEFAULT or len(self.jwt_secret) < 32:
                raise ValueError("SPENDWISE_JWT_SECRET must be set to >=32 chars in production")
            if self.encryption_key == Settings.model_fields["encryption_key"].default:
                raise ValueError("SPENDWISE_ENCRYPTION_KEY must be set in production")
            if not self.cookie_secure:
                raise ValueError("SPENDWISE_COOKIE_SECURE must be true in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
