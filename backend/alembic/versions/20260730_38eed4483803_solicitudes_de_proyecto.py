"""solicitudes de proyecto

F8f (req. de dirección): flag es_proyecto en solicitudes — se define al crear,
solo cambia en BORRADOR y dispara notificaciones especiales al enviarse.

Revision ID: 38eed4483803
Revises: 969c0e20b141
Create Date: 2026-07-30 14:56:54.078401

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "38eed4483803"
down_revision: str | None = "969c0e20b141"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "solicitudes",
        sa.Column("es_proyecto", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("solicitudes", "es_proyecto")
