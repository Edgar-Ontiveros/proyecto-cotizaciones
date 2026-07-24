"""Catálogos administrables: motivos de rechazo y días festivos."""

from datetime import date
from enum import StrEnum

from sqlalchemy import Date, Enum, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FamiliaMotivo(StrEnum):
    # falta_informacion: se espera corrección y reenvío; no_procede: terminal.
    FALTA_INFORMACION = "falta_informacion"
    NO_PROCEDE = "no_procede"


class MotivoRechazo(Base):
    __tablename__ = "motivos_rechazo"
    __table_args__ = (UniqueConstraint("familia", "texto"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    familia: Mapped[FamiliaMotivo] = mapped_column(
        Enum(FamiliaMotivo, name="familia_motivo", values_callable=lambda e: [m.value for m in e])
    )
    texto: Mapped[str]
    activo: Mapped[bool] = mapped_column(server_default=true())


class DiaFestivo(Base):
    __tablename__ = "dias_festivos"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[date] = mapped_column(Date, unique=True)
    descripcion: Mapped[str | None]
