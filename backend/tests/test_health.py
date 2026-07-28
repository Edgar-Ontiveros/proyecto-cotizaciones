from datetime import UTC, datetime, timedelta

from app.core.database import get_db
from app.main import app
from app.models.scheduler_heartbeat import SchedulerHeartbeat


def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["scheduler"] == "n/a"


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
    assert r.json() == {"status": "error", "database": "down", "scheduler": "n/a"}
