from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_unknown_route_uses_fastapi_default_not_core_error() -> None:
    response = TestClient(app).get("/api/missing")

    assert response.status_code == 404
