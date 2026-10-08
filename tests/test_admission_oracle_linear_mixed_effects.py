"""Independent R admission oracle for linear_mixed_effects; real Workbench workflow."""
import math
import json
import os
import time
import shutil

from fastapi.testclient import TestClient
from workbench.app import app
from pathlib import Path

import pytest
import evidence_retention
from evidence_retention import run_dir
from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.projects import create_project
from workbench.services.lmm_result_adapter import read_lmm_public_results
from workbench.services.server_run_artifacts import read_server_owned_run_artifacts

FIXTURES = Path(__file__).parent / "fixtures/admission/linear_mixed_effects"
ORACLE = read_json(FIXTURES / "oracle.json")
VARIANCE_ORACLE = read_json(FIXTURES / "variance_oracle.json")


@pytest.fixture(scope="module")
def local_contained_profile():
    """Select the contained local profile for this module only; the real
    startup canary still runs. Other modules keep the fail-closed default."""
    import workbench.services.execution_profile as profiles

    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("WORKBENCH_EXECUTION_PROFILE", "local_contained")
        profiles._reset_execution_profile_for_test()
        try:
            yield
        finally:
            patch.undo()
            profiles._reset_execution_profile_for_test()


@pytest.fixture(scope="module")
def fitted(request, tmp_path_factory, local_contained_profile):
    project = create_project(tmp_path_factory.mktemp("oracle-linear_mixed_effects"), "oracle")
    failures_before = request.session.testsfailed
    run_id = None
    try:
        # Only the public run service can issue an admission sealed to this run's
        # executed inputs. An environment profile alone is not that live binding.
        # The service executes the real startup canary; this fixture never mocks it.
        with TestClient(app) as client:
            with (FIXTURES / "data.csv").open("rb") as source:
                submitted = client.post("/runs", data={
                    "project_root": str(project.root), "mode": "auto",
                    "model_type": "linear_mixed_effects", "y": "y", "x": "x",
                    "model_options": json.dumps({"subject_id": "g", "time": "time",
                        "group": "arm", "fit_method": "reml", "random_slope": False}),
                }, files={"file": ("data.csv", source, "text/csv")})
            assert submitted.status_code == 200, submitted.text
            run_id = submitted.json()["run_id"]
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                response = client.get(f"/runs/{run_id}", params={"project_root": str(project.root)})
                assert response.status_code == 200, response.text
                outcome = response.json()
                if outcome["status"] in {"completed", "blocked", "failed"}:
                    break
                time.sleep(0.05)
            else:
                pytest.fail("Host LMM run did not finish within 180 seconds")
        root = project.root / "runs" / run_id
        assert outcome["status"] == "completed", read_json(root / "errors.json")
        manifest = read_json(root / "run_manifest.json")
        assert manifest["execution_profile"] == "local_contained"
        assert manifest["containment_evidence"] == "local_startup_canary"
        read_server_owned_run_artifacts(project.root, run_id, required=True)
        public = read_lmm_public_results(root)
        assert len(public) == 1
        assert public[0]["payload"]["converged"] is True
        result = read_json(root / kernel_relative_path('linear_mixed_effects_1')), public[0]["payload"], root
    except BaseException:
        if run_id is not None:
            _retain_host_run(project.root, run_id, failed_by=request.node.nodeid + " (fixture)")
        raise
    yield result
    # The host run is kept only when a test on it failed or the user asked for
    # it (WORKBENCH_KEEP_EVIDENCE=1); retention is bounded by evidence_retention.
    if request.session.testsfailed > failures_before:
        _retain_host_run(project.root, run_id, failed_by=request.node.nodeid)
    elif os.environ.get("WORKBENCH_KEEP_EVIDENCE") == "1":
        _retain_host_run(project.root, run_id)


def _retain_host_run(project_root, run_id, *, failed_by=None):
    source = project_root / "runs" / run_id
    if not source.is_dir():
        return
    evidence = run_dir("lmm-host")
    retained = evidence / "runs" / run_id
    shutil.copytree(source, retained)
    read_server_owned_run_artifacts(evidence, run_id, required=True)
    if failed_by:
        evidence_retention.STORE.mark_failed("lmm-host", failed_by)
    print("host evidence:", str(retained))

