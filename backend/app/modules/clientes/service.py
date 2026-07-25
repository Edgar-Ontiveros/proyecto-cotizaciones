from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.cliente import Cliente
from app.models.usuario import Usuario


def normalizar(nombre: str) -> str:
    """strip + colapsar espacios internos + upper (acentos intactos):
    '  aceros   lópez ' → 'ACEROS LÓPEZ'."""
    return " ".join(nombre.split()).upper()


def obtener_o_crear(db: Session, nombre: str, usuario: Usuario) -> Cliente:
    """Alta al vuelo contra el catálogo interno (sin SAP, §4.4).

    Race-safe: dos vendedores creando el mismo cliente a la vez no producen
    IntegrityError — INSERT ... ON CONFLICT DO NOTHING + re-select (mismo
    patrón que folios)."""
    normalizado = normalizar(nombre)
    if not normalizado:
        raise AppError(422, "El nombre del cliente no puede estar vacío", "cliente_invalido")
    stmt = select(Cliente).where(Cliente.nombre_normalizado == normalizado)
    cliente = db.scalar(stmt)
    if cliente is None:
        db.execute(
            pg_insert(Cliente)
            .values(nombre_normalizado=normalizado, creado_por=usuario.id)
            .on_conflict_do_nothing()
        )
        cliente = db.execute(stmt).scalar_one()
    return cliente


def buscar(db: Session, texto: str | None) -> list[Cliente]:
    stmt = select(Cliente).order_by(Cliente.nombre_normalizado).limit(20)
    if texto:
        stmt = stmt.where(Cliente.nombre_normalizado.ilike(f"%{texto.strip()}%"))
    return list(db.scalars(stmt))
