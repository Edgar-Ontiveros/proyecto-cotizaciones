"""bitacora de impresiones

F14 p.2 (ADITIVA, compatible con filas existentes): tabla NUEVA `impresiones`
— registro de qué documento se imprimió (Cotización / Pedido confirmado), por
quién y cuándo. Snapshot autosuficiente SIN FKs, al estilo de la bitácora de
eliminaciones. No toca ninguna tabla existente.

Revision ID: a3f19c25d8e4
Revises: ce7770847875
Create Date: 2026-08-21 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3f19c25d8e4"
down_revision: str | None = "ce7770847875"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "impresiones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("solicitud_id", sa.Integer(), nullable=False),
        sa.Column("folio", sa.String(), nullable=True),
        sa.Column("documento", sa.String(), nullable=False),
        sa.Column("estado", sa.String(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("usuario", sa.Text(), nullable=False),
        sa.Column("rol", sa.String(), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_impresiones")),
    )


def downgrade() -> None:
    op.drop_table("impresiones")
