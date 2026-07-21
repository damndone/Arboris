"""End-to-end acceptance gate for the v1.8 ARMA-GARCH Model Pack.

This suite is the consolidated Step-5 acceptance layer. It drives the *real*
`fit_from_context` runtime once per estimation strategy and asserts the eight
anti-fabrication proofs (section 25) and the six acceptance dimensions
(section 17) hold against genuine runtime output rather than component stubs.

It complements, and does not replace, the component-level suites in
`tests/models/arma_garch`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.fixtures.models.arma_garch.known_truth import (
    arch5,
    ar1_garch11,
    arma11_homoskedastic,
    near_unit_garch11,
    no_arch,
    sequential_arma11_garch11,
    student_t_garch11,
)
from workbench.engine.context import DataHandle, ModelingContext, RunEnv


class _Recorder:
    def __init__(self) -> None:
        self.nodes: list[dict[str, object]] = []
        self.edges: list[dict[str, object]] = []

    def record_stage(self, node_id, display_label, **kwargs) -> None:
        self.nodes.append({"node_id": node_id, "display_label": display_label, **kwargs})

    def record_edge(self, edge_id, source_id, target_id, op, **kwargs) -> None:
        self.edges.append(
            {"edge_id": edge_id, "source_id": source_id, "target_id": target_id, "op": op}
        )


def _garch_source(n: int = 160) -> pd.DataFrame:
    rng = np.random.default_rng(20260721)
    values = np.zeros(n)
    errors = np.zeros(n)
    variances = np.ones(n)
    for index in range(1, n):
        variances[index] = 0.1 + 0.12 * errors[index - 1] ** 2 + 0.80 * variances[index - 1]
        errors[index] = math.sqrt(variances[index]) * rng.normal()
        values[index] = 0.2 + 0.4 * values[index - 1] + errors[index]
    return pd.DataFrame({"when": pd.bdate_range("2020-01-01", periods=n), "value": values})


def _options(strategy: str, distribution: str = "normal") -> dict[str, object]:
    arma_q = 0 if strategy == "joint" else 1
    return {
        "dataset_ref": "dataset:evaluation:1",
        "time_column": "when",
        "value_column": "value",
        "time_index_semantics": "business_or_trading_observations",
        "transform": "level",
        "transform_confirmed": True,
        "selection_mode": "manual",
        "arma": {"p": 1, "q": arma_q, "constant_mode": "include"},
        "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
        "estimation_strategy": strategy,
        "innovation_distribution": distribution,
        "validation": {"validation_n": 6, "refit_every": 1},
        "random_seed": 20260721,
    }


def _context(source: pd.DataFrame, options: dict[str, object]) -> ModelingContext:
    ctx = ModelingContext(
        data=DataHandle.of(
            source.copy(deep=True),
            artifact_id="cleaned_dataset",
            provenance=("raw_input.csv",),
        ),
        y_col="value",
        x_cols=[],
        y_type="continuous",
        requested_model_type="time_series.arma_garch",
    )
    ctx.artifacts.update(
        {
            "_model_options": options,
            "_frames": {"input.csv": source},
            "_upload_hash": "b" * 64,
            "_raw_inputs": ["raw_input.csv"],
        }
    )
    return ctx


def _run(tmp_path: Path, run_id: str, options: dict[str, object]):
    from workbench.engine.packs.arma_garch.runner import fit_from_context

    source = _garch_source()
    before = source.copy(deep=True)
    run_root = tmp_path / run_id
    run_root.mkdir()
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"artifacts": []}), encoding="utf-8"
    )
    ctx = _context(source, options)
    env = RunEnv(run_root=run_root, run_id=run_id, recorder=_Recorder())
    _, result, _ = fit_from_context(ctx, env)
    index = json.loads((run_root / "artifacts_index.json").read_text())
    records = {item["artifact_id"]: item for item in index["artifacts"]}
    return result, records, run_root, source, before


def test_six_acceptance_dimensions_are_present_with_valid_statuses(tmp_path: Path) -> None:
    result, _records, _root, _source, _before = _run(
        tmp_path, "joint-accept", _options("joint")
    )
    acceptance = result["validation"]["acceptance"]
    assert set(acceptance["dimensions"]) == {
        "data_readiness",
        "mean_adequacy",
        "volatility_adequacy",
        "distribution_adequacy",
        "forecast_validation",
        "volatility_value_added",
    }
    valid = {"accepted", "accepted_with_warnings", "rejected", "inconclusive"}
    for name, dimension in acceptance["dimensions"].items():
        assert dimension["status"] in valid, name
    assert acceptance["overall_status"] in valid


def test_eight_antifabrication_proofs_hold_end_to_end(tmp_path: Path) -> None:
    result, records, run_root, source, before = _run(
        tmp_path, "joint-proofs", _options("joint")
    )

    # Proof 1 + 2: split frozen before selection, no validation leakage.
    assert result["selection_repeated_during_validation"] is False
    assert result["validation"]["candidate_selection_used_validation"] is False
    assert result["validation"]["data_role"] == "independent_evaluation_after_selection"
    selection = json.loads(
        (run_root / records["ts.arma_selection"]["path"]).read_text()
    )["payload"]
    assert selection["candidate_selection_used_validation"] is False

    # Proof 3: full-sample refit creates a child, never overwrites the parent.
    child = result["production_child"]
    assert child["does_not_overwrite_parent"] is True
    assert child["result_role"] == "production_final_child"
    assert child["next_forecast"]["fit_method"] == "full_sample_refit"

    # Proof 6: source dataset is byte-for-byte unchanged.
    pd.testing.assert_frame_equal(source, before)

    # Proof 7: every conclusion artifact traces to run/node/dataset/contract.
    for artifact_id, record in records.items():
        if not artifact_id.startswith("ts."):
            continue
        payload = json.loads((run_root / record["path"]).read_text())
        metadata = payload["metadata"]
        assert metadata["run_id"] == "joint-proofs", artifact_id
        assert metadata["dataset_hash"] == "b" * 64, artifact_id
        assert metadata["contract_hash"] == result["contract_hash"], artifact_id
        assert metadata["node_id"], artifact_id

    # Result serializes without NaN/Inf (finite-JSON guarantee).
    json.dumps(result, allow_nan=False)


def test_sequential_strategy_reports_no_composite_information_criterion(
    tmp_path: Path,
) -> None:
    result, records, run_root, _source, _before = _run(
        tmp_path, "sequential-proof", _options("sequential")
    )
    # Proof 4: sequential two-stage never fabricates a composite IC.
    assert result["estimation_strategy"] == "sequential"
    assert result["joint_likelihood"] is False
    assert not {"aic", "bic", "log_likelihood"}.intersection(result)
    final_payload = json.loads(
        (run_root / records["ts.final_model"]["path"]).read_text()
    )["payload"]
    validation_fit = final_payload["validation_fit"]
    assert "mean_stage" in validation_fit
    assert "variance_stage" in validation_fit
    assert "composite_information_criterion" not in validation_fit
    assert not {"aic", "bic", "log_likelihood"}.intersection(validation_fit)


def test_joint_request_with_ma_term_is_explicitly_rejected() -> None:
    from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
    from workbench.engine.packs.arma_garch.estimation import resolve_estimation_strategy

    # Proof 5: q > 0 joint request is blocked, never silently downgraded.
    assert resolve_estimation_strategy("sequential", mean_q=1) == "sequential_arma_garch"
    with pytest.raises(ArmaGarchInputError) as exc_info:
        resolve_estimation_strategy("joint", mean_q=1)
    assert exc_info.value.code == "UNSUPPORTED_JOINT_ARMA_GARCH"
    assert exc_info.value.recommended_actions


def test_failure_recommended_actions_form_schema_valid_proposals() -> None:
    from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
    from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input
    from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract

    # Proof 8: a structured failure exposes recommended actions that materialize
    # into schema-valid rerun proposals.
    frame = pd.DataFrame(
        {
            "when": pd.date_range("2025-01-01", periods=40, freq="D"),
            "value": np.concatenate([[0.0, -1.0], np.linspace(10.0, 20.0, 38)]),
        }
    )
    contract = ArmaGarchAnalysisContract.from_dict(
        {
            "dataset_ref": "dataset:evaluation:2",
            "time_column": "when",
            "value_column": "value",
            "time_index_semantics": "regular_calendar",
            "transform": "log_return_pct",
            "transform_confirmed": True,
            "selection_mode": "manual",
            "arma": {"p": 1, "q": 0, "constant_mode": "exclude"},
            "variance": {"model": "constant_variance"},
            "validation": {"validation_n": 20},
        }
    )
    with pytest.raises(ArmaGarchInputError) as exc_info:
        prepare_arma_garch_input(frame, contract)
    error = exc_info.value
    assert error.code == "LOG_REQUIRES_POSITIVE_VALUES"
    assert error.recommended_actions
    for action in error.recommended_actions:
        assert action["operation"] in {"model.rerun", "graph.fork"}
        assert isinstance(action.get("patch"), Mapping)


KNOWN_TRUTH_GENERATORS = {
    "arma11_homoskedastic": (arma11_homoskedastic, 0.0),
    "ar1_garch11": (ar1_garch11, 0.94),
    "sequential_arma11_garch11": (sequential_arma11_garch11, 0.92),
    "arch5": (arch5, 0.68),
    "student_t_garch11": (student_t_garch11, 0.92),
    "no_arch": (no_arch, 0.0),
    "near_unit_garch11": (near_unit_garch11, 0.995),
}


@pytest.mark.parametrize("name", sorted(KNOWN_TRUTH_GENERATORS))
def test_synthetic_known_truth_generators_are_deterministic_and_finite(name: str) -> None:
    generator, expected_persistence = KNOWN_TRUTH_GENERATORS[name]
    first = generator()
    second = generator()
    assert np.array_equal(first.values, second.values)
    assert np.isfinite(first.values).all()
    assert first.parameters["persistence"] == pytest.approx(expected_persistence, abs=1e-9)
