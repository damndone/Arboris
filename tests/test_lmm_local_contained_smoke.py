from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.app import app
from workbench.events import get_event_manager
from workbench.services.lmm_result_adapter import read_lmm_public_results


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "models"
    / "linear_mixed_effects"
    / "known_truth.csv"
)


@pytest.fixture(autouse=True)
def _reset_process_state() -> None:
    import workbench.services.execution_profile as profiles

    profiles._reset_execution_profile_for_test()
    get_event_manager()._reset_for_testing()
    yield
    profiles._reset_execution_profile_for_test()
    get_event_manager()._reset_for_testing()


def test_http_lmm_run_completes_under_explicit_local_contained_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.services.execution_profile as profiles

    monkeypatch.setenv("WORKBENCH_EXECUTION_PROFILE", "local_contained")
    monkeypatch.setattr(profiles, "_run_local_containment_canary", lambda: None)
    profiles._reset_execution_profile_for_test()

    started = time.perf_counter()
    with TestClient(app) as client:
        project = client.post(
            "/projects", json={"parent": str(tmp_path), "name": "lmm-smoke"}
        )
        assert project.status_code == 200
        project_root = Path(project.json()["project_root"])
        with FIXTURE.open("rb") as source:
            submitted = client.post(
                "/runs",
                data={
                    "project_root": str(project_root),
                    "mode": "auto",
                    "model_type": "linear_mixed_effects",
                    "y": "score",
                    "x": "baseline_score",
                    "model_options": json.dumps(
                        {
                            "subject_id": "participant_id",
                            "time": "week",
                            "group": "arm",
                            "fit_method": "reml",
                            "random_slope": True,
                        }
                    ),
                },
                files={"file": ("known_truth.csv", source, "text/csv")},
            )
        assert submitted.status_code == 200, submitted.text
        run_id = submitted.json()["run_id"]
        for _ in range(300):
            detail = client.get(
                f"/runs/{run_id}", params={"project_root": str(project_root)}
            )
            assert detail.status_code == 200
            if detail.json()["status"] in {"completed", "blocked", "failed"}:
                break
            time.sleep(0.05)
        else:
            pytest.fail("local LMM smoke did not reach a terminal state")

    elapsed = time.perf_counter() - started
    assert detail.json()["status"] == "completed", detail.json()
    assert elapsed < 30.0

    run_root = project_root / "runs" / run_id
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["execution_profile"] == "local_contained"
    assert manifest["containment_evidence"] == "local_startup_canary"
    assert manifest["release_evaluation_eligible"] is False

    public = read_lmm_public_results(run_root)
    assert len(public) == 1
    payload = public[0]["payload"]
    assert payload["model_type"] == "linear_mixed_effects"
    assert payload["status"] == "complete"
    assert payload["converged"] is True
    assert abs(payload["coefficients"]["group_time_interaction"]["estimate"] - 0.9) <= 0.35
