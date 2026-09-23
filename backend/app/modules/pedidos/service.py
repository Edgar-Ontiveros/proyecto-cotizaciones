"""Pedidos en SAP (F16a §3–§5): vínculo de OC al fincar, sincronización y
listado. SAP es SOLO lectura; aquí nunca se escribe hacia HANA.

- `buscar`: consulta HANA, valida la sucursal SAP pedida, deriva estatus y
  arma la tarjeta. 422 `oc_no_encontrada` (dice qué sucursal buscó y, si la OC
  existe en otra serie, cuál), 409 `oc_ya_vinculada` a OTRA solicitud (con su
  folio), 503 `sap_no_disponible` si HANA no responde.
- F16a.1: si OPOR no tiene la OC se consulta su BORRADOR (ODRF + OWDD) para
  responder un 422 ACCIONABLE: `oc_aprobada_sin_anadir`,
  `oc_pendiente_autorizacion`, `oc_rechazada`, `oc_borrador_convertido`; sin
  borrador, el `oc_no_encontrada` de siempre. NINGUNO crea vínculo: PROHIBIDO
  vincular contra borradores (su DocNum no está garantizado hasta el Añadir).
- `vincular`: mismo camino + guarda snapshot + evento `oc_vinculada`. Solo
  lado compras (comprador asignado, gerente_compras, admin) y solo CONFIRMADA.
- `desvincular`: apaga `activa` + evento `oc_desvinculada`. No borra.
- `sincronizar_oc`: re-consulta, recalcula estatus/vencida y guarda el
  snapshot. Función de dominio SIN acoplarse a HTTP: la reutiliza el sondeo
  de F16b. Si HANA falla, conserva el snapshot anterior y anota
  `ultimo_error` (no revienta al caller salvo que se le pida).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.permissions import scope_solicitudes_query, ve_fincada
from app.integrations.sap.base import (
    BorradorOC,
    CadenaOC,
    EncabezadoOC,
    FuenteOC,
    LineaOC,
    SapNoDisponible,
    normalizar_sucursal_sap,
)
from app.integrations.sap.estatus import EstatusOC, derivar_estatus, es_vencida
from app.models.cliente import Cliente
from app.models.pedido import SolicitudOC
from app.models.solicitud import Estado, Solicitud
from app.models.sucursal import Sucursal
from app.models.usuario import Rol, Usuario
from app.modules.pedidos.schemas import (
    EntradaOut,
    FacturaComprasOut,
    FacturaVentasOut,
    LineaOCComprasOut,
    LineaOCVentasOut,
    OCBusquedaOut,
    OCComprasOut,
    OCVentasOut,
    PedidoItemComprasOut,
    PedidoItemVentasOut,
)
from app.modules.solicitudes.service import obtener_scoped
from app.modules.solicitudes.state_machine import autoriza_compras, registrar_evento

MENSAJE_SAP_CAIDO = "SAP no responde, intenta en unos minutos"


def sap_no_disponible(exc: Exception | None = None) -> AppError:
    return AppError(503, MENSAJE_SAP_CAIDO, "sap_no_disponible")


# ------------------------------------------------------------ snapshot


def _json(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, date | datetime):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [_json(v) for v in valor]
    return valor


def _snapshot(encabezado: EncabezadoOC, lineas: list[LineaOC], cadena: CadenaOC) -> dict[str, Any]:
    return {
        "encabezado": _json(asdict(encabezado)),
        "lineas": [_json(asdict(linea)) for linea in lineas],
        "cadena": {
            "entradas": [
                {
                    **_json(asdict(entrada)),
                    "almacenes": entrada.almacenes,
                    "cantidad_total": str(entrada.cantidad_total),
                }
                for entrada in cadena.entradas
            ],
            "facturas": [_json(asdict(factura)) for factura in cadena.facturas],
        },
    }


def _donde_oc(lineas: list[LineaOC]) -> str | None:
    vistos: list[str] = []
    for linea in lineas:
        nombre = linea.almacen_nombre or linea.almacen_codigo
        if nombre and nombre not in vistos:
            vistos.append(nombre)
    return " · ".join(vistos) or None


def _donde_entrada(cadena: CadenaOC) -> str | None:
    vistos: list[str] = []
    for entrada in cadena.entradas:
        if entrada.cancelada:
            continue
        for nombre in entrada.almacenes:
            if nombre not in vistos:
                vistos.append(nombre)
    return " · ".join(vistos) or None


def _leer_completa(
    fuente: FuenteOC, doc_num: int
) -> tuple[EncabezadoOC, list[LineaOC], CadenaOC] | None:
    """Encabezado + líneas + cadena en tres SELECT; None si la OC no existe."""
    try:
        encabezado = fuente.buscar_oc(doc_num)
        if encabezado is None:
            return None
        lineas = fuente.lineas_oc(encabezado.doc_entry)
        cadena = fuente.cadena_oc(encabezado.doc_entry)
    except SapNoDisponible as exc:
        raise sap_no_disponible(exc) from exc
    return encabezado, lineas, cadena


def _timezone_de(db: Session, solicitud: Solicitud) -> str:
    return db.scalar(select(Sucursal.timezone).where(Sucursal.id == solicitud.sucursal_id)) or "UTC"


def _aplicar_lectura(
    oc: SolicitudOC,
    encabezado: EncabezadoOC,
    lineas: list[LineaOC],
    cadena: CadenaOC,
    timezone: str,
    ahora: datetime,
) -> None:
    estatus = derivar_estatus(encabezado, lineas, cadena)
    oc.doc_entry = encabezado.doc_entry
    oc.doc_num = encabezado.doc_num
    oc.serie = encabezado.serie
    oc.sucursal_sap = encabezado.sucursal_sap
    oc.proveedor_codigo = encabezado.proveedor_codigo
    oc.proveedor = encabezado.proveedor_nombre
    oc.moneda = encabezado.moneda
    oc.total = encabezado.total
    oc.tipo_cambio = encabezado.tipo_cambio
    oc.fecha_creacion = encabezado.fecha_creacion
    oc.fecha_contabilizacion = encabezado.fecha_contabilizacion
    oc.fecha_entrega = encabezado.fecha_entrega
    oc.encargado_compras = encabezado.encargado_compras
    oc.estatus_derivado = estatus.value
    oc.vencida = es_vencida(estatus, encabezado.fecha_entrega, timezone, ahora)
    oc.donde_oc = _donde_oc(lineas)
    oc.donde_entrada = _donde_entrada(cadena)
    oc.snapshot = _snapshot(encabezado, lineas, cadena)
    oc.ultimo_sync_en = ahora
    oc.ultimo_error = None


# ------------------------------------------------------------ búsqueda


def _error_borrador(borrador: BorradorOC, doc_num: int) -> AppError:
    """422 accionable según la situación del borrador en SAP (F16a.1)."""
    if borrador.autorizacion == "N":
        return AppError(
            422,
            f"La OC {doc_num} fue rechazada en la autorización de SAP; no se puede vincular.",
            "oc_rechazada",
        )
    if not borrador.abierto:
        return AppError(
            422,
            f"El borrador {doc_num} ya se añadió en SAP con OTRO número; "
            "verifica el número final de la OC en SAP y vuelve a buscarla aquí.",
            "oc_borrador_convertido",
        )
    if borrador.autorizacion == "Y":
        return AppError(
            422,
            f"La OC {doc_num} ya está autorizada en SAP pero aún no se ha añadido: "
            "ábrela desde el borrador aprobado, dale 'Añadir' y vuelve a buscarla aquí.",
            "oc_aprobada_sin_anadir",
        )
    return AppError(
        422,
        f"La OC {doc_num} sigue pendiente de autorización en SAP; "
        "cuando la autoricen y la añadan, vuelve a buscarla aquí.",
        "oc_pendiente_autorizacion",
    )


def _error_oc_ausente(fuente: FuenteOC, doc_num: int, sucursal_sap: str) -> AppError:
    """OPOR no tiene la OC: explica por qué (borrador) o `oc_no_encontrada`."""
    try:
        borrador = fuente.buscar_borrador(doc_num)
    except SapNoDisponible as exc:
        raise sap_no_disponible(exc) from exc
    if borrador is not None:
        return _error_borrador(borrador, doc_num)
    return AppError(
        422,
        f"No se encontró la OC {doc_num} en la sucursal SAP "
        f"{normalizar_sucursal_sap(sucursal_sap)}",
        "oc_no_encontrada",
    )


def _validar_sucursal(encabezado: EncabezadoOC, sucursal_sap: str, doc_num: int) -> None:
    pedida = normalizar_sucursal_sap(sucursal_sap)
    if encabezado.sucursal_sap != pedida:
        donde = f" (la OC existe en la sucursal SAP {encabezado.sucursal_sap})"
        raise AppError(
            422,
            f"No se encontró la OC {doc_num} en la sucursal SAP {pedida}{donde}",
            "oc_no_encontrada",
        )


def _vinculo_activo_ajeno(db: Session, doc_entry: int, solicitud_id: int) -> str | None:
    """Folio (o #id) de OTRA solicitud que ya tiene esta OC activa."""
    fila = db.execute(
        select(Solicitud.folio, Solicitud.id)
        .join(SolicitudOC, SolicitudOC.solicitud_id == Solicitud.id)
        .where(
            SolicitudOC.doc_entry == doc_entry,
            SolicitudOC.activa.is_(True),
            SolicitudOC.solicitud_id != solicitud_id,
        )
    ).first()
    if fila is None:
        return None
    folio, sid = fila
    return folio or f"#{sid}"


def _advertencia_encargado(db: Session, solicitud: Solicitud, encargado: str | None) -> str | None:
    """Advertencia SUAVE: el encargado de compras de la OC (OSLP.SlpName) no
    parece ser el comprador asignado. Comparación laxa por apellidos/nombres
    (SAP escribe 'JAHNA MICHELLE MONARREZ RASCON'; aquí 'Michelle Monarrez')."""
    if solicitud.comprador_id is None or not encargado:
        return None
    nombre = db.scalar(select(Usuario.nombre).where(Usuario.id == solicitud.comprador_id)) or ""
    palabras = [p for p in nombre.upper().split() if len(p) > 2]
    if palabras and all(p in encargado.upper() for p in palabras):
        return None
    return f"El encargado de compras de la OC es {encargado}, no el comprador asignado ({nombre})"


def _autorizar_compras(db: Session, solicitud_id: int, user: Usuario) -> Solicitud:
    if not ve_fincada(user.rol):
        raise AppError(403, "Las OC de SAP las administra el área compras", "forbidden")
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_compras(user, solicitud):
        raise AppError(403, "Las OC de SAP las administra el área compras", "forbidden")
    if solicitud.estado != Estado.CONFIRMADA:
        raise AppError(
            409,
            f"Solo un pedido CONFIRMADO lleva OC de SAP: está en {solicitud.estado.value}",
            "estado_conflicto",
        )
    return solicitud


def buscar(
    db: Session,
    fuente: FuenteOC,
    solicitud_id: int,
    doc_num: int,
    sucursal_sap: str,
    user: Usuario,
    ahora: datetime | None = None,
) -> OCBusquedaOut:
    ahora = ahora or datetime.now(UTC)
    solicitud = _autorizar_compras(db, solicitud_id, user)
    lectura = _leer_completa(fuente, doc_num)
    if lectura is None:
        raise _error_oc_ausente(fuente, doc_num, sucursal_sap)
    encabezado, lineas, cadena = lectura
    _validar_sucursal(encabezado, sucursal_sap, doc_num)
    ajena = _vinculo_activo_ajeno(db, encabezado.doc_entry, solicitud.id)
    if ajena is not None:
        raise AppError(
            409, f"La OC {doc_num} ya está vinculada a la solicitud {ajena}", "oc_ya_vinculada"
        )
    estatus = derivar_estatus(encabezado, lineas, cadena)
    ya_aqui = db.scalar(
        select(SolicitudOC.id).where(
            SolicitudOC.solicitud_id == solicitud.id,
            SolicitudOC.doc_entry == encabezado.doc_entry,
            SolicitudOC.activa.is_(True),
        )
    )
    return OCBusquedaOut(
        doc_entry=encabezado.doc_entry,
        doc_num=encabezado.doc_num,
        serie=encabezado.serie,
        sucursal_sap=encabezado.sucursal_sap,
        proveedor=encabezado.proveedor_nombre,
        encargado_compras=encabezado.encargado_compras,
        fecha_contabilizacion=encabezado.fecha_contabilizacion,
        fecha_entrega=encabezado.fecha_entrega,
        moneda=encabezado.moneda,
        total=encabezado.total,
        estatus_derivado=estatus,
        vencida=es_vencida(estatus, encabezado.fecha_entrega, _timezone_de(db, solicitud), ahora),
        donde_oc=_donde_oc(lineas),
        advertencia_encargado=_advertencia_encargado(db, solicitud, encabezado.encargado_compras),
        ya_vinculada_aqui=ya_aqui is not None,
    )


# ------------------------------------------------------------ vínculo


def vincular(
    db: Session,
    fuente: FuenteOC,
    solicitud_id: int,
    doc_num: int,
    sucursal_sap: str,
    user: Usuario,
    ahora: datetime | None = None,
) -> SolicitudOC:
    ahora = ahora or datetime.now(UTC)
    solicitud = _autorizar_compras(db, solicitud_id, user)
    lectura = _leer_completa(fuente, doc_num)
    if lectura is None:
        raise _error_oc_ausente(fuente, doc_num, sucursal_sap)
    encabezado, lineas, cadena = lectura
    _validar_sucursal(encabezado, sucursal_sap, doc_num)
    ajena = _vinculo_activo_ajeno(db, encabezado.doc_entry, solicitud.id)
    if ajena is not None:
        raise AppError(
            409, f"La OC {doc_num} ya está vinculada a la solicitud {ajena}", "oc_ya_vinculada"
        )
    oc = db.scalar(
        select(SolicitudOC).where(
            SolicitudOC.solicitud_id == solicitud.id, SolicitudOC.doc_entry == encabezado.doc_entry
        )
    )
    if oc is not None and oc.activa:
        raise AppError(
            409, f"La OC {doc_num} ya está vinculada a esta solicitud", "oc_ya_vinculada"
        )
    if oc is None:
        oc = SolicitudOC(
            solicitud_id=solicitud.id,
            doc_entry=encabezado.doc_entry,
            doc_num=encabezado.doc_num,
            estatus_derivado=EstatusOC.ABIERTA.value,
            vencida=False,
            snapshot={},
            ultimo_sync_en=ahora,
        )
        db.add(oc)
    # Re-vincular una OC desvinculada antes REACTIVA la misma fila.
    oc.activa = True
    oc.vinculada_por = user.id
    oc.vinculada_en = ahora
    _aplicar_lectura(oc, encabezado, lineas, cadena, _timezone_de(db, solicitud), ahora)
    registrar_evento(
        db,
        solicitud,
        user,
        f"oc_vinculada: OC {encabezado.doc_num} (sucursal SAP {encabezado.sucursal_sap})",
    )
    db.commit()
    db.refresh(oc)
    return oc


def desvincular(db: Session, solicitud_id: int, oc_id: int, user: Usuario) -> SolicitudOC:
    if not ve_fincada(user.rol):
        raise AppError(403, "Las OC de SAP las administra el área compras", "forbidden")
    solicitud = obtener_scoped(db, solicitud_id, user, for_update=True)
    if not autoriza_compras(user, solicitud):
        raise AppError(403, "Las OC de SAP las administra el área compras", "forbidden")
    oc = db.scalar(
        select(SolicitudOC).where(
            SolicitudOC.id == oc_id,
            SolicitudOC.solicitud_id == solicitud.id,
            SolicitudOC.activa.is_(True),
        )
    )
    if oc is None:
        raise AppError(404, "OC no vinculada a esta solicitud", "oc_no_encontrada")
    oc.activa = False
    registrar_evento(
        db, solicitud, user, f"oc_desvinculada: OC {oc.doc_num} (sucursal SAP {oc.sucursal_sap})"
    )
    db.commit()
    return oc


def ocs_activas(db: Session, solicitud_id: int) -> list[SolicitudOC]:
    return list(
        db.scalars(
            select(SolicitudOC)
            .where(SolicitudOC.solicitud_id == solicitud_id, SolicitudOC.activa.is_(True))
            .order_by(SolicitudOC.vinculada_en, SolicitudOC.id)
        )
    )


def tiene_oc_activa(db: Session, solicitud_id: int) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(SolicitudOC)
            .where(SolicitudOC.solicitud_id == solicitud_id, SolicitudOC.activa.is_(True))
        )
        or 0
    ) > 0


