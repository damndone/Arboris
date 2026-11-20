"""The outcome_family playbook against real Logit and Probit fits, not hand-built payloads.

binary_logit.open.r1 (501cdda6 round, 2026-11-08): the Agent fitted Logit and a Probit
comparison, and the gate still reported no distinct sensitivity fit for 40 requests,
because these fits write no point_estimation_fingerprint. The unit fixtures had one.
"""
import hashlib

import numpy as np
import pandas as pd
import pytest

from workbench.agent import completion
from workbench.agent.completion_outcome import OUTCOME_FAMILY
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

DISTINCT = f"{OUTCOME_FAMILY}:sensitivity:distinct_point_estimation"


@pytest.fixture(scope="module")
def fits(tmp_path_factory):
    root = tmp_path_factory.mktemp("outcome-real")
    rng = np.random.default_rng(20261108)
    income = rng.normal(50, 15, 600)
    age = rng.integers(22, 70, 600)
    owns = (rng.random(600) < 1 / (1 + np.exp(-(-3 + 0.06 * income)))).astype(int)
    source = root / "binary.csv"
    pd.DataFrame({"owns_home": owns, "income_k": income, "age": age}).to_csv(source, index=False)
    project = create_project(root, "outcome")
    runs = {}
    for name, model_type in (("logit", "logit"), ("probit", "probit"), ("logit_again", "logit")):
        outcome = run_workflow(project.root, [source], mode="auto", model_type=model_type,
                               y="owns_home", x=["income_k", "age"])
        assert outcome["status"] == "completed", outcome
        runs[name] = {"run_id": outcome["run_id"], "artifact_id": f"{model_type}_1"}
    data = project.root / "runs" / runs["logit"]["run_id"] / "processed/cleaned_dataset.parquet"
    contract = {"playbooks": [OUTCOME_FAMILY], "source": {
        "run_id": runs["logit"]["run_id"], "artifact_id": "cleaned_dataset",
        "sha256": hashlib.sha256(data.read_bytes()).hexdigest()}}
    return project.root, contract, runs


def test_a_probit_comparison_is_a_distinct_point_estimation(fits):
    root, contract, runs = fits
    evidence = {"models": [runs["logit"]], "sensitivity": [runs["probit"]]}
    assert DISTINCT not in completion.evaluate(root, contract, evidence)["missing"]


def test_the_models_the_agent_named_together_bind_logit_primary_and_probit_comparison(fits):
    # The recorded update_plan put both fits under models.
    root, contract, runs = fits
    evidence, _ = completion.derive_evidence(root, contract, {"models": [runs["logit"], runs["probit"]]})
    assert evidence["models"] == [runs["logit"]] and runs["probit"] in evidence["sensitivity"]
    result = completion.evaluate(root, contract, evidence)
    assert DISTINCT not in result["missing"]
    assert f"{OUTCOME_FAMILY}:diagnostics:computed_and_model_bound" not in result["missing"]


def test_refitting_the_same_specification_is_not_a_comparison(fits):
    root, contract, runs = fits
    evidence = {"models": [runs["logit"]], "sensitivity": [runs["logit_again"]]}
    assert DISTINCT in completion.evaluate(root, contract, evidence)["missing"]


def test_the_repair_names_the_rerun_to_another_serving_family(fits):
    # The prepared options here are new specifications (model.genesis), which that project refused.
    root, contract, runs = fits
    result = completion.evaluate(root, contract, {"models": [runs["logit"]]}, suggest=True, options=True)
    repair = next(step for step in result["repair_steps"] if step["reason"] == "no_distinct_sensitivity_fit")
    assert "model.rerun" in repair["action"] and "probit" in repair["action"] and "logit," not in repair["action"]


def _execute(root, contract, workflow_id, steps):
    from workbench.agent.workflow import WorkflowExecutor, compile_workflow
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    draft = compile_workflow(workflow_id=workflow_id, target={**{k: contract["source"][k] for k in ("run_id", "artifact_id")},
                                                              "node_ref": "stage:cleaned"},
                             preconditions={"context_fingerprint": "fp"}, steps=steps,
                             available_columns=["owns_home", "income_k", "age"])
    state = WorkflowExecutor(root).execute(draft, build_workflow_step_executor(root, draft))
    assert state.status == "completed", state
    return state


def test_the_gate_s_own_report_over_a_descriptive_result_runs_and_completes_the_analysis(fits):
    # b25d3a1b round, binary_logit.open.r1: the gate bound the Agent's statistical.explore results and asked for
    # a report covering them; report.compose refused them as diagnostics, so no report could ever satisfy it.
    root, contract, runs = fits
    state = _execute(root, contract, "wf-explore", [{"step_id": "describe", "operation_id": "statistical.explore",
        "spec": {"operation": "summarize_detail", "selected_columns": ["owns_home", "income_k"]}, "depends_on": []}])
    explored = [{"run_id": contract["source"]["run_id"], "artifact_id": name}
                for name in state.steps["describe"].artifact_ids if name.startswith("statistical_exploration_")
                and not name.endswith(("_html", "_pdf", "_xlsx")) and "transcript" not in name]
    assert explored
    given = {"models": [runs["logit"], runs["probit"]], "results": explored}
    evidence, notes = completion.derive_evidence(root, contract, given)
    spec = notes["compose_report"]["spec"]
    assert any(ref["artifact_id"] == explored[0]["artifact_id"] for ref in spec["result_refs"])
    from workbench.agent.report_sources import collect_report_sources
    rows = collect_report_sources(root, contract["source"], spec["result_refs"])["diagnostic_rows"]
    assert {ref["artifact_id"] for ref in spec["result_refs"] if ref["role"] == "diagnostic"} <= {
        row["artifact_id"] for row in rows}
    _execute(root, contract, "wf-report", [{"step_id": "report", "operation_id": "report.compose", "spec": spec,
                                            "depends_on": []}])
    evidence, notes = completion.derive_evidence(root, contract, given)
    assert "report" in notes["bound_by_workbench"]
    assert completion.evaluate(root, contract, evidence)["missing"] == []


