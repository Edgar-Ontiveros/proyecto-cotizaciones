from sqlalchemy import func, select

from app.cli.seed import PASSWORD_DEFAULT, email_provisional, run
from app.core.security import verify_password
from app.models.catalogos import DiaFestivo, MotivoRechazo
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario


def _conteo_por_rol(db, rol: Rol) -> int:
    return db.scalar(select(func.count()).where(Usuario.rol == rol).select_from(Usuario))


def test_seed_idempotente_y_conteos_exactos(db):
    run(db)
    run(db)  # correr dos veces no duplica

    assert db.scalar(select(func.count()).select_from(Sucursal)) == 11
    assert _conteo_por_rol(db, Rol.COMPRADOR) == 6
    assert _conteo_por_rol(db, Rol.GERENTE) == 9
    assert _conteo_por_rol(db, Rol.VENDEDOR) == 35
    assert _conteo_por_rol(db, Rol.ADMIN) == 1
    assert db.scalar(select(func.count()).select_from(MotivoRechazo)) == 5
    assert db.scalar(select(func.count()).select_from(FolioCounter)) == 11
    assert db.scalar(select(func.count()).select_from(DiaFestivo)) == 14

    # Territorios completos: los 6 compradores son titulares y cubren las 11
    # sucursales (una titularidad por sucursal).
    territorios = db.scalars(select(CompradorSucursal)).all()
    assert len(territorios) == 11
    assert all(t.titular for t in territorios)
    assert len({t.sucursal_id for t in territorios}) == 11

    # Todos entran con la contraseña por defecto y deben cambiarla.
    usuarios = db.scalars(select(Usuario)).all()
    assert len(usuarios) == 51
    assert all(u.must_change_password for u in usuarios)
    admin = db.scalar(select(Usuario).where(Usuario.email == "edgar@herinox.demo"))
    assert admin is not None and admin.rol == Rol.ADMIN
    assert verify_password(PASSWORD_DEFAULT, admin.password_hash)


def test_emails_provisionales_sin_acentos():
    assert email_provisional("Fabián Flores") == "fabian.flores@herinox.demo"
    assert email_provisional("Alonso Muñoz") == "alonso.munoz@herinox.demo"
    assert email_provisional("Gloria de la Luz Murillo") == "gloria.murillo@herinox.demo"
