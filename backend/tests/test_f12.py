"""F12: comprobantes al comprador, notificaciones auditadas, eliminación
definitiva y fincado.

- p.1: la descarga del comprobante responde 200 a CADA rol autorizado y 404
  al vendedor ajeno (la capa rota era la UI; esto fija el backend).
- p.2: pedido_confirmado y no_confirmada al comprador ASIGNADO + el test
  MATRICIAL que fija evento → destinatarios para toda la tabla.
- p.4: eliminación definitiva exclusiva del admin (404 para el resto),
  cascada completa, bitácora inborrable, archivos fuera del disco y folio
  counter intacto.
- p.5: fincado interno del lado compras — permisos, claves ausentes en el
  JSON de ventas, solo CONFIRMADA, reversible, filtro y export sin columna.
"""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.catalogos import FamiliaMotivo, MotivoRechazo
from app.models.eliminacion import SolicitudEliminada
from app.models.notificacion import Notificacion
from app.models.solicitud import Solicitud
from app.models.sucursal import CompradorSucursal, FolioCounter
from app.models.usuario import Rol
from app.modules.archivos.service import ruta_de
from app.modules.notificaciones import service as notificaciones
from app.scheduler.jobs import job_bandas

BASE = "/api/v1/solicitudes"
CAMBIOS = "/api/v1/cambios"

PARTIDA = {"cantidad": "10", "unidad": "PZ", "descripcion": "SOLERA 1/8 X 1"}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("F12 Suc")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.add(MotivoRechazo(familia=FamiliaMotivo.FALTA_INFORMACION, texto="Falta información F12"))
    db.commit()
    motivo_id = db.scalar(
        select(MotivoRechazo.id).where(MotivoRechazo.texto == "Falta información F12")
    )
    return SimpleNamespace(
        sucursal=sucursal,
        motivo_id=motivo_id,
        comprador=comprador,
        otro_comprador=make_user(Rol.COMPRADOR),
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        otro_vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        ajeno=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gerente=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=sucursal.id),
        gerente_compras=make_user(Rol.GERENTE_COMPRAS),
        director=make_user(Rol.DIRECTOR_VENTAS),
        admin=make_user(Rol.ADMIN),
        admin2=make_user(Rol.ADMIN),
    )


def _enviada(client, entorno, auth_headers, es_proyecto=False):
    headers = auth_headers(entorno.vendedor)
    r = client.post(
        BASE,
        headers=headers,
        json={"cliente": "DINCO", "es_proyecto": es_proyecto, "partidas": [PARTIDA]},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    return sid


def _capturar_a(client, entorno, auth_headers, sid, precio="100.00"):
    headers = auth_headers(entorno.comprador)
    detalle = client.get(f"{BASE}/{sid}", headers=headers).json()
    renglones = [
        {
            "partida_id": p["id"],
            "moneda": "MXN",
            "precio_unitario": precio,
            "tiempo_entrega": "1 semana",
            "proveedor": "ACEROS SA",
        }
        for p in detalle["partidas"]
    ]
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=headers,
        json={"vigencia": "2026-12-31", "renglones": renglones},
    )
    assert r.status_code == 200, r.text
    return renglones


def _cotizada(client, entorno, auth_headers, es_proyecto=False):
    sid = _enviada(client, entorno, auth_headers, es_proyecto)
    _capturar_a(client, entorno, auth_headers, sid)
    r = client.post(f"{BASE}/{sid}/cotizar", headers=auth_headers(entorno.comprador), json={})
    assert r.status_code == 200, r.text
    return sid


def _confirmada(client, entorno, auth_headers, con_comprobante):
    sid = _cotizada(client, entorno, auth_headers)
    con_comprobante(sid, entorno.vendedor)
    r = client.post(
        f"{BASE}/{sid}/seleccionar", headers=auth_headers(entorno.vendedor), json={"letra": "A"}
    )
    assert r.status_code == 200, r.text
    return sid


# ------------------------------------------------ p.1: descarga por rol


