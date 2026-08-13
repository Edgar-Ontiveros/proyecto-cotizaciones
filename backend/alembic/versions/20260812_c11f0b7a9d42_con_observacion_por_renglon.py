"""con observacion por renglon

F11 p.1 (ADITIVA, compatible con datos existentes): tercer estatus de renglón
"Con observación" — el renglón se cotiza normal (precio, totales y completitud
intactos) y solo adjunta un comentario de esa partida. Dos columnas nuevas en
opcion_partidas: el flag con server_default false (las filas existentes quedan
sin observación) y el texto nullable.

Revision ID: c11f0b7a9d42
Revises: 2db348b42524
Create Date: 2026-08-12 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c11f0b7a9d42"
down_revision: str | None = "2db348b42524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "opcion_partidas",
        sa.Column("con_observacion", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("opcion_partidas", sa.Column("observacion", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("opcion_partidas", "observacion")
    op.drop_column("opcion_partidas", "con_observacion")
