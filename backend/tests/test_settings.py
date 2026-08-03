"""F9: pools de BD configurables por entorno (DB_POOL_SIZE / DB_MAX_OVERFLOW)."""

import pytest

from app.core.config import Settings, get_settings
from app.core.database import _create_engine


def test_pools_default_cinco_cinco() -> None:
    """Sin variables de entorno, los pools conservan los valores históricos."""
    settings = Settings(_env_file=None)
    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 5


def test_pools_por_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB_POOL_SIZE/DB_MAX_OVERFLOW del entorno mandan (scheduler prod: 2/0)."""
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    settings = Settings(_env_file=None)
    assert settings.db_pool_size == 2
    assert settings.db_max_overflow == 0


def test_engine_usa_pools_de_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """_create_engine construye el pool con los valores de Settings."""
    monkeypatch.setenv("DB_POOL_SIZE", "2")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    get_settings.cache_clear()
    try:
        engine = _create_engine()
        assert engine.pool.size() == 2
        assert engine.pool._max_overflow == 0  # type: ignore[attr-defined]
        engine.dispose()
    finally:
        # El entorno del conftest sigue intacto: recachear con él.
        get_settings.cache_clear()
        get_settings()
