from fastapi.testclient import TestClient

from workbench.app import app
from workbench.http import projects_routes


def test_system_appearance_route_returns_the_server_owned_projection(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        projects_routes,
        "detect_system_appearance",
        lambda: {"theme": "light", "source": "darwin-native"},
    )

    response = TestClient(app).get("/system/appearance")

    assert response.status_code == 200
    assert response.json() == {"theme": "light", "source": "darwin-native"}
