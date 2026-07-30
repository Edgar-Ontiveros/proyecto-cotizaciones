"""F8g: comprobante de pedido obligatorio y subsistema de archivos.

El punto del requerimiento: el pedido NO se genera sin comprobante, validado
también por API directa; la validación de formato es por MAGIC BYTES del
contenido, nunca por extensión ni content-type del cliente.
"""

from io import BytesIO
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect, select

from app.models.archivo import Archivo
from app.models.usuario import Rol
from app.modules.archivos import service as archivos
from app.modules.archivos.service import pdf_minimo

BASE = "/api/v1/solicitudes"
PARTIDA = {"cantidad": "2", "unidad": "PZ", "descripcion": "PTR 2X2"}

# Contenidos de prueba (magic bytes reales).
PDF = pdf_minimo()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBP" + b"\x00" * 32
EXE = b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 32  # ejecutable renombrado
TEXTO = b"esto no es un pdf aunque el nombre lo diga"


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    from app.models.sucursal import CompradorSucursal

    sucursal = make_sucursal("F8g Suc")
    otra = make_sucursal("F8g Otra")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        otra=otra,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gerente=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=sucursal.id),
        director=make_user(Rol.DIRECTOR_VENTAS),
        gerente_compras=make_user(Rol.GERENTE_COMPRAS),
        admin=make_user(Rol.ADMIN),
        ajeno=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
    )


def _cotizada(client, entorno, auth_headers):
    """Solicitud del vendedor llevada a COTIZADA por el comprador (API real)."""
    headers = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers, json={"cliente": "DINCO", "partidas": [PARTIDA]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    headers_c = auth_headers(entorno.comprador)
    detalle = client.get(f"{BASE}/{sid}", headers=headers_c).json()
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=headers_c,
        json={
            "vigencia": "2026-09-30",
            "renglones": [
                {
                    "partida_id": p["id"],
                    "moneda": "MXN",
                    "precio_unitario": "100.00",
                    "tiempo_entrega": "1 semana",
                }
                for p in detalle["partidas"]
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert client.post(f"{BASE}/{sid}/cotizar", headers=headers_c).status_code == 200
    return sid


def _subir(client, headers, sid, contenido=PDF, nombre="comprobante.pdf", mime="application/pdf"):
    return client.post(
        f"{BASE}/{sid}/comprobante",
        headers=headers,
        files={"archivo": (nombre, BytesIO(contenido), mime)},
    )


# ------------------------------------------------------- validación de contenido


def test_exe_renombrado_a_pdf_da_422(client, entorno, auth_headers):
    """Un .exe con nombre y content-type de PDF NO pasa: la validación es por
    magic bytes del contenido, no por lo que declare el cliente."""
    sid = _cotizada(client, entorno, auth_headers)
    r = _subir(client, auth_headers(entorno.vendedor), sid, EXE, "factura.pdf")
    assert r.status_code == 422 and r.json()["code"] == "archivo_invalido"


def test_texto_con_extension_pdf_da_422(client, entorno, auth_headers):
    sid = _cotizada(client, entorno, auth_headers)
    r = _subir(client, auth_headers(entorno.vendedor), sid, TEXTO, "comprobante.pdf")
    assert r.status_code == 422 and r.json()["code"] == "archivo_invalido"


def test_formatos_validos_por_contenido(client, entorno, auth_headers):
    """PDF, JPG, PNG y WebP pasan y el MIME guardado es el DETECTADO (el
    content-type mentiroso del cliente se ignora)."""
    casos = [
        (PDF, "application/pdf"),
        (JPG, "image/jpeg"),
        (PNG, "image/png"),
        (WEBP, "image/webp"),
    ]
    headers = auth_headers(entorno.vendedor)
    for contenido, mime_esperado in casos:
        sid = _cotizada(client, entorno, auth_headers)
        r = _subir(client, headers, sid, contenido, "archivo.bin", "application/octet-stream")
        assert r.status_code == 200, r.text
        assert r.json()["mime"] == mime_esperado


def test_mas_de_10_mb_rechazo_claro(client, entorno, auth_headers):
    sid = _cotizada(client, entorno, auth_headers)
    gigante = b"%PDF" + b"\x00" * (10 * 1024 * 1024)  # 10 MB + 4 bytes
    r = _subir(client, auth_headers(entorno.vendedor), sid, gigante)
    assert r.status_code == 413 and r.json()["code"] == "archivo_demasiado_grande"


def test_nombre_original_sanitizado(client, entorno, auth_headers):
    # Unidad: rutas, control chars y caracteres problemáticos fuera.
    assert archivos.sanitizar_nombre('../../etc/pa"sswd;\x01.pdf') == "passwd.pdf"
    assert archivos.sanitizar_nombre("C:\\Users\\x\\orden.pdf") == "orden.pdf"
    assert archivos.sanitizar_nombre(None) == "comprobante"
    assert len(archivos.sanitizar_nombre("a" * 500 + ".pdf")) == 140
    # API: el path traversal no sobrevive al guardado.
    sid = _cotizada(client, entorno, auth_headers)
    r = _subir(client, auth_headers(entorno.vendedor), sid, PDF, "../../etc/orden final.pdf")
    assert r.status_code == 200
    assert r.json()["nombre_original"] == "orden final.pdf"


# ------------------------------------------------------------ estados y permisos


def test_subir_en_estado_invalido(client, entorno, auth_headers):
    headers = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers, json={"cliente": "DINCO", "partidas": [PARTIDA]})
    sid = r.json()["id"]
    # BORRADOR → 409 con el estado real.
    r = _subir(client, headers, sid)
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"
    # ENVIADA → 409 también (solo COTIZADA acepta).
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers).status_code == 200
    r = _subir(client, headers, sid)
    assert r.status_code == 409 and r.json()["code"] == "estado_conflicto"


def test_comprador_no_sube_comprobante(client, entorno, auth_headers):
    """El comprobante es del lado ventas (quienes confirman); el comprador
    asignado VE la solicitud pero no puede subirlo."""
    sid = _cotizada(client, entorno, auth_headers)
    r = _subir(client, auth_headers(entorno.comprador), sid)
    assert r.status_code == 403


# ----------------------------------------------------------------- la regla dura


def test_confirmar_sin_comprobante_422_por_api_directa(client, entorno, auth_headers):
    """EL punto del requerimiento: POST /seleccionar sin comprobante → 422
    comprobante_requerido, aunque el frontend se salte."""
    sid = _cotizada(client, entorno, auth_headers)
    r = client.post(
        f"{BASE}/{sid}/seleccionar", headers=auth_headers(entorno.vendedor), json={"letra": "A"}
    )
    assert r.status_code == 422 and r.json()["code"] == "comprobante_requerido"


def test_confirmar_con_comprobante_y_archivo_persiste(client, db, entorno, auth_headers):
    sid = _cotizada(client, entorno, auth_headers)
    headers = auth_headers(entorno.vendedor)
    r = _subir(client, headers, sid, PDF, "orden-compra.pdf")
    assert r.status_code == 200
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=headers, json={"letra": "A"})
    assert r.status_code == 200 and r.json()["estado"] == "CONFIRMADA"
    archivo = db.scalar(select(Archivo).where(Archivo.solicitud_id == sid))
    assert archivo is not None
    assert archivos.ruta_de(archivo.id).read_bytes() == PDF
    # El detalle expone los metadatos (nombre, quién, cuándo).
    detalle = client.get(f"{BASE}/{sid}", headers=headers).json()
    assert detalle["comprobante"]["nombre_original"] == "orden-compra.pdf"
    assert detalle["comprobante"]["subido_por"] == entorno.vendedor.id


