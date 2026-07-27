"""Agregados de medición (F6, §4.7/§4.9/§6). Definiciones que NO se
reinterpretan:

- Mediana / % esperada / distribución: SOLO ciclos CERRADOS cuya APERTURA cae
  en el periodo filtrado.
- ROJAS AHORA y carga abierta: foto del momento, independientes del periodo.
- Dinero CONFIRMADO por confirmado_en; dinero de REFERENCIA = opción A de las
  solicitudes HOY en COTIZADA por cotizado_en. MXN y USD JAMÁS se suman.
- Conversión por fecha del desenlace (confirmado_en; para NO_CONFIRMADA, el
  último evento →NO_CONFIRMADA del historial).
- Scoping FORZADO sobre los filtros: gerente → su sucursal aunque pida otra;
  comprador → él mismo; vendedor → él mismo.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import median
from typing import Any, Literal

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.core.horario_habil import Banda
from app.core.permissions import scope_solicitudes_query
from app.models.cliente import Cliente
from app.models.cotizacion import CotizacionOpcion, Letra, Moneda
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, Prioridad, Solicitud, SolicitudPartida
from app.models.sucursal import Sucursal
from app.models.usuario import Rol, Usuario
from app.modules.metricas.ciclos import (
    ESTADOS_CICLO_ABIERTO,
    Ciclo,
    cargar_ciclos,
    ciclo_vigente,
)
from app.modules.metricas.schemas import (
    ConversionOut,
    FiltrosOut,
    GrupoOut,
    MaterialesOut,
    MaterialOut,
    MiPanelOut,
    OpcionFiltroOut,
    ResumenOut,
    RojaOut,
    SinDesenlaceOut,
)

Dimension = Literal["comprador", "sucursal", "vendedor", "cliente"]


@dataclass
class Filtros:
    desde: date | None = None
    hasta: date | None = None
    sucursal_id: int | None = None
    comprador_id: int | None = None
    vendedor_id: int | None = None
    cliente_id: int | None = None
    prioridad: Prioridad | None = None
    moneda: Moneda | None = None


def con_scoping(user: Usuario, f: Filtros) -> Filtros:
    """Fuerza el alcance por rol SOBRE los filtros (los del usuario se
    sobreescriben si contradicen su alcance)."""
    if user.rol == Rol.GERENTE:
        # Fail-closed: gerente sin sucursal no ve nada (-1 no matchea).
        f.sucursal_id = user.sucursal_id if user.sucursal_id is not None else -1
    elif user.rol == Rol.COMPRADOR:
        f.comprador_id = user.id
    elif user.rol == Rol.VENDEDOR:
        f.vendedor_id = user.id
    return f


def _limites(f: Filtros) -> tuple[datetime | None, datetime | None]:
    """Fechas inclusivas interpretadas en UTC (mismo criterio que el listado)."""
    ini = datetime(f.desde.year, f.desde.month, f.desde.day, tzinfo=UTC) if f.desde else None
    fin = (
        datetime(f.hasta.year, f.hasta.month, f.hasta.day, tzinfo=UTC) + timedelta(days=1)
        if f.hasta
        else None
    )
    return ini, fin


def _en_periodo(col: Any, ini: datetime | None, fin: datetime | None) -> list[Any]:
    conds = []
    if ini is not None:
        conds.append(col >= ini)
    if fin is not None:
        conds.append(col < fin)
    return conds


def _filtrar(stmt: Select[Any], user: Usuario, f: Filtros) -> Select[Any]:
    """Scope por rol + filtros no temporales sobre Solicitud."""
    stmt = scope_solicitudes_query(user, stmt)
    if f.sucursal_id is not None:
        stmt = stmt.where(Solicitud.sucursal_id == f.sucursal_id)
    if f.comprador_id is not None:
        stmt = stmt.where(Solicitud.comprador_id == f.comprador_id)
    if f.vendedor_id is not None:
        stmt = stmt.where(Solicitud.vendedor_id == f.vendedor_id)
    if f.cliente_id is not None:
        stmt = stmt.where(Solicitud.cliente_id == f.cliente_id)
    if f.prioridad is not None:
        stmt = stmt.where(Solicitud.prioridad == f.prioridad)
    return stmt


_APERTURA = (
    HistorialEstado.a == Estado.ENVIADA,
    or_(HistorialEstado.de.is_(None), HistorialEstado.de != HistorialEstado.a),
)


def _aperturas_en_periodo(db: Session, user: Usuario, f: Filtros) -> dict[int, int | None]:
    """{solicitud_id: None} de las solicitudes con apertura de ciclo en el
    periodo (el valor se reutiliza en las tablas por dimensión)."""
    ini, fin = _limites(f)
    stmt = (
        select(HistorialEstado.solicitud_id)
        .join(Solicitud, HistorialEstado.solicitud_id == Solicitud.id)
        .where(*_APERTURA, *_en_periodo(HistorialEstado.timestamp, ini, fin))
        .distinct()
    )
    return dict.fromkeys(db.scalars(_filtrar(stmt, user, f)))


def _cerrados_en_periodo(db: Session, user: Usuario, f: Filtros, ahora: datetime) -> list[Ciclo]:
    """Ciclos CERRADOS cuya apertura cae en el periodo (universo de mediana,
    % esperada y distribución)."""
    ids = list(_aperturas_en_periodo(db, user, f))
    ini, fin = _limites(f)
    cerrados = []
    for lista in cargar_ciclos(db, ids, ahora).values():
        for ciclo in lista:
            if ciclo.cierre is None:
                continue
            if ini is not None and ciclo.apertura < ini:
                continue
            if fin is not None and ciclo.apertura >= fin:
                continue
            cerrados.append(ciclo)
    return cerrados


def _stats(cerrados: list[Ciclo]) -> tuple[float | None, float | None, dict[str, int]]:
    distribucion = {banda.value: 0 for banda in Banda}
    for ciclo in cerrados:
        distribucion[ciclo.banda.value] += 1
    if not cerrados:
        return None, None, distribucion
    mediana = round(median(c.horas_habiles for c in cerrados), 2)
    pct = round(distribucion[Banda.ESPERADA.value] / len(cerrados), 4)
    return mediana, pct, distribucion


def _abiertas(db: Session, user: Usuario, f: Filtros) -> list[Solicitud]:
    stmt = _filtrar(select(Solicitud), user, f).where(Solicitud.estado.in_(ESTADOS_CICLO_ABIERTO))
    return list(db.scalars(stmt))


def _rojas_ahora(db: Session, user: Usuario, f: Filtros, ahora: datetime) -> dict[int, Ciclo]:
    """Solicitudes con ciclo abierto y T >= 3 — foto del momento."""
    vigentes = ciclo_vigente(db, _abiertas(db, user, f), ahora)
    return {sid: c for sid, c in vigentes.items() if c.t >= 3}


def _dinero_por_moneda(db: Session, stmt: Select[Any]) -> dict[str, Decimal]:
    """{moneda: suma} — series SIEMPRE separadas, jamás sumadas entre sí."""
    return {
        moneda.value: total
        for moneda, total in db.execute(stmt).all()
        if moneda is not None and total is not None
    }


def _dinero_confirmado(db: Session, user: Usuario, f: Filtros, *extra_group: Any) -> Select[Any]:
    ini, fin = _limites(f)
    stmt = (
        select(*extra_group, Solicitud.moneda_confirmada, func.sum(Solicitud.monto_confirmado))
        .where(
            Solicitud.estado == Estado.CONFIRMADA,
            *_en_periodo(Solicitud.confirmado_en, ini, fin),
        )
        .group_by(*extra_group, Solicitud.moneda_confirmada)
    )
    if f.moneda is not None:
        stmt = stmt.where(Solicitud.moneda_confirmada == f.moneda)
    return _filtrar(stmt, user, f)


def _dinero_referencia(db: Session, user: Usuario, f: Filtros) -> dict[str, Decimal]:
    """Monto de referencia (§4.9): opción A de las solicitudes HOY en COTIZADA
    con cotizado_en en el periodo."""
    ini, fin = _limites(f)
    stmt = (
        select(CotizacionOpcion.moneda, func.sum(CotizacionOpcion.total))
        .join(Solicitud, CotizacionOpcion.solicitud_id == Solicitud.id)
        .where(
            CotizacionOpcion.letra == Letra.A,
            Solicitud.estado == Estado.COTIZADA,
            *_en_periodo(Solicitud.cotizado_en, ini, fin),
        )
        .group_by(CotizacionOpcion.moneda)
    )
    if f.moneda is not None:
        stmt = stmt.where(CotizacionOpcion.moneda == f.moneda)
    return _dinero_por_moneda(db, _filtrar(stmt, user, f))


def _sub_desenlace_no_confirmada() -> Any:
    """Último evento →NO_CONFIRMADA por solicitud (fecha del desenlace)."""
    return (
        select(
            HistorialEstado.solicitud_id.label("sid"),
            func.max(HistorialEstado.timestamp).label("ts"),
        )
        .where(
            HistorialEstado.a == Estado.NO_CONFIRMADA,
            HistorialEstado.de != HistorialEstado.a,
        )
        .group_by(HistorialEstado.solicitud_id)
        .subquery()
    )


def _conversion(db: Session, user: Usuario, f: Filtros, ahora: datetime) -> ConversionOut:
    ini, fin = _limites(f)
    confirmadas = db.scalar(
        _filtrar(select(func.count()).select_from(Solicitud), user, f).where(
            Solicitud.estado == Estado.CONFIRMADA,
            *_en_periodo(Solicitud.confirmado_en, ini, fin),
        )
    )
    sub = _sub_desenlace_no_confirmada()
    no_confirmadas = db.scalar(
        _filtrar(
            select(func.count()).select_from(Solicitud).join(sub, sub.c.sid == Solicitud.id),
            user,
            f,
        ).where(Solicitud.estado == Estado.NO_CONFIRMADA, *_en_periodo(sub.c.ts, ini, fin))
    )
    confirmadas, no_confirmadas = confirmadas or 0, no_confirmadas or 0
    total = confirmadas + no_confirmadas
    fechas = db.scalars(
        _filtrar(select(Solicitud.cotizado_en), user, f).where(
            Solicitud.estado == Estado.COTIZADA,
            *_en_periodo(Solicitud.cotizado_en, ini, fin),
        )
    ).all()
    dias = [(ahora - ts).days for ts in fechas if ts is not None]
    return ConversionOut(
        confirmadas=confirmadas,
        no_confirmadas=no_confirmadas,
        tasa=round(confirmadas / total, 4) if total else None,
        sin_desenlace=SinDesenlaceOut(
            total=len(dias),
            antiguedad_promedio_dias=round(sum(dias) / len(dias), 1) if dias else None,
            antiguedad_maxima_dias=max(dias) if dias else None,
        ),
    )


def resumen(db: Session, user: Usuario, f: Filtros) -> ResumenOut:
    f = con_scoping(user, f)
    ahora = datetime.now(UTC)
    ini, fin = _limites(f)

    embudo_filas = db.execute(
        _filtrar(select(Solicitud.estado, func.count()), user, f)
        .where(*_en_periodo(Solicitud.creado_en, ini, fin))
        .group_by(Solicitud.estado)
    ).all()
    embudo = {estado.value: conteo for estado, conteo in embudo_filas}

    cerrados = _cerrados_en_periodo(db, user, f, ahora)
    mediana, pct, distribucion = _stats(cerrados)

    return ResumenOut(
        solicitudes_periodo=sum(embudo.values()),
        ciclos_cerrados=len(cerrados),
        mediana_horas_habiles=mediana,
        pct_banda_esperada=pct,
        distribucion_bandas=distribucion,
        rojas_ahora=len(_rojas_ahora(db, user, f, ahora)),
        embudo=embudo,
        dinero_confirmado=_dinero_por_moneda(db, _dinero_confirmado(db, user, f)),
        dinero_referencia=_dinero_referencia(db, user, f),
        conversion=_conversion(db, user, f, ahora),
    )


_COLUMNA_DIMENSION = {
    "comprador": Solicitud.comprador_id,
    "sucursal": Solicitud.sucursal_id,
    "vendedor": Solicitud.vendedor_id,
    "cliente": Solicitud.cliente_id,
}


def _nombres_de(db: Session, dimension: Dimension, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    if dimension == "sucursal":
        stmt = select(Sucursal.id, Sucursal.nombre).where(Sucursal.id.in_(ids))
    elif dimension == "cliente":
        stmt = select(Cliente.id, Cliente.nombre_normalizado).where(Cliente.id.in_(ids))
    else:
        stmt = select(Usuario.id, Usuario.nombre).where(Usuario.id.in_(ids))
    # .all() antes de dict(): dict() trata al Result como mapping (tiene
    # .keys()) e intenta indexarlo; .tuples() solo aporta el tipado.
    return dict(db.execute(stmt).tuples().all())


def tabla_por(db: Session, user: Usuario, f: Filtros, dimension: Dimension) -> list[GrupoOut]:
    f = con_scoping(user, f)
    ahora = datetime.now(UTC)
    ini, fin = _limites(f)
    col = _COLUMNA_DIMENSION[dimension]

    # Aperturas en periodo con su clave de grupo (grupo = valor ACTUAL de la
    # solicitud: una reasignada cuenta para su comprador actual).
    filas = db.execute(
        _filtrar(
            select(HistorialEstado.solicitud_id, col).join(
                Solicitud, HistorialEstado.solicitud_id == Solicitud.id
            ),
            user,
            f,
        )
        .where(*_APERTURA, *_en_periodo(HistorialEstado.timestamp, ini, fin))
        .distinct()
    ).all()
    grupo_de = {sid: clave for sid, clave in filas if clave is not None}

    cerrados_por_grupo: dict[int, list[Ciclo]] = {}
    for lista in cargar_ciclos(db, list(grupo_de), ahora).values():
        for ciclo in lista:
            if ciclo.cierre is None:
                continue
            if ini is not None and ciclo.apertura < ini:
                continue
            if fin is not None and ciclo.apertura >= fin:
                continue
            cerrados_por_grupo.setdefault(grupo_de[ciclo.solicitud_id], []).append(ciclo)

    volumen: dict[int, int] = {}
    for clave in grupo_de.values():
        volumen[clave] = volumen.get(clave, 0) + 1

    dinero_filas = db.execute(_dinero_confirmado(db, user, f, col)).all()
    dinero: dict[int, dict[str, Decimal]] = {}
    for clave, moneda, total in dinero_filas:
        if clave is None or moneda is None:
            continue
        dinero.setdefault(clave, {})[moneda.value] = total

    claves = set(volumen) | set(dinero) | set(cerrados_por_grupo)

    carga: dict[int, int] = {}
    if dimension == "comprador":
        carga_filas = db.execute(
            _filtrar(select(col, func.count()), user, f)
            .where(Solicitud.estado.in_(ESTADOS_CICLO_ABIERTO))
            .group_by(col)
        ).all()
        carga = {clave: n for clave, n in carga_filas if clave is not None}
        claves |= set(carga)

    extras: dict[int, dict[str, int]] = {}
    if dimension == "cliente":
        extras = _extras_cliente(db, user, f)
        claves |= set(extras)

    nombres = _nombres_de(db, dimension, claves)
    grupos = []
    for clave in claves:
        cerrados = cerrados_por_grupo.get(clave, [])
        mediana, pct, distribucion = _stats(cerrados)
        grupo = GrupoOut(
            id=clave,
            nombre=nombres.get(clave, f"#{clave}"),
            volumen=volumen.get(clave, 0),
            ciclos_cerrados=len(cerrados),
            mediana_horas_habiles=mediana,
            pct_banda_esperada=pct,
            distribucion_bandas=distribucion,
            dinero_confirmado=dinero.get(clave, {}),
        )
        if dimension == "comprador":
            grupo.carga_abierta = carga.get(clave, 0)
        if dimension == "cliente":
            e = extras.get(clave, {})
            grupo.cotizadas = e.get("cotizadas", 0)
            grupo.confirmadas = e.get("confirmadas", 0)
            grupo.no_confirmadas = e.get("no_confirmadas", 0)
            grupo.sin_desenlace = e.get("sin_desenlace", 0)
            grupo.ratio_confirmacion = (
                round(grupo.confirmadas / grupo.cotizadas, 4) if grupo.cotizadas else None
            )
        grupos.append(grupo)

    if dimension == "cliente":
        # "Cotizan mucho y confirman poco" primero (resp. 57).
        grupos.sort(key=lambda g: (g.ratio_confirmacion is None, g.ratio_confirmacion, g.nombre))
    else:
        grupos.sort(key=lambda g: g.nombre)
    return grupos


def _extras_cliente(db: Session, user: Usuario, f: Filtros) -> dict[int, dict[str, int]]:
    """Por cliente: cotizadas (cotizado_en en periodo), confirmadas,
    no confirmadas (desenlace en periodo) y sin desenlace (HOY en COTIZADA)."""
    ini, fin = _limites(f)
    col = Solicitud.cliente_id
    extras: dict[int, dict[str, int]] = {}

    def _acumular(stmt: Any, campo: str) -> None:
        for clave, n in db.execute(stmt).all():
            if clave is not None:
                extras.setdefault(clave, {})[campo] = n

    base = _filtrar(select(col, func.count()).group_by(col), user, f)
    _acumular(base.where(*_en_periodo(Solicitud.cotizado_en, ini, fin)), "cotizadas")
    _acumular(
        base.where(
            Solicitud.estado == Estado.CONFIRMADA,
            *_en_periodo(Solicitud.confirmado_en, ini, fin),
        ),
        "confirmadas",
    )
    sub = _sub_desenlace_no_confirmada()
    _acumular(
        _filtrar(
            select(col, func.count())
            .select_from(Solicitud)
            .join(sub, sub.c.sid == Solicitud.id)
            .group_by(col),
            user,
            f,
        ).where(Solicitud.estado == Estado.NO_CONFIRMADA, *_en_periodo(sub.c.ts, ini, fin)),
        "no_confirmadas",
    )
    _acumular(
        base.where(
            Solicitud.estado == Estado.COTIZADA,
            *_en_periodo(Solicitud.cotizado_en, ini, fin),
        ),
        "sin_desenlace",
    )
    return extras


def materiales(db: Session, user: Usuario, f: Filtros, limite: int) -> MaterialesOut:
    """Tops por descripción normalizada (upper/trim) y por codigo_sap no nulo,
    sobre partidas de solicitudes creadas en el periodo."""
    f = con_scoping(user, f)
    ini, fin = _limites(f)

    def _top(expr: Any, *conds: Any) -> list[MaterialOut]:
        stmt = (
            _filtrar(
                select(expr.label("valor"), func.count()).join(
                    Solicitud, SolicitudPartida.solicitud_id == Solicitud.id
                ),
                user,
                f,
            )
            .where(*conds, *_en_periodo(Solicitud.creado_en, ini, fin))
            .group_by("valor")
            .order_by(func.count().desc(), "valor")
            .limit(limite)
        )
        return [MaterialOut(valor=v, conteo=n) for v, n in db.execute(stmt).all()]

    return MaterialesOut(
        por_descripcion=_top(func.upper(func.trim(SolicitudPartida.descripcion))),
        por_codigo_sap=_top(SolicitudPartida.codigo_sap, SolicitudPartida.codigo_sap.is_not(None)),
    )


def mi_panel(db: Session, comprador: Usuario) -> MiPanelOut:
    """Panel personal del comprador: SUS números del mes en curso (resp. 49)."""
    ahora = datetime.now(UTC)
    hoy = ahora.date()
    f = con_scoping(comprador, Filtros(desde=hoy.replace(day=1), hasta=hoy))
    cerrados = _cerrados_en_periodo(db, comprador, f, ahora)
    mediana, pct, distribucion = _stats(cerrados)
    abiertas = _abiertas(db, comprador, f)
    rojas = _rojas_ahora(db, comprador, f, ahora)
    folios = {s.id: s.folio for s in abiertas}
    return MiPanelOut(
        mes=hoy.strftime("%Y-%m"),
        ciclos_cerrados=len(cerrados),
        mediana_horas_habiles=mediana,
        pct_banda_esperada=pct,
        distribucion_bandas=distribucion,
        carga_abierta=len(abiertas),
        rojas=[
            RojaOut(
                solicitud_id=sid,
                folio=folios.get(sid),
                dias_transcurridos=ciclo.t,
                horas_habiles=round(ciclo.horas_habiles, 2),
            )
            for sid, ciclo in sorted(rojas.items(), key=lambda kv: -kv[1].t)
        ],
    )


def filtros(db: Session, user: Usuario) -> FiltrosOut:
    """Catálogos para filtros de F8, acotados por rol. El gerente sigue SIN
    acceso a /usuarios: esto expone solo id+nombre de lo que puede filtrar."""
    sucursales = [
        OpcionFiltroOut(id=s.id, nombre=s.nombre)
        for s in db.scalars(select(Sucursal).where(Sucursal.activa).order_by(Sucursal.nombre))
    ]
    compradores = vendedores = None
    if user.rol in (Rol.ADMIN, Rol.GERENTE):
        compradores = [
            OpcionFiltroOut(id=u.id, nombre=u.nombre)
            for u in db.scalars(
                select(Usuario)
                .where(Usuario.rol == Rol.COMPRADOR, Usuario.activo)
                .order_by(Usuario.nombre)
            )
        ]
        stmt = select(Usuario).where(Usuario.rol == Rol.VENDEDOR, Usuario.activo)
        if user.rol == Rol.GERENTE:
            sucursal = user.sucursal_id if user.sucursal_id is not None else -1
            stmt = stmt.where(Usuario.sucursal_id == sucursal)
        vendedores = [
            OpcionFiltroOut(id=u.id, nombre=u.nombre)
            for u in db.scalars(stmt.order_by(Usuario.nombre))
        ]
    return FiltrosOut(sucursales=sucursales, compradores=compradores, vendedores=vendedores)
