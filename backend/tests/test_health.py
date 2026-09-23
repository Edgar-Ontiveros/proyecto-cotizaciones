from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.integrations.sap.factory import MENSAJE_FUENTE_PROHIBIDA, validar_fuente_oc
from app.main import app
from app.models.scheduler_heartbeat import SchedulerHeartbeat


def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["scheduler"] == "n/a"
    assert body["sap"] == "ok"  # F16a: FakeFuenteOC responde al ping
    assert body["sap_fuente"] == "fake"  # F16a.2: la fuente REAL que sirve, por su clase


def test_health_scheduler_degraded_y_ok(client, db):
    """Heartbeat con >30 min sin latir → degraded; reciente → ok (F8d)."""
    db.add(SchedulerHeartbeat(id=1, ultima_corrida=datetime.now(UTC) - timedelta(minutes=31)))
    db.commit()
    assert client.get("/api/v1/health").json()["scheduler"] == "degraded"

    heartbeat = db.get(SchedulerHeartbeat, 1)
    assert heartbeat is not None
    heartbeat.ultima_corrida = datetime.now(UTC)
    db.commit()
    assert client.get("/api/v1/health").json()["scheduler"] == "ok"


def test_health_503_bd_caida(client):
    """Con la BD abajo: 503 y el cuerpo exacto de error (F8d)."""

    class _SesionRota:
        def execute(self, *args, **kwargs):
            raise RuntimeError("db down")

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = _SesionRota
    try:
        r = client.get("/api/v1/health")
    finally:
        app.dependency_overrides[get_db] = original
    assert r.status_code == 503
    assert r.json() == {"status": "error", "database": "down", "scheduler": "n/a", "sap": "n/a"}


# ===================================================== F16a.2 guardarraíl


def _settings(**kw):
    return Settings(database_url="postgresql+psycopg://x/y", jwt_secret="s", **kw)


def test_prod_exige_fuente_hana():
    with pytest.raises(RuntimeError, match="ENV=prod exige FUENTE_OC=hana"):
        validar_fuente_oc(_settings(env="prod", fuente_oc="fake"))
    # Con HANA en prod y con Fake fuera de prod, arranca.
    validar_fuente_oc(_settings(env="prod", fuente_oc="hana"))
    validar_fuente_oc(_settings(env="dev", fuente_oc="fake"))
    validar_fuente_oc(_settings(env="test", fuente_oc="fake"))


def test_la_app_no_arranca_en_prod_con_fake(monkeypatch, capsys):
    """El lifespan corre la validación: TestClient (como uvicorn) revienta al
    arrancar y el log dice por qué."""
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setenv("FUENTE_OC", "fake")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match=MENSAJE_FUENTE_PROHIBIDA[:30]), TestClient(app):
            pass
    finally:
        get_settings.cache_clear()
    assert "fuente_oc_prohibida_en_prod" in capsys.readouterr().out