def test_a_large_reference_cannot_take_every_report_row():
    # b25d3a1b binary_logit.open.r1: one exploration and the fit checks took all 128 rows; the margins got none.
    from workbench.agent.report_sources import MAX_EVIDENCE_ROWS, _shares
    shares = _shares([3, 57, 82, 15, 14], MAX_EVIDENCE_ROWS)
    assert sum(shares) == MAX_EVIDENCE_ROWS and shares[0] == 3 and shares[3:] == [15, 14]
    assert _shares([10, 20], MAX_EVIDENCE_ROWS) == [10, 20]


DIAGNOSED = f"{OUTCOME_FAMILY}:diagnostics:computed_and_model_bound"


def _model_diagnostic(root, ref):
    from workbench.agent.completion import _Products
    diagnostic = {"run_id": ref["run_id"], "artifact_id": f"diagnostics_{ref['artifact_id']}"}
    assert _Products(root).load(diagnostic).artifact_type == "model_diagnostic"
    return diagnostic


def test_naming_the_fit_s_diagnostics_still_binds_its_check_record(fits):
    # 428ee909 round, binary_logit.open.r1: the Agent named diagnostics_logit_1, which made the gate skip
    # checks_logit_1, the record outcome_family reads; it reported the diagnostics missing for 30+ requests.
    root, contract, runs = fits
    given = {"models": [runs["logit"]], "sensitivity": [runs["probit"]],
             "diagnostics": [_model_diagnostic(root, runs["logit"])]}
    evidence, _ = completion.derive_evidence(root, contract, given)
    assert {"run_id": runs["logit"]["run_id"], "artifact_id": "checks_logit_1"} in evidence["diagnostics"]
    assert DIAGNOSED not in completion.evaluate(root, contract, evidence)["missing"]


def test_the_catalog_shows_the_check_record_that_meets_the_requirement(fits):
    root, contract, runs = fits
    evidence = {"models": [runs["logit"]], "diagnostics": [_model_diagnostic(root, runs["logit"])]}
    catalog = completion.evaluate(root, contract, evidence, suggest=True)["evidence_catalog"]
    entry = next(m for m in catalog["models"] if m["ref"] == runs["logit"])
    assert {"run_id": runs["logit"]["run_id"], "artifact_id": "checks_logit_1"} in entry["diagnostics"]
    assert entry["diagnostics_meet_requirements"] is True


def test_missing_outcome_diagnostics_come_with_the_exact_reference(fits):
    root, contract, runs = fits
    evidence = {"models": [runs["logit"]], "diagnostics": [_model_diagnostic(root, runs["logit"])]}
    result = completion.evaluate(root, contract, evidence, suggest=True)
    assert DIAGNOSED in result["missing"]
    repair = next(step for step in result["repair_steps"] if step["reason"] == "fit_checks_not_bound")
    assert repair["diagnostics"] == [{"run_id": runs["logit"]["run_id"], "artifact_id": "checks_logit_1"}]


def test_with_no_outcome_fit_the_repair_names_the_existing_model_to_refit(tmp_path):
    # 7821c4c7 round, binary_logit.open.r3: model.genesis was denied, the gate's repair said "bind an eligible
    # primary" with no candidates, and the Agent never refitted the imported OLS with Logit; it ran only tests.
    rng = np.random.default_rng(20261109)
    income = rng.normal(50, 15, 400)
    owns = (rng.random(400) < 1 / (1 + np.exp(-(-3 + 0.06 * income)))).astype(int)
    source = tmp_path / "binary.csv"
    pd.DataFrame({"owns_home": owns, "income_k": income}).to_csv(source, index=False)
    project = create_project(tmp_path, "unserved")
    outcome = run_workflow(project.root, [source], mode="auto", model_type="ols", y="owns_home", x=["income_k"])
    assert outcome["status"] == "completed", outcome
    run_id = outcome["run_id"]
    data = project.root / "runs" / run_id / "processed/cleaned_dataset.parquet"
    contract = {"playbooks": [OUTCOME_FAMILY], "source": {"run_id": run_id, "artifact_id": "cleaned_dataset",
                                                        "sha256": hashlib.sha256(data.read_bytes()).hexdigest()}}
    result = completion.evaluate(project.root, contract, {}, suggest=True)
    repair = next(step for step in result["repair_steps"] if step["reason"] == "no_eligible_primary")
    assert repair["refit"] == {"operation_id": "model.rerun", "owner_run_id": run_id, "op_node_id": "model:ols_1"}
    assert "model.rerun" in repair["action"] and "logit" in repair["action"]
