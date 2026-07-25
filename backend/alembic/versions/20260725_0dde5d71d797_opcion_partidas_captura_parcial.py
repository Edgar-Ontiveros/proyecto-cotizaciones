"""opcion partidas captura parcial

Revision ID: 0dde5d71d797
Revises: c9992a839cc8
Create Date: 2026-07-25 08:14:41.036958

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0dde5d71d797"
down_revision: str | None = "c9992a839cc8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # La captura del comprador puede ser parcial (§4.8): un renglón puede traer
    # tiempo_entrega sin precio todavía. La obligatoriedad se exige al cotizar.
    op.alter_column(
        "opcion_partidas", "precio_unitario", existing_type=sa.Numeric(14, 2), nullable=True
    )
    op.alter_column("opcion_partidas", "importe", existing_type=sa.Numeric(14, 2), nullable=True)


def downgrade() -> None:
    op.alter_column("opcion_partidas", "importe", existing_type=sa.Numeric(14, 2), nullable=False)
    op.alter_column(
        "opcion_partidas", "precio_unitario", existing_type=sa.Numeric(14, 2), nullable=False
    )
