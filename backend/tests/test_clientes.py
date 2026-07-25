import threading

from app.models.cliente import Cliente
from app.models.usuario import Rol, Usuario
from app.modules.clientes.service import normalizar, obtener_o_crear


def test_normalizar():
    assert normalizar("  dinco  ") == "DINCO"
    assert normalizar("aceros   lópez") == "ACEROS LÓPEZ"  # acentos intactos


def test_obtener_o_crear_mismo_id(db, make_user, make_sucursal):
    vendedor = make_user(Rol.VENDEDOR, sucursal_id=make_sucursal().id)
    c1 = obtener_o_crear(db, "  dinco  ", vendedor)
    c2 = obtener_o_crear(db, "DINCO", vendedor)
    assert c1.id == c2.id
    assert c1.nombre_normalizado == "DINCO"


def test_alta_concurrente_un_solo_cliente(db):
    """Addendum b: N altas simultáneas del mismo nombre → UN solo cliente y
    cero errores (INSERT ... ON CONFLICT DO NOTHING + re-select).

    Hilos con sesiones reales fuera del aislamiento por savepoints; limpieza
    manual (patrón del test de concurrencia de folios)."""
    from app.core.database import SessionLocal
    from app.core.security import hash_password

    setup = SessionLocal()
    vendedor = Usuario(
        nombre="Race Clientes",
        email="race.clientes@test.demo",
        password_hash=hash_password("Password123!"),
        rol=Rol.VENDEDOR,
    )
    setup.add(vendedor)
    setup.commit()
    vendedor_id = vendedor.id
    setup.close()

    n_hilos = 6
    ids: list[int] = []
    errores: list[Exception] = []
    barrera = threading.Barrier(n_hilos)

    def alta() -> None:
        sesion = SessionLocal()
        try:
            usuario = sesion.get(Usuario, vendedor_id)
            barrera.wait()
            try:
                cliente = obtener_o_crear(sesion, "  cliente   carrera f5 ", usuario)
                sesion.commit()
                ids.append(cliente.id)
            except Exception as exc:
                errores.append(exc)
        finally:
            sesion.close()

    hilos = [threading.Thread(target=alta) for _ in range(n_hilos)]
    try:
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        assert errores == []
        assert len(ids) == n_hilos and len(set(ids)) == 1  # un solo cliente
    finally:
        limpieza = SessionLocal()
        limpieza.execute(
            Cliente.__table__.delete().where(Cliente.nombre_normalizado == "CLIENTE CARRERA F5")
        )
        limpieza.execute(Usuario.__table__.delete().where(Usuario.id == vendedor_id))
        limpieza.commit()
        limpieza.close()


def test_autocomplete(client, db, make_user, make_sucursal, auth_headers):
    vendedor = make_user(Rol.VENDEDOR, sucursal_id=make_sucursal().id)
    db.add_all(
        [Cliente(nombre_normalizado=f"CLIENTE {i:02d}", creado_por=vendedor.id) for i in range(25)]
    )
    db.add(Cliente(nombre_normalizado="DINCO", creado_por=vendedor.id))
    db.commit()
    headers = auth_headers(vendedor)

    r = client.get("/api/v1/clientes", params={"buscar": "din"}, headers=headers)
    assert r.status_code == 200
    assert [c["nombre_normalizado"] for c in r.json()] == ["DINCO"]

    # Máximo 20 resultados.
    r = client.get("/api/v1/clientes", params={"buscar": "CLIENTE"}, headers=headers)
    assert len(r.json()) == 20

    # Requiere autenticación.
    assert client.get("/api/v1/clientes").status_code == 401
