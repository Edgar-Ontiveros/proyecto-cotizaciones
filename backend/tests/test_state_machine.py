"""Matriz de estados EXHAUSTIVA con el modelo de permisos final (F5): todas
las combinaciones (origen, destino, actor). Válidas ejecutan y escriben
historial con el EJECUTOR REAL; inválidas → 409 con el estado real; actor no
autorizado → 403.

Lados: VENTAS = vendedor dueño | gerente de LA sucursal | admin;
COMPRAS = comprador asignado | admin; ADMINISTRACION = solo admin."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.models.catalogos import FamiliaMotivo, MotivoRechazo
from app.models.historial import HistorialEstado
from app.models.solicitud import Estado, Prioridad, Solicitud
from app.models.sucursal import CompradorSucursal
from app.models.usuario import Rol
from app.modules.solicitudes.state_machine import MATRIZ, Lado, ejecutar_transicion

# Copia escrita A MANO de la especificación §3 + modelo de permisos F5 — si
# MATRIZ del módulo se desvía, este test truena.
MATRIZ_ESPERADA = {
    (Estado.BORRADOR, Estado.ENVIADA): Lado.VENTAS,
    (Estado.RECHAZADA, Estado.ENVIADA): Lado.VENTAS,
    (Estado.ENVIADA, Estado.EN_PROCESO): Lado.COMPRAS,
    (Estado.ENVIADA, Estado.RECHAZADA): Lado.COMPRAS,
    (Estado.EN_PROCESO, Estado.RECHAZADA): Lado.COMPRAS,
    (Estado.EN_PROCESO, Estado.COTIZADA): Lado.COMPRAS,
    (Estado.COTIZADA, Estado.CONFIRMADA): Lado.VENTAS,
    (Estado.COTIZADA, Estado.NO_CONFIRMADA): Lado.VENTAS,
    (Estado.NO_CONFIRMADA, Estado.COTIZADA): Lado.ADMINISTRACION,
    (Estado.BORRADOR, Estado.CANCELADA): Lado.VENTAS,
    (Estado.ENVIADA, Estado.CANCELADA): Lado.VENTAS,
    (Estado.EN_PROCESO, Estado.CANCELADA): Lado.VENTAS,
    (Estado.RECHAZADA, Estado.CANCELADA): Lado.VENTAS,
}

# Quién está autorizado por lado (modelo F5). El admin ejecuta TODO.
AUTORIZADOS = {
    Lado.VENTAS: {"vendedor_dueno", "gerente_sucursal", "admin"},
    Lado.COMPRAS: {"comprador_asignado", "admin"},
    Lado.ADMINISTRACION: {"admin"},
}

ACTORES = [
    "vendedor_dueno",
    "otro_vendedor",
    "comprador_asignado",
    "otro_comprador",
    "gerente_sucursal",
    "gerente_otra_sucursal",
    "admin",
]


def test_matriz_es_exactamente_la_especificada():
    assert MATRIZ == MATRIZ_ESPERADA


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal()
    otra_sucursal = make_sucursal()
    comprador = make_user(Rol.COMPRADOR)
    db.add(CompradorSucursal(comprador_id=comprador.id, sucursal_id=sucursal.id, titular=True))
    motivo = MotivoRechazo(familia=FamiliaMotivo.NO_PROCEDE, texto="Motivo de prueba")
    db.add(motivo)
    db.commit()
    return SimpleNamespace(
        sucursal=sucursal,
        vendedor_dueno=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        otro_vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        comprador_asignado=comprador,
        otro_comprador=make_user(Rol.COMPRADOR),
        gerente_sucursal=make_user(Rol.GERENTE, sucursal_id=sucursal.id),
        gerente_otra_sucursal=make_user(Rol.GERENTE, sucursal_id=otra_sucursal.id),
        admin=make_user(Rol.ADMIN),
        motivo=motivo,
    )


def _solicitud_en(db, entorno, estado: Estado) -> Solicitud:
    solicitud = Solicitud(
        vendedor_id=entorno.vendedor_dueno.id,
        sucursal_id=entorno.sucursal.id,
        estado=estado,
        prioridad=Prioridad.NORMAL,
    )
    if estado != Estado.BORRADOR:
        solicitud.comprador_id = entorno.comprador_asignado.id
    db.add(solicitud)
    db.flush()
    if estado != Estado.BORRADOR:
        solicitud.folio = f"TST-{solicitud.id}"
    db.commit()
    return solicitud


@pytest.mark.parametrize("actor_key", ACTORES)
@pytest.mark.parametrize("a", list(Estado))
@pytest.mark.parametrize("de", list(Estado))
def test_matriz_exhaustiva(db, entorno, de: Estado, a: Estado, actor_key: str):
    solicitud = _solicitud_en(db, entorno, de)
    folio_original = solicitud.folio
    usuario = getattr(entorno, actor_key)
    motivo_id = entorno.motivo.id if a == Estado.RECHAZADA else None

    lado = MATRIZ_ESPERADA.get((de, a))
    if lado is None:
        with pytest.raises(AppError) as exc:
            ejecutar_transicion(db, solicitud.id, a, usuario, motivo_id=motivo_id)
        assert exc.value.status_code == 409
        assert exc.value.code == "estado_conflicto"
        assert de.value in exc.value.detail  # el estado real viaja en detail
        return

    if actor_key not in AUTORIZADOS[lado]:
        with pytest.raises(AppError) as exc:
            ejecutar_transicion(db, solicitud.id, a, usuario, motivo_id=motivo_id)
        assert exc.value.status_code == 403
        assert exc.value.code == "transicion_no_permitida"
        return

    resultado = ejecutar_transicion(db, solicitud.id, a, usuario, motivo_id=motivo_id)
    assert resultado.estado == a
    evento = db.scalars(
        select(HistorialEstado)
        .where(HistorialEstado.solicitud_id == solicitud.id)
        .order_by(HistorialEstado.id.desc())
    ).first()
    assert evento is not None and (evento.de, evento.a) == (de, a)
    # El historial registra SIEMPRE al ejecutor real (F5): gerente o admin
    # actuando por el lado ventas quedan registrados como ellos mismos.
    assert evento.usuario_id == usuario.id
    if a == Estado.ENVIADA:
        assert resultado.comprador_id == entorno.comprador_asignado.id
        if de == Estado.BORRADOR:
            assert resultado.folio is not None and resultado.enviado_en is not None
        else:  # reenvío: conserva folio
            assert resultado.folio == folio_original
    if a == Estado.RECHAZADA:
        assert evento.motivo_id == entorno.motivo.id


def test_gerente_sin_sucursal_no_autoriza_ventas(db, entorno, make_user):
    """Fail-closed (addendum g): un gerente con sucursal_id NULL por datos
    viejos no ejecuta nada del lado ventas."""
    from sqlalchemy import update

    from app.models.usuario import Usuario

    gerente = make_user(Rol.GERENTE, sucursal_id=entorno.sucursal.id)
    db.execute(update(Usuario).where(Usuario.id == gerente.id).values(sucursal_id=None))
    db.commit()
    db.refresh(gerente)
    solicitud = _solicitud_en(db, entorno, Estado.RECHAZADA)
    with pytest.raises(AppError) as exc:
        ejecutar_transicion(db, solicitud.id, Estado.ENVIADA, gerente)
    assert (exc.value.status_code, exc.value.code) == (403, "transicion_no_permitida")


def test_solicitud_inexistente_404(db, entorno):
    with pytest.raises(AppError) as exc:
        ejecutar_transicion(db, 999999, Estado.ENVIADA, entorno.vendedor_dueno)
    assert exc.value.status_code == 404


def test_rechazo_sin_motivo_422(db, entorno):
    solicitud = _solicitud_en(db, entorno, Estado.ENVIADA)
    with pytest.raises(AppError) as exc:
        ejecutar_transicion(db, solicitud.id, Estado.RECHAZADA, entorno.comprador_asignado)
    assert (exc.value.status_code, exc.value.code) == (422, "motivo_requerido")


def test_rechazo_motivo_inactivo_422(db, entorno):
    entorno.motivo.activo = False
    db.commit()
    solicitud = _solicitud_en(db, entorno, Estado.ENVIADA)
    with pytest.raises(AppError) as exc:
        ejecutar_transicion(
            db,
            solicitud.id,
            Estado.RECHAZADA,
            entorno.comprador_asignado,
            motivo_id=entorno.motivo.id,
        )
    assert (exc.value.status_code, exc.value.code) == (422, "motivo_invalido")


def test_envio_sin_titular_409_y_no_transiciona(db, make_user, make_sucursal):
    sucursal = make_sucursal()  # sin titular
    vendedor = make_user(Rol.VENDEDOR, sucursal_id=sucursal.id)
    solicitud = Solicitud(
        vendedor_id=vendedor.id,
        sucursal_id=sucursal.id,
        estado=Estado.BORRADOR,
        prioridad=Prioridad.NORMAL,
    )
    db.add(solicitud)
    db.commit()
    with pytest.raises(AppError) as exc:
        ejecutar_transicion(db, solicitud.id, Estado.ENVIADA, vendedor)
    assert (exc.value.status_code, exc.value.code) == (409, "sucursal_sin_titular")
    db.rollback()
    assert db.get(Solicitud, solicitud.id).estado == Estado.BORRADOR


def test_hitos_solo_primera_ocurrencia(db, entorno):
    """cotizado_en no se pisa si la solicitud vuelve a COTIZADA (reversión
    admin de NO_CONFIRMADA, F4)."""
    solicitud = _solicitud_en(db, entorno, Estado.EN_PROCESO)
    ejecutar_transicion(db, solicitud.id, Estado.COTIZADA, entorno.comprador_asignado)
    primer_cotizado = solicitud.cotizado_en
    assert primer_cotizado is not None
    ejecutar_transicion(db, solicitud.id, Estado.NO_CONFIRMADA, entorno.vendedor_dueno)
    ejecutar_transicion(db, solicitud.id, Estado.COTIZADA, entorno.admin)
    assert solicitud.cotizado_en == primer_cotizado
