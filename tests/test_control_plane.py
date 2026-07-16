from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from workbench.app import app
from workbench.control_plane import SingleWorkerConfigurationError, validate_control_plane


def test_default_control_plane_is_explicitly_single_worker(monkeypatch) -> None:
    monkeypatch.delenv("WORKBENCH_CONTROL_PLANE_MODE", raising=False)
    monkeypatch.delenv("WORKBENCH_WORKERS", raising=False)
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    assert validate_control_plane() == {
        "mode": "single_worker",
        "workers": 1,
    }


def test_multiple_workers_are_rejected_before_serving(monkeypatch) -> None:
    monkeypatch.setenv("WORKBENCH_WORKERS", "2")

    with pytest.raises(SingleWorkerConfigurationError, match="single_worker"):
        validate_control_plane()


def test_agent_capabilities_and_health_report_control_plane_mode(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        capabilities = client.get(
            "/agent/capabilities", params={"project_root": str(project_root)}
        )
        health = client.get("/health")

    assert capabilities.status_code == 200
    assert capabilities.json()["control_plane_mode"] == "single_worker"
    assert health.status_code == 200
    assert health.json()["control_plane_mode"] == "single_worker"
