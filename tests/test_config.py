import pytest
from pydantic import ValidationError

from growth_os.core.config import Settings


def test_settings_are_loaded_from_prefixed_environment(monkeypatch) -> None:
    monkeypatch.setenv("GROWTH_OS_ENVIRONMENT", "test")
    monkeypatch.setenv("GROWTH_OS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("GROWTH_OS_DATABASE_URL", "postgresql+asyncpg://db.example/growth")

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"
    assert settings.database_url.get_secret_value() == "postgresql+asyncpg://db.example/growth"
    assert "db.example" not in repr(settings)


def test_settings_ignore_unknown_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("GROWTH_OS_FUTURE_OPTION", "safe-to-ignore")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Growth OS API"


def test_settings_reject_non_postgresql_persistence(monkeypatch) -> None:
    monkeypatch.setenv("GROWTH_OS_DATABASE_URL", "sqlite+aiosqlite:///local.db")

    with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
        Settings(_env_file=None)
