"""esquema inicial

Revision ID: 450bd8f7d5fc
Revises:
Create Date: 2026-07-24

Generada con autogenerate y revisada a mano:
- Los tipos enum se crean explícitamente UNA vez (moneda y estado se usan en
  varias tablas; el CREATE TYPE inline de autogenerate fallaría por duplicado)
  y las columnas usan create_type=False.
- La FK circular solicitudes.opcion_seleccionada_id → cotizacion_opciones
  (use_alter) se emite como create_foreign_key explícito: op.create_table la
  omite silenciosamente.
- Índice único parcial de titular por sucursal verificado (postgresql_where).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "450bd8f7d5fc"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS: dict[str, list[str]] = {
    "rol": ["vendedor", "comprador", "admin", "gerente"],
    "estado": [
        "BORRADOR",
        "ENVIADA",
        "EN_PROCESO",
        "COTIZADA",
        "CONFIRMADA",
        "RECHAZADA",
        "CANCELADA",
        "NO_CONFIRMADA",
    ],
    "prioridad": ["NORMAL", "URGENTE"],
    "moneda": ["MXN", "USD"],
    "letra": ["A", "B", "C", "D", "E"],
    "familia_motivo": ["falta_informacion", "no_procede"],
    "alcance_gerente": ["global", "sucursal"],
}


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        sa.Enum(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "dias_festivos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("descripcion", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dias_festivos")),
        sa.UniqueConstraint("fecha", name=op.f("uq_dias_festivos_fecha")),
    )
    op.create_table(
        "motivos_rechazo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("familia", _enum("familia_motivo"), nullable=False),
        sa.Column("texto", sa.String(), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_motivos_rechazo")),
        sa.UniqueConstraint("familia", "texto", name=op.f("uq_motivos_rechazo_familia")),
    )
    op.create_table(
        "sucursales",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(), nullable=False),
        sa.Column("prefijo_folio", sa.String(), nullable=False),
        sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("activa", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sucursales")),
        sa.UniqueConstraint("nombre", name=op.f("uq_sucursales_nombre")),
        sa.UniqueConstraint("prefijo_folio", name=op.f("uq_sucursales_prefijo_folio")),
    )
    op.create_table(
        "folio_counters",
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("ultimo", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["sucursal_id"],
            ["sucursales.id"],
            name=op.f("fk_folio_counters_sucursal_id_sucursales"),
        ),
        sa.PrimaryKeyConstraint("sucursal_id", name=op.f("pk_folio_counters")),
    )
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("rol", _enum("rol"), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=True),
        sa.Column("alcance_gerente", _enum("alcance_gerente"), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "must_change_password", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["sucursal_id"], ["sucursales.id"], name=op.f("fk_usuarios_sucursal_id_sucursales")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuarios")),
    )
    # Unicidad case-insensitive del email.
    op.create_index(
        "ix_usuarios_email_lower", "usuarios", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "clientes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre_normalizado", sa.String(), nullable=False),
        sa.Column("creado_por", sa.Integer(), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["creado_por"], ["usuarios.id"], name=op.f("fk_clientes_creado_por_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clientes")),
        sa.UniqueConstraint("nombre_normalizado", name=op.f("uq_clientes_nombre_normalizado")),
    )
    op.create_table(
        "comprador_sucursal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("comprador_id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("titular", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["comprador_id"],
            ["usuarios.id"],
            name=op.f("fk_comprador_sucursal_comprador_id_usuarios"),
        ),
        sa.ForeignKeyConstraint(
            ["sucursal_id"],
            ["sucursales.id"],
            name=op.f("fk_comprador_sucursal_sucursal_id_sucursales"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comprador_sucursal")),
        sa.UniqueConstraint(
            "comprador_id", "sucursal_id", name=op.f("uq_comprador_sucursal_comprador_id")
        ),
    )
    # Solo UN titular por sucursal (índice único parcial).
    op.create_index(
        "ix_comprador_sucursal_titular_unico",
        "comprador_sucursal",
        ["sucursal_id"],
        unique=True,
        postgresql_where=sa.text("titular"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expira_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revocado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_refresh_tokens_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_table(
        "solicitudes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("folio", sa.String(), nullable=True),
        sa.Column("vendedor_id", sa.Integer(), nullable=False),
        sa.Column("comprador_id", sa.Integer(), nullable=True),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=True),
        sa.Column("estado", _enum("estado"), nullable=False),
        sa.Column("prioridad", _enum("prioridad"), nullable=False),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("opcion_seleccionada_id", sa.Integer(), nullable=True),
        sa.Column("monto_confirmado", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("moneda_confirmada", _enum("moneda"), nullable=True),
        sa.Column("motivo_no_confirmada", sa.Text(), nullable=True),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("enviado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cotizado_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmado_en", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["cliente_id"], ["clientes.id"], name=op.f("fk_solicitudes_cliente_id_clientes")
        ),
        sa.ForeignKeyConstraint(
            ["comprador_id"], ["usuarios.id"], name=op.f("fk_solicitudes_comprador_id_usuarios")
        ),
        sa.ForeignKeyConstraint(
            ["sucursal_id"], ["sucursales.id"], name=op.f("fk_solicitudes_sucursal_id_sucursales")
        ),
        sa.ForeignKeyConstraint(
            ["vendedor_id"], ["usuarios.id"], name=op.f("fk_solicitudes_vendedor_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solicitudes")),
        sa.UniqueConstraint("folio", name=op.f("uq_solicitudes_folio")),
    )
    op.create_index("ix_solicitudes_cliente", "solicitudes", ["cliente_id"], unique=False)
    op.create_index(
        "ix_solicitudes_comprador_estado", "solicitudes", ["comprador_id", "estado"], unique=False
    )
    op.create_index(
        "ix_solicitudes_sucursal_creado", "solicitudes", ["sucursal_id", "creado_en"], unique=False
    )
    op.create_index(
        "ix_solicitudes_vendedor_estado", "solicitudes", ["vendedor_id", "estado"], unique=False
    )
    op.create_table(
        "cotizacion_opciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("solicitud_id", sa.Integer(), nullable=False),
        sa.Column("letra", _enum("letra"), nullable=False),
        sa.Column("moneda", _enum("moneda"), nullable=True),
        sa.Column("vigencia", sa.Date(), nullable=True),
        sa.Column("comentarios", sa.Text(), nullable=True),
        sa.Column("proveedor", sa.String(), nullable=True),
        sa.Column(
            "total",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("completa", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["solicitud_id"],
            ["solicitudes.id"],
            name=op.f("fk_cotizacion_opciones_solicitud_id_solicitudes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cotizacion_opciones")),
        sa.UniqueConstraint(
            "solicitud_id", "letra", name=op.f("uq_cotizacion_opciones_solicitud_id")
        ),
    )
    # FK circular (use_alter): se agrega DESPUÉS de crear cotizacion_opciones.
    op.create_foreign_key(
        op.f("fk_solicitudes_opcion_seleccionada_id_cotizacion_opciones"),
        "solicitudes",
        "cotizacion_opciones",
        ["opcion_seleccionada_id"],
        ["id"],
    )
    op.create_table(
        "historial_estados",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("solicitud_id", sa.Integer(), nullable=False),
        sa.Column("de", _enum("estado"), nullable=True),
        sa.Column("a", _enum("estado"), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("motivo_id", sa.Integer(), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["motivo_id"],
            ["motivos_rechazo.id"],
            name=op.f("fk_historial_estados_motivo_id_motivos_rechazo"),
        ),
        sa.ForeignKeyConstraint(
            ["solicitud_id"],
            ["solicitudes.id"],
            name=op.f("fk_historial_estados_solicitud_id_solicitudes"),
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_historial_estados_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_historial_estados")),
    )
    op.create_index(
        "ix_historial_estados_solicitud_ts",
        "historial_estados",
        ["solicitud_id", "timestamp"],
        unique=False,
    )
    op.create_table(
        "notificaciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("solicitud_id", sa.Integer(), nullable=True),
        sa.Column("tipo", sa.String(), nullable=False),
        sa.Column("mensaje", sa.Text(), nullable=False),
        sa.Column("leida", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["solicitud_id"],
            ["solicitudes.id"],
            name=op.f("fk_notificaciones_solicitud_id_solicitudes"),
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_notificaciones_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notificaciones")),
    )
    op.create_index(
        "ix_notificaciones_usuario_leida", "notificaciones", ["usuario_id", "leida"], unique=False
    )
    op.create_table(
        "solicitud_partidas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("solicitud_id", sa.Integer(), nullable=False),
        sa.Column("num_partida", sa.Integer(), nullable=False),
        sa.Column("codigo_sap", sa.String(), nullable=True),
        sa.Column("cantidad", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unidad", sa.String(), nullable=False),
        sa.Column("tipo_acero", sa.String(), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("medidas", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["solicitud_id"],
            ["solicitudes.id"],
            name=op.f("fk_solicitud_partidas_solicitud_id_solicitudes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_solicitud_partidas")),
        sa.UniqueConstraint(
            "solicitud_id", "num_partida", name=op.f("uq_solicitud_partidas_solicitud_id")
        ),
    )
    op.create_table(
        "opcion_partidas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("opcion_id", sa.Integer(), nullable=False),
        sa.Column("partida_id", sa.Integer(), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("importe", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tiempo_entrega", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["opcion_id"],
            ["cotizacion_opciones.id"],
            name=op.f("fk_opcion_partidas_opcion_id_cotizacion_opciones"),
        ),
        sa.ForeignKeyConstraint(
            ["partida_id"],
            ["solicitud_partidas.id"],
            name=op.f("fk_opcion_partidas_partida_id_solicitud_partidas"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opcion_partidas")),
        sa.UniqueConstraint("opcion_id", "partida_id", name=op.f("uq_opcion_partidas_opcion_id")),
    )


def downgrade() -> None:
    op.drop_table("opcion_partidas")
    op.drop_table("solicitud_partidas")
    op.drop_index("ix_notificaciones_usuario_leida", table_name="notificaciones")
    op.drop_table("notificaciones")
    op.drop_index("ix_historial_estados_solicitud_ts", table_name="historial_estados")
    op.drop_table("historial_estados")
    # Primero la FK circular; sin esto no se puede tirar cotizacion_opciones.
    op.drop_constraint(
        op.f("fk_solicitudes_opcion_seleccionada_id_cotizacion_opciones"),
        "solicitudes",
        type_="foreignkey",
    )
    op.drop_table("cotizacion_opciones")
    op.drop_index("ix_solicitudes_vendedor_estado", table_name="solicitudes")
    op.drop_index("ix_solicitudes_sucursal_creado", table_name="solicitudes")
    op.drop_index("ix_solicitudes_comprador_estado", table_name="solicitudes")
    op.drop_index("ix_solicitudes_cliente", table_name="solicitudes")
    op.drop_table("solicitudes")
    op.drop_table("refresh_tokens")
    op.drop_index(
        "ix_comprador_sucursal_titular_unico",
        table_name="comprador_sucursal",
        postgresql_where=sa.text("titular"),
    )
    op.drop_table("comprador_sucursal")
    op.drop_table("clientes")
    op.drop_index("ix_usuarios_email_lower", table_name="usuarios")
    op.drop_table("usuarios")
    op.drop_table("folio_counters")
    op.drop_table("sucursales")
    op.drop_table("motivos_rechazo")
    op.drop_table("dias_festivos")

    bind = op.get_bind()
    for name in ENUMS:
        sa.Enum(name=name).drop(bind, checkfirst=True)
