"""bitacora de eliminaciones

F12 p.4 (ADITIVA, compatible con filas existentes): tabla NUEVA
`solicitudes_eliminadas` — snapshot autosuficiente (texto plano, SIN FKs) de
cada solicitud eliminada definitivamente por un admin. Solo INSERT y SELECT;
no existe endpoint que la borre o edite. No toca ninguna tabla existente.

Revision ID: 4b7e2f91a6c3
Revises: c11f0b7a9d42
Create Date: 2026-08-17 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4b7e2f91a6c3"
down_revision: str | None = "c11f0b7a9d42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "solicitudes_eliminadas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("solicitud_id", sa.Integer(), nullable=False),
        sa.Column("folio", sa.String(), nullable=True),
        sa.Column("cliente", sa.String(), nullable=True),
        sa.Column("sucursal", sa.Text(), nullable=False),
        sa.Column("estado_final", sa.String(), nullable=False),
        sa.Column("monto_confirmado", sa.Numeric(14, 2), nullable=True),
        sa.Column("vendedor", sa.Text(), nullable=False),
        sa.Column("comprador", sa.Text(), nullable=True),
        sa.Column("num_partidas", sa.Integer(), nullable=False),
        sa.Column("num_opciones", sa.Integer(), nullable=False),
        sa.Column("num_comprobantes", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("eliminado_por_id", sa.Integer(), nullable=False),
        sa.Column("eliminado_por", sa.Text(), nullable=False),
        sa.Column(
            "eliminado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solicitudes_eliminadas")),
    )


def downgrade() -> None:
    op.drop_table("solicitudes_eliminadas")
