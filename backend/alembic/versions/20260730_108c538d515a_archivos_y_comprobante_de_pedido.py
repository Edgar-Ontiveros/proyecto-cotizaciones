"""archivos y comprobante de pedido

F8g (req. de dirección): subsistema de archivos — tabla `archivos` con UNA
fila vigente por (solicitud, tipo). El contenido vive en el filesystem
(settings.archivos_dir) con el UUID como nombre; aquí solo los metadatos.

Revision ID: 108c538d515a
Revises: 38eed4483803
Create Date: 2026-07-30 15:24:48.667742

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "108c538d515a"
down_revision: str | None = "38eed4483803"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "archivos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("solicitud_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("nombre_original", sa.String(), nullable=False),
        sa.Column("mime", sa.String(), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("subido_por", sa.Integer(), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["solicitud_id"], ["solicitudes.id"], name=op.f("fk_archivos_solicitud_id_solicitudes")
        ),
        sa.ForeignKeyConstraint(
            ["subido_por"], ["usuarios.id"], name=op.f("fk_archivos_subido_por_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_archivos")),
        sa.UniqueConstraint("solicitud_id", "tipo", name=op.f("uq_archivos_solicitud_id")),
    )


def downgrade() -> None:
    op.drop_table("archivos")
