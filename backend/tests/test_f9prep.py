"""F9-prep: filtro del historial de TC para el lado ventas y seed de
producción."""

import inspect
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.cli.seed import PASSWORD_DEFAULT
from app.cli.seed_produccion import _plantilla_completa, generar_emails
from app.cli.seed_produccion import run as seed_produccion
from app.core.security import verify_password
from app.models.solicitud import Solicitud
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario

BASE = "/api/v1/solicitudes"

PARTIDA_PZ = {"cantidad": "20", "unidad": "PZ", "descripcion": 'ANGULO 2" X 1/4"'}
PARTIDA_KG = {"cantidad": "100", "unidad": "KG", "descripcion": "SOLERA INOX 1/4 X 2"}


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("F9p")
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=comprador,
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        gsuc=make_user(Rol.GERENTE_SUCURSAL, sucursal_id=sucursal.id),
        gcompras=make_user(Rol.GERENTE_COMPRAS),
        dventas=make_user(Rol.DIRECTOR_VENTAS),
        admin=make_user(Rol.ADMIN),
    )


# ------------------------------------------- filtro del historial (punto 1)


def test_historial_tc_redactado_para_ventas(client, entorno, auth_headers):
    """El evento de corrección de TC es visible para TODOS, pero su comentario
    solo llega completo al área compras y admin; el lado ventas ve 'Ajuste
    administrativo'."""
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(
        BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ, PARTIDA_KG]}
    )
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    pid_pz, pid_kg = [p["id"] for p in detalle["partidas"]]
    headers_c = auth_headers(entorno.comprador)
    r = client.put(
        f"{BASE}/{sid}/opciones/A",
        headers=headers_c,
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
    r = client.post(f"{BASE}/{sid}/cotizar", headers=headers_c, json={"tipo_cambio": "18.5"})
    assert r.status_code == 200, r.text
    r = client.patch(f"{BASE}/{sid}/tipo-cambio", headers=headers_c, json={"tipo_cambio": "20.0"})
    assert r.status_code == 200, r.text

    def evento_de(usuario):
        detalle = client.get(f"{BASE}/{sid}", headers=auth_headers(usuario)).json()
        # El evento (de==a COTIZADA) SIEMPRE es visible para todos.
        return next(
            h for h in detalle["historial"] if h["de"] == "COTIZADA" and h["a"] == "COTIZADA"
        )

    # Compras y admin: comentario COMPLETO.
    for usuario in (entorno.comprador, entorno.gcompras, entorno.admin):
        assert evento_de(usuario)["comentario"] == "TC corregido de 18.5000 a 20.0", usuario.rol
    # Lado ventas: REDACTADO — misma solicitud, mismo evento.
    for usuario in (entorno.vendedor, entorno.gsuc, entorno.dventas):
        assert evento_de(usuario)["comentario"] == "Ajuste administrativo", usuario.rol


def test_historial_eventos_normales_sin_redactar(client, entorno, auth_headers):
    """Un evento de==a normal (edición del vendedor) NO se redacta."""
    headers_v = auth_headers(entorno.vendedor)
    r = client.post(BASE, headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]})
    sid = r.json()["id"]
    assert client.post(f"{BASE}/{sid}/enviar", headers=headers_v).status_code == 200
    r = client.patch(
        f"{BASE}/{sid}", headers=headers_v, json={"cliente": "DINCO", "partidas": [PARTIDA_PZ]}
    )
    assert r.status_code == 200
    detalle = client.get(f"{BASE}/{sid}", headers=headers_v).json()
    edicion = next(h for h in detalle["historial"] if h["de"] == h["a"] == "ENVIADA")
    assert edicion["comentario"] == "Solicitud editada por el vendedor"


# ------------------------------------------- seed de producción (punto 4)


