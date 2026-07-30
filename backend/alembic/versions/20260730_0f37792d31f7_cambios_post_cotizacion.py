"""cambios post-cotizacion

F8h (req. de dirección, especificación §4.8b): solicitudes de cambio de
cantidad/unidad tras COTIZADA con aprobación del comprador — snapshot
inmutable del antes/después, UN solo PENDIENTE por solicitud y flag
materializado `solicitudes.cambio_pendiente`.

Revision ID: 0f37792d31f7
Revises: 108c538d515a
Create Date: 2026-07-30 16:01:36.606638

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0f37792d31f7"
down_revision: str | None = "108c538d515a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

estado_cambio = sa.Enum("PENDIENTE", "APROBADO", "RECHAZADO", "RETIRADO", name="estado_cambio")


def upgrade() -> None:
    op.create_table(
        "solicitudes_cambio",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("solicitud_id", sa.Integer(), nullable=False),
        sa.Column("estado_cambio", estado_cambio, nullable=False),
        sa.Column("solicitado_por", sa.Integer(), nullable=False),
        sa.Column("resuelto_por", sa.Integer(), nullable=True),
        sa.Column("comentario_solicitante", sa.Text(), nullable=True),
        sa.Column("comentario_resolucion", sa.Text(), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("resuelto_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["solicitud_id"],
            ["solicitudes.id"],
            name=op.f("fk_solicitudes_cambio_solicitud_id_solicitudes"),
        ),
        sa.ForeignKeyConstraint(
            ["solicitado_por"],
            ["usuarios.id"],
            name=op.f("fk_solicitudes_cambio_solicitado_por_usuarios"),
        ),
        sa.ForeignKeyConstraint(
            ["resuelto_por"],
            ["usuarios.id"],
            name=op.f("fk_solicitudes_cambio_resuelto_por_usuarios"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solicitudes_cambio")),
    )
    op.create_index(
        "ix_solicitudes_cambio_pendiente_unico",
        "solicitudes_cambio",
        ["solicitud_id"],
        unique=True,
        postgresql_where=sa.text("estado_cambio = 'PENDIENTE'"),
    )
    op.create_table(
        "cambio_partidas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cambio_id", sa.Integer(), nullable=False),
        sa.Column("partida_id", sa.Integer(), nullable=False),
        sa.Column("cantidad_anterior", sa.Numeric(14, 3), nullable=False),
        sa.Column("cantidad_nueva", sa.Numeric(14, 3), nullable=False),
        sa.Column("unidad_anterior", sa.String(), nullable=False),
        sa.Column("unidad_nueva", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cambio_id"],
            ["solicitudes_cambio.id"],
            name=op.f("fk_cambio_partidas_cambio_id_solicitudes_cambio"),
        ),
        sa.ForeignKeyConstraint(
            ["partida_id"],
            ["solicitud_partidas.id"],
            name=op.f("fk_cambio_partidas_partida_id_solicitud_partidas"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cambio_partidas")),
    )
    op.add_column(
        "solicitudes",
        sa.Column("cambio_pendiente", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("solicitudes", "cambio_pendiente")
    op.drop_table("cambio_partidas")
    op.drop_index("ix_solicitudes_cambio_pendiente_unico", table_name="solicitudes_cambio")
    op.drop_table("solicitudes_cambio")
    estado_cambio.drop(op.get_bind(), checkfirst=True)
