"""F7: scheduler — bandas con dedup, limpieza semanal y heartbeat/health.

Historial SINTÉTICO con "ahora" inyectado. Sucursal America/Chihuahua (UTC-6
fijo). Calendario marzo 2026 (sin festivos aquí): 02=lun, 03=mar, 04=mié,
05=jue — apertura lun 02 09:00 local (15:00Z): T0=lun02; mar03 → T=1;
mié04 → T=2 (amarilla); jue05 → T=3 (roja)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update

from app.models.historial import HistorialEstado
from app.models.notificacion import Notificacion
from app.models.refresh_token import RefreshToken
from app.models.scheduler_heartbeat import SchedulerHeartbeat
from app.models.solicitud import Estado, Prioridad, Solicitud
from app.models.usuario import Rol
from app.scheduler.jobs import job_bandas, job_limpieza

_folio = iter(range(1, 10_000))


@pytest.fixture
def entorno(db, make_user, make_sucursal):
    sucursal = make_sucursal("Sched Suc")  # America/Chihuahua
    return SimpleNamespace(
        sucursal=sucursal,
        comprador=make_user(Rol.COMPRADOR),
        vendedor=make_user(Rol.VENDEDOR, sucursal_id=sucursal.id),
        admin_1=make_user(Rol.ADMIN),
        admin_2=make_user(Rol.ADMIN),
        admin_inactivo=make_user(Rol.ADMIN, activo=False),
    )


def _sintetica(db, entorno, *, estado, eventos):
    solicitud = Solicitud(
        folio=f"SCH-{next(_folio)}",
        vendedor_id=entorno.vendedor.id,
        sucursal_id=entorno.sucursal.id,
        comprador_id=entorno.comprador.id,
        estado=estado,
        prioridad=Prioridad.NORMAL,
    )
    db.add(solicitud)
    db.flush()
    for de, a, ts in eventos:
        db.add(
            HistorialEstado(
                solicitud_id=solicitud.id, de=de, a=a, usuario_id=entorno.vendedor.id, timestamp=ts
            )
        )
    db.commit()
    return solicitud


def _utc(d, hh, mm=0):
    return datetime(2026, 3, d, hh, mm, tzinfo=UTC)


APERTURA = _utc(2, 15)  # lun 02-mar 09:00 local


@pytest.fixture
def abierta(db, entorno):
    return _sintetica(
        db,
        entorno,
        estado=Estado.ENVIADA,
        eventos=[(Estado.BORRADOR, Estado.ENVIADA, APERTURA)],
    )


def _bandas(db) -> list[Notificacion]:
    return list(
        db.scalars(
            select(Notificacion)
            .where(Notificacion.tipo.in_(("banda_amarilla", "banda_roja")))
            .order_by(Notificacion.id)
        )
    )


def test_t1_no_alerta_pero_late(db, entorno, abierta):
    conteos = job_bandas(db, ahora=_utc(3, 18))  # mar 03: T=1
    assert conteos == {"amarillas": 0, "rojas": 0}
    assert _bandas(db) == []
    assert db.scalar(select(SchedulerHeartbeat.ultima_corrida)) == _utc(3, 18)


def test_t2_amarilla_al_comprador_sin_duplicados(db, entorno, abierta):
    conteos = job_bandas(db, ahora=_utc(4, 18))  # mié 04: T=2
    assert conteos == {"amarillas": 1, "rojas": 0}
    # Correr el job 3 veces seguidas: CERO duplicados.
    for _ in range(3):
        assert job_bandas(db, ahora=_utc(4, 18, 30)) == {"amarillas": 0, "rojas": 0}
    bandas = _bandas(db)
    assert len(bandas) == 1
    n = bandas[0]
    assert n.usuario_id == entorno.comprador.id
    assert n.tipo == "banda_amarilla"
    assert abierta.folio in n.mensaje
    assert n.dedup == f"banda_amarilla:{abierta.id}:{entorno.comprador.id}:{APERTURA.isoformat()}"


def test_t3_roja_a_comprador_y_admins_activos(db, entorno, abierta):
    conteos = job_bandas(db, ahora=_utc(5, 18))  # jue 05: T=3
    # Primera corrida en T=3: la amarilla (T>=2) también entra, más 3 rojas
    # (comprador + 2 admins activos; el inactivo NO).
    assert conteos == {"amarillas": 1, "rojas": 3}
    rojas = [n for n in _bandas(db) if n.tipo == "banda_roja"]
    assert {n.usuario_id for n in rojas} == {
        entorno.comprador.id,
        entorno.admin_1.id,
        entorno.admin_2.id,
    }
    assert all(abierta.folio in n.mensaje for n in rojas)
    # Idempotencia también en rojo.
    assert job_bandas(db, ahora=_utc(5, 19)) == {"amarillas": 0, "rojas": 0}


def test_reenvio_con_ciclo_nuevo_vuelve_a_alertar(db, entorno):
    solicitud = _sintetica(
        db,
        entorno,
        estado=Estado.ENVIADA,
        eventos=[(Estado.BORRADOR, Estado.ENVIADA, APERTURA)],
    )
    assert job_bandas(db, ahora=_utc(4, 18))["amarillas"] == 1  # ciclo 1, T=2

    # Rechazo (cierra ciclo 1) y reenvío jue 05 09:00 local (ciclo 2).
    apertura_2 = _utc(5, 15)
    for de, a, ts in [
        (Estado.ENVIADA, Estado.RECHAZADA, _utc(4, 19)),
        (Estado.RECHAZADA, Estado.ENVIADA, apertura_2),
    ]:
        db.add(
            HistorialEstado(
                solicitud_id=solicitud.id, de=de, a=a, usuario_id=entorno.vendedor.id, timestamp=ts
            )
        )
    db.commit()
    # Sáb 07-mar 12:00 local: T0=jue05, vie06(+1), sáb07(+2) → ciclo 2 en T=2.
    conteos = job_bandas(db, ahora=_utc(7, 18))
    assert conteos["amarillas"] == 1  # apertura nueva → dedup nuevo → alerta
    amarillas = [n for n in _bandas(db) if n.tipo == "banda_amarilla"]
    assert len(amarillas) == 2
    assert {n.dedup for n in amarillas} == {
        f"banda_amarilla:{solicitud.id}:{entorno.comprador.id}:{APERTURA.isoformat()}",
        f"banda_amarilla:{solicitud.id}:{entorno.comprador.id}:{apertura_2.isoformat()}",
    }


def test_estados_sin_ciclo_abierto_jamas_alertan(db, entorno):
    vieja = _utc(2, 15)
    _sintetica(
        db,
        entorno,
        estado=Estado.COTIZADA,
        eventos=[
            (Estado.BORRADOR, Estado.ENVIADA, vieja),
            (Estado.EN_PROCESO, Estado.COTIZADA, _utc(3, 15)),
        ],
    )
    _sintetica(
        db,
        entorno,
        estado=Estado.CANCELADA,
        eventos=[
            (Estado.BORRADOR, Estado.ENVIADA, vieja),
            (Estado.ENVIADA, Estado.CANCELADA, _utc(3, 15)),
        ],
    )
    _sintetica(
        db,
        entorno,
        estado=Estado.CONFIRMADA,
        eventos=[
            (Estado.BORRADOR, Estado.ENVIADA, vieja),
            (Estado.EN_PROCESO, Estado.COTIZADA, _utc(3, 15)),
            (Estado.COTIZADA, Estado.CONFIRMADA, _utc(3, 16)),
        ],
    )
    assert job_bandas(db, ahora=_utc(20, 18)) == {"amarillas": 0, "rojas": 0}
    assert _bandas(db) == []


def test_limpieza_borra_exactamente_lo_viejo(db, entorno):
    ahora = datetime.now(UTC)

    def _notif(leida: bool, dias: int) -> int:
        n = Notificacion(
            usuario_id=entorno.comprador.id, tipo="asignacion", mensaje="x", leida=leida
        )
        db.add(n)
        db.flush()
        db.execute(
            update(Notificacion)
            .where(Notificacion.id == n.id)
            .values(creado_en=ahora - timedelta(days=dias))
        )
        return n.id

    borrable = _notif(leida=True, dias=91)
    leida_reciente = _notif(leida=True, dias=89)
    vieja_sin_leer = _notif(leida=False, dias=200)

    def _token(*, expira_hace: int | None, revocado_hace: int | None = None) -> int:
        t = RefreshToken(
            usuario_id=entorno.comprador.id,
            token_hash=f"hash-{next(_folio)}",
            expira_en=ahora - timedelta(days=expira_hace)
            if expira_hace is not None
            else ahora + timedelta(days=7),
            revocado_en=ahora - timedelta(days=revocado_hace)
            if revocado_hace is not None
            else None,
        )
        db.add(t)
        db.flush()
        return t.id

    tok_expirado_viejo = _token(expira_hace=31)
    tok_revocado_viejo = _token(expira_hace=None, revocado_hace=31)
    tok_expirado_reciente = _token(expira_hace=5)
    tok_vigente = _token(expira_hace=None)
    db.commit()

    conteos = job_limpieza(db, ahora=ahora)
    assert conteos == {"notificaciones": 1, "refresh_tokens": 2}

    notif_ids = set(db.scalars(select(Notificacion.id)))
    assert borrable not in notif_ids
    assert {leida_reciente, vieja_sin_leer} <= notif_ids
    token_ids = set(db.scalars(select(RefreshToken.id)))
    assert {tok_expirado_viejo, tok_revocado_viejo} & token_ids == set()
    assert {tok_expirado_reciente, tok_vigente} <= token_ids


def test_heartbeat_y_health(client, db, entorno, abierta):
    # Tabla vacía: el scheduler nunca ha corrido.
    assert client.get("/api/v1/health").json()["scheduler"] == "n/a"

    job_bandas(db)  # ahora real → recién latido
    assert client.get("/api/v1/health").json()["scheduler"] == "ok"

    # Heartbeat viejo (inyectado): más de 30 minutos sin latir.
    db.execute(
        update(SchedulerHeartbeat).values(ultima_corrida=datetime.now(UTC) - timedelta(minutes=35))
    )
    db.commit()
    assert client.get("/api/v1/health").json()["scheduler"] == "degraded"

    db.execute(delete(SchedulerHeartbeat))
    db.commit()
    assert client.get("/api/v1/health").json()["scheduler"] == "n/a"
