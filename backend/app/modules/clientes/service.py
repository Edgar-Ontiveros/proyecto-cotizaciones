from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.cliente import Cliente
from app.models.usuario import Usuario


def normalizar(nombre: str) -> str:
    """strip + colapsar espacios internos + upper (acentos intactos):
    '  aceros   lópez ' → 'ACEROS LÓPEZ'."""
    return " ".join(nombre.split()).upper()


def obtener_o_crear(db: Session, nombre: str, usuario: Usuario) -> Cliente:
    """Alta al vuelo contra el catálogo interno (sin SAP, §4.4)."""
    normalizado = normalizar(nombre)
    if not normalizado:
        raise AppError(422, "El nombre del cliente no puede estar vacío", "cliente_invalido")
    cliente = db.scalar(select(Cliente).where(Cliente.nombre_normalizado == normalizado))
    if cliente is None:
        cliente = Cliente(nombre_normalizado=normalizado, creado_por=usuario.id)
        db.add(cliente)
        db.flush()
    return cliente


def buscar(db: Session, texto: str | None) -> list[Cliente]:
    stmt = select(Cliente).order_by(Cliente.nombre_normalizado).limit(20)
    if texto:
        stmt = stmt.where(Cliente.nombre_normalizado.ilike(f"%{texto.strip()}%"))
    return list(db.scalars(stmt))
