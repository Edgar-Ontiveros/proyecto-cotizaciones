"""roles finales y precio cuatro decimales

F5: (1) desaparece el alcance "global" del gerente — el rol gerente es
siempre de sucursal y los directores se dan de alta como admin; se elimina
la columna usuarios.alcance_gerente y su tipo enum. (2) Los precios reales
traen 3–4 decimales: opcion_partidas.precio_unitario pasa a Numeric(14,4)
(el importe sigue en 14,2 y se calcula del precio almacenado).

Revision ID: 4c369bedc2b5
Revises: 0dde5d71d797
Create Date: 2026-07-25 08:43:20.668935

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "4c369bedc2b5"
down_revision: str | None = "0dde5d71d797"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALCANCE = postgresql.ENUM("global", "sucursal", name="alcance_gerente", create_type=False)


def upgrade() -> None:
    op.drop_column("usuarios", "alcance_gerente")
    _ALCANCE.drop(op.get_bind(), checkfirst=True)
    op.alter_column(
        "opcion_partidas",
        "precio_unitario",
        existing_type=sa.Numeric(14, 2),
        type_=sa.Numeric(14, 4),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "opcion_partidas",
        "precio_unitario",
        existing_type=sa.Numeric(14, 4),
        type_=sa.Numeric(14, 2),
        existing_nullable=True,
    )
    _ALCANCE.create(op.get_bind(), checkfirst=True)
    # Los gerentes existentes quedan con alcance "sucursal" (todos tienen
    # sucursal_id desde F5).
    op.add_column("usuarios", sa.Column("alcance_gerente", _ALCANCE, nullable=True))
    op.execute("UPDATE usuarios SET alcance_gerente = 'sucursal' WHERE rol = 'gerente'")
