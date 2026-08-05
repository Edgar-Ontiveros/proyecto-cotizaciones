"""comprobantes multiples

F10 p.6 (ADITIVA, compatible con datos existentes): una solicitud puede tener
N comprobantes. Cae el UNIQUE(solicitud_id, tipo) — las filas existentes
quedan tal cual (una por solicitud, ahora simplemente la primera de N) — y
entra un índice normal para las búsquedas por (solicitud, tipo).

El downgrade recrea el UNIQUE: solo es posible si ninguna solicitud acumuló
más de un comprobante (en ese caso hay que depurar a mano antes de bajar).

Revision ID: 2db348b42524
Revises: 0f37792d31f7
Create Date: 2026-08-04 17:30:24.799404

"""

from collections.abc import Sequence

from alembic import op

revision: str = "2db348b42524"
down_revision: str | None = "0f37792d31f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_archivos_solicitud_id", "archivos", type_="unique")
    op.create_index("ix_archivos_solicitud_tipo", "archivos", ["solicitud_id", "tipo"])


def downgrade() -> None:
    op.drop_index("ix_archivos_solicitud_tipo", table_name="archivos")
    op.create_unique_constraint("uq_archivos_solicitud_id", "archivos", ["solicitud_id", "tipo"])
