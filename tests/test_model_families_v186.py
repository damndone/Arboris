from __future__ import annotations

import io
import json
import math
import time
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.artifacts import read_json
from workbench.api import app
from workbench.agent.context_tools import (
    NodeOperationContextProvider,
    _bounded_model_family_evidence,
)
from workbench.agent.tools import ToolContext
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.v186_model_families import (
    MultinomialResultContract,
    OrdinalDiagnosticsContract,
    OrdinalResultContract,
    QuantileRegressionResultContract,
    SurvivalEvidenceContract,
)
from workbench.services.results_service import read_model_results
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.router import YKind, detect_y_kind


def _run(tmp_path: Path, frame: pd.DataFrame, *, model_type: str, y: str, x: list[str], model_options: dict | None = None) -> Path:
    source = tmp_path / f"{model_type}.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, model_type)
    result = run_workflow(project.root, [source], mode="auto", y=y, x=x, model_type=model_type, model_options=model_options)
    assert result["status"] == "completed", result
    return project.root / "runs" / result["run_id"]


def _agent_model_family_evidence(run_root: Path, model_type: str) -> dict:
    run_id = run_root.name
    provider = NodeOperationContextProvider(run_root.parent.parent)
    tool = next(
        definition
        for definition in provider.tool_definitions(chain_id="v186-agent-chain", session_id="v186-agent-session")
        if definition.tool_id == "inspect_result_summary"
    )
    output = tool.handler(
        {
            "request_id": f"agent-v186-{model_type}",
            "owner_run_id": run_id,
            "op_node_id": f"model:{model_type}_1",
            "active_head_run_id": run_id,
        },
        ToolContext(session_id="v186-agent-session"),
    )
    evidence = output["result_summary"]["model_family_evidence"]
    assert isinstance(evidence, dict)
    return evidence


def test_ordinal_logit_run_persists_probabilities_effects_and_parallel_lines(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "rating": [1, 2, 3, 1, 2, 3, 2, 3, 1, 2, 3, 2] * 5,
        "x": [float(i) / 5 for i in range(60)],
    })
    run_root = _run(tmp_path, frame, model_type="ordinal_logit", y="rating", x=["x"])
    result = read_json(run_root / "model_results" / "ordinal_logit_1.json")
    assert result["model_type"] == "ordinal_logit"
    assert len(result["predicted_probabilities"]) == len(frame)
    assert result["odds_ratios"]
    assert result["marginal_effects"]
    diagnostics = read_json(run_root / "model_results" / "diagnostics_ordinal_logit_1.json")
    assert diagnostics["parallel_lines"]["status"] in {"computed", "insufficient_support"}
    # v1.8.7 A3 replaced the flat "not_verified" with the reference this family
    # is now checked against. What the assertion guards is unchanged: the packet
    # must state its evidence rather than assert correctness bare.
    assert diagnostics["validation"]["level"] == "external_oracle_within_tolerance"
    assert "polr" in diagnostics["validation"]["external_oracle"]
    OrdinalResultContract.from_dict(result)
    OrdinalDiagnosticsContract.from_dict(diagnostics)
    projected = _bounded_model_family_evidence(run_root, read_model_results(run_root))
    assert projected["contract"] == "workbench.ordinal_logit.result.v1"
    assert projected["odds_ratios"] == result["odds_ratios"]
    assert projected["outcome_levels"] == result["outcome_levels"]
    assert projected["parallel_lines"]["method"] == diagnostics["parallel_lines"]["method"]
    assert projected["parallel_lines"]["comparisons"][0]["threshold"] == diagnostics["parallel_lines"]["comparisons"][0]["threshold"]
    agent_evidence = _agent_model_family_evidence(run_root, "ordinal_logit")
    assert agent_evidence["odds_ratios"] == result["odds_ratios"]
    assert agent_evidence["predicted_probabilities"] == result["predicted_probabilities"][:8]
    assert agent_evidence["parallel_lines"]["slope_ranges"] == diagnostics["parallel_lines"]["slope_ranges"]


