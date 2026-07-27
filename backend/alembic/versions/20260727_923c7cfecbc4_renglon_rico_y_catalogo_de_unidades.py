"""renglon rico y catalogo de unidades

Revision ID: 923c7cfecbc4
Revises: b68dfde07905
Create Date: 2026-07-27 16:04:08.139465

F8b: (1) catálogo cerrado de unidades PZ/KG/TON/MTS/M2 con CHECK en
solicitud_partidas y opcion_partidas, normalizando primero los datos
existentes; (2) renglón rico en opcion_partidas: cantidad/unidad cotizadas
(backfill desde la partida), proveedor POR RENGLÓN (migrado desde la opción,
que pierde la columna), no_encontrada y es_alternativa+descripción.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "923c7cfecbc4"
down_revision: str | None = "b68dfde07905"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIDADES = "('PZ', 'KG', 'TON', 'MTS', 'M2')"

# Sinónimos reales → catálogo; lo irreconocible cae a PZ (solo hay datos demo:
# no existe producción todavía).
_NORMALIZACION = f"""
UPDATE {{tabla}} SET unidad = CASE
    WHEN upper(trim(unidad)) IN ('PZ', 'PZA', 'PZAS', 'PIEZA', 'PIEZAS') THEN 'PZ'
    WHEN upper(trim(unidad)) IN ('KG', 'KGS', 'KILO', 'KILOS', 'KILOGRAMO', 'KILOGRAMOS') THEN 'KG'
    WHEN upper(trim(unidad)) IN ('TON', 'TONS', 'TONELADA', 'TONELADAS') THEN 'TON'
    WHEN upper(trim(unidad)) IN ('MTS', 'MT', 'M', 'METRO', 'METROS', 'ML') THEN 'MTS'
    WHEN upper(trim(unidad)) IN ('M2', 'MT2', 'M²', 'METROS CUADRADOS') THEN 'M2'
    ELSE 'PZ'
END
WHERE upper(trim(unidad)) NOT IN {_UNIDADES}
"""


def upgrade() -> None:
    # 1) Normalizar unidades existentes y fijar el catálogo en las partidas.
    op.execute(_NORMALIZACION.format(tabla="solicitud_partidas"))
    op.execute("UPDATE solicitud_partidas SET unidad = upper(trim(unidad))")
    op.create_check_constraint("unidad_catalogo", "solicitud_partidas", f"unidad IN {_UNIDADES}")

    # 2) Renglón rico.
    op.add_column("opcion_partidas", sa.Column("cantidad", sa.Numeric(14, 3), nullable=True))
    op.add_column("opcion_partidas", sa.Column("unidad", sa.String(), nullable=True))
    op.add_column("opcion_partidas", sa.Column("proveedor", sa.String(), nullable=True))
    op.add_column(
        "opcion_partidas",
        sa.Column("no_encontrada", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "opcion_partidas",
        sa.Column("es_alternativa", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("opcion_partidas", sa.Column("alternativa_descripcion", sa.Text(), nullable=True))

    # Backfill: cantidad/unidad cotizadas parten de lo pedido (ya normalizado);
    # el proveedor baja de la opción a sus renglones.
    op.execute(
        """
        UPDATE opcion_partidas op
        SET cantidad = sp.cantidad, unidad = sp.unidad
        FROM solicitud_partidas sp
        WHERE op.partida_id = sp.id
        """
    )
    op.execute(
        """
        UPDATE opcion_partidas op
        SET proveedor = co.proveedor
        FROM cotizacion_opciones co
        WHERE op.opcion_id = co.id AND co.proveedor IS NOT NULL
        """
    )
    op.alter_column("opcion_partidas", "cantidad", nullable=False)
    op.alter_column("opcion_partidas", "unidad", nullable=False)
    op.create_check_constraint("unidad_catalogo", "opcion_partidas", f"unidad IN {_UNIDADES}")

    # 3) La opción pierde su proveedor (ahora vive en el renglón).
    op.drop_column("cotizacion_opciones", "proveedor")


def downgrade() -> None:
    op.add_column("cotizacion_opciones", sa.Column("proveedor", sa.String(), nullable=True))
    # Mejor esfuerzo: un proveedor cualquiera de los renglones vuelve a la
    # opción (el modelo viejo solo tenía uno).
    op.execute(
        """
        UPDATE cotizacion_opciones co
        SET proveedor = (
            SELECT max(op.proveedor) FROM opcion_partidas op
            WHERE op.opcion_id = co.id AND op.proveedor IS NOT NULL
        )
        """
    )
    # El nombre corto: la naming_convention del MetaData antepone ck_<tabla>_.
    op.drop_constraint("unidad_catalogo", "opcion_partidas", type_="check")
    op.drop_column("opcion_partidas", "alternativa_descripcion")
    op.drop_column("opcion_partidas", "es_alternativa")
    op.drop_column("opcion_partidas", "no_encontrada")
    op.drop_column("opcion_partidas", "proveedor")
    op.drop_column("opcion_partidas", "unidad")
    op.drop_column("opcion_partidas", "cantidad")
    op.drop_constraint("unidad_catalogo", "solicitud_partidas", type_="check")
