"""F8e: TC del comprador al cotizar, consolidado por opción oculto al
vendedor (patrón proveedor) y roles v3 (gerente crea/envía, reasignaciones
individuales)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models.solicitud import Solicitud
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol

BASE = "/api/v1/solicitudes"

PARTIDA_PZ = {"cantidad": "20", "unidad": "PZ", "descripcion": 'ANGULO 2" X 1/4"'}
PARTIDA_KG = {"cantidad": "100", "unidad": "KG", "descripcion": "SOLERA INOX 1/4 X 2"}

CLAVES_CONSOLIDADO = ("monto_confirmado", "moneda_confirmada", "tipo_cambio")


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    suc_a = make_sucursal("F8e A")
    suc_b = make_sucursal("F8e B")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=suc_a.id, titular=True))
    db.commit()
    return SimpleNamespace(
        suc_a=suc_a,
        suc_b=suc_b,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=suc_a.id),
        otro_vendedor=make_user(Rol.VENDEDOR, sucursal_id=suc_a.id),
        vendedor_b=make_user(Rol.VENDEDOR, sucursal_id=suc_b.id),
        gsuc=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=suc_a.id),
        gcompras=make_user(Rol.GERENTE_COMPRAS),
        dventas=make_user(Rol.DIRECTOR_VENTAS),
        admin=make_user(Rol.ADMIN),
    )


def _mixta_en_proceso(client, entorno, auth_headers):
    """Solicitud con opción A mixta (12,000 MXN + 500 USD) capturada, SIN
    cotizar todavía."""
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(
        BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ, PARTIDA_KG]}
    )
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    pid_pz, pid_kg = [p["id"] for p in detalle["partidas"]]
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=auth_headers(entorno.comprador),
        json={
            "vigencia": "2026-08-31",
            "renglones": [
                {
                    "partida_id": pid_pz,
                    "moneda": "MXN",
                    "precio_unitario": "600.00",
                    "tiempo_entrega": "1 semana",
                },
                {
                    "partida_id": pid_kg,
                    "moneda": "USD",
                    "precio_unitario": "5.00",
                    "tiempo_entrega": "3 semanas",
                },
            ],
        },
    )
    assert r.status_code == 200, r.text
    return sid


# ------------------------------------------------- TC v3 en cotizar


def test_cotizar_con_usd_exige_tc_y_guarda(client, db, entorno, auth_headers):
    sid = _mixta_en_proceso(client, entorno, auth_headers)
    headers_c = auth_headers(entorno.comprador)
    # Sin TC → 422 exacto (hay USD).
    r = client.post(f"{BASE}/{sid}/cotizar", headers=headers_c)
    assert r.status_code == 422 and r.json()["code"] == "tipo_cambio_requerido"
    # Con TC → 200 y el TC queda GUARDADO desde la cotización.
    r = client.post(f"{BASE}/{sid}/cotizar", headers=headers_c, json={"tipo_cambio": "18.5"})
    assert r.status_code == 200, r.text
    assert db.scalar(select(Solicitud.tipo_cambio).where(Solicitud.id == sid)) == Decimal("18.5")


def test_consolidado_por_opcion_para_roles_autorizados(client, entorno, auth_headers):
    sid = _mixta_en_proceso(client, entorno, auth_headers)
    headers_c = auth_headers(entorno.comprador)
    assert (
        client.post(f"{BASE}/{sid}/cotizar", headers=headers_c, json={"tipo_cambio": "18.5"})
    ).status_code == 200
    # Comprador, gerente_compras, admin y gerentes de VENTAS ven el
    # consolidado POR OPCIÓN: 12,000 + 500 × 18.5 = 21,250.00.
    autorizados = (
        entorno.comprador,
        entorno.gcompras,
        entorno.admin,
        entorno.gsuc,
        entorno.dventas,
    )
    for usuario in autorizados:
        detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(usuario)).json()
        assert detalle["tipo_cambio"] == "18.5000", usuario.rol
        assert detalle["opciones"][0]["consolidado_mxn"] == "21250.00", usuario.rol
    # El vendedor: la clave NO existe (ni en la opción ni arriba).
    detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.vendedor)).json()
    assert "consolidado_mxn" not in detalle["opciones"][0]
    for clave in CLAVES_CONSOLIDADO:
        assert clave not in detalle


def test_seleccionar_datos_viejos_usd_sin_tc_422(
    client, db, entorno, auth_headers, con_comprobante
):
    sid = _mixta_en_proceso(client, entorno, auth_headers)
    headers_c = auth_headers(entorno.comprador)
    assert (
        client.post(f"{BASE}/{sid}/cotizar", headers=headers_c, json={"tipo_cambio": "18.5"})
    ).status_code == 200
    con_comprobante(sid, entorno.vendedor)  # F8g: para llegar al check del TC
    # Simula datos pre-F8e: cotizada con USD y sin TC.
    db.execute(Solicitud.__table__.update().where(Solicitud.id == sid).values(tipo_cambio=None))
    db.commit()
    r = client.post(
        f"{BASE}/{sid}/seleccionar", headers=auth_headers(entorno.vendedor), json={"letra": "A"}
    )
    assert r.status_code == 422 and r.json()["code"] == "tipo_cambio_requerido"
    assert "PATCH tipo-cambio" in r.json()["detail"]  # el mensaje guía al arreglo


# ------------------------------------------------- PATCH TC v3


def test_patch_tc_en_cotizada_por_compras(client, entorno, auth_headers, con_comprobante):
    sid = _mixta_en_proceso(client, entorno, auth_headers)
    headers_c = auth_headers(entorno.comprador)
    assert (
        client.post(f"{BASE}/{sid}/cotizar", headers=headers_c, json={"tipo_cambio": "18.5"})
    ).status_code == 200
    # Comprador ASIGNADO corrige en COTIZADA; el consolidado por opción se
    # recalcula: 12,000 + 500 × 20 = 22,000.00.
    r = client.patch(f"{BASE}/{sid}/tipo-cambio", headers=headers_c, json={"tipo_cambio": "20.0"})
    assert r.status_code == 200, r.text
    detalle = client.get(f"{BASE}/{sid}", headers=headers_c).json()
    assert detalle["opciones"][0]["consolidado_mxn"] == "22000.00"
    evento = next(
        h for h in detalle["historial"] if (h["comentario"] or "").startswith("TC corregido")
    )
    assert evento["de"] == evento["a"] == "COTIZADA"  # evento de==a
    # gerente_compras también puede (cubre al equipo).
    r = client.patch(
        f"{BASE}/{sid}/tipo-cambio",
        headers=auth_headers(entorno.gcompras),
        json={"tipo_cambio": "19.0"},
    )
    assert r.status_code == 200
    # El lado ventas NO: vendedor, gerente de sucursal y director → 403.
    for usuario in (entorno.vendedor, entorno.gsuc, entorno.dventas):
        r = client.patch(
            f"{BASE}/{sid}/tipo-cambio",
            headers=auth_headers(usuario),
            json={"tipo_cambio": "21.0"},
        )
        assert r.status_code == 403, usuario.rol
    # La selección posterior usa el TC corregido (19.0): 12,000 + 9,500.
    con_comprobante(sid, entorno.vendedor)  # F8g
    r = client.post(
        f"{BASE}/{sid}/seleccionar", headers=auth_headers(entorno.vendedor), json={"letra": "A"}
    )
    assert r.status_code == 200
    oficial = client.get(f"{BASE}/{sid}", headers=auth_headers(entorno.admin)).json()
    assert oficial["monto_confirmado"] == "21500.00"
    assert oficial["tipo_cambio"] == "19.0000"


def test_patch_tc_cotizada_cien_mxn_422(client, entorno, auth_headers):
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    headers_c = auth_headers(entorno.comprador)
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=headers_c,
        json={
            "vigencia": "2026-08-31",
            "renglones": [
                {
                    "partida_id": detalle["partidas"][0]["id"],
                    "moneda": "MXN",
                    "precio_unitario": "10.00",
                    "tiempo_entrega": "1 semana",
                }
            ],
        },
    )
    assert r.status_code == 200
    assert client.post(f"{BASE}/{sid}/cotizar", headers=headers_c).status_code == 200
    r = client.patch(f"{BASE}/{sid}/tipo-cambio", headers=headers_c, json={"tipo_cambio": "18.5"})
    assert r.status_code == 422 and r.json()["code"] == "tipo_cambio_invalido"


# ------------------------------------- ausencia de claves para el vendedor


def test_vendedor_sin_claves_de_consolidado_en_todas_las_vistas(
    client, entorno, auth_headers, con_comprobante
):
    sid = _mixta_en_proceso(client, entorno, auth_headers)
    headers_c = auth_headers(entorno.comprador)
    headers_v = auth_headers(entorno.vendedor)
    assert (
        client.post(f"{BASE}/{sid}/cotizar", headers=headers_c, json={"tipo_cambio": "18.5"})
    ).status_code == 200

    # Detalle y comparador (opciones) en COTIZADA.
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    for clave in CLAVES_CONSOLIDADO:
        assert clave not in detalle
    for opcion in detalle["opciones"]:
        assert "consolidado_mxn" not in opcion

    # Respuesta de la selección + listado y detalle en CONFIRMADA.
    con_comprobante(sid, entorno.vendedor)  # F8g
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=headers_v, json={"letra": "A"})
    assert r.status_code == 200
    for clave in CLAVES_CONSOLIDADO:
        assert clave not in r.json()
    fila = next(i for i in client.get(BASE, headers=headers_v).json()["items"] if i["id"] == sid)
    for clave in CLAVES_CONSOLIDADO:
        assert clave not in fila
    # La ganadora se ve en SUBTOTALES por moneda original (referencia).
    assert fila["referencia_mxn"] == "12000.00" and fila["referencia_usd"] == "500.00"
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    for clave in CLAVES_CONSOLIDADO:
        assert clave not in detalle
    assert detalle["referencia_mxn"] == "12000.00" and detalle["referencia_usd"] == "500.00"

    # Los demás roles SÍ ven el consolidado en el listado.
    for usuario in (entorno.gsuc, entorno.dventas, entorno.gcompras, entorno.admin):
        fila = next(
            i
            for i in client.get(BASE, headers=auth_headers(usuario)).json()["items"]
            if i["id"] == sid
        )
        assert fila["monto_confirmado"] == "21250.00", usuario.rol


# ------------------------------------------------- roles v3


def test_gerente_sucursal_crea_y_envia(client, entorno, auth_headers):
    headers_g = auth_headers(entorno.gsuc)
    r = client.post(BASE, headers=headers_g, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]})
    assert r.status_code == 201, r.text
    body = r.json()
    # Nace con vendedor_id = ÉL MISMO, en SU sucursal.
    assert body["vendedor_id"] == entorno.gsuc.id
    assert body["sucursal_id"] == entorno.suc_a.id
    sid = body["id"]
    # Envía: folio de la sucursal y comprador titular correctos.
    r = client.post(f"{BASE}/{sid}/enviar", headers=headers_g)
    assert r.status_code == 200, r.text
    assert r.json()["folio"] == f"{entorno.suc_a.prefijo_folio}-1"
    assert r.json()["comprador_id"] == entorno.comprador.id
    # Aparece en SU listado.
    assert any(i["id"] == sid for i in client.get(BASE, headers=headers_g).json()["items"])


def test_reasignacion_individual_vendedor_gerente(client, entorno, auth_headers):
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    headers_g = auth_headers(entorno.gsuc)
    # Dentro de su sucursal → 200 y evento con el ejecutor real.
    r = client.post(
        f"{BASE}/{sid}/reasignar-vendedor",
        headers=headers_g,
        json={"vendedor_id": entorno.otro_vendedor.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["vendedor_id"] == entorno.otro_vendedor.id
    # Hacia un vendedor de OTRA sucursal → 403 explícito.
    r = client.post(
        f"{BASE}/{sid}/reasignar-vendedor",
        headers=headers_g,
        json={"vendedor_id": entorno.vendedor_b.id},
    )
    assert r.status_code == 403 and r.json()["code"] == "gestion_no_permitida"
    # Una solicitud de OTRA sucursal es invisible para él → 404.
    headers_vb = auth_headers(entorno.vendedor_b)
    r = client.post(BASE, headers=headers_vb, json={"cliente": "AJENA", "partidas": [PARTIDA_PZ]})
    sid_b = r.json()["id"]
    r = client.post(
        f"{BASE}/{sid_b}/reasignar-vendedor",
        headers=headers_g,
        json={"vendedor_id": entorno.otro_vendedor.id},
    )
    assert r.status_code == 404


def test_reasignacion_individual_comprador_gcompras(client, db, entorno, make_user, auth_headers):
    otro_comprador = make_user(Rol.COMPRADOR)
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    r = client.post(
        f"{BASE}/{sid}/reasignar-comprador",
        headers=auth_headers(entorno.gcompras),
        json={"comprador_id": otro_comprador.id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["comprador_id"] == otro_comprador.id
