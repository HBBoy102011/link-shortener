"""Application settings.

Every value can be supplied through environment variables or a local ``.env``
file.  Only development defaults are embedded here; deployments must provide
their own secrets, and the application refuses to start in production with the
placeholder values.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Value that is only acceptable while developing locally.
INSECURE_SECRET = "insecure-development-secret-change-me"
INSECURE_PEPPER = "insecure-development-pepper"

#: Environment in which placeholder secrets are tolerated.
DEV_ENVIRONMENTS = {"development", "test"}


def default_base_url() -> str:
    """Return the public URL, preferring the host assigned by the platform.

    Render (and similar PaaS providers) inject the public origin instead of
    asking for it up front, which keeps the blueprint a one-click deploy.
    An explicit ``BASE_URL`` still wins, because environment variables take
    precedence over field defaults.
    """
    return os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")


class Settings(BaseSettings):
    """Typed application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General
    app_name: str = "Link Shortener"
    app_version: str = "1.0.0"
    environment: Literal["development", "production", "test"] = "development"
    debug: bool = False
    base_url: str = Field(default_factory=default_base_url)

    # Security
    secret_key: str = INSECURE_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = Field(default=60 * 24 * 7, ge=1, le=60 * 24 * 365)
    ip_hash_pepper: str = INSECURE_PEPPER
    password_min_length: int = Field(default=8, ge=6, le=64)
    password_max_length: int = Field(default=128, ge=16, le=512)

    # Database
    database_url: str = "postgresql+psycopg://linkshort:linkshort@localhost:5432/linkshort"
    database_echo: bool = False
    auto_create_tables: bool = False

    # Cache
    redis_url: str = ""
    cache_ttl_seconds: int = Field(default=300, ge=0, le=86_400)

    # Limits
    rate_limit_create_per_minute: int = Field(default=20, ge=1, le=10_000)
    rate_limit_auth_per_minute: int = Field(default=10, ge=1, le=10_000)
    short_code_length: int = Field(default=7, ge=6, le=12)
    min_custom_code_length: int = Field(default=3, ge=3, le=12)
    max_custom_code_length: int = Field(default=32, ge=6, le=64)
    max_url_length: int = Field(default=2048, ge=32, le=8192)

    # HTTP
    cors_origins: list[str] = Field(default_factory=list)
    trusted_proxy: bool = False

    @field_validator("base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        """Normalise the public base URL so short links never double-slash."""
        return value.rstrip("/")

    @field_validator("redis_url")
    @classmethod
    def _blank_redis_is_disabled(cls, value: str) -> str:
        """Treat blank ``REDIS_URL`` as "use the in-process cache"."""
        return value.strip()

    @field_validator("database_url")
    @classmethod
    def _force_psycopg_driver(cls, value: str) -> str:
        """Pin the psycopg 3 driver whatever scheme a platform supplies.

        Render, Railway and Heroku hand out ``postgresql://`` (sometimes
        ``postgres://``) URLs without a driver name.  Without one, SQLAlchemy
        2.0 picks psycopg2, which this project does not install, and rejects
        ``postgres://`` outright, so the scheme is normalised here.
        """
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value.split("://", 1)[1]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept both JSON arrays and comma-separated strings for CORS."""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                return value
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _reject_placeholder_secrets(self) -> Settings:
        """Fail fast when production runs with example secrets."""
        if self.environment in DEV_ENVIRONMENTS:
            return self
        leaked = [
            name
            for name, value in (
                ("SECRET_KEY", self.secret_key),
                ("IP_HASH_PEPPER", self.ip_hash_pepper),
            )
            if value in {INSECURE_SECRET, INSECURE_PEPPER, "change-me", "change-me-too"}
        ]
        if leaked:
            raise ValueError(
                f"Refusing to start in {self.environment}: replace placeholder secrets "
                f"{', '.join(leaked)}."
            )
        if not self.base_url.startswith("https://"):
            raise ValueError("BASE_URL must use https:// in production.")
        return self

    @property
    def is_production(self) -> bool:
        """Return whether the service runs in production mode."""
        return self.environment == "production"

    @property
    def base_host(self) -> str:
        """Return the host part of the public base URL."""
        return urlparse(self.base_url).netloc.lower()

    def short_url(self, code: str) -> str:
        """Build the absolute short URL for a code."""
        return f"{self.base_url}/{code}"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()


settings = get_settings()