def test_seed_produccion_plantilla_completa(db):
    """Mini-fase v2: 4 directivos + 9 gerentes + 35 vendedores + 6
    compradores = 54, con titularidades reales y CERO cuentas demo."""
    conteos = seed_produccion(db)
    assert conteos == {
        "sucursales": 11,
        "motivos_rechazo": 5,
        "dias_festivos": 14,
        "directivos": 4,
        "gerentes_sucursal": 9,
        "vendedores": 35,
        "compradores": 6,
        "usuarios_creados": 54,
        "titularidades_creadas": 11,
    }

    # Contadores de folio EN CERO en las 11 sucursales.
    contadores = list(db.scalars(select(FolioCounter.ultimo)))
    assert len(contadores) == 11 and all(u == 0 for u in contadores)

    # 54 usuarios exactos; todos con la temporal FIJA y cambio forzado.
    usuarios = list(db.scalars(select(Usuario)))
    assert len(usuarios) == 54
    assert all(u.must_change_password and u.activo for u in usuarios)
    assert all(verify_password(PASSWORD_DEFAULT, u.password_hash) for u in usuarios)
    por_rol = {rol: sum(1 for u in usuarios if u.rol == rol) for rol in Rol}
    assert por_rol[Rol.ADMIN] == 2
    assert por_rol[Rol.DIRECTOR_VENTAS] == 1
    assert por_rol[Rol.GERENTE_COMPRAS] == 1
    assert por_rol[Rol.GERENTE_SUCURSAL] == 9
    assert por_rol[Rol.VENDEDOR] == 35
    assert por_rol[Rol.COMPRADOR] == 6
    # Gerentes y vendedores con SU sucursal; ningún correo demo.
    assert all(
        u.sucursal_id is not None for u in usuarios if u.rol in (Rol.GERENTE_SUCURSAL, Rol.VENDEDOR)
    )
    assert all(u.email.endswith("@herinox.com.mx") for u in usuarios)
    assert not any("demo" in u.email for u in usuarios)

    # Titularidades reales por comprador (titular en TODO su territorio).
    esperadas = {
        "nvictor@herinox.com.mx": {"Cd. Juárez", "Hermosillo"},
        "olopez@herinox.com.mx": {"León"},
        "mmonarrez@herinox.com.mx": {"Matriz", "Manufactura"},
        "hruelas@herinox.com.mx": {"Mexicali", "Culiacán", "Obregón"},
        "imata@herinox.com.mx": {"TIK", "Norte"},
        "fflores@herinox.com.mx": {"Monterrey"},
    }
    sucursales = {s.id: s.nombre for s in db.scalars(select(Sucursal))}
    compradores = {u.id: u.email for u in usuarios if u.rol == Rol.COMPRADOR}
    reales: dict[str, set[str]] = {}
    for cs in db.scalars(select(CompradorSucursal).where(CompradorSucursal.titular)):
        reales.setdefault(compradores[cs.comprador_id], set()).add(sucursales[cs.sucursal_id])
    assert reales == esperadas

    # Cero solicitudes.
    assert db.scalar(select(func.count()).select_from(Solicitud)) == 0


def test_regla_de_correos_acentos_enie_y_colision():
    emails = generar_emails(_plantilla_completa())
    # Ejemplo canónico de la regla.
    assert emails["Maribel Rocha"] == "mrocha@herinox.com.mx"
    # Acentos fuera: Fabián → f…, López → lopez.
    assert emails["Fabián Flores"] == "fflores@herinox.com.mx"
    assert emails["Oscar López"] == "olopez@herinox.com.mx"
    # ñ→n: Alonso Muñoz → amunoz.
    assert emails["Alonso Muñoz"] == "amunoz@herinox.com.mx"
    # PRIMER apellido en nombres largos (dato explícito, no posición).
    assert emails["Abraham Arturo Prado Hernandez"] == "aprado@herinox.com.mx"
    assert emails["Gloria de la Luz Murillo"] == "gmurillo@herinox.com.mx"
    # En la plantilla real NO hay colisiones: 50 correos únicos (9+6+35).
    assert len(set(emails.values())) == len(emails) == 50

    # Colisión SINTÉTICA: el segundo usa las DOS primeras letras del nombre.
    sinteticos = generar_emails(["Ana Prueba", "Alberto Prueba"])
    assert sinteticos["Ana Prueba"] == "aprueba@herinox.com.mx"
    assert sinteticos["Alberto Prueba"] == "alprueba@herinox.com.mx"
    # Doble colisión: se reporta, no se inventa.
    with pytest.raises(RuntimeError, match="Colisión doble"):
        generar_emails(["Ana Prueba", "Alba Prueba", "Alma Prueba"])
    # Nombre largo sin regla de apellido: igual — se pregunta.
    with pytest.raises(RuntimeError, match="ambiguo"):
        generar_emails(["Juan Carlos Perez Gomez Extra"])


def test_seed_produccion_sin_flag_ni_cuentas_demo(db):
    """El flag --con-demo NO existe y ninguna corrida crea cuentas demo."""
    import app.cli.seed_produccion as modulo

    assert "con_demo" not in inspect.signature(seed_produccion).parameters
    assert not hasattr(modulo, "USUARIOS_DEMO")
    with pytest.raises(TypeError):
        seed_produccion(db, con_demo=True)  # type: ignore[call-arg]
    seed_produccion(db)
    demos = list(db.scalars(select(Usuario).where(Usuario.email.ilike("%demo%"))))
    assert demos == []


def test_seed_produccion_idempotente_sin_pisar_passwords(db):
    primera = seed_produccion(db)
    assert primera["usuarios_creados"] == 54
    # Simula que una vendedora ya cambió su contraseña.
    maribel = db.scalar(select(Usuario).where(Usuario.email == "mrocha@herinox.com.mx"))
    assert maribel is not None
    maribel.password_hash = "hash-cambiado-por-la-usuaria"
    maribel.must_change_password = False
    db.commit()

    conteos = seed_produccion(db)
    # Segunda corrida: nada nuevo y la contraseña cambiada queda INTACTA.
    assert conteos["usuarios_creados"] == 0 and conteos["titularidades_creadas"] == 0
    assert db.scalar(select(func.count()).select_from(Usuario)) == 54
    assert db.scalar(select(func.count()).select_from(CompradorSucursal)) == 11
    db.refresh(maribel)
    assert maribel.password_hash == "hash-cambiado-por-la-usuaria"
    assert maribel.must_change_password is False
