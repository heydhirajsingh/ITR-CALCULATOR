from fastapi.testclient import TestClient

from backend.app.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["offline"] is True


def test_institution_choices_are_canonical():
    with TestClient(app) as client:
        response = client.get("/api/institutions")
        assert response.status_code == 200
        assert "IDFC First Bank" in response.json()
        assert "State Bank of India" in response.json()
        assert "SBI" not in response.json()