# --------------------------------------------------------- sincronización


def sincronizar_oc(
    db: Session,
    fuente: FuenteOC,
    oc: SolicitudOC,
    timezone: str,
    ahora: datetime | None = None,
    *,
    propagar: bool = False,
) -> bool:
    """Re-consulta la OC en SAP y actualiza el snapshot/derivados. SIN commit
    (lo da el caller: petición HTTP o job de F16b). Regresa True si sincronizó;
    si HANA falla, conserva el snapshot anterior, anota `ultimo_error` y
    regresa False — o levanta 503 si `propagar=True`."""
    ahora = ahora or datetime.now(UTC)
    try:
        encabezado = fuente.buscar_oc(oc.doc_num)
        if encabezado is None or encabezado.doc_entry != oc.doc_entry:
            oc.ultimo_error = f"La OC {oc.doc_num} ya no existe en SAP"
            return False
        lineas = fuente.lineas_oc(oc.doc_entry)
        cadena = fuente.cadena_oc(oc.doc_entry)
    except SapNoDisponible as exc:
        oc.ultimo_error = MENSAJE_SAP_CAIDO
        if propagar:
            raise sap_no_disponible(exc) from exc
        return False
    _aplicar_lectura(oc, encabezado, lineas, cadena, timezone, ahora)
    return True