def test_ordered_model_preserves_numeric_order_and_supports_probit_link(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "rating": [1, 2, 10, 1, 2, 10] * 12,
        "x": [float(i) for i in range(72)],
    })
    run_root = _run(
        tmp_path,
        frame,
        model_type="ordinal_logit",
        y="rating",
        x=["x"],
        model_options={"link": "probit"},
    )
    result = read_json(run_root / "model_results" / "ordinal_logit_1.json")
    assert result["link"] == "probit"
    assert result["outcome_levels"] == ["1", "2", "10"]
    assert result["odds_ratios"] is None
    assert result["predicted_probabilities"]


def test_ordered_logit_persists_odds_ratio_confidence_intervals(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "rating": [1, 2, 3, 1, 2, 3] * 15,
        "x": [float(i % 11) for i in range(90)],
    })
    run_root = _run(tmp_path, frame, model_type="ordinal_logit", y="rating", x=["x"])
    result = read_json(run_root / "model_results" / "ordinal_logit_1.json")
    odds_ratio = result["odds_ratios"]["x"]
    assert {"odds_ratio", "ci_lower", "ci_upper"} <= set(odds_ratio)


def test_multinomial_logit_run_persists_probabilities_rrr_and_marginal_effects(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "choice": ["a" if i % 3 == 0 else "b" if i % 3 == 1 else "c" for i in range(120)],
        "x": [float(i) for i in range(120)],
    })
    run_root = _run(tmp_path, frame, model_type="multinomial_logit", y="choice", x=["x"])
    result = read_json(run_root / "model_results" / "multinomial_logit_1.json")
    assert result["model_type"] == "multinomial_logit"
    assert set(result["predicted_probabilities"]) == {"a", "b", "c"}
    assert result["relative_risk_ratios"]
    assert result["marginal_effects"]
    assert {"relative_risk_ratio", "ci_lower", "ci_upper"} <= set(
        result["relative_risk_ratios"]["a:x"]
    )
    MultinomialResultContract.from_dict(result)
    projected = _bounded_model_family_evidence(run_root, read_model_results(run_root))
    assert projected["contract"] == "workbench.multinomial_logit.result.v1"
    assert projected["relative_risk_ratios"] == result["relative_risk_ratios"]
    assert projected["predicted_probabilities"]["a"] == result["predicted_probabilities"]["a"][:8]
    agent_evidence = _agent_model_family_evidence(run_root, "multinomial_logit")
    assert agent_evidence["relative_risk_ratios"] == result["relative_risk_ratios"]
    assert agent_evidence["predicted_probabilities"] == {
        category: values[:8]
        for category, values in result["predicted_probabilities"].items()
    }


def test_multinomial_coefficients_use_the_declared_base_category(tmp_path: Path) -> None:
    """The coefficient labels must reconstruct the persisted probabilities."""

    frame = pd.DataFrame({
        "choice": ["a" if i % 3 == 0 else "b" if i % 3 == 1 else "c" for i in range(120)],
        "x": [float(i) for i in range(120)],
    })
    run_root = _run(tmp_path, frame, model_type="multinomial_logit", y="choice", x=["x"])
    result = read_json(run_root / "model_results" / "multinomial_logit_1.json")

    intercept_weights = {
        category: math.exp(result["coefficients"][f"{category}:const"]["estimate"])
        for category in ("a", "b")
    }
    denominator = 1.0 + sum(intercept_weights.values())
    expected = {
        "a": intercept_weights["a"] / denominator,
        "b": intercept_weights["b"] / denominator,
        "c": 1.0 / denominator,
    }
    observed = {
        category: result["predicted_probabilities"][category][0]
        for category in ("a", "b", "c")
    }
    assert observed == pytest.approx(expected, rel=0.0, abs=1e-10)


def test_multinomial_logit_honors_explicit_base_category(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "choice": ["a" if i % 3 == 0 else "b" if i % 3 == 1 else "c" for i in range(120)],
        "x": [float(i) for i in range(120)],
    })
    run_root = _run(
        tmp_path,
        frame,
        model_type="multinomial_logit",
        y="choice",
        x=["x"],
        model_options={"base_category": "a"},
    )
    result = read_json(run_root / "model_results" / "multinomial_logit_1.json")
    assert result["base_category"] == "a"


