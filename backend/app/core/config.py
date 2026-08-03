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
    # Intervalo del job de bandas del scheduler (900 s = 15 min); env var
    # SCHEDULER_BANDAS_SEGUNDOS para bajarlo en desarrollo.
    scheduler_bandas_segundos: int = 900
    # F8g: directorio del subsistema de archivos (comprobantes). En dev es
    # relativo al backend y está en .gitignore; F9 lo monta como volumen
    # persistente incluido en los backups.
    archivos_dir: str = "./var/archivos"
    # F9: pools del engine configurables por entorno (DB_POOL_SIZE /
    # DB_MAX_OVERFLOW). La RDS de producción tiene 1 GB de RAM: la API corre
    # con 5/5 y el proceso del scheduler con 2/0 (lo fija su servicio en
    # compose.prod.yml — abre su propio pool y no atiende requests).
    db_pool_size: int = 5
    db_max_overflow: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