def sincronizar_solicitud(
    db: Session, fuente: FuenteOC, solicitud_id: int, user: Usuario
) -> list[SolicitudOC]:
    """Botón "Actualizar desde SAP" (compras/admin): sincroniza TODAS las OC
    activas de la solicitud; si HANA no responde → 503 y nada cambia."""
    if not ve_fincada(user.rol):
        raise AppError(403, "Las OC de SAP las administra el área compras", "forbidden")
    solicitud = obtener_scoped(db, solicitud_id, user)
    ocs = ocs_activas(db, solicitud.id)
    timezone = _timezone_de(db, solicitud)
    ahora = datetime.now(UTC)
    try:
        for oc in ocs:
            sincronizar_oc(db, fuente, oc, timezone, ahora, propagar=True)
    except AppError:
        db.rollback()
        raise
    db.commit()
    return ocs_activas(db, solicitud.id)


# ----------------------------------------------------------- serialización


def _lineas_out(snapshot: dict[str, Any], compras: bool) -> list[Any]:
    filas: list[Any] = []
    for linea in snapshot.get("lineas", []):
        base = {
            "num_linea": linea["num_linea"],
            "articulo": linea.get("articulo"),
            "descripcion": linea.get("descripcion"),
            "cantidad": linea["cantidad"],
            "cantidad_abierta": linea["cantidad_abierta"],
            "almacen": linea.get("almacen_nombre") or linea.get("almacen_codigo"),
            "estatus_linea": linea.get("estatus_linea"),
            "fecha_entrega": linea.get("fecha_entrega"),
        }
        if compras:
            filas.append(
                LineaOCComprasOut(
                    **base,
                    precio=linea.get("precio"),
                    importe=linea.get("importe"),
                    moneda=linea.get("moneda"),
                )
            )
        else:
            filas.append(LineaOCVentasOut(**base))
    return filas


