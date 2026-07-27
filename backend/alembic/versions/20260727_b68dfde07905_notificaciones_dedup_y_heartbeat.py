"""notificaciones dedup y scheduler heartbeat

Revision ID: b68dfde07905
Revises: 4c369bedc2b5
Create Date: 2026-07-27 08:44:34.541767

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b68dfde07905"
down_revision: str | None = "4c369bedc2b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # dedup: clave de idempotencia de las alertas del scheduler (F7). Las
    # notificaciones de eventos la dejan NULL (el UNIQUE de PostgreSQL admite
    # múltiples NULL).
    op.add_column("notificaciones", sa.Column("dedup", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_notificaciones_dedup", "notificaciones", ["dedup"])
    op.create_table(
        "scheduler_heartbeat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ultima_corrida", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_heartbeat")),
    )


def downgrade() -> None:
    op.drop_table("scheduler_heartbeat")
    op.drop_constraint("uq_notificaciones_dedup", "notificaciones", type_="unique")
    op.drop_column("notificaciones", "dedup")