def test_survival_cox_run_persists_km_logrank_risk_and_schoenfeld_evidence(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "duration": [1, 2, 3, 4, 5, 6, 7, 8] * 8,
        "event": [1, 1, 0, 1, 0, 1, 0, 1] * 8,
        "group": [0, 0, 1, 1, 0, 1, 0, 1] * 8,
        "x": [float(i % 5) for i in range(64)],
    })
    run_root = _run(
        tmp_path,
        frame,
        model_type="survival_cox",
        y="duration",
        x=["x"],
        model_options={"event_column": "event", "group_column": "group"},
    )
    evidence = read_json(run_root / "survival" / "evidence.json")
    assert evidence["contract"] == "workbench.survival.v1"
    assert evidence["kaplan_meier"]
    assert "log_rank" in evidence
    assert evidence["risk_set"]
    assert evidence["censoring"]["censored"] > 0
    assert evidence["schoenfeld"]
    projected = _bounded_model_family_evidence(run_root, read_model_results(run_root))
    assert projected["contract"] == "workbench.survival.v1"
    assert projected["censoring"] == evidence["censoring"]
    assert projected["kaplan_meier"][:4] == evidence["kaplan_meier"][:4]
    assert projected["risk_set"][:4] == evidence["risk_set"][:4]
    agent_evidence = _agent_model_family_evidence(run_root, "survival_cox")
    assert agent_evidence["censoring"] == evidence["censoring"]
    assert agent_evidence["log_rank"]["statistic"] == evidence["log_rank"]["statistic"]
    assert agent_evidence["log_rank"]["p_value"] == evidence["log_rank"]["p_value"]
    assert agent_evidence["risk_set"] == evidence["risk_set"]
    assert agent_evidence["schoenfeld"][0]["time_correlation"] == evidence["schoenfeld"][0]["time_correlation"]


def test_survival_cox_matches_r_survival_coxph_oracle_fixture(tmp_path: Path) -> None:
    """Compare the cleaned Cox fixture with R survival::coxph.

    Oracle command (R survival 3.8-3, ties = "breslow"):
    coxph(Surv(duration, event) ~ x, data = unique(df), ties = "breslow")
    The CI tolerance is 1e-14 because R and SciPy can differ in the final
    libm/qnorm bit while the coefficient, standard error, and p-value agree.
    """

    frame = pd.DataFrame({
        "duration": [1, 2, 3, 4, 5, 6, 7, 8] * 8,
        "event": [1, 1, 0, 1, 0, 1, 0, 1] * 8,
        "x": [float(i % 5) for i in range(64)],
    })
    run_root = _run(
        tmp_path,
        frame,
        model_type="survival_cox",
        y="duration",
        x=["x"],
        model_options={"event_column": "event"},
    )
    coefficient = read_json(run_root / "model_results" / "survival_cox_1.json")["coefficients"]["x"]
    oracle = {
        "nobs": 40,
        "estimate": 0.0,
        "std_error": 0.1414213562373095,
        "p_value": 1.0,
        "ci_lower": -0.27718076486993548,
        "ci_upper": 0.27718076486993548,
    }
    assert read_json(run_root / "model_results" / "survival_cox_1.json")["nobs"] == oracle["nobs"]
    assert coefficient["estimate"] == oracle["estimate"]
    assert coefficient["std_error"] == pytest.approx(oracle["std_error"], abs=1e-15)
    assert coefficient["p_value"] == oracle["p_value"]
    assert coefficient["ci_lower"] == pytest.approx(oracle["ci_lower"], abs=1e-14)
    assert coefficient["ci_upper"] == pytest.approx(oracle["ci_upper"], abs=1e-14)


def test_survival_contract_tracks_left_truncation_and_time_to_event(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "duration": [2, 3, 4, 5, 6, 7, 8, 9] * 8,
        "entry": [0, 1, 0, 2, 1, 0, 3, 1] * 8,
        "event": [1, 1, 0, 1, 0, 1, 0, 1] * 8,
        "group": [0, 0, 1, 1, 0, 1, 0, 1] * 8,
        "x": [float(i % 5) for i in range(64)],
    })
    run_root = _run(
        tmp_path,
        frame,
        model_type="survival_cox",
        y="duration",
        x=["x"],
        model_options={
            "event_column": "event",
            "group_column": "group",
            "entry_column": "entry",
        },
    )
    evidence = read_json(run_root / "survival" / "evidence.json")
    assert evidence["entry_column"] == "entry"
    assert evidence["time_to_event"] == {
        "duration_column": "duration",
        "event_column": "event",
        "entry_column": "entry",
    }
    assert any(row["at_risk"] < len(frame) for row in evidence["risk_set"])
    SurvivalEvidenceContract.from_dict(evidence)