def test_descarga_comprobante_por_cada_rol_autorizado(
    client, entorno, auth_headers, con_comprobante
):
    """El backend YA autorizaba (F8g vía obtener_scoped); esto lo deja fijado
    por CADA rol autorizado — y 404 idéntico para el vendedor ajeno."""
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.comprador)).json()
    archivo_id = detalle["comprobantes"][0]["id"]
    url = f"{BASE}/{sid}/comprobantes/{archivo_id}"

    autorizados = [
        entorno.vendedor,
        entorno.comprador,
        entorno.gerente,
        entorno.gerente_compras,
        entorno.director,
        entorno.admin,
    ]
    for usuario in autorizados:
        r = client.get(url, headers=auth_headers(usuario))
        assert r.status_code == 200, f"{usuario.rol}: {r.status_code}"
        assert r.headers["content-type"].startswith("application/pdf")

    r = client.get(url, headers=auth_headers(entorno.ajeno))
    assert r.status_code == 404
    assert r.json()["code"] == "solicitud_no_encontrada"


# ------------------------------------------- p.2: confirmada / no confirmada


def _notifs(db, tipo):
    return list(db.scalars(select(Notificacion).where(Notificacion.tipo == tipo)))


def test_confirmar_notifica_al_comprador_asignado(
    client, db, entorno, auth_headers, con_comprobante
):
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    filas = _notifs(db, notificaciones.TIPO_PEDIDO_CONFIRMADO)
    assert len(filas) == 1
    notif = filas[0]
    folio = db.scalar(select(Solicitud.folio).where(Solicitud.id == sid))
    assert notif.usuario_id == entorno.comprador.id
    assert notif.solicitud_id == sid
    assert folio in notif.mensaje
    # El monto NO viaja en la campana.
    assert "1000" not in notif.mensaje and "$" not in notif.mensaje


def test_no_confirmada_notifica_al_comprador_asignado(client, db, entorno, auth_headers):
    sid = _cotizada(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{sid}/no-confirmar",
        headers=auth_headers(entorno.vendedor),
        json={"motivo": "PRECIO"},
    )
    assert r.status_code == 200, r.text
    filas = _notifs(db, notificaciones.TIPO_NO_CONFIRMADA)
    assert len(filas) == 1
    assert filas[0].usuario_id == entorno.comprador.id
    assert "precio" in filas[0].mensaje


def test_reversion_no_confirmada_sigue_sin_notificar(client, db, entorno, auth_headers):
    """La reversión (admin) es silenciosa por diseño — que no se cuele una
    notificación de 'cotizada' ni ninguna otra al revertir."""
    sid = _cotizada(client, entorno, auth_headers)
    client.post(
        f"{BASE}/{sid}/no-confirmar",
        headers=auth_headers(entorno.vendedor),
        json={"motivo": "OTRO"},
    )
    antes = db.scalar(select(Notificacion.id).order_by(Notificacion.id.desc()).limit(1))
    r = client.post(f"{BASE}/{sid}/revertir-no-confirmada", headers=auth_headers(entorno.admin))
    assert r.status_code == 200, r.text
    despues = db.scalar(select(Notificacion.id).order_by(Notificacion.id.desc()).limit(1))
    assert antes == despues


