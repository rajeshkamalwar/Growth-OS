from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="GROWTH_OS_",
        extra="ignore",
    )

    app_name: str = "Growth OS API"
    environment: Literal["local", "test", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://growth_os:growth_os@localhost:5432/growth_os"
    )

    @field_validator("database_url")
    @classmethod
    def database_must_use_async_postgresql(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("database_url must use the postgresql+asyncpg driver")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
