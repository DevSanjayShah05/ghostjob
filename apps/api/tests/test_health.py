from fastapi.testclient import TestClient

from ghostjob_api import db
from ghostjob_api.main import app

client = TestClient(app)


def test_health_ok_when_db_up(monkeypatch):
    monkeypatch.setattr(db, "ping", lambda url, timeout_s=2: True)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"


def test_health_still_ok_when_db_down(monkeypatch):
    # The API process being up is what /health reports; the DB state is a separate field.
    monkeypatch.setattr(db, "ping", lambda url, timeout_s=2: False)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db"] == "unavailable"


def test_ping_returns_false_for_unreachable_db():
    assert db.ping("postgresql://nobody:x@127.0.0.1:1/none", timeout_s=1) is False