def _cadena_out(snapshot: dict[str, Any], compras: bool) -> tuple[list[EntradaOut], list[Any]]:
    cadena = snapshot.get("cadena", {})
    entradas = [
        EntradaOut(
            doc_num=e["doc_num"],
            fecha=e.get("fecha"),
            cancelada=e.get("cancelada", False),
            donde=e.get("almacenes", []),
            cantidad_total=e.get("cantidad_total", "0"),
        )
        for e in cadena.get("entradas", [])
    ]
    facturas: list[Any] = []
    for f in cadena.get("facturas", []):
        base = {
            "doc_num": f["doc_num"],
            "fecha": f.get("fecha"),
            "cancelada": f.get("cancelada", False),
            "ligada_a": f.get("ligada_a", "oc"),
        }
        facturas.append(
            FacturaComprasOut(**base, total=f.get("total"), moneda=f.get("moneda"))
            if compras
            else FacturaVentasOut(**base)
        )
    return entradas, facturas


def oc_out(oc: SolicitudOC, rol: Rol, vinculada_por_nombre: str | None) -> OCVentasOut:
    compras = ve_fincada(rol)
    entradas, facturas = _cadena_out(oc.snapshot, compras)
    base: dict[str, Any] = {
        "id": oc.id,
        "doc_num": oc.doc_num,
        "serie": oc.serie,
        "sucursal_sap": oc.sucursal_sap,
        "estatus_derivado": EstatusOC(oc.estatus_derivado),
        "vencida": oc.vencida,
        "fecha_creacion": oc.fecha_creacion,
        "fecha_contabilizacion": oc.fecha_contabilizacion,
        "fecha_entrega": oc.fecha_entrega,
        "donde_oc": oc.donde_oc,
        "donde_entrada": oc.donde_entrada,
        "ultimo_sync_en": oc.ultimo_sync_en,
        "ultimo_error": oc.ultimo_error,
        "vinculada_por_nombre": vinculada_por_nombre,
        "vinculada_en": oc.vinculada_en,
        "lineas": _lineas_out(oc.snapshot, compras),
        "entradas": entradas,
        "facturas": facturas,
    }
    if not compras:
        return OCVentasOut(**base)
    encabezado = oc.snapshot.get("encabezado", {})
    return OCComprasOut(
        **base,
        proveedor_codigo=oc.proveedor_codigo,
        proveedor=oc.proveedor,
        moneda=oc.moneda,
        total=oc.total,
        tipo_cambio=oc.tipo_cambio,
        comentarios=encabezado.get("comentarios"),
        encargado_compras=oc.encargado_compras,
    )