def test_matriz_notificaciones(client, db, entorno, auth_headers, con_comprobante):
    """LA TABLA COMPLETA evento → destinatarios, fijada como dato para que
    nunca vuelva a divergir en silencio. Si agregas o quitas un destinatario,
    este test es el lugar donde esa decisión se hace explícita."""
    headers_v = auth_headers(entorno.vendedor)
    headers_c = auth_headers(entorno.comprador)

    # S1 — PROYECTO: enviar → rechazar → corregir/reenviar → editar → cotizar
    # → corregir cotización → cambio rechazado → cambio aprobado → confirmar.
    s1 = _enviada(client, entorno, auth_headers, es_proyecto=True)
    r = client.post(
        f"{BASE}/{s1}/rechazar", headers=headers_c, json={"motivo_id": entorno.motivo_id}
    )
    assert r.status_code == 200, r.text
    r = client.patch(
        f"{BASE}/{s1}",
        headers=headers_v,
        json={"cliente": "DINCO", "es_proyecto": True, "partidas": [PARTIDA]},
    )
    assert r.status_code == 200, r.text  # edición en RECHAZADA: sin notificación
    assert client.post(f"{BASE}/{s1}/enviar", headers=headers_v).status_code == 200
    r = client.patch(
        f"{BASE}/{s1}",
        headers=headers_v,
        json={"cliente": "DINCO", "es_proyecto": True, "partidas": [PARTIDA]},
    )
    assert r.status_code == 200, r.text  # edición en ENVIADA → notifica
    _capturar_a(client, entorno, auth_headers, s1)
    assert client.post(f"{BASE}/{s1}/cotizar", headers=headers_c, json={}).status_code == 200
    _capturar_a(client, entorno, auth_headers, s1, precio="110.00")  # corrección

    partida_id = client.get(f"{BASE}/{s1}", headers=headers_c).json()["partidas"][0]["id"]

    def _cambio(cantidad):
        r = client.post(
            f"{BASE}/{s1}/cambios",
            headers=headers_v,
            json={
                "partidas": [
                    {"partida_id": partida_id, "cantidad_nueva": cantidad, "unidad_nueva": "PZ"}
                ]
            },
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    cambio1 = _cambio("15")
    r = client.post(
        f"{CAMBIOS}/{cambio1}/rechazar", headers=headers_c, json={"comentario": "No procede"}
    )
    assert r.status_code == 200, r.text
    cambio2 = _cambio("25")
    assert client.post(f"{CAMBIOS}/{cambio2}/aprobar", headers=headers_c, json={}).status_code == (
        200
    )
    con_comprobante(s1, entorno.vendedor)
    r = client.post(f"{BASE}/{s1}/seleccionar", headers=headers_v, json={"letra": "A"})
    assert r.status_code == 200, r.text

    # S2 — no confirmada.
    s2 = _cotizada(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{s2}/no-confirmar", headers=headers_v, json={"motivo": "CLIENTE_DESISTIO"}
    )
    assert r.status_code == 200, r.text

    # S3 — abierta para el semáforo (S1/S2 ya están cerradas) + reasignaciones.
    s3 = _enviada(client, entorno, auth_headers)
    job_bandas(db, ahora=datetime.now(UTC) + timedelta(days=30))
    r = client.post(
        f"{BASE}/{s3}/reasignar-comprador",
        headers=auth_headers(entorno.admin),
        json={"comprador_id": entorno.otro_comprador.id},
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"{BASE}/{s3}/reasignar-vendedor",
        headers=auth_headers(entorno.admin),
        json={"vendedor_id": entorno.otro_vendedor.id},
    )
    assert r.status_code == 200, r.text

    # Seguridad: reuso de refresh → todos los admins (service directo).
    notificaciones.notificar_reuso_refresh(db, entorno.vendedor)
    db.commit()

    etiquetas = {
        entorno.comprador.id: "comprador",
        entorno.otro_comprador.id: "otro_comprador",
        entorno.vendedor.id: "vendedor",
        entorno.otro_vendedor.id: "otro_vendedor",
        entorno.gerente.id: "gerente",
        entorno.gerente_compras.id: "gcompras",
        entorno.director.id: "director",
        entorno.admin.id: "admin",
        entorno.admin2.id: "admin2",
    }
    matriz: dict[str, set[str]] = {}
    for notif in db.scalars(select(Notificacion)):
        matriz.setdefault(notif.tipo, set()).add(etiquetas[notif.usuario_id])

    assert matriz == {
        "asignacion": {"comprador"},  # envío Y reenvío: comprador titular
        "proyecto_compras": {"gcompras"},  # todos los gerente_compras activos
        "proyecto_sucursal": {"gerente"},  # gerente de LA sucursal
        "rechazo": {"vendedor"},
        "edicion": {"comprador"},  # solo en ENVIADA/EN_PROCESO
        "cotizada": {"vendedor"},
        "correccion": {"vendedor"},
        "cambio_solicitado": {"comprador", "gcompras"},
        "cambio_aprobado": {"vendedor"},  # el solicitante
        "cambio_rechazado": {"vendedor"},  # el solicitante
        "pedido_confirmado": {"comprador"},  # F12: el hueco crítico, reparado
        "no_confirmada": {"comprador"},  # F12: hueco reparado
        "banda_amarilla": {"comprador"},
        "banda_roja": {"comprador", "admin", "admin2"},
        "reasignacion": {"otro_comprador", "otro_vendedor"},  # el destino
        "seguridad": {"admin", "admin2"},
    }


# ------------------------------------------- p.4: eliminación definitiva


MOTIVO_OK = {"motivo": "Registro duplicado creado por error en el piloto"}


def test_eliminar_404_para_cada_otro_rol(client, entorno, auth_headers, con_comprobante):
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    otros = [
        entorno.vendedor,  # dueño: ni él
        entorno.ajeno,
        entorno.comprador,
        entorno.gerente,
        entorno.gerente_compras,
        entorno.director,
    ]
    for usuario in otros:
        r = client.request("DELETE", f"{BASE}/{sid}", headers=auth_headers(usuario), json=MOTIVO_OK)
        assert r.status_code == 404, f"{usuario.rol}: {r.status_code}"
        assert r.json()["code"] == "solicitud_no_encontrada"
    # Sigue viva.
    assert client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).status_code == 200


