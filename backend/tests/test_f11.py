"""F11 — lote del piloto.

p.2/p.3a: el catálogo de motivos vive en /api/v1/motivos-rechazo (SIN
/catalogos: el frontend llamaba a un prefijo inexistente y el 404 dejaba el
modal de rechazo sin motivos y las altas del admin muertas). Aquí el flujo
completo: alta del motivo → uso inmediato en un rechazo → RECHAZADA +
notificación al vendedor.

p.3b: un festivo recién dado de alta cambia las horas hábiles y la banda de
los ciclos EN LA MISMA lectura (festivos_de lee BD por request, sin caché).

p.4: el semáforo tiene UNA sola fuente de verdad (el último ciclo, abierto o
cerrado): detalle, listado y distribución del dashboard deben COINCIDIR para
la misma solicitud, con el ciclo abierto en amarillo y también ya cerrado.
Calendario fijo del caso festivo (marzo 2026): 02=lun, 03=mar, 04=mié.
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.core.horario_habil import dias_habiles_transcurridos
from app.models.historial import HistorialEstado
from app.models.notificacion import Notificacion
from app.models.solicitud import Estado
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol

BASE = "/api/v1/solicitudes"
MOTIVOS = "/api/v1/motivos-rechazo"
FESTIVOS = "/api/v1/dias-festivos"
RESUMEN = "/api/v1/metricas/resumen"
TZ = "America/Chihuahua"  # default del factory de sucursales


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("F11 Suc")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        admin=make_user(Rol.ADMIN),
    )


def _enviada(client, entorno, auth_headers):
    headers = auth_headers(entorno.vendedor)
    r = client.post(
        BASE,
        headers=headers,
        json={
            "cliente": "F11",
            "partidas": [{"cantidad": "5", "unidad": "PZ", "descripcion": "PTR 2x2"}],
        },
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    return sid


def _mover_apertura(db, sid, apertura):
    """Retrocede el evento →ENVIADA (la apertura del ciclo es el historial,
    nunca la columna enviado_en — pero se mueve también por coherencia)."""
    db.execute(
        update(HistorialEstado)
        .where(HistorialEstado.solicitud_id == sid, HistorialEstado.a == Estado.ENVIADA)
        .values(timestamp=apertura)
    )
    db.commit()


# ------------------------------------------------- p.2/p.3a: motivos+rechazo


def test_alta_de_motivo_y_uso_inmediato_en_rechazo(client, db, entorno, auth_headers):
    """El flujo que el 404 de /catalogos rompía de punta a punta: el admin da
    de alta el motivo, el comprador lo ve en el catálogo y rechaza con él →
    RECHAZADA con motivo en historial y notificación al vendedor."""
    r = client.post(
        MOTIVOS,
        headers=auth_headers(entorno.admin),
        json={"familia": "no_procede", "texto": "Material descontinuado F11"},
    )
    assert r.status_code == 201, r.text
    motivo_id = r.json()["id"]

    # El comprador (cualquier autenticado) ve el motivo nuevo en el catálogo.
    headers_c = auth_headers(entorno.comprador)
    catalogo = client.get(MOTIVOS, headers=headers_c).json()
    assert any(m["id"] == motivo_id for m in catalogo)

    sid = _enviada(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{sid}/rechazar",
        headers=headers_c,
        json={"motivo_id": motivo_id, "comentario": "Ya no se fabrica"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "RECHAZADA"

    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()
    assert detalle["estado"] == "RECHAZADA"
    rechazo = next(h for h in detalle["historial"] if h["a"] == "RECHAZADA")
    assert rechazo["motivo_texto"] == "Material descontinuado F11"
    notif = db.scalars(
        select(Notificacion).where(Notificacion.usuario_id == entorno.vendedor.id)
    ).all()
    assert any(n.tipo == "rechazo" and "Material descontinuado F11" in n.mensaje for n in notif)


# ------------------------------------------------------ p.3b: festivo nuevo


def test_festivo_nuevo_afecta_horas_habiles(client, db, entorno, auth_headers):
    """Ciclo cerrado lun 02-mar 09:00 → mié 04-mar 09:00 local: 20.0 h
    hábiles, T=2 (NORMAL). El alta del festivo martes 03 lo deja en 10.0 h,
    T=1 (ESPERADA) en la SIGUIENTE lectura — sin reinicios ni cachés."""
    sid = _enviada(client, entorno, auth_headers)
    headers_c = auth_headers(entorno.comprador)
    detalle = client.get(f"{BASE}/{sid}", headers=headers_c).json()
    pid = detalle["partidas"][0]["id"]
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=headers_c,
        json={
            "vigencia": "2026-08-31",
            "renglones": [
                {
                    "partida_id": pid,
                    "moneda": "MXN",
                    "precio_unitario": "10.00",
                    "tiempo_entrega": "1 semana",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert client.post(f"{BASE}/{sid}/cotizar", headers=headers_c).status_code == 200

    apertura = datetime(2026, 3, 2, 15, 0, tzinfo=UTC)  # lun 09:00 local
    cierre = datetime(2026, 3, 4, 15, 0, tzinfo=UTC)  # mié 09:00 local
    _mover_apertura(db, sid, apertura)
    db.execute(
        update(HistorialEstado)
        .where(HistorialEstado.solicitud_id == sid, HistorialEstado.a == Estado.COTIZADA)
        .values(timestamp=cierre)
    )
    db.commit()

    detalle = client.get(f"{BASE}/{sid}", headers=headers_c).json()
    assert detalle["banda"] == "NORMAL"
    assert detalle["horas_habiles"] == 20.0 and detalle["dias_transcurridos"] == 2

    r = client.post(
        FESTIVOS,
        headers=auth_headers(entorno.admin),
        json={"fecha": "2026-03-03", "descripcion": "Festivo F11"},
    )
    assert r.status_code == 201, r.text

    detalle = client.get(f"{BASE}/{sid}", headers=headers_c).json()
    assert detalle["banda"] == "ESPERADA"
    assert detalle["horas_habiles"] == 10.0 and detalle["dias_transcurridos"] == 1


# --------------------------------------------------- p.4: semáforo unificado


def _apertura_con_t(objetivo: int) -> datetime:
    """Instante de apertura (09:00 local de un día hábil pasado) cuyo T actual
    es `objetivo`, calculado con la MISMA aritmética de horario_habil."""
    ahora = datetime.now(UTC)
    for dias_atras in range(1, 15):
        candidato = (ahora - timedelta(days=dias_atras)).astimezone(UTC)
        candidato = candidato.replace(hour=15, minute=0, second=0, microsecond=0)
        if dias_habiles_transcurridos(candidato, ahora, TZ, frozenset()) == objetivo:
            return candidato
    raise AssertionError(f"sin apertura con T={objetivo} en 14 días")


def _tres_lecturas(client, entorno, auth_headers, sid):
    """(detalle, listado, distribución) — las tres vistas del semáforo."""
    headers_v = auth_headers(entorno.vendedor)
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    fila = next(
        i
        for i in client.get(BASE, headers=headers_v, params={"limit": 100}).json()["items"]
        if i["id"] == sid
    )
    hoy = date.today()
    resumen = client.get(
        RESUMEN,
        headers=auth_headers(entorno.admin),
        params={"desde": str(hoy - timedelta(days=30)), "hasta": str(hoy)},
    ).json()
    return detalle, fila, resumen["distribucion_bandas"]


def test_semaforo_coincide_en_detalle_listado_y_dashboard(client, db, entorno, auth_headers):
    """La regresión del piloto: una solicitud en banda amarilla DEBE verse
    amarilla en las TRES lecturas — abierta (T=2) y también después de
    cotizarse (ciclo cerrado NORMAL)."""
    sid = _enviada(client, entorno, auth_headers)
    _mover_apertura(db, sid, _apertura_con_t(2))

    # ABIERTA en amarillo: antes del fix la distribución la ignoraba (solo
    # contaba ciclos cerrados y rojas_ahora exige t>=3).
    detalle, fila, distribucion = _tres_lecturas(client, entorno, auth_headers, sid)
    assert detalle["estado"] == "ENVIADA"
    assert detalle["banda"] == "NORMAL" == fila["banda"]
    assert distribucion["NORMAL"] >= 1

    # Cerrada en amarillo (cotizada hoy, mismo T): antes del fix detalle y
    # listado pasaban a null y solo el dashboard la contaba.
    headers_c = auth_headers(entorno.comprador)
    pid = client.get(f"{BASE}/{sid}", headers=headers_c).json()["partidas"][0]["id"]
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=headers_c,
        json={
            "vigencia": "2026-12-31",
            "renglones": [
                {
                    "partida_id": pid,
                    "moneda": "MXN",
                    "precio_unitario": "10.00",
                    "tiempo_entrega": "1 semana",
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert client.post(f"{BASE}/{sid}/cotizar", headers=headers_c).status_code == 200

    detalle, fila, distribucion = _tres_lecturas(client, entorno, auth_headers, sid)
    assert detalle["estado"] == "COTIZADA"
    assert detalle["banda"] == "NORMAL" == fila["banda"]
    assert distribucion["NORMAL"] >= 1
