"""Independent public count integration attacks, not statistical redefinition.

Fresh projects and assets are temporary. Original fixtures and production are
read-only. Existing real R/Stata references anchor unchanged numerical cases.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.artifacts import read_json, write_json
from workbench.agent.family_evidence import bounded_model_family_evidence
from workbench.agent.workflow import compile_workflow, WorkflowExecutionError
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.agent.postestimation_steps import execute_postestimation_step
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.lineage.run_inputs import read_run_inputs, write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes
from workbench.model_options import bind_new_model_options, verify_bound_model_options, ModelOptionsError
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
POST = FIXTURES / "postestimation/data.csv"
FRACTIONAL = FIXTURES / "count_models/p1-remediation-20261004/fractional-oracle"


def fit(project, source, family, y, x, **extra):
    outcome = run_workflow(project, [source], mode="auto", model_type=family, y=y, x=x, **extra)
    run_root = project / "runs" / outcome["run_id"]
    assert outcome["status"] == "completed", read_json(run_root / "errors.json")
    model_id = ("glm" if family.startswith("glm:") else family) + "_1"
    packet = read_json(run_root / f"model_results/{model_id}.json")
    kernel = read_json(run_root / kernel_relative_path(model_id))
    print(json.dumps({"run_root": str(run_root), "family": family, "outcome": y,
        "param_names": kernel["param_names"], "dispersion": packet.get("dispersion"),
        "alpha_fixed_value": packet.get("alpha_fixed_value")}, allow_nan=False))
    return run_root, packet, kernel


def post(project, run_id, operation, **spec):
    step = SimpleNamespace(operation_id="postestimation." + operation,
                           spec={"model_ref": "model:glm_1", **spec}, depends_on=())
    return execute_postestimation_step(project, run_id, step)[0]


@pytest.mark.parametrize("family,source,options", [
    ("negative_binomial", FIXTURES / "count_models/reference-v3/nb1.csv", {"dispersion": "constant"}),
    ("negative_binomial", FRACTIONAL / "data.csv", {"alpha": .5}),
    ("glm:negative_binomial", FRACTIONAL / "data.csv", {"alpha": .5}),
])
def test_http_reaches_actual_owner_and_preserves_fractional_support(tmp_path, family, source, options):
    client = TestClient(app)
    project = client.post("/projects", json={"parent": str(tmp_path), "name": "review"}).json()["project_root"]
    response = client.post("/runs", data={"project_root": project, "mode": "auto",
        "model_type": family, "y": "y", "x": '["x1","x2"]',
        "model_options": json.dumps(options)}, files={"file": (source.name, source.read_bytes(), "text/csv")})
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + 30
    detail = {}
    while time.monotonic() < deadline:
        detail = client.get(f"/runs/{run_id}", params={"project_root": project}).json()
        if detail.get("status") in {"completed", "failed", "blocked", "partial"}:
            break
        time.sleep(.05)
    assert detail.get("status") == "completed", detail.get("errors")
    root = Path(project) / "runs" / run_id
    model_id = "glm_1" if family.startswith("glm:") else "negative_binomial_1"
    packet = read_json(root / f"model_results/{model_id}.json")
    executed = read_run_inputs(root)["form"]
    assert executed["model_options"] == options
    assert executed["model_options_binding"]["owner_model_id"] == model_id
    assert packet["dispersion"] == options.get("dispersion", "mean")
    if "alpha" in options:
        assert packet["alpha_fixed_value"] == .5 and not packet["alpha_estimated"]
        native = read_json(FRACTIONAL / "stata.json")
        for term, ref in [("Intercept", "_cons"), ("x1", "x1"), ("x2", "x2")]:
            assert abs(packet["coefficients"][term]["estimate"] - native["b_" + ref]) < 1e-8
    print(json.dumps({"http_run": str(root), "options": options, "status": detail["status"]}))


@pytest.mark.parametrize("family,options", [
    ("negative_binomial", {"dispersion": "constant"}),
    ("glm:negative_binomial", {"alpha": .5}),
])
def test_agent_spec_and_execution_frame_share_options(tmp_path, family, options):
    from tests.test_data_column_cast import _source_project
    source = FIXTURES / "count_models/reference-v3/nb1.csv" if "dispersion" in options else FRACTIONAL / "data.csv"
    frame = pd.read_csv(source, float_precision="round_trip")
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    upload = store_upload_bytes(project, source.read_bytes(), filename=source.name)
    write_run_inputs(project / "runs" / run_id, form={"model_type": "auto", "y": "", "x": ""},
        upload={"sha256": upload, "filename": source.name}, rerun_of=None, from_node=None,
        rerun_reason="initial", override_hash=None, dag_hash="independent-count-review")
    draft = compile_workflow(workflow_id="count-review-genesis",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:count-review", "active_head_run_id": run_id,
            "owner_resolution": "single_candidate"}, available_columns=list(frame),
        steps=[{"step_id": "estimate", "operation_id": "model.genesis", "spec": {
            "model_family": family, "model_options": options,
            "branches": [{"branch_id": "a", "outcome": "y", "predictors": ["x1", "x2"]}]}}])
    result = build_workflow_step_executor(project, draft)(draft.steps[0], {})
    branch = result.payload["branches"][0]
    packet = read_json(project / "runs" / branch["run_id"] / f'model_results/{branch["model_id"]}.json')
    assert packet["dispersion"] == options.get("dispersion", "mean")
    if "alpha" in options:
        assert packet["alpha_fixed_value"] == .5 and not packet["alpha_estimated"]
    print(json.dumps({"agent_branch": branch, "options": options}))


@pytest.mark.parametrize("name", ["alpha", "lnalpha", "delta", "lndelta"])
def test_persisted_beta_kernel_keeps_ordinary_ancillary_named_regressors(tmp_path, name):
    frame = pd.read_csv(POST, float_precision="round_trip").rename(columns={"x1": name})
    source = tmp_path / "named.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path / "projects", "named").root
    _, packet, kernel = fit(project, source, "negative_binomial", "ynb", [name, "x2", "x3"])
    native = read_json(FIXTURES / "count_models/integration-strict-v1811/native-reference/nb2-postestimation-reference.json")["full_precision"]
    assert kernel["param_names"] == ["Intercept", name, "x2", "x3"]
    assert kernel["params"][1] == pytest.approx(float(native["params"]["x1"]), abs=1e-6)
    np.testing.assert_allclose(kernel["vcov"], np.asarray(native["beta_vcov"], float), rtol=1e-4)
    assert packet["coefficients"][name]["std_error"] == pytest.approx(np.sqrt(kernel["vcov"][1][1]), rel=1e-12)


def test_unbound_default_and_null_alpha_preserve_nb2_legacy(tmp_path):
    project = create_project(tmp_path, "legacy").root
    a, first, ka = fit(project, POST, "negative_binomial", "ynb", ["x1", "x2", "x3"])
    b, second, kb = fit(project, POST, "negative_binomial", "ynb", ["x1", "x2", "x3"], model_options={"alpha": None})
    assert first["dispersion"] == second["dispersion"] == "mean"
    assert first["alpha_estimated"] and second["alpha_estimated"]
    assert ka["params"] == kb["params"] and ka["vcov"] == kb["vcov"]
    assert not read_run_inputs(a)["form"].get("model_options_binding")


def test_bound_fixed_alpha_cannot_be_replaced_without_rebinding():
    bound = bind_new_model_options("negative_binomial", {"alpha": .5})
    with pytest.raises(ModelOptionsError):
        verify_bound_model_options({"alpha": .7}, bound.binding.to_dict())


@pytest.mark.parametrize("family,options", [
    ("negative_binomial", {"dispersion": "constant", "alpha": .5}),
    ("glm:negative_binomial", {}), ("glm:negative_binomial", {"alpha": None}),
])
def test_public_invalid_modes_do_not_create_success_packets(tmp_path, family, options):
    project = create_project(tmp_path, "invalid").root
    try:
        result = run_workflow(project, [POST], mode="auto", model_type=family,
            y="ynb", x=["x1", "x2", "x3"], model_options=options)
    except ModelOptionsError:
        return
    assert result["status"] == "failed", result
    root = project / "runs" / result["run_id"]
    assert not (root / "model_results/glm_1.json").exists()
    assert not (root / "model_results/negative_binomial_1.json").exists()


def test_numeric_range_warning_reaches_public_evidence_and_shared_issues(tmp_path, monkeypatch):
    from workbench.econometrics import count_models
    # Metadata transport probe: keep the certified fit/OIM, induce only the CI
    # representation branch. This is not a new statistical reference case.
    monkeypatch.setattr(count_models, "_exp_confidence_limit", lambda log_limit: None)
    project = create_project(tmp_path, "warning").root
    root, packet, _ = fit(project, POST, "negative_binomial", "ynb", ["x1", "x2", "x3"])
    code = "NB_ANCILLARY_CI_NUMERIC_RANGE"
    assert any(w["code"] == code for w in packet["warnings"])
    bounded = bounded_model_family_evidence(root, [packet])
    issues = read_json(root / "errors.json")["issues"]
    print(json.dumps({"raw_warnings": packet["warnings"], "bounded": bounded, "issues": issues}))
    assert code in json.dumps(bounded), "Agent auxiliary null limits lost their explicit reason"
    assert any(issue.get("code") == code for issue in issues), "UI shared warnings omit the owner warning"


@pytest.fixture(scope="module")
def glm_runs(tmp_path_factory):
    project = create_project(tmp_path_factory.mktemp("count-glm-owners"), "glm").root
    runs = {}
    for key, family, y, x in [
        ("poisson", "glm:poisson", "yc", ["x1", "x2", "x3"]),
        ("restricted", "glm:poisson", "yc", ["x1"]),
        ("other_outcome", "glm:poisson", "yb", ["x1", "x2", "x3"]),
        ("binomial", "glm:binomial", "yb", ["x1", "x2", "x3"]),
    ]:
        runs[key] = fit(project, POST, family, y, x)
    return project, runs


@pytest.mark.parametrize("key", ["poisson", "binomial"])
def test_glm_operations_resolve_exact_persisted_owner_and_no_nb_admission(glm_runs, key):
    from workbench.postestimation.registry import VALIDATED
    project, runs = glm_runs
    root, packet, kernel = runs[key]
    specs = {"wald": {"constraints": [{"terms": {"x1": 1}, "value": 0}]},
        "lincom": {"terms": {"x1": 1}, "constant": .125},
        "nlcom": {"expression": "exp(x1)"}, "margins": {"variables": ["x1"], "at": "means"}}
    for operation, spec in specs.items():
        value = post(project, root.name, operation, **spec)
        assert value["model_id"] == kernel["model_id"] == "glm_1"
        assert value["model_type"] == packet["kernel_family"] == "glm:" + key
        json.dumps(value, allow_nan=False)
    assert not any(family == "glm:negative_binomial" for family, operation in VALIDATED)
    if key == "poisson":
        value = post(project, root.name, "lr", restricted_model_ref="model:glm_1",
                     restricted_model_run_id=runs["restricted"][0].name)
        assert value["df"] == 2 and value["statistic"] > 0


def test_glm_lr_refuses_different_outcomes_even_with_same_rows_and_nested_names(glm_runs):
    project, runs = glm_runs
    full = runs["other_outcome"][0]
    restricted = runs["restricted"][0]
    with pytest.raises(WorkflowExecutionError, match="outcome|response|nested|comparable"):
        value = post(project, full.name, "lr", restricted_model_ref="model:glm_1",
                     restricted_model_run_id=restricted.name)
        print(json.dumps({"invalid_different_outcome_LR": value, "full_y": "yb", "restricted_y": "yc"}))


def test_glm_lr_refuses_cross_family_kernel(glm_runs):
    project, runs = glm_runs
    with pytest.raises(WorkflowExecutionError, match="different kinds|not comparable"):
        post(project, runs["binomial"][0].name, "lr", restricted_model_ref="model:glm_1",
             restricted_model_run_id=runs["restricted"][0].name)


def test_new_kernel_loader_refuses_other_model_identity(tmp_path, glm_runs):
    from workbench.agent.postestimation_steps import _load_kernel
    _, runs = glm_runs
    kernel = deepcopy(runs["poisson"][2])
    kernel["model_id"] = "logit_999"
    path = tmp_path / kernel_relative_path("glm_1")
    path.parent.mkdir(parents=True)
    write_json(path, kernel)
    with pytest.raises(WorkflowExecutionError, match="identity|owner|match"):
        _load_kernel(tmp_path, "glm_1")
