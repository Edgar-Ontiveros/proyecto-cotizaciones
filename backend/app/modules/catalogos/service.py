"""Catálogos administrables (F5): motivos de rechazo y días festivos.

Motivos: NUNCA se borran — el historial los referencia; solo se desactivan.
Festivos: alterar fechas pasadas altera las métricas históricas de horas
hábiles (F6) — responsabilidad del admin."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.catalogos import DiaFestivo, FamiliaMotivo, MotivoRechazo
from app.modules.catalogos.schemas import FestivoCreate, MotivoCreate, MotivoUpdate


def listar_motivos(
    db: Session, familia: FamiliaMotivo | None, solo_activos: bool
) -> list[MotivoRechazo]:
    stmt = select(MotivoRechazo).order_by(MotivoRechazo.familia, MotivoRechazo.texto)
    if familia is not None:
        stmt = stmt.where(MotivoRechazo.familia == familia)
    if solo_activos:
        stmt = stmt.where(MotivoRechazo.activo)
    return list(db.scalars(stmt))


def _check_motivo_unico(
    db: Session, familia: FamiliaMotivo, texto: str, excluir_id: int | None = None
) -> None:
    stmt = select(MotivoRechazo.id).where(
        MotivoRechazo.familia == familia, MotivoRechazo.texto == texto
    )
    if excluir_id is not None:
        stmt = stmt.where(MotivoRechazo.id != excluir_id)
    if db.scalar(stmt) is not None:
        raise AppError(409, "Ya existe ese motivo en la misma familia", "motivo_duplicado")


def crear_motivo(db: Session, data: MotivoCreate) -> MotivoRechazo:
    texto = data.texto.strip()
    _check_motivo_unico(db, data.familia, texto)
    motivo = MotivoRechazo(familia=data.familia, texto=texto)
    db.add(motivo)
    db.commit()
    return motivo


def actualizar_motivo(db: Session, motivo_id: int, data: MotivoUpdate) -> MotivoRechazo:
    motivo = db.get(MotivoRechazo, motivo_id)
    if motivo is None:
        raise AppError(404, "Motivo no encontrado", "motivo_no_encontrado")
    cambios = data.model_dump(exclude_unset=True)
    if "texto" in cambios:
        cambios["texto"] = cambios["texto"].strip()
        _check_motivo_unico(db, motivo.familia, cambios["texto"], excluir_id=motivo.id)
    for campo, valor in cambios.items():
        setattr(motivo, campo, valor)
    db.commit()
    return motivo


def listar_festivos(db: Session) -> list[DiaFestivo]:
    return list(db.scalars(select(DiaFestivo).order_by(DiaFestivo.fecha)))


def crear_festivo(db: Session, data: FestivoCreate) -> DiaFestivo:
    if db.scalar(select(DiaFestivo.id).where(DiaFestivo.fecha == data.fecha)) is not None:
        raise AppError(409, f"Ya existe un festivo el {data.fecha}", "festivo_duplicado")
    festivo = DiaFestivo(fecha=data.fecha, descripcion=data.descripcion)
    db.add(festivo)
    db.commit()
    return festivo


def eliminar_festivo(db: Session, festivo_id: int) -> None:
    """Borrado físico. OJO: quitar (o haber agregado) un festivo en fechas ya
    transcurridas altera las métricas históricas de horas hábiles —
    responsabilidad del admin (F5 §5)."""
    festivo = db.get(DiaFestivo, festivo_id)
    if festivo is None:
        raise AppError(404, "Festivo no encontrado", "festivo_no_encontrado")
    db.delete(festivo)
    db.commit()
