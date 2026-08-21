"""F6: ciclos, bandas, KPIs y dinero — con historial SINTÉTICO de timestamps
controlados (permitido aquí para fijar fechas exactas; los estados de cada
solicitud quedan coherentes con su último evento).

Sucursal base: America/Chihuahua (UTC-6 fijo, sin DST desde 2022).
Festivo usado: 2026-03-16, Natalicio de Benito Juárez (tercer lunes de marzo,
mismo dato que carga el seed). Calendario de marzo 2026: el 1 es domingo;
02=lun, 05=jue, 06=vie, 07=sáb, 09=lun, 13=vie, 14=sáb, 16=lun FESTIVO,
17=mar, 18=mié."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.catalogos import DiaFestivo
from app.models.cliente import Cliente
from app.models.cotizacion import CotizacionOpcion, Letra, Moneda
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, Prioridad, Solicitud, SolicitudPartida
from app.models.usuario import Rol

RESUMEN = "/api/v1/metricas/resumen"
MARZO = {"desde": "2026-03-01", "hasta": "2026-03-31"}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    cuu = make_sucursal("Metricas CUU")  # America/Chihuahua (default del factory)
    tij = make_sucursal("Metricas TIJ")
    tij.timezone = "America/Tijuana"
    db.add(DiaFestivo(fecha=date(2026, 3, 16), descripcion="Natalicio de Benito Juárez"))
    db.commit()
    return SimpleNamespace(
        cuu=cuu,
        tij=tij,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=cuu.id),
        otro_vendedor=make_user(Rol.VENDEDOR, sucursal_id=cuu.id),
        comprador=make_user(Rol.COMPRADOR),
        otro_comprador=make_user(Rol.COMPRADOR),
        gerente_cuu=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=cuu.id),
        admin=make_user(Rol.ADMIN),
    )


_contador_folio = iter(range(1, 10_000))


def _sintetica(
    db,
    entorno,
    *,
    estado,
    eventos=(),
    sucursal=None,
    vendedor=None,
    comprador=None,
    cliente_id=None,
    creado_en=None,
    **campos,
):
    sucursal = sucursal or entorno.cuu
    vendedor = vendedor or entorno.vendedor
    solicitud = Solicitud(
        folio=f"MET-{next(_contador_folio)}",
        vendedor_id=vendedor.id,
        sucursal_id=sucursal.id,
        comprador_id=(comprador or entorno.comprador).id,
        cliente_id=cliente_id,
        estado=estado,
        prioridad=Prioridad.NORMAL,
        **campos,
    )
    db.add(solicitud)
    db.flush()
    if creado_en is not None:
        solicitud.creado_en = creado_en
    for de, a, ts in eventos:
        db.add(
            HistorialEstado(
                solicitud_id=solicitud.id, de=de, a=a, usuario_id=vendedor.id, timestamp=ts
            )
        )
    db.commit()
    return solicitud


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


def _ciclo_cerrado(db, entorno, apertura, cierre, cierre_estado=Estado.COTIZADA, **kwargs):
    campos = {}
    if cierre_estado == Estado.COTIZADA:
        campos["cotizado_en"] = cierre
    return _sintetica(
        db,
        entorno,
        estado=cierre_estado,
        eventos=[
            (Estado.BORRADOR, Estado.ENVIADA, apertura),
            (Estado.EN_PROCESO, cierre_estado, cierre),
        ],
        creado_en=apertura,
        **campos,
        **kwargs,
    )


@pytest.fixture
def tres_bandas(db, entorno):
    """Un ciclo cerrado en cada banda, con la aritmética verificada A MANO
    (hora local = UTC-6):

    ESPERADA — abre jue 05-mar 15:00, cierra vie 06-mar 10:00:
      jue 15→18 = 3h, vie 8→10 = 2h → 5.0h; T0=jue05, vie06 → T=1.
    NORMAL (cruza fin de semana) — abre vie 06 16:00, cierra lun 09 12:00:
      vie 16→18 = 2h, sáb 8→13 = 5h, lun 8→12 = 4h → 11.0h;
      T0=vie06, sáb07(+1), dom no, lun09(+2) → T=2.
    LENTA (cruza fin de semana Y el festivo lun 16) — abre vie 13 09:00,
      cierra mié 18 09:00 en RECHAZADA:
      vie 9→18 = 9h, sáb 8→13 = 5h, dom 0, lun16 FESTIVO 0, mar 8→18 = 10h,
      mié 8→9 = 1h → 25.0h; T0=vie13, sáb14(+1), mar17(+2), mié18(+3) → T=3.

    Mediana de horas [5.0, 11.0, 25.0] = 11.0 (el promedio sería 13.67).
    """
    a = _ciclo_cerrado(db, entorno, _utc(2026, 3, 5, 21), _utc(2026, 3, 6, 16))
    b = _ciclo_cerrado(db, entorno, _utc(2026, 3, 6, 22), _utc(2026, 3, 9, 18))
    c = _ciclo_cerrado(
        db, entorno, _utc(2026, 3, 13, 15), _utc(2026, 3, 18, 15), cierre_estado=Estado.RECHAZADA
    )
    return [a, b, c]


def test_bandas_y_kpis_verificados_a_mano(client, entorno, tres_bandas, auth_headers):
    r = client.get(RESUMEN, params=MARZO, headers=auth_headers(entorno.admin))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ciclos_cerrados"] == 3
    assert body["mediana_horas_habiles"] == 11.0  # mediana, NO promedio (13.67)
    assert body["pct_banda_esperada"] == 0.3333
    assert body["distribucion_bandas"] == {"ESPERADA": 1, "NORMAL": 1, "LENTA": 1}
    assert body["solicitudes_periodo"] == 3  # creadas en el periodo (embudo)
    assert body["embudo"] == {"COTIZADA": 2, "RECHAZADA": 1}


def test_detalle_de_ciclos_por_solicitud(client, db, entorno, tres_bandas, auth_headers):
    detalle = client.get(
        f"/api/v1/solicitudes/{tres_bandas[2].id}", headers=auth_headers(entorno.admin)
    ).json()
    assert detalle["ciclos"] == [
        {
            "numero": 1,
            "apertura": "2026-03-13T15:00:00Z",
            "cierre": "2026-03-18T15:00:00Z",
            "horas_habiles": 25.0,
            "dias_transcurridos": 3,
            "banda": "LENTA",
        }
    ]


def test_reenvio_dos_ciclos_sin_arrastrar_rechazada(client, db, entorno, auth_headers):
    """Reenviada = 2 ciclos y AMBOS cuentan; el tiempo en RECHAZADA (mar 03
    09:00 → jue 05 09:00) NO cuenta para el segundo ciclo (resp. 31).

    Ciclo 1: lun 02-mar 09:00 → mar 03 09:00 = lun 9→18 (9h) + mar 8→9 (1h)
    = 10.0h, T=1. Ciclo 2: jue 05 09:00 → jue 05 12:00 = 3.0h, T=0."""
    _sintetica(
        db,
        entorno,
        estado=Estado.COTIZADA,
        cotizado_en=_utc(2026, 3, 5, 18),
        creado_en=_utc(2026, 3, 2, 15),
        eventos=[
            (Estado.BORRADOR, Estado.ENVIADA, _utc(2026, 3, 2, 15)),
            (Estado.EN_PROCESO, Estado.RECHAZADA, _utc(2026, 3, 3, 15)),
            (Estado.RECHAZADA, Estado.ENVIADA, _utc(2026, 3, 5, 15)),
            (Estado.EN_PROCESO, Estado.COTIZADA, _utc(2026, 3, 5, 18)),
        ],
    )
    r = client.get(RESUMEN, params=MARZO, headers=auth_headers(entorno.admin))
    body = r.json()
    assert body["ciclos_cerrados"] == 2  # ambos cierres cuentan como respuesta
    assert body["mediana_horas_habiles"] == 6.5  # mediana de [10.0, 3.0]
    assert body["distribucion_bandas"] == {"ESPERADA": 2, "NORMAL": 0, "LENTA": 0}


def test_eventos_de_edicion_no_abren_ni_cierran_ciclos(client, db, entorno, auth_headers):
    """Los eventos de==a (edición, corrección, reasignación) no tocan ciclos."""
    _sintetica(
        db,
        entorno,
        estado=Estado.COTIZADA,
        cotizado_en=_utc(2026, 3, 6, 16),
        creado_en=_utc(2026, 3, 5, 21),
        eventos=[
            (Estado.BORRADOR, Estado.ENVIADA, _utc(2026, 3, 5, 21)),
            (Estado.ENVIADA, Estado.ENVIADA, _utc(2026, 3, 5, 22)),  # edición
            (Estado.EN_PROCESO, Estado.COTIZADA, _utc(2026, 3, 6, 16)),
            (Estado.COTIZADA, Estado.COTIZADA, _utc(2026, 3, 6, 17)),  # corrección
        ],
    )
    body = client.get(RESUMEN, params=MARZO, headers=auth_headers(entorno.admin)).json()
    assert body["ciclos_cerrados"] == 1
    assert body["mediana_horas_habiles"] == 5.0


def test_multi_tz_mismo_instante_t_distinto(client, db, entorno, auth_headers):
    """El mismo par de instantes UTC produce T distinto por zona horaria:
    apertura sáb 11-jul-2026 00:30Z = vie 10-jul 18:30 en Chihuahua (UTC-6,
    después del cierre → T0=sáb 11) pero vie 17:30 en Tijuana (UTC-7 en
    verano, antes del cierre → T0=vie 10). Cierre lun 13-jul 16:00Z:
    CUU: dom no, lun(+1) → T=1 ESPERADA · TIJ: sáb(+1), lun(+2) → T=2 NORMAL."""
    apertura, cierre = _utc(2026, 7, 11, 0, 30), _utc(2026, 7, 13, 16)
    _ciclo_cerrado(db, entorno, apertura, cierre, sucursal=entorno.cuu)
    _ciclo_cerrado(db, entorno, apertura, cierre, sucursal=entorno.tij)
    body = client.get(
        RESUMEN,
        params={"desde": "2026-07-01", "hasta": "2026-07-20"},
        headers=auth_headers(entorno.admin),
    ).json()
    assert body["distribucion_bandas"] == {"ESPERADA": 1, "NORMAL": 1, "LENTA": 0}


def test_dinero_por_moneda_jamas_mezclado(client, db, entorno, auth_headers):
    _sintetica(
        db,
        entorno,
        estado=Estado.CONFIRMADA,
        monto_confirmado=Decimal("1000.00"),
        moneda_confirmada=Moneda.MXN,
        confirmado_en=_utc(2026, 3, 20, 12),
    )
    # F8c: una confirmada que ERA USD ya viene consolidada (500 × 18.50).
    _sintetica(
        db,
        entorno,
        estado=Estado.CONFIRMADA,
        monto_confirmado=Decimal("9250.00"),
        moneda_confirmada=Moneda.MXN,
        tipo_cambio=Decimal("18.50"),
        confirmado_en=_utc(2026, 3, 21, 12),
    )
    cotizada = _sintetica(db, entorno, estado=Estado.COTIZADA, cotizado_en=_utc(2026, 3, 15, 12))
    # Opción A MIXTA (F8c): subtotales por moneda que JAMÁS se suman.
    db.add(
        CotizacionOpcion(
            solicitud_id=cotizada.id,
            letra=Letra.A,
            total_mxn=Decimal("700.00"),
            total_usd=Decimal("120.00"),
            completa=True,
        )
    )
    # La opción B NO cuenta como referencia (solo la A, §4.9).
    db.add(
        CotizacionOpcion(
            solicitud_id=cotizada.id,
            letra=Letra.B,
            total_mxn=Decimal("9999.00"),
            completa=True,
        )
    )
    db.commit()

    headers = auth_headers(entorno.admin)
    body = client.get(RESUMEN, params=MARZO, headers=headers).json()
    # Confirmado: UNA serie consolidada MXN (1000 + 9250); referencia: series
    # separadas por moneda de la opción A.
    assert body["dinero_confirmado"] == {"MXN": "10250.00"}
    assert body["dinero_referencia"] == {"MXN": "700.00", "USD": "120.00"}
    # Sin opción ganadora ligada (datos sintéticos), el desglose queda vacío.
    assert body["dinero_confirmado_desglose"] == {}

    # Filtro de moneda: restringe las series, no las mezcla.
    body = client.get(RESUMEN, params={**MARZO, "moneda": "USD"}, headers=headers).json()
    assert body["dinero_confirmado"] == {}  # todo confirmado vive en MXN
    assert body["dinero_referencia"] == {"USD": "120.00"}


def test_conversion_y_sin_desenlace(client, db, entorno, auth_headers):
    """F14 p.1: la conversión cuenta por CICLOS — el denominador son las
    transiciones reales →COTIZADA del periodo, el numerador las de ESAS hoy
    en CONFIRMADA. A mano: cotizadas = {confirmada, no_confirmada, abierta}
    = 3; confirmadas = 1 → tasa = 1/3 = 0.3333."""
    _sintetica(
        db,
        entorno,
        estado=Estado.CONFIRMADA,
        monto_confirmado=Decimal("100.00"),
        moneda_confirmada=Moneda.MXN,
        confirmado_en=_utc(2026, 3, 10, 12),
        eventos=[(Estado.EN_PROCESO, Estado.COTIZADA, _utc(2026, 3, 9, 12))],
    )
    _sintetica(
        db,
        entorno,
        estado=Estado.NO_CONFIRMADA,
        motivo_no_confirmada="PRECIO",
        eventos=[
            (Estado.EN_PROCESO, Estado.COTIZADA, _utc(2026, 3, 10, 12)),
            (Estado.COTIZADA, Estado.NO_CONFIRMADA, _utc(2026, 3, 11, 12)),
        ],
    )
    cotizado_en = datetime.now(UTC) - timedelta(days=5)
    _sintetica(
        db,
        entorno,
        estado=Estado.COTIZADA,
        cotizado_en=cotizado_en,
        eventos=[(Estado.EN_PROCESO, Estado.COTIZADA, cotizado_en)],
    )

    params = {"desde": "2026-03-01", "hasta": date.today().isoformat()}
    body = client.get(RESUMEN, params=params, headers=auth_headers(entorno.admin)).json()
    conv = body["conversion"]
    assert (conv["cotizadas"], conv["confirmadas"], conv["no_confirmadas"]) == (3, 1, 1)
    assert conv["tasa"] == 0.3333
    assert conv["sin_desenlace"]["total"] == 1
    assert conv["sin_desenlace"]["antiguedad_maxima_dias"] == 5


def test_rojas_ahora_foto_del_momento(client, db, entorno, auth_headers):
    """Ciclo abierto con apertura hace 10 días naturales → T>=3 (rojo) sin
    importar el periodo filtrado."""
    _sintetica(
        db,
        entorno,
        estado=Estado.ENVIADA,
        eventos=[(Estado.BORRADOR, Estado.ENVIADA, datetime.now(UTC) - timedelta(days=10))],
    )
    headers = auth_headers(entorno.admin)
    body = client.get(RESUMEN, headers=headers).json()
    assert body["rojas_ahora"] == 1
    # Con un periodo viejo que NO incluye la apertura, la foto no cambia.
    body = client.get(
        RESUMEN, params={"desde": "2020-01-01", "hasta": "2020-01-31"}, headers=headers
    ).json()
    assert body["rojas_ahora"] == 1 and body["ciclos_cerrados"] == 0


# ------------------------------------------------------------- tablas por X


def test_por_comprador_con_carga_abierta(client, db, entorno, tres_bandas, auth_headers):
    _sintetica(
        db,
        entorno,
        estado=Estado.EN_PROCESO,
        eventos=[(Estado.BORRADOR, Estado.ENVIADA, datetime.now(UTC) - timedelta(hours=2))],
    )
    _sintetica(
        db,
        entorno,
        estado=Estado.ENVIADA,
        comprador=entorno.otro_comprador,
        eventos=[(Estado.BORRADOR, Estado.ENVIADA, datetime.now(UTC) - timedelta(hours=1))],
    )
    r = client.get(
        "/api/v1/metricas/por-comprador", params=MARZO, headers=auth_headers(entorno.admin)
    )
    assert r.status_code == 200
    filas = {f["id"]: f for f in r.json()}
    principal = filas[entorno.comprador.id]
    assert principal["volumen"] == 3 and principal["ciclos_cerrados"] == 3
    assert principal["carga_abierta"] == 1
    assert filas[entorno.otro_comprador.id]["carga_abierta"] == 1


def test_por_cliente_cotizan_y_no_confirman(client, db, entorno, auth_headers):
    cliente_a = Cliente(nombre_normalizado="CLIENTE VOLATIL", creado_por=entorno.vendedor.id)
    cliente_b = Cliente(nombre_normalizado="CLIENTE FIEL", creado_por=entorno.vendedor.id)
    db.add_all([cliente_a, cliente_b])
    db.commit()
    # VOLATIL: 2 cotizadas → 1 no confirmada, 1 sin desenlace (ratio 0).
    _sintetica(
        db,
        entorno,
        estado=Estado.NO_CONFIRMADA,
        cliente_id=cliente_a.id,
        cotizado_en=_utc(2026, 3, 10, 12),
        motivo_no_confirmada="PRECIO",
        eventos=[(Estado.COTIZADA, Estado.NO_CONFIRMADA, _utc(2026, 3, 12, 12))],
    )
    _sintetica(
        db,
        entorno,
        estado=Estado.COTIZADA,
        cliente_id=cliente_a.id,
        cotizado_en=_utc(2026, 3, 11, 12),
    )
    # FIEL: 1 cotizada → confirmada (ratio 1.0).
    _sintetica(
        db,
        entorno,
        estado=Estado.CONFIRMADA,
        cliente_id=cliente_b.id,
        cotizado_en=_utc(2026, 3, 9, 12),
        confirmado_en=_utc(2026, 3, 10, 12),
        monto_confirmado=Decimal("800.00"),
        moneda_confirmada=Moneda.MXN,
    )
    r = client.get(
        "/api/v1/metricas/por-cliente", params=MARZO, headers=auth_headers(entorno.admin)
    )
    filas = r.json()
    # Orden: peores ratios primero ("cotizan mucho y confirman poco").
    assert [f["nombre"] for f in filas] == ["CLIENTE VOLATIL", "CLIENTE FIEL"]
    volatil, fiel = filas
    assert (volatil["cotizadas"], volatil["no_confirmadas"], volatil["sin_desenlace"]) == (2, 1, 1)
    assert volatil["ratio_confirmacion"] == 0.0
    assert fiel["ratio_confirmacion"] == 1.0
    assert fiel["dinero_confirmado"] == {"MXN": "800.00"}


def test_materiales_frecuentes(client, db, entorno, auth_headers):
    s = _sintetica(
        db,
        entorno,
        estado=Estado.ENVIADA,
        creado_en=_utc(2026, 3, 5, 12),
        eventos=[(Estado.BORRADOR, Estado.ENVIADA, _utc(2026, 3, 5, 12))],
    )
    db.add_all(
        [
            SolicitudPartida(
                solicitud_id=s.id,
                num_partida=1,
                cantidad=Decimal("1"),
                unidad="PZ",
                descripcion="solera 1/8",
                codigo_sap="205494",
            ),
            SolicitudPartida(
                solicitud_id=s.id,
                num_partida=2,
                cantidad=Decimal("2"),
                unidad="PZ",
                descripcion="SOLERA 1/8",
                codigo_sap="205494",
            ),
            SolicitudPartida(
                solicitud_id=s.id,
                num_partida=3,
                cantidad=Decimal("3"),
                unidad="PZ",
                descripcion="PLACA 1/2",
                codigo_sap=None,
            ),
        ]
    )
    db.commit()
    r = client.get("/api/v1/metricas/materiales", params=MARZO, headers=auth_headers(entorno.admin))
    body = r.json()
    assert body["por_descripcion"][0] == {"valor": "SOLERA 1/8", "conteo": 2}
    assert body["por_codigo_sap"] == [{"valor": "205494", "conteo": 2}]


# ------------------------------------------------------------------ scoping


def test_gerente_forzado_a_su_sucursal(client, db, entorno, auth_headers):
    _sintetica(
        db,
        entorno,
        estado=Estado.CONFIRMADA,
        sucursal=entorno.cuu,
        monto_confirmado=Decimal("100.00"),
        moneda_confirmada=Moneda.MXN,
        confirmado_en=_utc(2026, 3, 10, 12),
    )
    _sintetica(
        db,
        entorno,
        estado=Estado.CONFIRMADA,
        sucursal=entorno.tij,
        monto_confirmado=Decimal("200.00"),
        moneda_confirmada=Moneda.MXN,
        confirmado_en=_utc(2026, 3, 11, 12),
    )
    # El gerente pide EXPLÍCITAMENTE la sucursal ajena: recibe SOLO la suya.
    body = client.get(
        RESUMEN,
        params={**MARZO, "sucursal_id": entorno.tij.id},
        headers=auth_headers(entorno.gerente_cuu),
    ).json()
    assert body["dinero_confirmado"] == {"MXN": "100.00"}
    # El admin con el mismo filtro sí ve la otra sucursal.
    body = client.get(
        RESUMEN,
        params={**MARZO, "sucursal_id": entorno.tij.id},
        headers=auth_headers(entorno.admin),
    ).json()
    assert body["dinero_confirmado"] == {"MXN": "200.00"}


def test_vendedor_solo_lo_suyo_en_resumen(client, db, entorno, auth_headers):
    _sintetica(
        db,
        entorno,
        estado=Estado.CONFIRMADA,
        vendedor=entorno.vendedor,
        monto_confirmado=Decimal("100.00"),
        moneda_confirmada=Moneda.MXN,
        confirmado_en=_utc(2026, 3, 10, 12),
        creado_en=_utc(2026, 3, 9, 12),
    )
    _sintetica(
        db,
        entorno,
        estado=Estado.CONFIRMADA,
        vendedor=entorno.otro_vendedor,
        monto_confirmado=Decimal("900.00"),
        moneda_confirmada=Moneda.MXN,
        confirmado_en=_utc(2026, 3, 10, 12),
        creado_en=_utc(2026, 3, 9, 12),
    )
    # F14 §0b (§4.9): el vendedor YA NO recibe dinero_confirmado — el scoping
    # "solo lo suyo" se verifica con el embudo; el consolidado escopeado se
    # verifica con el gerente de la sucursal (que sí lo ve).
    body = client.get(RESUMEN, params=MARZO, headers=auth_headers(entorno.vendedor)).json()
    assert "dinero_confirmado" not in body
    assert body["embudo"] == {"CONFIRMADA": 1}  # la del otro vendedor no está
    body = client.get(RESUMEN, params=MARZO, headers=auth_headers(entorno.gerente_cuu)).json()
    assert body["dinero_confirmado"] == {"MXN": "1000.00"}  # 100 + 900, su sucursal


def test_mi_panel_solo_del_comprador(client, db, entorno, auth_headers):
    ahora = datetime.now(UTC)
    # Ciclo cerrado del comprador en el mes en curso + uno ajeno.
    _sintetica(
        db,
        entorno,
        estado=Estado.COTIZADA,
        comprador=entorno.comprador,
        cotizado_en=ahora - timedelta(minutes=30),
        eventos=[
            (Estado.BORRADOR, Estado.ENVIADA, ahora - timedelta(minutes=60)),
            (Estado.EN_PROCESO, Estado.COTIZADA, ahora - timedelta(minutes=30)),
        ],
    )
    _sintetica(
        db,
        entorno,
        estado=Estado.ENVIADA,
        comprador=entorno.comprador,
        eventos=[(Estado.BORRADOR, Estado.ENVIADA, ahora - timedelta(days=10))],
    )
    _sintetica(
        db,
        entorno,
        estado=Estado.ENVIADA,
        comprador=entorno.otro_comprador,
        eventos=[(Estado.BORRADOR, Estado.ENVIADA, ahora - timedelta(days=10))],
    )
    r = client.get("/api/v1/metricas/mi-panel", headers=auth_headers(entorno.comprador))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mes"] == ahora.strftime("%Y-%m")
    assert body["ciclos_cerrados"] == 1
    assert body["carga_abierta"] == 1  # la del otro comprador NO aparece
    assert len(body["rojas"]) == 1 and body["rojas"][0]["dias_transcurridos"] >= 3
    # Solo compradores tienen panel personal.
    assert (
        client.get("/api/v1/metricas/mi-panel", headers=auth_headers(entorno.admin)).status_code
        == 403
    )


def test_filtros_por_rol(client, db, entorno, auth_headers):
    body = client.get("/api/v1/metricas/filtros", headers=auth_headers(entorno.admin)).json()
    nombres_sucursales = [s["nombre"] for s in body["sucursales"]]
    assert "Metricas CUU" in nombres_sucursales and "Metricas TIJ" in nombres_sucursales
    assert any(c["id"] == entorno.comprador.id for c in body["compradores"])
    assert any(v["id"] == entorno.otro_vendedor.id for v in body["vendedores"])

    body = client.get("/api/v1/metricas/filtros", headers=auth_headers(entorno.gerente_cuu)).json()
    # v2 (F8c): el gerente de sucursal ya NO ve compradores (área compras).
    assert body["compradores"] is None
    # Vendedores: SOLO los de su sucursal.
    assert {v["id"] for v in body["vendedores"]} == {
        entorno.vendedor.id,
        entorno.otro_vendedor.id,
    }

    body = client.get("/api/v1/metricas/filtros", headers=auth_headers(entorno.vendedor)).json()
    assert body["sucursales"] and body["compradores"] is None and body["vendedores"] is None