def _nombres_usuarios(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    filas = db.execute(select(Usuario.id, Usuario.nombre).where(Usuario.id.in_(ids))).all()
    return {int(uid): str(nombre) for uid, nombre in filas}


def ocs_out_de(db: Session, solicitud_id: int, rol: Rol) -> list[OCVentasOut]:
    """OC activas de UNA solicitud serializadas para el rol (detalle)."""
    ocs = ocs_activas(db, solicitud_id)
    nombres = _nombres_usuarios(db, {oc.vinculada_por for oc in ocs})
    return [oc_out(oc, rol, nombres.get(oc.vinculada_por)) for oc in ocs]


# ---------------------------------------------------------------- listado


def listar(
    db: Session,
    user: Usuario,
    *,
    estatus: EstatusOC | None,
    vencidas: bool | None,
    sucursal_id: int | None,
    limit: int,
    offset: int,
) -> tuple[list[PedidoItemVentasOut] | list[PedidoItemComprasOut], int]:
    """Solicitudes con al menos una OC activa (que cumpla los filtros), con el
    MISMO scoping que el listado de solicitudes. Sin N+1: dos queries."""
    oc_filtro: list[Any] = [SolicitudOC.activa.is_(True)]
    if estatus is not None:
        oc_filtro.append(SolicitudOC.estatus_derivado == estatus.value)
    if vencidas is not None:
        oc_filtro.append(SolicitudOC.vencida.is_(vencidas))
    con_oc = select(SolicitudOC.solicitud_id).where(*oc_filtro).distinct()
    base = scope_solicitudes_query(user, select(Solicitud)).where(Solicitud.id.in_(con_oc))
    if sucursal_id is not None:
        base = base.where(Solicitud.sucursal_id == sucursal_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    filas = _filas_listado(db, base, limit, offset)
    ids = [s.id for s, _, _ in filas]
    ocs_por_solicitud: dict[int, list[SolicitudOC]] = {}
    if ids:
        for oc in db.scalars(
            select(SolicitudOC)
            .where(SolicitudOC.solicitud_id.in_(ids), *oc_filtro)
            .order_by(SolicitudOC.vinculada_en, SolicitudOC.id)
        ):
            ocs_por_solicitud.setdefault(oc.solicitud_id, []).append(oc)
    nombres = _nombres_usuarios(
        db, {oc.vinculada_por for lista in ocs_por_solicitud.values() for oc in lista}
    )
    compras = ve_fincada(user.rol)
    items: list[Any] = []
    for solicitud, cliente, sucursal in filas:
        datos = {
            "solicitud_id": solicitud.id,
            "folio": solicitud.folio,
            "cliente_nombre": cliente,
            "estado": solicitud.estado.value,
            "sucursal_id": solicitud.sucursal_id,
            "sucursal_nombre": sucursal,
            "fincada": solicitud.fincada if compras else None,
            "ocs": [
                oc_out(oc, user.rol, nombres.get(oc.vinculada_por))
                for oc in ocs_por_solicitud.get(solicitud.id, [])
            ],
        }
        items.append(PedidoItemComprasOut(**datos) if compras else PedidoItemVentasOut(**datos))
    return items, total


def _filas_listado(db: Session, base: Any, limit: int, offset: int) -> list[Any]:
    stmt = (
        base.add_columns(Cliente.nombre_normalizado, Sucursal.nombre)
        .outerjoin(Cliente, Cliente.id == Solicitud.cliente_id)
        .join(Sucursal, Sucursal.id == Solicitud.sucursal_id)
        .order_by(Solicitud.confirmado_en.desc().nullslast(), Solicitud.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).all())