def test_gerente_confirmando_tambien_exige_comprobante(client, entorno, auth_headers):
    """La regla es de la TRANSICIÓN, no del rol: el gerente de la sucursal
    tampoco confirma sin comprobante — y con él, sí."""
    sid = _cotizada(client, entorno, auth_headers)
    headers_g = auth_headers(entorno.gerente)
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=headers_g, json={"letra": "A"})
    assert r.status_code == 422 and r.json()["code"] == "comprobante_requerido"
    assert _subir(client, headers_g, sid).status_code == 200
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=headers_g, json={"letra": "A"})
    assert r.status_code == 200 and r.json()["estado"] == "CONFIRMADA"


# ------------------------------------------------------------ reemplazo e inmutable


def test_reemplazo_pre_confirmacion(client, db, entorno, auth_headers):
    """Re-subir antes de confirmar REEMPLAZA: fila sustituida, archivo viejo
    fuera del disco y evento de==a 'Comprobante actualizado'."""
    sid = _cotizada(client, entorno, auth_headers)
    headers = auth_headers(entorno.vendedor)
    primero = _subir(client, headers, sid, PDF, "v1.pdf").json()
    ruta_primero = archivos.ruta_de(primero["id"])
    assert ruta_primero.is_file()

    segundo = _subir(client, headers, sid, PNG, "v2.png").json()
    assert segundo["id"] != primero["id"]
    assert not ruta_primero.exists()  # el viejo se fue del disco
    assert archivos.ruta_de(segundo["id"]).read_bytes() == PNG
    filas = db.scalars(select(Archivo).where(Archivo.solicitud_id == sid)).all()
    assert len(filas) == 1 and filas[0].nombre_original == "v2.png"

    historial = client.get(f"{BASE}/{sid}", headers=headers).json()["historial"]
    eventos = [h["comentario"] for h in historial if h["de"] == h["a"]]
    assert "Comprobante cargado (v1.pdf)" in eventos
    assert "Comprobante actualizado" in eventos