def test_quantile_regression_run_persists_multiple_quantiles_bootstrap_and_comparison(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "y": [float(i) + float(i % 4) * 0.3 for i in range(48)],
        "x": [float(i) for i in range(48)],
    })
    run_root = _run(
        tmp_path,
        frame,
        model_type="quantile_regression",
        y="y",
        x=["x"],
        model_options={"quantiles": [0.25, 0.5, 0.75], "bootstrap_reps": 12, "random_state": 7},
    )
    result = read_json(run_root / "model_results" / "quantile_regression_1.json")
    assert result["quantiles"] == [0.25, 0.5, 0.75]
    assert set(result["fits"]) == {"0.25", "0.5", "0.75"}
    assert result["bootstrap"]["repetitions"] == 12
    assert result["bootstrap"]["successful_repetitions"]
    assert result["confidence_intervals"]
    assert result["reference_quantile"] == 0.5
    assert result["cross_quantile_comparisons"]
    assert read_json(run_root / "model_results" / "diagnostics_quantile_regression_1.json")["status"] == "family_owned"
    QuantileRegressionResultContract.from_dict(result)
    projected = _bounded_model_family_evidence(run_root, read_model_results(run_root))
    assert projected["contract"] == "workbench.quantile_regression.result.v1"
    assert projected["cross_quantile_comparisons"]
    agent_evidence = _agent_model_family_evidence(run_root, "quantile_regression")
    assert agent_evidence["quantiles"] == result["quantiles"]
    assert agent_evidence["fits"]["0.5"]["coefficients"]["x"]["ci_lower"] == result["fits"]["0.5"]["coefficients"]["x"]["ci_lower"]
    assert agent_evidence["fits"]["0.5"]["coefficients"]["x"]["ci_upper"] == result["fits"]["0.5"]["coefficients"]["x"]["ci_upper"]
    assert agent_evidence["cross_quantile_comparisons"] == result["cross_quantile_comparisons"]


def test_survival_cox_fails_closed_when_event_column_is_missing(tmp_path: Path) -> None:
    frame = pd.DataFrame({
        "duration": [1, 2, 3, 4, 5, 6, 7, 8] * 8,
        "x": [float(i % 5) for i in range(64)],
    })
    source = tmp_path / "survival.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "survival-missing-event")
    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="duration",
        x=["x"],
        model_type="survival_cox",
    )
    assert result["status"] == "failed"
    issues = read_json(project.root / "runs" / result["run_id"] / "errors.json")["issues"]
    assert issues[0]["code"] == "SURVIVAL_EVENT_REQUIRED"


def test_survival_packet_contract_rejects_unverified_external_claim() -> None:
    with pytest.raises(ContractError):
        SurvivalEvidenceContract.from_dict({"contract": "workbench.survival.v1"})


def test_auto_y_type_detection_distinguishes_ordered_and_nominal_categories() -> None:
    ordered = pd.DataFrame({
        "rating": pd.Categorical(["low", "medium", "high"],
                                  categories=["low", "medium", "high"],
                                  ordered=True),
    })
    nominal = pd.DataFrame({"choice": ["red", "blue", "green"]})

    assert detect_y_kind(ordered, "rating") is YKind.ORDINAL
    assert detect_y_kind(nominal, "choice") is YKind.NOMINAL


