"""Sucursales, territorios comprador↔sucursal y titularidad (F5, solo admin).

El cambio de titular afecta SOLO asignaciones futuras (las abiertas se mueven
con las reasignaciones). El contador de folios NUNCA retrocede: folios
duplicados prohibidos."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario
from app.modules.sucursales.schemas import (
    SucursalCreate,
    SucursalUpdate,
    TerritorioComprador,
    TerritorioSucursal,
)


def _validar_timezone(tz: str) -> None:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise AppError(422, f"Zona horaria IANA inválida: {tz}", "timezone_invalida") from None


def _get_sucursal(db: Session, sucursal_id: int) -> Sucursal:
    sucursal = db.get(Sucursal, sucursal_id)
    if sucursal is None:
        raise AppError(404, "Sucursal no encontrada", "sucursal_no_encontrada")
    return sucursal


def _check_unicos(
    db: Session, nombre: str | None, prefijo: str | None, excluir_id: int | None = None
) -> None:
    for campo, valor, code in (
        (Sucursal.nombre, nombre, "nombre_duplicado"),
        (Sucursal.prefijo_folio, prefijo, "prefijo_duplicado"),
    ):
        if valor is None:
            continue
        stmt = select(Sucursal.id).where(campo == valor)
        if excluir_id is not None:
            stmt = stmt.where(Sucursal.id != excluir_id)
        if db.scalar(stmt) is not None:
            raise AppError(409, f"Ya existe una sucursal con ese valor: {valor}", code)


def listar(db: Session) -> list[Sucursal]:
    return list(db.scalars(select(Sucursal).order_by(Sucursal.nombre)))


def crear(db: Session, data: SucursalCreate) -> Sucursal:
    _validar_timezone(data.timezone)
    _check_unicos(db, data.nombre, data.prefijo_folio)
    sucursal = Sucursal(
        nombre=data.nombre.strip(), prefijo_folio=data.prefijo_folio.strip(), timezone=data.timezone
    )
    db.add(sucursal)
    db.flush()
    db.add(FolioCounter(sucursal_id=sucursal.id, ultimo=data.contador_inicial))
    db.commit()
    return sucursal


def actualizar(db: Session, sucursal_id: int, data: SucursalUpdate) -> Sucursal:
    sucursal = _get_sucursal(db, sucursal_id)
    cambios = data.model_dump(exclude_unset=True)
    if "timezone" in cambios:
        _validar_timezone(cambios["timezone"])
    _check_unicos(db, cambios.get("nombre"), cambios.get("prefijo_folio"), excluir_id=sucursal.id)
    if cambios.get("activa") is False and sucursal.activa:
        _validar_desactivacion(db, sucursal)
    for campo, valor in cambios.items():
        setattr(sucursal, campo, valor)
    db.commit()
    return sucursal


def _validar_desactivacion(db: Session, sucursal: Sucursal) -> None:
    """Desactivar exige sucursal sin personal activo ni titularidad vigente."""
    usuarios = db.scalars(
        select(Usuario.nombre).where(
            Usuario.sucursal_id == sucursal.id,
            Usuario.activo,
            Usuario.rol.in_((Rol.VENDEDOR, Rol.GERENTE)),
        )
    ).all()
    titular = db.scalar(
        select(Usuario.nombre)
        .join(CompradorSucursal, CompradorSucursal.comprador_id == Usuario.id)
        .where(CompradorSucursal.sucursal_id == sucursal.id, CompradorSucursal.titular)
    )
    problemas = []
    if usuarios:
        problemas.append(f"{len(usuarios)} vendedor(es)/gerente(s) activos")
    if titular:
        problemas.append(f"titular vigente: {titular}")
    if problemas:
        raise AppError(
            409,
            f"No se puede desactivar la sucursal {sucursal.nombre}: " + "; ".join(problemas),
            "sucursal_en_uso",
        )


def actualizar_folio_counter(db: Session, sucursal_id: int, ultimo: int) -> FolioCounter:
    _get_sucursal(db, sucursal_id)
    counter = db.execute(
        select(FolioCounter)
        .where(FolioCounter.sucursal_id == sucursal_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if counter is None:
        counter = FolioCounter(sucursal_id=sucursal_id, ultimo=0)
        db.add(counter)
        db.flush()
    if ultimo < counter.ultimo:
        raise AppError(
            422,
            f"El contador no puede retroceder (actual: {counter.ultimo}); "
            "folios duplicados prohibidos",
            "contador_retrocede",
        )
    counter.ultimo = ultimo
    db.commit()
    return counter


def cambiar_titular(db: Session, sucursal_id: int, comprador_id: int) -> None:
    """Baja el flag del titular anterior y asigna el nuevo, en una transacción.
    Afecta solo asignaciones futuras."""
    _get_sucursal(db, sucursal_id)
    comprador = db.get(Usuario, comprador_id)
    if comprador is None or comprador.rol != Rol.COMPRADOR or not comprador.activo:
        raise AppError(422, "El titular debe ser un comprador activo", "comprador_invalido")
    # Primero se baja el flag anterior: el índice único parcial (un titular por
    # sucursal) se valida por sentencia.
    db.execute(
        update(CompradorSucursal)
        .where(CompradorSucursal.sucursal_id == sucursal_id, CompradorSucursal.titular)
        .values(titular=False)
    )
    fila = db.scalar(
        select(CompradorSucursal).where(
            CompradorSucursal.comprador_id == comprador_id,
            CompradorSucursal.sucursal_id == sucursal_id,
        )
    )
    if fila is None:
        db.add(CompradorSucursal(comprador_id=comprador_id, sucursal_id=sucursal_id, titular=True))
    else:
        fila.titular = True
    db.commit()


def transferir_titularidades(db: Session, de_id: int, a_id: int, commit: bool = True) -> list[str]:
    """Mueve TODAS las titularidades de un comprador a otro (baja segura).
    Devuelve los nombres de las sucursales transferidas."""
    destino = db.get(Usuario, a_id)
    if destino is None or destino.rol != Rol.COMPRADOR or not destino.activo:
        raise AppError(422, "El titular debe ser un comprador activo", "comprador_invalido")
    filas = db.execute(
        select(CompradorSucursal, Sucursal.nombre)
        .join(Sucursal, CompradorSucursal.sucursal_id == Sucursal.id)
        .where(CompradorSucursal.comprador_id == de_id, CompradorSucursal.titular)
        .order_by(Sucursal.nombre)
    ).all()
    nombres = []
    for fila, nombre in filas:
        fila.titular = False
        db.flush()  # baja el flag antes de subir el nuevo (índice parcial)
        existente = db.scalar(
            select(CompradorSucursal).where(
                CompradorSucursal.comprador_id == a_id,
                CompradorSucursal.sucursal_id == fila.sucursal_id,
            )
        )
        if existente is None:
            db.add(CompradorSucursal(comprador_id=a_id, sucursal_id=fila.sucursal_id, titular=True))
        else:
            existente.titular = True
        nombres.append(nombre)
    if commit:
        db.commit()
    return nombres


def titularidades_de(db: Session, comprador_id: int) -> list[str]:
    return list(
        db.scalars(
            select(Sucursal.nombre)
            .join(CompradorSucursal, CompradorSucursal.sucursal_id == Sucursal.id)
            .where(CompradorSucursal.comprador_id == comprador_id, CompradorSucursal.titular)
            .order_by(Sucursal.nombre)
        )
    )


def territorios(db: Session) -> list[TerritorioComprador]:
    """Mapa completo comprador↔sucursales con titularidad (§4.5)."""
    filas = db.execute(
        select(Usuario, Sucursal, CompradorSucursal.titular)
        .join(CompradorSucursal, CompradorSucursal.comprador_id == Usuario.id)
        .join(Sucursal, CompradorSucursal.sucursal_id == Sucursal.id)
        .order_by(Usuario.nombre, Sucursal.nombre)
    ).all()
    por_comprador: dict[int, TerritorioComprador] = {}
    for comprador, sucursal, titular in filas:
        item = por_comprador.setdefault(
            comprador.id,
            TerritorioComprador(
                comprador_id=comprador.id,
                comprador_nombre=comprador.nombre,
                comprador_activo=comprador.activo,
                sucursales=[],
            ),
        )
        item.sucursales.append(
            TerritorioSucursal(
                sucursal_id=sucursal.id, sucursal_nombre=sucursal.nombre, titular=titular
            )
        )
    return list(por_comprador.values())