def test_eliminar_motivo_obligatorio(client, entorno, auth_headers):
    sid = _enviada(client, entorno, auth_headers)
    headers = auth_headers(entorno.admin)
    r = client.request("DELETE", f"{BASE}/{sid}", headers=headers, json={"motivo": "corto"})
    assert r.status_code == 422
    r = client.request("DELETE", f"{BASE}/{sid}", headers=headers, json={})
    assert r.status_code == 422


def test_eliminar_borrador(client, db, entorno, auth_headers):
    r = client.post(
        BASE, headers=auth_headers(entorno.vendedor), json={"cliente": "DINCO", "partidas": []}
    )
    sid = r.json()["id"]
    r = client.request(
        "DELETE", f"{BASE}/{sid}", headers=auth_headers(entorno.admin), json=MOTIVO_OK
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["folio"] is None
    assert cuerpo["estado_final"] == "BORRADOR"
    assert db.get(Solicitud, sid) is None


def test_eliminar_confirmada_cascada_completa(client, db, entorno, auth_headers, con_comprobante):
    """El caso máximo: CONFIRMADA con 2 comprobantes EN DISCO, opciones,
    cambios, notificaciones, comentarios e historial. Todo muere en una
    transacción; los archivos se van del disco; el folio no se recicla."""
    sid = _cotizada(client, entorno, auth_headers)
    con_comprobante(sid, entorno.vendedor)
    con_comprobante(sid, entorno.vendedor)
    # Un cambio rechazado, para que existan filas en solicitudes_cambio.
    partida_id = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.comprador)).json()[
        "partidas"
    ][0]["id"]
    r = client.post(
        f"{BASE}/{sid}/cambios",
        headers=auth_headers(entorno.vendedor),
        json={
            "partidas": [{"partida_id": partida_id, "cantidad_nueva": "12", "unidad_nueva": "PZ"}]
        },
    )
    cambio_id = r.json()["id"]
    client.post(
        f"{CAMBIOS}/{cambio_id}/rechazar",
        headers=auth_headers(entorno.comprador),
        json={"comentario": "no"},
    )
    r = client.post(
        f"{BASE}/{sid}/seleccionar", headers=auth_headers(entorno.vendedor), json={"letra": "A"}
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"{BASE}/{sid}/comentarios",
        headers=auth_headers(entorno.vendedor),
        json={"texto": "comentario que también debe morir"},
    )
    assert r.status_code in (200, 201), r.text

    solicitud = db.get(Solicitud, sid)
    folio = solicitud.folio
    contador_antes = db.scalar(
        select(FolioCounter.ultimo).where(FolioCounter.sucursal_id == entorno.sucursal.id)
    )
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    rutas = [ruta_de(c["id"]) for c in detalle["comprobantes"]]
    assert all(ruta.is_file() for ruta in rutas)

    r = client.request(
        "DELETE",
        f"{BASE}/{sid}",
        headers=auth_headers(entorno.admin),
        json={"motivo": "Pedido de prueba del piloto, eliminado con autorización de dirección"},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["folio"] == folio
    assert cuerpo["estado_final"] == "CONFIRMADA"
    assert cuerpo["monto_confirmado"] == "1000.00"  # 10 PZ × 100.00
    assert cuerpo["vendedor"] == entorno.vendedor.nombre
    assert cuerpo["comprador"] == entorno.comprador.nombre
    assert cuerpo["cliente"] == "DINCO"
    assert cuerpo["sucursal"] == entorno.sucursal.nombre
    assert (cuerpo["num_partidas"], cuerpo["num_opciones"], cuerpo["num_comprobantes"]) == (1, 1, 2)
    assert cuerpo["eliminado_por"] == entorno.admin.nombre
    assert cuerpo["archivos_huerfanos"] == []

    # Cero rastro en BD, archivos fuera del disco, contador intacto.
    assert db.get(Solicitud, sid) is None
    from app.models.archivo import Archivo
    from app.models.cambio import SolicitudCambio
    from app.models.comentario import Comentario
    from app.models.cotizacion import CotizacionOpcion
    from app.models.historial import HistorialEstado
    from app.models.solicitud import SolicitudPartida

    for modelo in (
        SolicitudPartida,
        CotizacionOpcion,
        HistorialEstado,
        Archivo,
        Comentario,
        SolicitudCambio,
        Notificacion,
    ):
        assert db.scalar(select(modelo).where(modelo.solicitud_id == sid).limit(1)) is None
    assert not any(ruta.is_file() for ruta in rutas)
    contador_despues = db.scalar(
        select(FolioCounter.ultimo).where(FolioCounter.sucursal_id == entorno.sucursal.id)
    )
    assert contador_despues == contador_antes

    # La bitácora quedó — y el 404 del GET del admin confirma que la
    # solicitud ya no existe por ningún camino.
    fila = db.scalar(select(SolicitudEliminada).where(SolicitudEliminada.solicitud_id == sid))
    assert fila is not None and fila.motivo.startswith("Pedido de prueba")
    assert client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).status_code == 404


