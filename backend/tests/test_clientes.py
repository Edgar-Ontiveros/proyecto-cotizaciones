from app.models.cliente import Cliente
from app.models.usuario import Rol
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
