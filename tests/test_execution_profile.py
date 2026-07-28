from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _reset_profile_between_tests():
    import workbench.services.execution_profile as profiles

    profiles._reset_execution_profile_for_test()
    yield
    profiles._reset_execution_profile_for_test()


def test_default_profile_keeps_lmm_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.services.execution_profile as profiles

    monkeypatch.delenv("WORKBENCH_EXECUTION_PROFILE", raising=False)
    profiles._reset_execution_profile_for_test()

    profile = profiles.current_execution_profile()

    assert profile.public_status() == {
        "profile": "default",
        "lmm_admitted": False,
        "high_risk_code_admitted": False,
        "canary_status": "not_requested",
    }
    with pytest.raises(profiles.ExecutionProfileError, match="LMM_FROZEN_CONTAINMENT_REQUIRED"):
        profile.require_lmm_admission()


def test_local_contained_requires_and_records_a_passing_canary(monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.services.execution_profile as profiles

    monkeypatch.setenv("WORKBENCH_EXECUTION_PROFILE", "local_contained")
    monkeypatch.setattr(profiles, "_run_local_containment_canary", lambda: None)
    profiles._reset_execution_profile_for_test()

    profile = profiles.current_execution_profile()

    profile.require_lmm_admission()
    assert profile.public_status() == {
        "profile": "local_contained",
        "lmm_admitted": True,
        "high_risk_code_admitted": True,
        "canary_status": "passed",
    }


def test_invalid_profile_is_rejected_without_running_a_canary(monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.services.execution_profile as profiles

    monkeypatch.setenv("WORKBENCH_EXECUTION_PROFILE", "always_on")
    monkeypatch.setattr(
        profiles,
        "_run_local_containment_canary",
        lambda: pytest.fail("invalid profile must not run a canary"),
    )
    profiles._reset_execution_profile_for_test()

    with pytest.raises(profiles.ExecutionProfileError, match="LOCAL_CONTAINMENT_PROFILE_INVALID"):
        profiles.current_execution_profile()


def test_failed_canary_refuses_local_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.services.execution_profile as profiles

    monkeypatch.setenv("WORKBENCH_EXECUTION_PROFILE", "local_contained")
    monkeypatch.setattr(
        profiles,
        "_run_local_containment_canary",
        lambda: (_ for _ in ()).throw(profiles.ExecutionProfileError("LOCAL_CONTAINMENT_CANARY_FAILED")),
    )
    profiles._reset_execution_profile_for_test()

    with pytest.raises(profiles.ExecutionProfileError, match="LOCAL_CONTAINMENT_CANARY_FAILED"):
        profiles.current_execution_profile()


def test_run_submission_boundary_allows_lmm_only_after_local_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.services.execution_profile as profiles
    import workbench.services.run_service as run_service

    monkeypatch.setenv("WORKBENCH_EXECUTION_PROFILE", "local_contained")
    monkeypatch.setattr(profiles, "_run_local_containment_canary", lambda: None)
    profiles._reset_execution_profile_for_test()

    assert run_service._require_lmm_frozen_containment("linear_mixed_effects") == {
        "execution_profile": "local_contained",
        "containment_evidence": "local_startup_canary",
        "release_evaluation_eligible": False,
    }


def test_health_reports_the_process_selected_local_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.services.execution_profile as profiles
    from workbench.app import app

    monkeypatch.setenv("WORKBENCH_EXECUTION_PROFILE", "local_contained")
    monkeypatch.setattr(profiles, "_run_local_containment_canary", lambda: None)
    profiles._reset_execution_profile_for_test()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "control_plane_mode": "single_worker",
        "workers": 1,
        "execution_profile": "local_contained",
        "lmm_admitted": True,
        "high_risk_code_admitted": True,
        "canary_status": "passed",
        "capability_factory": {
            "configured": False,
            "catalog_configured": False,
            "execution_gateway_configured": False,
            "dependency_gate_configured": False,
        },
    }