def _http_family_run(
    tmp_path: Path,
    *,
    name: str,
    frame: pd.DataFrame,
    y: str,
    x: str,
    model_type: str,
    model_options: dict[str, object] | None = None,
) -> dict:
    client = TestClient(app)
    project_root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": name}
    ).json()["project_root"]
    response = client.post(
        "/runs",
        data={
            "project_root": project_root,
            "mode": "auto",
            "model_type": model_type,
            "y": y,
            "x": x,
            "model_options": json.dumps(model_options or {}),
        },
        files={"file": (f"{name}.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    for _ in range(240):
        detail = client.get(f"/runs/{run_id}", params={"project_root": project_root}).json()
        if detail.get("status") in {"completed", "failed", "blocked", "partial", "interrupted"}:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"HTTP model-family run did not terminate: {run_id}")


@pytest.mark.parametrize(
    ("name", "frame", "y", "model_type", "options", "evidence_keys"),
    [
        (
            "http-ordinal",
            pd.DataFrame({"rating": [1, 2, 3, 1, 2, 3] * 12, "x": [float(i) for i in range(72)]}),
            "rating",
            "ordinal_logit",
            {},
            {"parallel_lines", "outcome_levels"},
        ),
        (
            "http-multinomial",
            pd.DataFrame({"choice": ["a", "b", "c"] * 40, "x": [float(i) for i in range(120)]}),
            "choice",
            "multinomial_logit",
            {"base_category": "a"},
            {"relative_risk_ratios", "predicted_probabilities"},
        ),
        (
            "http-survival",
            pd.DataFrame({
                "duration": [1, 2, 3, 4, 5, 6, 7, 8] * 8,
                "event": [1, 1, 0, 1, 0, 1, 0, 1] * 8,
                "group": [0, 0, 1, 1, 0, 1, 0, 1] * 8,
                "x": [float(i % 5) for i in range(64)],
            }),
            "duration",
            "survival_cox",
            {"event_column": "event", "group_column": "group"},
            {"kaplan_meier", "risk_set", "censoring"},
        ),
        (
            "http-quantile",
            pd.DataFrame({"y": [float(i) + float(i % 4) * 0.3 for i in range(48)], "x": [float(i) for i in range(48)]}),
            "y",
            "quantile_regression",
            {"quantiles": [0.25, 0.5, 0.75], "bootstrap_reps": 4, "random_state": 7},
            {"quantiles", "bootstrap", "cross_quantile_comparisons"},
        ),
    ],
)
def test_model_family_packets_are_reachable_from_real_http_run(
    tmp_path: Path,
    name: str,
    frame: pd.DataFrame,
    y: str,
    model_type: str,
    options: dict[str, object],
    evidence_keys: set[str],
) -> None:
    detail = _http_family_run(
        tmp_path,
        name=name,
        frame=frame,
        y=y,
        x="x",
        model_type=model_type,
        model_options=options,
    )
    assert detail["status"] == "completed", detail
    assert any(row.get("model_type") == model_type for row in detail["model_results"])
    evidence = detail["model_family_evidence"]
    assert isinstance(evidence, dict)
    assert evidence_keys <= set(evidence)


def test_ordinal_logit_thresholds_are_named_by_the_declared_outcome_levels(tmp_path: Path) -> None:
    """Cutpoints must be labelled with the levels a reader can actually see.

    Naming them from the internal 0-based codes points users at an outcome
    level that does not exist in their data.
    """
    frame = pd.DataFrame({
        "rating": [1, 2, 3, 1, 2, 3, 2, 3, 1, 2, 3, 2] * 5,
        "x": [float(i) / 5 for i in range(60)],
    })
    run_root = _run(tmp_path, frame, model_type="ordinal_logit", y="rating", x=["x"])
    result = read_json(run_root / "model_results" / "ordinal_logit_1.json")

    assert result["outcome_levels"] == ["1", "2", "3"]
    threshold_names = [name for name in result["coefficients"] if "/" in name]
    assert threshold_names == ["1/2", "2/3"], threshold_names
    assert "0/1" not in result["coefficients"]


def test_multinomial_logit_does_not_report_an_estimated_variable_as_dropped(tmp_path: Path) -> None:
    """A predictor that has coefficients was not dropped.

    Multinomial coefficients are named "<outcome>:<term>", so a name-equality
    check reads every estimated predictor as collinear and tells the user their
    variable was discarded.
    """
    frame = pd.DataFrame({
        "choice": ["a" if i % 3 == 0 else "b" if i % 3 == 1 else "c" for i in range(120)],
        "x": [float(i) for i in range(120)],
    })
    run_root = _run(tmp_path, frame, model_type="multinomial_logit", y="choice", x=["x"])
    result = read_json(run_root / "model_results" / "multinomial_logit_1.json")
    assert any(name.endswith(":x") for name in result["coefficients"])

    errors_path = run_root / "errors.json"
    issues = read_json(errors_path)["issues"] if errors_path.exists() else []
    dropped = [
        issue for issue in issues
        if issue.get("code") == "VARIABLE_DROPPED"
        and issue.get("evidence", {}).get("variable") == "x"
    ]
    assert dropped == [], dropped
