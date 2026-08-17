"""fincada lado compras

F12 p.5 (ADITIVA, compatible con filas existentes): marcado interno FINCADA
en solicitudes — flag con server_default false (todas las filas existentes
quedan sin fincar), quién la marcó (FK nullable a usuarios) y cuándo. Visible
SOLO para comprador, gerente_compras y admin; el lado ventas no recibe las
claves en su JSON.

Revision ID: 9d3a51c8e7f2
Revises: 4b7e2f91a6c3
Create Date: 2026-08-17 18:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9d3a51c8e7f2"
down_revision: str | None = "4b7e2f91a6c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "solicitudes",
        sa.Column("fincada", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("solicitudes", sa.Column("fincada_por", sa.Integer(), nullable=True))
    op.add_column("solicitudes", sa.Column("fincada_en", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_solicitudes_fincada_por_usuarios"),
        "solicitudes",
        "usuarios",
        ["fincada_por"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_solicitudes_fincada_por_usuarios"), "solicitudes", type_="foreignkey"
    )
    op.drop_column("solicitudes", "fincada_en")
    op.drop_column("solicitudes", "fincada_por")
    op.drop_column("solicitudes", "fincada")
