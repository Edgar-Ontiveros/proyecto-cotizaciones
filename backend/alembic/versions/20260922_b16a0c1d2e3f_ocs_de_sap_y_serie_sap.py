"""ocs de sap y serie sap

F16a (ADITIVA): tabla nueva `solicitud_ocs` (vínculo solicitud ↔ OC de SAP con
snapshot y estatus derivado) y columna NULL `sucursales.serie_sap` con
BACKFILL por nombre de sucursal según las series reales de OPOR en HANA
(NNM1.SeriesName sin punto). No toca filas existentes fuera de ese backfill.

Revision ID: b16a0c1d2e3f
Revises: f15a7c3d9e01
Create Date: 2026-09-22 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b16a0c1d2e3f"
down_revision: str | None = "f15a7c3d9e01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# nombre de sucursal (seed real) → prefijo de serie SAP verificado en HANA.
SERIES_SAP = {
    "Matriz": "CH",
    "Norte": "CN",
    "Manufactura": "MA",
    "TIK": "TIK",
    "Cd. Juárez": "JU",
    "Hermosillo": "HE",
    "Obregón": "OB",
    "Culiacán": "CU",
    "Mexicali": "ME",
    "Monterrey": "MTY",
    "León": "LE",
}


def upgrade() -> None:
    op.add_column("sucursales", sa.Column("serie_sap", sa.String(), nullable=True))
    for nombre, serie in SERIES_SAP.items():
        op.execute(
            sa.text(
                "UPDATE sucursales SET serie_sap = :serie "
                "WHERE nombre = :nombre AND serie_sap IS NULL"
            ).bindparams(serie=serie, nombre=nombre)
        )
    op.create_table(
        "solicitud_ocs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("solicitud_id", sa.Integer(), nullable=False),
        sa.Column("doc_entry", sa.Integer(), nullable=False),
        sa.Column("doc_num", sa.Integer(), nullable=False),
        sa.Column("serie", sa.String(), nullable=True),
        sa.Column("sucursal_sap", sa.String(), nullable=True),
        sa.Column("proveedor_codigo", sa.String(), nullable=True),
        sa.Column("proveedor", sa.String(), nullable=True),
        sa.Column("moneda", sa.String(), nullable=True),
        sa.Column("total", sa.Numeric(14, 2), nullable=True),
        sa.Column("tipo_cambio", sa.Numeric(10, 4), nullable=True),
        sa.Column("fecha_creacion", sa.Date(), nullable=True),
        sa.Column("fecha_contabilizacion", sa.Date(), nullable=True),
        sa.Column("fecha_entrega", sa.Date(), nullable=True),
        sa.Column("encargado_compras", sa.String(), nullable=True),
        sa.Column("estatus_derivado", sa.String(), nullable=False),
        sa.Column("vencida", sa.Boolean(), nullable=False),
        sa.Column("donde_oc", sa.String(), nullable=True),
        sa.Column("donde_entrada", sa.String(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ultimo_sync_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vinculada_por", sa.Integer(), nullable=False),
        sa.Column(
            "vinculada_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("activa", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("ultimo_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["solicitud_id"],
            ["solicitudes.id"],
            name=op.f("fk_solicitud_ocs_solicitud_id_solicitudes"),
        ),
        sa.ForeignKeyConstraint(
            ["vinculada_por"], ["usuarios.id"], name=op.f("fk_solicitud_ocs_vinculada_por_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solicitud_ocs")),
        sa.UniqueConstraint(
            "solicitud_id", "doc_entry", name=op.f("uq_solicitud_ocs_solicitud_id_doc_entry")
        ),
    )
    op.create_index("ix_solicitud_ocs_doc_entry_activa", "solicitud_ocs", ["doc_entry", "activa"])


def downgrade() -> None:
    op.drop_index("ix_solicitud_ocs_doc_entry_activa", table_name="solicitud_ocs")
    op.drop_table("solicitud_ocs")
    op.drop_column("sucursales", "serie_sap")
