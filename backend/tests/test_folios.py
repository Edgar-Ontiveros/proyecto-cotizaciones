"""Folios: {PREFIJO}-{CONSECUTIVO} sin año, corrido por sucursal, race-safe."""

import threading

from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, Prioridad, Solicitud
from app.models.sucursal import CompradorSucursal, FolioCounter, Sucursal
from app.models.usuario import Rol, Usuario
from app.modules.solicitudes.state_machine import ejecutar_transicion
from tests.conftest import _PASSWORD_HASH


def _preparar_sucursal(db, make_user, nombre: str, prefijo: str):
    sucursal = Sucursal(nombre=nombre, prefijo_folio=prefijo, timezone="America/Chihuahua")
    db.add(sucursal)
    db.flush()
    vendedor = make_user(Rol.VENDEDOR, sucursal_id=sucursal.id)
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    db.commit()
    return sucursal, vendedor


def _borrador(db, vendedor, sucursal) -> Solicitud:
    solicitud = Solicitud(
        vendedor_id=vendedor.id,
        sucursal_id=sucursal.id,
        estado=Estado.BORRADOR,
        prioridad=Prioridad.NORMAL,
    )
    db.add(solicitud)
    db.commit()
    return solicitud


def test_secuencia_por_sucursal_independiente(db, make_user):
    norte, vend_norte = _preparar_sucursal(db, make_user, "Norte folios", "CCN")
    matriz, vend_matriz = _preparar_sucursal(db, make_user, "Matriz folios", "MTZ")

    folios = []
    for _ in range(2):
        s = _borrador(db, vend_norte, norte)
        folios.append(ejecutar_transicion(db, s.id, Estado.ENVIADA, vend_norte).folio)
    s = _borrador(db, vend_matriz, matriz)
    folios.append(ejecutar_transicion(db, s.id, Estado.ENVIADA, vend_matriz).folio)

    assert folios == ["CCN-1", "CCN-2", "MTZ-1"]


def test_reenvio_conserva_folio(db, make_user):
    from app.models.catalogos import FamiliaMotivo, MotivoRechazo

    sucursal, vendedor = _preparar_sucursal(db, make_user, "Suc reenvío", "RNV")
    motivo = MotivoRechazo(familia=FamiliaMotivo.FALTA_INFORMACION, texto="Motivo folios")
    db.add(motivo)
    db.commit()
    solicitud = _borrador(db, vendedor, sucursal)
    ejecutar_transicion(db, solicitud.id, Estado.ENVIADA, vendedor)
    folio = solicitud.folio
    enviado_en = solicitud.enviado_en
    comprador = db.get(Usuario, solicitud.comprador_id)
    ejecutar_transicion(db, solicitud.id, Estado.RECHAZADA, comprador, motivo_id=motivo.id)
    ejecutar_transicion(db, solicitud.id, Estado.ENVIADA, vendedor)
    assert solicitud.folio == folio == "RNV-1"
    assert solicitud.enviado_en == enviado_en  # el reenvío no toca enviado_en


def test_folios_concurrentes_unicos_y_consecutivos(_database):
    """N envíos simultáneos (sesiones y transacciones REALES, sin savepoints):
    el FOR UPDATE del contador garantiza folios únicos y consecutivos."""
    n = 8
    setup = SessionLocal()
    sucursal = Sucursal(
        nombre="Suc concurrencia", prefijo_folio="CONC", timezone="America/Chihuahua"
    )
    setup.add(sucursal)
    setup.flush()
    vendedor = Usuario(
        nombre="Vendedor Conc",
        email="conc.vendedor@test.demo",
        password_hash=_PASSWORD_HASH,
        rol=Rol.VENDEDOR,
        sucursal_id=sucursal.id,
    )
    comprador = Usuario(
        nombre="Comprador Conc",
        email="conc.comprador@test.demo",
        password_hash=_PASSWORD_HASH,
        rol=Rol.COMPRADOR,
    )
    setup.add_all([vendedor, comprador])
    setup.flush()
    setup.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    ids = []
    for _ in range(n):
        s = Solicitud(
            vendedor_id=vendedor.id,
            sucursal_id=sucursal.id,
            estado=Estado.BORRADOR,
            prioridad=Prioridad.NORMAL,
        )
        setup.add(s)
        setup.flush()
        ids.append(s.id)
    setup.commit()

    barrera = threading.Barrier(n)
    folios: list[str] = []
    errores: list[Exception] = []

    def enviar(solicitud_id: int) -> None:
        sesion = SessionLocal()
        try:
            barrera.wait()
            resultado = ejecutar_transicion(sesion, solicitud_id, Estado.ENVIADA, vendedor)
            folios.append(resultado.folio)
        except Exception as e:
            errores.append(e)
        finally:
            sesion.close()

    hilos = [threading.Thread(target=enviar, args=(i,)) for i in ids]
    try:
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()

        assert errores == []
        assert sorted(folios, key=lambda f: int(f.split("-")[1])) == [
            f"CONC-{i}" for i in range(1, n + 1)
        ]
        assert len(set(folios)) == n
        ultimo = setup.scalar(
            select(FolioCounter.ultimo).where(FolioCounter.sucursal_id == sucursal.id)
        )
        assert ultimo == n
    finally:
        limpieza = SessionLocal()
        limpieza.execute(delete(HistorialEstado).where(HistorialEstado.solicitud_id.in_(ids)))
        limpieza.execute(delete(Solicitud).where(Solicitud.id.in_(ids)))
        limpieza.execute(delete(FolioCounter).where(FolioCounter.sucursal_id == sucursal.id))
        limpieza.execute(
            delete(CompradorSucursal).where(CompradorSucursal.sucursal_id == sucursal.id)
        )
        limpieza.execute(delete(Usuario).where(Usuario.id.in_([vendedor.id, comprador.id])))
        limpieza.execute(delete(Sucursal).where(Sucursal.id == sucursal.id))
        limpieza.commit()
        limpieza.close()
        setup.close()
