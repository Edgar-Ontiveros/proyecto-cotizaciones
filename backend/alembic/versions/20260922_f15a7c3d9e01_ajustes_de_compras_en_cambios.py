"""ajustes de compras en cambios

F15 p.3 (ADITIVA, compatible con filas existentes): tres columnas NULL en
`cambio_partidas` que registran, al APROBAR, el valor FINAL que capturó
compras cuando difiere de lo que pidió ventas — cantidad, unidad y/o
descripción de la partida. NULL = compras respetó lo solicitado. El snapshot
del "antes/después pedido" (columnas *_anterior / *_nueva) sigue inmutable.

Revision ID: f15a7c3d9e01
Revises: a3f19c25d8e4
Create Date: 2026-09-22 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f15a7c3d9e01"
down_revision: str | None = "a3f19c25d8e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cambio_partidas", sa.Column("cantidad_ajustada", sa.Numeric(14, 3), nullable=True)
    )
    op.add_column("cambio_partidas", sa.Column("unidad_ajustada", sa.String(), nullable=True))
    op.add_column("cambio_partidas", sa.Column("descripcion_ajustada", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("cambio_partidas", "descripcion_ajustada")
    op.drop_column("cambio_partidas", "unidad_ajustada")
    op.drop_column("cambio_partidas", "cantidad_ajustada")
