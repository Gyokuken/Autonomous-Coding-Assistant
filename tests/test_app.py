"""Flask layer: health check and /run input validation (no LLM calls)."""

import pytest

import app as app_module


@pytest.fixture
def client():
    return app_module.app.test_client()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["sandbox"]["driver"] == "subprocess"


def test_run_requires_requirement(client):
    assert client.post("/run", json={"requirement": "   "}).status_code == 400


def test_run_rejects_non_json(client):
    assert client.post("/run", data="x", content_type="text/plain").status_code == 400


def test_run_rejects_unknown_profile(client):
    r = client.post("/run", json={"requirement": "do a thing", "profile": "nope"})
    assert r.status_code == 400


def test_run_rejects_unknown_model(client):
    r = client.post("/run", json={"requirement": "do a thing", "model": "not-a-real-model"})
    assert r.status_code == 400


def test_run_rejects_oversized_requirement(client):
    r = client.post("/run", json={"requirement": "x" * 9000})
    assert r.status_code == 400
