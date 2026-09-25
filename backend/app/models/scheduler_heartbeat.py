"""Heartbeat del proceso scheduler (F7): una fila POR JOB que cada corrida
actualiza; /health las lee para reportar ok/degraded/n-a. F16b agrega la
fila del sondeo de OC de SAP (misma tabla, sin migración: son datos).

  id 1 → job de bandas (semáforo)    → /health "scheduler" y healthcheck del
                                        contenedor
  id 2 → job de sondeo de OC (F16b)  → /health "sondeo_oc"
"""

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

HEARTBEAT_BANDAS = 1
HEARTBEAT_SONDEO_OC = 2


class SchedulerHeartbeat(Base):
    __tablename__ = "scheduler_heartbeat"

    id: Mapped[int] = mapped_column(primary_key=True)
    ultima_corrida: Mapped[datetime] = mapped_column(DateTime(timezone=True))