def test_tras_confirmada_es_inmutable(client, entorno, auth_headers):
    sid = _cotizada(client, entorno, auth_headers)
    headers = auth_headers(entorno.vendedor)
    assert _subir(client, headers, sid).status_code == 200
    r = client.post(f"{BASE}/{sid}/seleccionar", headers=headers, json={"letra": "A"})
    assert r.status_code == 200
    r = _subir(client, headers, sid, PNG, "otro.png")
    assert r.status_code == 409 and r.json()["code"] == "comprobante_inmutable"


# ------------------------------------------------------------------- descarga


def test_descarga_por_cada_rol_permitido_y_404_para_ajeno(client, entorno, auth_headers):
    """Descargan TODOS los involucrados: dueño, gerente de la sucursal,
    director, comprador asignado, gerente_compras y admin. Un vendedor ajeno
    (misma sucursal) recibe el mismo 404 del scoping."""
    sid = _cotizada(client, entorno, auth_headers)
    assert _subir(client, auth_headers(entorno.vendedor), sid, PDF, "orden.pdf").status_code == 200

    permitidos = [
        entorno.vendedor,
        entorno.gerente,
        entorno.director,
        entorno.comprador,
        entorno.gerente_compras,
        entorno.admin,
    ]
    for usuario in permitidos:
        r = client.get(f"{BASE}/{sid}/comprobante", headers=auth_headers(usuario))
        assert r.status_code == 200, f"{usuario.rol}: {r.text}"
        assert r.content == PDF
        assert 'filename="orden.pdf"' in r.headers["content-disposition"]
        assert r.headers["content-type"].startswith("application/pdf")

    r = client.get(f"{BASE}/{sid}/comprobante", headers=auth_headers(entorno.ajeno))
    assert r.status_code == 404


def test_descarga_sin_comprobante_404(client, entorno, auth_headers):
    sid = _cotizada(client, entorno, auth_headers)
    r = client.get(f"{BASE}/{sid}/comprobante", headers=auth_headers(entorno.vendedor))
    assert r.status_code == 404 and r.json()["code"] == "comprobante_no_encontrado"


# --------------------------------------------------------- compatibilidad y pdf


def test_confirmadas_previas_sin_archivo_siguen_validas(client, db, entorno, auth_headers):
    """La regla es del flujo NUEVO: una CONFIRMADA histórica sin comprobante
    no se invalida — su detalle sirve y comprobante viene null."""
    sid = _cotizada(client, entorno, auth_headers)
    headers = auth_headers(entorno.vendedor)
    assert _subir(client, headers, sid).status_code == 200
    assert (
        client.post(f"{BASE}/{sid}/seleccionar", headers=headers, json={"letra": "A"}).status_code
        == 200
    )
    # Simula la histórica: se borra la fila del archivo (pre-F8g no existía).
    db.execute(Archivo.__table__.delete().where(Archivo.solicitud_id == sid))
    db.commit()
    detalle = client.get(f"{BASE}/{sid}", headers=headers).json()
    assert detalle["estado"] == "CONFIRMADA" and detalle["comprobante"] is None


def test_pdf_minimo_es_pdf_valido():
    contenido = pdf_minimo()
    assert contenido.startswith(b"%PDF-1.4")
    assert contenido.rstrip().endswith(b"%%EOF")
    assert len(contenido) < 2048
    assert archivos.detectar_mime(contenido) == "application/pdf"


# ------------------------------------------------------------------- migración


def test_migracion_up_down():
    """TODA la cadena de migraciones baja y sube limpia (head → base → head)
    en una BD scratch aparte — cubre el downgrade de archivos (F8g) y de
    cambios (F8h) sin depender de cuál sea la head vigente."""
    from alembic.config import Config
    from sqlalchemy import create_engine

    from alembic import command
    from tests.conftest import (
        BACKEND_DIR,
        _url,
        alembic_upgrade_head,
        drop_database,
        recreate_database,
    )

    nombre = "cotizaciones_test_migracion_f8g"
    recreate_database(nombre)
    try:
        alembic_upgrade_head(nombre)
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        cfg.set_main_option(
            "sqlalchemy.url", _url.set(database=nombre).render_as_string(hide_password=False)
        )
        engine = create_engine(_url.set(database=nombre))

        def tablas() -> set[str]:
            with engine.connect() as conn:
                return set(inspect(conn).get_table_names())

        assert {"archivos", "solicitudes_cambio", "cambio_partidas"} <= tablas()
        command.downgrade(cfg, "base")
        restantes = tablas()
        assert "archivos" not in restantes and "solicitudes_cambio" not in restantes
        assert restantes <= {"alembic_version"}
        command.upgrade(cfg, "head")
        assert {"archivos", "solicitudes_cambio", "cambio_partidas"} <= tablas()
        engine.dispose()
    finally:
        drop_database(nombre)
