"""ajuste admin en historial

F9-prep: marca EXPLÍCITA (no detección por texto) de los eventos cuyo
comentario expone valores administrativos (corrección de TC). Al serializar
para el lado ventas, el comentario se redacta a "Ajuste administrativo".

Revision ID: 969c0e20b141
Revises: db20b4ba897e
Create Date: 2026-07-28 12:12:41.103937

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "969c0e20b141"
down_revision: str | None = "db20b4ba897e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "historial_estados",
        sa.Column("ajuste_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Datos pre-F9: los eventos de corrección de TC ya escritos se marcan una
    # única vez por su comentario (a partir de aquí, la columna es la verdad).
    op.execute(
        "UPDATE historial_estados SET ajuste_admin = true WHERE comentario LIKE 'TC corregido%'"
    )


def downgrade() -> None:
    op.drop_column("historial_estados", "ajuste_admin")