def test_bitacora_solo_admin_y_sin_rutas_que_la_toquen(client, entorno, auth_headers):
    from app.main import app

    for usuario in (entorno.comprador, entorno.gerente_compras, entorno.director):
        r = client.get(f"{BASE}/eliminadas", headers=auth_headers(usuario))
        assert r.status_code == 404, f"{usuario.rol}: {r.status_code}"
    r = client.get(f"{BASE}/eliminadas", headers=auth_headers(entorno.admin))
    assert r.status_code == 200
    # Ningún camino escribe/borra la bitácora: la única operación publicada
    # sobre "eliminadas" en TODO el contrato de la API es GET.
    rutas = app.openapi()["paths"]
    metodos = {
        metodo.upper()
        for path, operaciones in rutas.items()
        if "eliminadas" in path
        for metodo in operaciones
    }
    assert metodos == {"GET"}


# ------------------------------------------------------- p.5: fincado


def test_fincada_permisos_y_claves_por_rol(client, entorno, auth_headers, con_comprobante):
    sid = _confirmada(client, entorno, auth_headers, con_comprobante)

    # Lado ventas: 403 en el PATCH y SIN claves en su JSON.
    for usuario in (entorno.vendedor, entorno.gerente, entorno.director):
        r = client.patch(
            f"{BASE}/{sid}/fincada", headers=auth_headers(usuario), json={"fincada": True}
        )
        assert r.status_code == 403, f"{usuario.rol}: {r.status_code}"
        detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(usuario)).json()
        assert not any("fincada" in clave for clave in detalle), usuario.rol
        listado = client.get(BASE, headers=auth_headers(usuario)).json()["items"]
        assert not any("fincada" in clave for item in listado for clave in item), usuario.rol

    # Comprador ASIGNADO marca; comprador ajeno ni ve la solicitud (404).
    r = client.patch(
        f"{BASE}/{sid}/fincada", headers=auth_headers(entorno.comprador), json={"fincada": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["fincada"] is True
    assert r.json()["fincada_por"] == entorno.comprador.id
    r = client.patch(
        f"{BASE}/{sid}/fincada",
        headers=auth_headers(entorno.otro_comprador),
        json={"fincada": True},
    )
    assert r.status_code == 404

    # Los tres roles autorizados la ven (detalle con nombre para el rótulo).
    for usuario in (entorno.comprador, entorno.gerente_compras, entorno.admin):
        detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(usuario)).json()
        assert detalle["fincada"] is True, usuario.rol
        assert detalle["fincada_por_nombre"] == entorno.comprador.nombre


def test_fincada_solo_confirmada_y_reversible(client, db, entorno, auth_headers, con_comprobante):
    cotizada = _cotizada(client, entorno, auth_headers)
    r = client.patch(
        f"{BASE}/{cotizada}/fincada",
        headers=auth_headers(entorno.comprador),
        json={"fincada": True},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "estado_conflicto"

    sid = _confirmada(client, entorno, auth_headers, con_comprobante)
    notifs_antes = db.scalar(select(Notificacion.id).order_by(Notificacion.id.desc()).limit(1))
    assert (
        client.patch(
            f"{BASE}/{sid}/fincada",
            headers=auth_headers(entorno.comprador),
            json={"fincada": True},
        ).status_code
        == 200
    )
    # Reversible las veces que sea; fincada_por/en son del ÚLTIMO que movió.
    r = client.patch(
        f"{BASE}/{sid}/fincada",
        headers=auth_headers(entorno.gerente_compras),
        json={"fincada": False},
    )
    assert r.status_code == 200
    assert r.json()["fincada"] is False
    assert r.json()["fincada_por"] == entorno.gerente_compras.id

    # Silencioso: sin notificaciones y sin eventos en el historial.
    notifs_despues = db.scalar(select(Notificacion.id).order_by(Notificacion.id.desc()).limit(1))
    assert notifs_antes == notifs_despues
    historial = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()[
        "historial"
    ]
    assert not any("finca" in (evento["comentario"] or "").lower() for evento in historial)


def test_fincada_filtro_y_export_sin_columna(client, entorno, auth_headers, con_comprobante):
    s1 = _confirmada(client, entorno, auth_headers, con_comprobante)
    s2 = _confirmada(client, entorno, auth_headers, con_comprobante)
    client.patch(
        f"{BASE}/{s1}/fincada", headers=auth_headers(entorno.comprador), json={"fincada": True}
    )

    headers_c = auth_headers(entorno.comprador)
    fincadas = client.get(BASE, headers=headers_c, params={"fincada": "true"}).json()["items"]
    assert [s["id"] for s in fincadas] == [s1]
    sin_fincar = client.get(
        BASE, headers=headers_c, params={"fincada": "false", "estado": "CONFIRMADA"}
    ).json()["items"]
    assert [s["id"] for s in sin_fincar] == [s2]

    # Para el lado ventas el filtro NO existe: se ignora sin filtrar nada.
    del_director = client.get(
        BASE,
        headers=auth_headers(entorno.director),
        params={"fincada": "true", "estado": "CONFIRMADA"},
    ).json()["items"]
    assert {s["id"] for s in del_director} == {s1, s2}

    # Export sin columna de fincado en esta versión (llega a Ventas).
    from openpyxl import load_workbook

    r = client.get("/api/v1/solicitudes/export", headers=auth_headers(entorno.admin))
    assert r.status_code == 200
    hoja = load_workbook(BytesIO(r.content)).active
    encabezados = [celda.value for celda in hoja[1]]
    assert not any("finca" in str(e).lower() for e in encabezados)
