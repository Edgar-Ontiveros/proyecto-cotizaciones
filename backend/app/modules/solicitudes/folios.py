"""Generación race-safe de folios: {PREFIJO_SUCURSAL}-{CONSECUTIVO}, sin año
ni padding (CCN-3036 → CCN-3037). Consecutivo corrido por sucursal vía
folio_counters con FOR UPDATE, SIEMPRE dentro de la transacción del envío."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.sucursal import FolioCounter, Sucursal


def siguiente_folio(db: Session, sucursal: Sucursal) -> str:
    stmt = select(FolioCounter).where(FolioCounter.sucursal_id == sucursal.id).with_for_update()
    counter = db.execute(stmt).scalar_one_or_none()
    if counter is None:
        # get-or-create race-safe: si otro proceso lo insertó primero, el
        # ON CONFLICT no hace nada y el re-SELECT FOR UPDATE lo toma bloqueado.
        db.execute(
            pg_insert(FolioCounter)
            .values(sucursal_id=sucursal.id, ultimo=0)
            .on_conflict_do_nothing()
        )
        counter = db.execute(stmt).scalar_one()
    counter.ultimo += 1
    db.flush()
    return f"{sucursal.prefijo_folio}-{counter.ultimo}"
