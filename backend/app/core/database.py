"""Engine sync (psycopg 3), sesión y MetaData con naming_convention estándar.

Todo modelo hereda de `Base`; la naming_convention garantiza nombres
deterministas de constraints e índices desde la primera migración.
"""

from collections.abc import Generator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    metadata = metadata


def _create_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )


engine: Engine = _create_engine()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Dependencia FastAPI: una sesión por request, siempre cerrada al final."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
