"""edicion completa de partidas en cambios

F13 (ADITIVA / no destructiva, §4.8b ampliado): la solicitud de cambio deja
de modelar solo cantidad/unidad de partidas existentes y pasa a soportar tres
tipos de renglón —MODIFICACION (ahora también descripcion), ALTA (partida
nueva sin partida_id, sin precio) y BAJA (partida existente marcada para
eliminar)—. El snapshot se vuelve AUTOSUFICIENTE a prueba de bajas físicas:
guarda num_partida y descripciones como texto, y la FK a solicitud_partidas
pasa a ON DELETE SET NULL para que al aprobar una BAJA la partida pueda morir
sin borrar el registro histórico del cambio.

Compatibilidad con filas existentes (cambios viejos):
- tipo_renglon nace con server_default 'MODIFICACION': toda fila previa queda
  clasificada como lo que era (una modificación de una partida existente).
- Las columnas cantidad/unidad anterior/nueva se AMPLÍAN a nullable (widening,
  no destructivo): las filas viejas conservan sus cuatro valores; solo ALTA
  (sin "anterior") y BAJA (sin "nueva") dejarán algunos en NULL.
- num_partida/descripcion_* nacen NULL en las filas viejas; el service cae al
  lookup vivo por partida_id para ellas (idéntico comportamiento a hoy).
- Ninguna fila viva se altera en su contenido: solo cambian tipos/constraints.

Revision ID: ce7770847875
Revises: 9d3a51c8e7f2
Create Date: 2026-08-18 16:55:20.705868

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ce7770847875"
down_revision: str | None = "9d3a51c8e7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

tipo_cambio_renglon = sa.Enum("ALTA", "BAJA", "MODIFICACION", name="tipo_cambio_renglon")

_FK_PARTIDA = "fk_cambio_partidas_partida_id_solicitud_partidas"


def upgrade() -> None:
    bind = op.get_bind()
    tipo_cambio_renglon.create(bind, checkfirst=True)
    # Tipo de renglón de cambio; las filas existentes = MODIFICACION.
    op.add_column(
        "cambio_partidas",
        sa.Column(
            "tipo_renglon",
            sa.Enum("ALTA", "BAJA", "MODIFICACION", name="tipo_cambio_renglon", create_type=False),
            server_default="MODIFICACION",
            nullable=False,
        ),
    )
    # Snapshot autosuficiente (sobrevive a la baja física de la partida).
    op.add_column("cambio_partidas", sa.Column("num_partida", sa.Integer(), nullable=True))
    op.add_column("cambio_partidas", sa.Column("descripcion_anterior", sa.Text(), nullable=True))
    op.add_column("cambio_partidas", sa.Column("descripcion_nueva", sa.Text(), nullable=True))
    # Widening a nullable (ALTA no tiene "anterior"; BAJA no tiene "nueva").
    op.alter_column("cambio_partidas", "partida_id", existing_type=sa.Integer(), nullable=True)
    op.alter_column(
        "cambio_partidas", "cantidad_anterior", existing_type=sa.Numeric(14, 3), nullable=True
    )
    op.alter_column(
        "cambio_partidas", "cantidad_nueva", existing_type=sa.Numeric(14, 3), nullable=True
    )
    op.alter_column("cambio_partidas", "unidad_anterior", existing_type=sa.String(), nullable=True)
    op.alter_column("cambio_partidas", "unidad_nueva", existing_type=sa.String(), nullable=True)
    # La FK a la partida pasa a ON DELETE SET NULL: aprobar una BAJA borra la
    # partida y deja partida_id en NULL sin tocar el snapshot de texto.
    op.drop_constraint(op.f(_FK_PARTIDA), "cambio_partidas", type_="foreignkey")
    op.create_foreign_key(
        op.f(_FK_PARTIDA),
        "cambio_partidas",
        "solicitud_partidas",
        ["partida_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Reversa a scratch (destructiva si existieran filas ALTA/BAJA con NULLs):
    # restaura la FK sin ON DELETE, re-exige NOT NULL en las cuatro columnas
    # ampliadas y elimina las columnas/tipo nuevos.
    op.drop_constraint(op.f(_FK_PARTIDA), "cambio_partidas", type_="foreignkey")
    op.create_foreign_key(
        op.f(_FK_PARTIDA),
        "cambio_partidas",
        "solicitud_partidas",
        ["partida_id"],
        ["id"],
    )
    op.alter_column("cambio_partidas", "unidad_nueva", existing_type=sa.String(), nullable=False)
    op.alter_column("cambio_partidas", "unidad_anterior", existing_type=sa.String(), nullable=False)
    op.alter_column(
        "cambio_partidas", "cantidad_nueva", existing_type=sa.Numeric(14, 3), nullable=False
    )
    op.alter_column(
        "cambio_partidas", "cantidad_anterior", existing_type=sa.Numeric(14, 3), nullable=False
    )
    op.alter_column("cambio_partidas", "partida_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("cambio_partidas", "descripcion_nueva")
    op.drop_column("cambio_partidas", "descripcion_anterior")
    op.drop_column("cambio_partidas", "num_partida")
    op.drop_column("cambio_partidas", "tipo_renglon")
    tipo_cambio_renglon.drop(op.get_bind(), checkfirst=True)