def test_coefficients_and_standard_errors_match_r(fitted):
    fitted, _, _ = fitted
    # Compare equivalent formula terms without changing the persisted names.
    aliases = {"C(Q('arm'), Treatment(reference='a'))[T.b]": "armb",
        "C(Q('arm'), Treatment(reference='a'))[T.b]:Q('time')": "armb:time"}
    names = [aliases.get(name, name) for name in fitted["param_names"]]
    assert set(names) == set(ORACLE["coefficients"]), (names, ORACLE["coefficients"])
    assert fitted["nobs"] == ORACLE["meta"]["n"]
    rows = []
    for index, term in enumerate(names):
        rows.append((term, fitted["params"][index], ORACLE["coefficients"][term],
                     math.sqrt(fitted["vcov"][index][index]), ORACLE["std_error"][term]))
    print("first three coefficients and SE (Workbench / R):", rows[:3])
    print("kernel settings:", {key: fitted.get(key) for key in (
        "covariance_estimator", "df_method", "reference_distribution", "df_resid")})
    print("max absolute differences:", max(abs(a-b) for _,a,b,_,_ in rows),
          max(abs(a-b) for _,_,_,a,b in rows))
    errors = []
    for term, estimate, reference, se, reference_se in rows:
        if abs(estimate-reference) > 1e-8:
            errors.append((term, "estimate", estimate, reference, estimate-reference))
        # The former 1e-4 allowance covered optimizer stopping and the inverse
        # Hessian covariance; both now match lme4, so the 1e-6 gate applies.
        if abs(se-reference_se) > 1e-6 * abs(reference_se):
            errors.append((term, "std_error", se, reference_se, se-reference_se))
    assert not errors, errors


def test_random_intercept_and_residual_variances_match_lme4_reml(fitted):
    kernel, payload, _ = fitted
    assert kernel["nobs"] == VARIANCE_ORACLE["meta"]["nobs"]
    actual = payload["random_effects"]
    assert actual["n_groups"] == VARIANCE_ORACLE["meta"]["n_groups"]
    rows = []
    for name, reference in VARIANCE_ORACLE["random_effects"].items():
        value = actual[name]
        assert math.isfinite(value)
        rows.append((name, value, reference, value-reference))
        # Match the existing REML SE allowance for this optimizer comparison.
        assert abs(value-reference) <= 1e-4, rows
    print("variance components (Workbench / lme4 / difference):", rows)


def test_terms_outside_the_published_estimand_are_not_reported_as_dropped(fitted):
    # The recipe publishes only group x time; x is a fitted fixed effect.
    kernel, _, root = fitted
    assert "x" in kernel["param_names"]
    issues = read_json(root / "errors.json").get("issues", []) if (root / "errors.json").exists() else []
    assert not [issue for issue in issues if issue.get("code") == "VARIABLE_DROPPED"], issues


def test_coefficient_reader_returns_the_published_estimand_unrounded(fitted):
    from workbench.agent.context_tools import _lmm_published_results, _public_requested_model_coefficients

    _, payload, root = fitted
    [result] = _lmm_published_results(root)
    projected = _public_requested_model_coefficients(
        run_id=root.name, result=result, requested_terms=("group_time_interaction",))
    [row] = projected["coefficients"]
    published = payload["coefficients"]["group_time_interaction"]
    assert row["estimate"] == published["estimate"] and row["std_error"] == published["std_error"]
    assert [row["ci_lower"], row["ci_upper"]] == published["confidence_interval"]
    assert row["std_error"] == pytest.approx(ORACLE["std_error"]["armb:time"], rel=1e-6)


def test_result_summary_points_at_the_result_file_that_exists(fitted):
    _, _, root = fitted
    reference = read_json(root / "diagnostic_summary.json")["coefficients_summary"]["full_table_ref"]
    assert (root / reference).is_file(), reference


def test_coefficient_reader_lists_every_fixed_effect_the_kernel_tests(fitted):
    # Wald/lincom/nlcom accept kernel terms; the reader must show them, on the
    # GLS covariance that matches lme4 vcov().
    from workbench.agent.context_tools import _lmm_published_results, _public_requested_model_coefficients

    gls = read_json(Path(__file__).parent / "fixtures/postestimation/lmm_v1811/gls_reference_r.json")["random_intercept_reml"]
    _, _, root = fitted
    [result] = _lmm_published_results(root)
    projected = _public_requested_model_coefficients(run_id=root.name, result=result, requested_terms=("time", "x"))
    assert projected["missing_terms"] == []
    rows = {row["term"]: row for row in projected["coefficients"]}
    for term in ("time", "x"):
        assert rows[term]["estimate"] == pytest.approx(gls["params"][term], abs=1e-8)
        assert rows[term]["std_error"] == pytest.approx(gls["std_error"][term], rel=1e-6)
