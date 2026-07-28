"""permisos v2 y moneda por renglon

Revision ID: db20b4ba897e
Revises: 923c7cfecbc4
Create Date: 2026-07-27 17:42:19.952530

F8c, dos frentes:

1. ROLES v2 por área: 'gerente' se renombra 'gerente_sucursal'; nacen
   'gerente_compras' (área compras, global) y 'director_ventas' (área ventas,
   global). El downgrade es BEST-EFFORT: gerente_sucursal vuelve a 'gerente' y
   los roles nuevos caen a 'admin' (el modelo viejo no puede representarlos).

2. MONEDA POR RENGLÓN + TC: la moneda baja de cotizacion_opciones a
   opcion_partidas (backfill desde la opción); la opción cambia su `total`
   por SUBTOTALES total_mxn/total_usd; solicitudes gana tipo_cambio
   Numeric(10,4). Las confirmadas en USD existentes (datos demo/dev) se
   consolidan a MXN con TC 18.50 — decisión documentada con Edgar para datos
   de demostración; no existe producción.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "db20b4ba897e"
down_revision: str | None = "923c7cfecbc4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TC_DEMO = "18.50"

_moneda = postgresql.ENUM(name="moneda", create_type=False)


def upgrade() -> None:
    # ---- 1) roles v2 (PG >= 12 permite ADD VALUE en transacción) ----
    op.execute("ALTER TYPE rol RENAME VALUE 'gerente' TO 'gerente_sucursal'")
    op.execute("ALTER TYPE rol ADD VALUE IF NOT EXISTS 'gerente_compras'")
    op.execute("ALTER TYPE rol ADD VALUE IF NOT EXISTS 'director_ventas'")

    # ---- 2) moneda por renglón + subtotales + tipo de cambio ----
    op.add_column("opcion_partidas", sa.Column("moneda", _moneda, nullable=True))
    op.execute(
        """
        UPDATE opcion_partidas op
        SET moneda = co.moneda
        FROM cotizacion_opciones co
        WHERE op.opcion_id = co.id AND co.moneda IS NOT NULL
        """
    )
    op.add_column(
        "cotizacion_opciones",
        sa.Column("total_mxn", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "cotizacion_opciones",
        sa.Column("total_usd", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False),
    )
    op.execute(
        """
        UPDATE cotizacion_opciones SET
            total_mxn = CASE WHEN moneda = 'MXN' THEN total ELSE 0 END,
            total_usd = CASE WHEN moneda = 'USD' THEN total ELSE 0 END
        """
    )
    op.drop_column("cotizacion_opciones", "total")
    op.drop_column("cotizacion_opciones", "moneda")

    op.add_column("solicitudes", sa.Column("tipo_cambio", sa.Numeric(10, 4), nullable=True))
    # Confirmadas en USD → consolidado MXN con el TC demo 18.50.
    op.execute(
        f"""
        UPDATE solicitudes SET
            tipo_cambio = {_TC_DEMO},
            monto_confirmado = round(monto_confirmado * {_TC_DEMO}, 2),
            moneda_confirmada = 'MXN'
        WHERE moneda_confirmada = 'USD'
        """
    )


def downgrade() -> None:
    # Best-effort (documentado): el TC demo se revierte; el consolidado de
    # otras confirmadas no es reversible sin el desglose original.
    op.execute(
        f"""
        UPDATE solicitudes SET
            monto_confirmado = round(monto_confirmado / {_TC_DEMO}, 2),
            moneda_confirmada = 'USD'
        WHERE tipo_cambio = {_TC_DEMO}
          AND monto_confirmado = round(round(monto_confirmado / {_TC_DEMO}, 2) * {_TC_DEMO}, 2)
        """
    )
    op.drop_column("solicitudes", "tipo_cambio")

    op.add_column("cotizacion_opciones", sa.Column("moneda", _moneda, nullable=True))
    op.add_column(
        "cotizacion_opciones",
        sa.Column("total", sa.Numeric(14, 2), server_default=sa.text("0"), nullable=False),
    )
    # La opción vieja tenía UNA moneda: se elige la dominante por subtotal.
    op.execute(
        """
        UPDATE cotizacion_opciones SET
            moneda = CASE
                WHEN total_usd > 0 AND total_mxn = 0 THEN 'USD'::moneda
                WHEN total_mxn > 0 OR total_usd = 0 THEN 'MXN'::moneda
            END,
            total = CASE
                WHEN total_usd > 0 AND total_mxn = 0 THEN total_usd
                ELSE total_mxn
            END
        """
    )
    op.execute(
        """
        UPDATE cotizacion_opciones co
        SET moneda = sub.m::moneda
        FROM (
            SELECT opcion_id, max(moneda::text) AS m FROM opcion_partidas
            WHERE moneda IS NOT NULL GROUP BY opcion_id
        ) sub
        WHERE co.id = sub.opcion_id AND co.moneda IS NULL
        """
    )
    op.drop_column("opcion_partidas", "moneda")
    op.drop_column("cotizacion_opciones", "total_usd")
    op.drop_column("cotizacion_opciones", "total_mxn")

    op.execute(
        "UPDATE usuarios SET rol = 'admin' WHERE rol IN ('gerente_compras', 'director_ventas')"
    )
    op.execute("ALTER TYPE rol RENAME VALUE 'gerente_sucursal' TO 'gerente'")
    op.execute("ALTER TYPE rol RENAME TO rol_viejo")
    op.execute("CREATE TYPE rol AS ENUM ('vendedor', 'comprador', 'admin', 'gerente')")
    op.execute("ALTER TABLE usuarios ALTER COLUMN rol TYPE rol USING rol::text::rol")
    op.execute("DROP TYPE rol_viejo")
