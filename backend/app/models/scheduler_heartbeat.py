"""Heartbeat del proceso scheduler (F7): una sola fila que cada corrida del
job de bandas actualiza; /health la lee para reportar ok/degraded/n-a."""

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SchedulerHeartbeat(Base):
    __tablename__ = "scheduler_heartbeat"

    id: Mapped[int] = mapped_column(primary_key=True)
    ultima_corrida: Mapped[datetime] = mapped_column(DateTime(timezone=True))
