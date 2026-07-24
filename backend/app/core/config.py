"""Configuración de la aplicación vía pydantic-settings.

Todas las variables viven en el entorno (o `.env` en desarrollo). Las que no
tienen default (DATABASE_URL, JWT_SECRET) son críticas: si faltan, la app
falla al arrancar con un error de validación.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    jwt_secret: str
    jwt_access_minutes: int = 30
    jwt_refresh_days: int = 7
    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
