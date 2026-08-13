"""Agregados de medición (F6, §4.7/§4.9/§6). Definiciones que NO se
reinterpretan:

- Mediana / % esperada: SOLO ciclos CERRADOS cuya APERTURA cae en el periodo
  filtrado (miden respuesta completada). La DISTRIBUCIÓN de bandas (F11 p.4)
  suma además los ciclos ABIERTOS del periodo con su banda ACTUAL — el
  semáforo del dashboard coincide con detalle y listado.
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
from app.models.cotizacion import CotizacionOpcion, Letra, Moneda, OpcionPartida
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
    EstadisticaTiempoOut,
    FiltrosOut,
    GrupoOut,
    MaterialesOut,
    MaterialOut,
    MiPanelOut,
    NoEncontradosGrupoOut,
    NoEncontradosOut,
    OpcionFiltroOut,
    ResumenOut,
    RojaOut,
    SemanaOut,
    SerieOut,
    SinDesenlaceOut,
    TiemposEtapaOut,
)
from app.modules.metricas.tiempos import ESTADOS_COMPRAS, ESTADOS_VENTAS, cargar_tiempos

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
    if user.rol == Rol.GERENTE_SUCURSAL:
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


def _ciclos_en_periodo(
    db: Session, user: Usuario, f: Filtros, ahora: datetime
) -> tuple[list[Ciclo], list[Ciclo]]:
    """(cerrados, abiertos) cuya apertura cae en el periodo. Los CERRADOS son
    el universo de mediana y % esperada (miden respuesta completada); la
    DISTRIBUCIÓN suma ambos (F11 p.4): un ciclo abierto en amarillo/rojo debe
    verse en el semáforo del dashboard igual que en detalle y listado."""
    ids = list(_aperturas_en_periodo(db, user, f))
    ini, fin = _limites(f)
    cerrados: list[Ciclo] = []
    abiertos: list[Ciclo] = []
    for lista in cargar_ciclos(db, ids, ahora).values():
        for ciclo in lista:
            if ini is not None and ciclo.apertura < ini:
                continue
            if fin is not None and ciclo.apertura >= fin:
                continue
            (cerrados if ciclo.cierre is not None else abiertos).append(ciclo)
    return cerrados, abiertos


def _stats(
    cerrados: list[Ciclo], abiertos: list[Ciclo]
) -> tuple[float | None, float | None, dict[str, int]]:
    distribucion = {banda.value: 0 for banda in Banda}
    for ciclo in [*cerrados, *abiertos]:
        distribucion[ciclo.banda.value] += 1
    if not cerrados:
        return None, None, distribucion
    mediana = round(median(c.horas_habiles for c in cerrados), 2)
    esperadas_cerradas = sum(1 for c in cerrados if c.banda == Banda.ESPERADA)
    pct = round(esperadas_cerradas / len(cerrados), 4)
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


def _series_por_moneda(
    mxn: Decimal | None, usd: Decimal | None, filtro: Moneda | None
) -> dict[str, Decimal]:
    """{MXN: x, USD: y} desde subtotales (F8c) — solo claves con dinero; el
    filtro de moneda restringe series, jamás las mezcla."""
    series: dict[str, Decimal] = {}
    if mxn:
        series["MXN"] = mxn
    if usd:
        series["USD"] = usd
    if filtro is not None:
        series = {k: v for k, v in series.items() if k == filtro.value}
    return series


def _dinero_referencia(db: Session, user: Usuario, f: Filtros) -> dict[str, Decimal]:
    """Monto de referencia (§4.9): opción A de las solicitudes HOY en COTIZADA
    con cotizado_en en el periodo. Series por moneda SEPARADAS (aún sin TC)."""
    ini, fin = _limites(f)
    stmt = (
        select(func.sum(CotizacionOpcion.total_mxn), func.sum(CotizacionOpcion.total_usd))
        .join(Solicitud, CotizacionOpcion.solicitud_id == Solicitud.id)
        .where(
            CotizacionOpcion.letra == Letra.A,
            Solicitud.estado == Estado.COTIZADA,
            *_en_periodo(Solicitud.cotizado_en, ini, fin),
        )
    )
    mxn, usd = db.execute(_filtrar(stmt, user, f)).one()
    return _series_por_moneda(mxn, usd, f.moneda)


def _dinero_confirmado_desglose(db: Session, user: Usuario, f: Filtros) -> dict[str, Decimal]:
    """Desglose ORIGINAL por moneda del dinero confirmado (dato secundario,
    F8c): subtotales de la opción ganadora, antes de consolidar con TC."""
    ini, fin = _limites(f)
    stmt = (
        select(func.sum(CotizacionOpcion.total_mxn), func.sum(CotizacionOpcion.total_usd))
        .join(Solicitud, Solicitud.opcion_seleccionada_id == CotizacionOpcion.id)
        .where(
            Solicitud.estado == Estado.CONFIRMADA,
            *_en_periodo(Solicitud.confirmado_en, ini, fin),
        )
    )
    mxn, usd = db.execute(_filtrar(stmt, user, f)).one()
    return _series_por_moneda(mxn, usd, f.moneda)


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

    cerrados, abiertos = _ciclos_en_periodo(db, user, f, ahora)
    mediana, pct, distribucion = _stats(cerrados, abiertos)

    return ResumenOut(
        solicitudes_periodo=sum(embudo.values()),
        ciclos_cerrados=len(cerrados),
        mediana_horas_habiles=mediana,
        pct_banda_esperada=pct,
        distribucion_bandas=distribucion,
        rojas_ahora=len(_rojas_ahora(db, user, f, ahora)),
        embudo=embudo,
        # F8c: el confirmado es UNA serie consolidada en MXN (el TC se fijó al
        # confirmar); el desglose original por moneda es dato secundario.
        dinero_confirmado=_dinero_por_moneda(db, _dinero_confirmado(db, user, f)),
        dinero_confirmado_desglose=_dinero_confirmado_desglose(db, user, f),
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
    abiertos_por_grupo: dict[int, list[Ciclo]] = {}
    for lista in cargar_ciclos(db, list(grupo_de), ahora).values():
        for ciclo in lista:
            if ini is not None and ciclo.apertura < ini:
                continue
            if fin is not None and ciclo.apertura >= fin:
                continue
            destino = cerrados_por_grupo if ciclo.cierre is not None else abiertos_por_grupo
            destino.setdefault(grupo_de[ciclo.solicitud_id], []).append(ciclo)

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
        mediana, pct, distribucion = _stats(cerrados, abiertos_por_grupo.get(clave, []))
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


def _lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def serie_semanal(db: Session, user: Usuario, f: Filtros) -> SerieOut:
    """Serie por semana (F8d): creadas por `creado_en`; confirmadas y dinero
    consolidado MXN por `confirmado_en`. La semana se trunca EXPLÍCITAMENTE en
    UTC (timezone('UTC', col)) para no depender del TimeZone del servidor;
    devuelve semanas continuas del periodo, rellenas con ceros."""
    f = con_scoping(user, f)
    ini, fin = _limites(f)

    semana_creada = func.date_trunc("week", func.timezone("UTC", Solicitud.creado_en))
    stmt_creadas = (
        select(semana_creada, func.count())
        .where(*_en_periodo(Solicitud.creado_en, ini, fin))
        .group_by(semana_creada)
    )
    creadas: dict[datetime, int] = dict(
        db.execute(_filtrar(stmt_creadas, user, f)).all()  # type: ignore[arg-type]
    )

    semana_conf = func.date_trunc("week", func.timezone("UTC", Solicitud.confirmado_en))
    stmt_conf = (
        select(
            semana_conf,
            func.count(),
            func.coalesce(func.sum(Solicitud.monto_confirmado), 0),
        )
        .where(
            Solicitud.confirmado_en.is_not(None),
            Solicitud.estado == Estado.CONFIRMADA,
            *_en_periodo(Solicitud.confirmado_en, ini, fin),
        )
        .group_by(semana_conf)
    )
    confirmadas: dict[datetime, tuple[int, Decimal]] = {
        semana: (conteo, dinero)
        for semana, conteo, dinero in db.execute(_filtrar(stmt_conf, user, f)).all()
    }

    observadas = sorted(dt.date() for dt in {*creadas, *confirmadas})
    inicio = _lunes(f.desde) if f.desde else (observadas[0] if observadas else None)
    final = _lunes(f.hasta) if f.hasta else (observadas[-1] if observadas else None)
    if inicio is None or final is None or inicio > final:
        return SerieOut(semanas=[])

    puntos = []
    semana = inicio
    while semana <= final:
        clave = datetime(semana.year, semana.month, semana.day)  # naive: como date_trunc
        conf, dinero = confirmadas.get(clave, (0, Decimal("0")))
        puntos.append(
            SemanaOut(
                semana=semana,
                creadas=creadas.get(clave, 0),
                confirmadas=conf,
                dinero_confirmado_mxn=dinero,
            )
        )
        semana += timedelta(days=7)
    return SerieOut(semanas=puntos)


def mi_panel(db: Session, comprador: Usuario) -> MiPanelOut:
    """Panel personal del comprador: SUS números del mes en curso (resp. 49)."""
    ahora = datetime.now(UTC)
    hoy = ahora.date()
    f = con_scoping(comprador, Filtros(desde=hoy.replace(day=1), hasta=hoy))
    cerrados, abiertos_periodo = _ciclos_en_periodo(db, comprador, f, ahora)
    mediana, pct, distribucion = _stats(cerrados, abiertos_periodo)
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
    # v2 por ÁREA: compradores solo para quien ve métricas de compras;
    # vendedores solo para el lado ventas gerencial (y admin todo).
    if user.rol in (Rol.ADMIN, Rol.GERENTE_COMPRAS):
        compradores = [
            OpcionFiltroOut(id=u.id, nombre=u.nombre)
            for u in db.scalars(
                select(Usuario)
                .where(Usuario.rol == Rol.COMPRADOR, Usuario.activo)
                .order_by(Usuario.nombre)
            )
        ]
    if user.rol in (Rol.ADMIN, Rol.DIRECTOR_VENTAS, Rol.GERENTE_SUCURSAL):
        stmt = select(Usuario).where(Usuario.rol == Rol.VENDEDOR, Usuario.activo)
        if user.rol == Rol.GERENTE_SUCURSAL:
            sucursal = user.sucursal_id if user.sucursal_id is not None else -1
            stmt = stmt.where(Usuario.sucursal_id == sucursal)
        vendedores = [
            OpcionFiltroOut(id=u.id, nombre=u.nombre)
            for u in db.scalars(stmt.order_by(Usuario.nombre))
        ]
    return FiltrosOut(sucursales=sucursales, compradores=compradores, vendedores=vendedores)


def _estadistica(observaciones: list[float]) -> EstadisticaTiempoOut:
    if not observaciones:
        return EstadisticaTiempoOut(n=0, promedio_horas_habiles=None, mediana_horas_habiles=None)
    return EstadisticaTiempoOut(
        n=len(observaciones),
        promedio_horas_habiles=round(sum(observaciones) / len(observaciones), 2),
        mediana_horas_habiles=round(median(observaciones), 2),
    )


def tiempos_etapa(db: Session, user: Usuario, f: Filtros) -> TiemposEtapaOut:
    """Promedio y mediana de horas hábiles por estado + agregados compras/
    ventas (F8f). Universo: solicitudes CREADAS en el periodo (mismo criterio
    que el embudo). Solo alimentan las estadísticas los segmentos CERRADOS
    (una estancia vigente aún no terminó); la observación es la SUMA por
    solicitud de sus segmentos cerrados en el estado o grupo."""
    f = con_scoping(user, f)
    ini, fin = _limites(f)
    ids = list(
        db.scalars(
            _filtrar(select(Solicitud.id), user, f).where(
                *_en_periodo(Solicitud.creado_en, ini, fin)
            )
        )
    )
    por_estado: dict[str, list[float]] = {e.value: [] for e in Estado}
    compras: list[float] = []
    ventas: list[float] = []
    for tiempos in cargar_tiempos(db, ids).values():
        sumas: dict[Estado, float] = {}
        for seg in tiempos.segmentos:
            if seg.fin is None:
                continue
            sumas[seg.estado] = sumas.get(seg.estado, 0.0) + seg.horas_habiles
        for estado, horas in sumas.items():
            por_estado[estado.value].append(horas)
        if any(e in ESTADOS_COMPRAS for e in sumas):
            compras.append(sum(h for e, h in sumas.items() if e in ESTADOS_COMPRAS))
        if any(e in ESTADOS_VENTAS for e in sumas):
            ventas.append(sum(h for e, h in sumas.items() if e in ESTADOS_VENTAS))
    return TiemposEtapaOut(
        por_estado={estado: _estadistica(obs) for estado, obs in por_estado.items()},
        compras=_estadistica(compras),
        ventas=_estadistica(ventas),
    )


def no_encontrados(db: Session, user: Usuario, f: Filtros, limite: int = 10) -> NoEncontradosOut:
    """% de renglones NO ENCONTRADOS (F8c): global, por comprador y top de
    materiales no conseguidos. Universo: renglones persistidos de solicitudes
    en el periodo (creado_en). Visible solo para gerente_compras y admin (lo
    exige el router)."""
    f = con_scoping(user, f)
    ini, fin = _limites(f)
    base = (
        select(
            Solicitud.comprador_id,
            func.count(OpcionPartida.id),
            func.count(OpcionPartida.id).filter(OpcionPartida.no_encontrada),
        )
        .join(CotizacionOpcion, OpcionPartida.opcion_id == CotizacionOpcion.id)
        .join(Solicitud, CotizacionOpcion.solicitud_id == Solicitud.id)
        .where(*_en_periodo(Solicitud.creado_en, ini, fin))
        .group_by(Solicitud.comprador_id)
    )
    filas = db.execute(_filtrar(base, user, f)).all()
    nombres = _nombres_de(db, "comprador", {cid for cid, _, _ in filas if cid is not None})
    total = sum(t for _, t, _ in filas)
    no_enc = sum(n for _, _, n in filas)
    por_comprador = [
        NoEncontradosGrupoOut(
            id=cid,
            nombre=nombres.get(cid, f"#{cid}"),
            total_renglones=t,
            no_encontrados=n,
            pct=round(n / t, 4) if t else None,
        )
        for cid, t, n in filas
        if cid is not None
    ]
    por_comprador.sort(key=lambda g: (-(g.pct or 0), g.nombre))

    top_stmt = (
        select(func.upper(func.trim(SolicitudPartida.descripcion)), func.count())
        .select_from(OpcionPartida)
        .join(SolicitudPartida, OpcionPartida.partida_id == SolicitudPartida.id)
        .join(CotizacionOpcion, OpcionPartida.opcion_id == CotizacionOpcion.id)
        .join(Solicitud, CotizacionOpcion.solicitud_id == Solicitud.id)
        .where(OpcionPartida.no_encontrada, *_en_periodo(Solicitud.creado_en, ini, fin))
        .group_by(func.upper(func.trim(SolicitudPartida.descripcion)))
        .order_by(func.count().desc())
        .limit(limite)
    )
    top = [
        MaterialOut(valor=valor, conteo=conteo)
        for valor, conteo in db.execute(_filtrar(top_stmt, user, f)).all()
    ]
    return NoEncontradosOut(
        total_renglones=total,
        no_encontrados=no_enc,
        pct=round(no_enc / total, 4) if total else None,
        por_comprador=por_comprador,
        top_materiales=top,
    )
