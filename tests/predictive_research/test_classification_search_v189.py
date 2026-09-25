from __future__ import annotations

from collections.abc import Sequence
import json

import pytest

from workbench.predictive_research import classification_protocol
from workbench.predictive_research.contracts import ContractError

BoundedSearchV1 = classification_protocol.BoundedSearchV1
run_classification_protocol = classification_protocol.run_classification_protocol


def run_bounded_search(*args: object, **kwargs: object) -> dict[str, object]:
    executor = getattr(classification_protocol, "run_bounded_search", None)
    assert callable(executor), "bounded search executor is not implemented"
    return executor(*args, **kwargs)


def _search(*, search_space: dict[str, tuple[object, ...]], max_trials: int = 2) -> BoundedSearchV1:
    return BoundedSearchV1(
        candidates=("logistic_regression",),
        search_space=search_space,
        primary_metric="roc_auc",
        max_trials=max_trials,
        max_seconds=30,
        max_cpu_seconds=30,
        seed=7,
    )


def _oof_result(score: float) -> dict[str, object]:
    return {
        "sample_scope": "development_oof",
        "evaluation_design": "cross_fitted_oof",
        "split_hash": "sha256:" + "a" * 64,
        "oof_metrics": {"metrics": {"roc_auc": {"point_estimate": score}}},
    }


def test_bounded_search_executes_deterministic_oof_trials_and_serializes_receipt() -> None:
    def evaluate(model_id: str, parameters: dict[str, object], seed: int) -> dict[str, object]:
        assert model_id == "logistic_regression"
        assert seed in {7, 8}
        return _oof_result(float(parameters["C"]))

    first = run_bounded_search(
        _search(search_space={"C": (0.1, 0.9)}),
        evaluate_trial=evaluate,
        monotonic_clock=lambda: 0.0,
        cpu_clock=lambda: 0.0,
    )
    second = run_bounded_search(
        _search(search_space={"C": (0.1, 0.9)}),
        evaluate_trial=evaluate,
        monotonic_clock=lambda: 0.0,
        cpu_clock=lambda: 0.0,
    )

    assert first == second
    assert first["status"] == "selected"
    assert first["selected"]["parameters"] == {"C": 0.9}
    assert first["selection_scope"] == "development_oof"
    assert all(trial["parameter_hash"].startswith("sha256:") for trial in first["trials"])
    assert all(
        trial["primary_metric"] == {
            "name": "roc_auc",
            "status": "computed",
            "point_estimate": trial["metric"],
        }
        and "oof_metrics" not in trial
        for trial in first["trials"]
    )
    json.dumps(first, allow_nan=False)


def test_bounded_search_rejects_unknown_or_out_of_range_parameters_before_fitting() -> None:
    calls: list[dict[str, object]] = []

    def evaluate(_model_id: str, parameters: dict[str, object], _seed: int) -> dict[str, object]:
        calls.append(parameters)
        return _oof_result(0.5)

    with pytest.raises(ContractError) as unknown:
        run_bounded_search(_search(search_space={"solver": ("liblinear",)}), evaluate_trial=evaluate)
    assert unknown.value.code == "CLASSIFICATION_SEARCH_PARAMETER_UNKNOWN"

    with pytest.raises(ContractError) as out_of_range:
        run_bounded_search(_search(search_space={"C": (0.0,)}), evaluate_trial=evaluate)
    assert out_of_range.value.code == "CLASSIFICATION_SEARCH_PARAMETER_OUT_OF_RANGE"
    assert calls == []


def test_bounded_search_budget_breach_is_blocked_without_selected_partial_result() -> None:
    clock = [0.0]

    def evaluate(_model_id: str, _parameters: dict[str, object], _seed: int) -> dict[str, object]:
        clock[0] = 31.0
        return _oof_result(0.9)

    search = BoundedSearchV1(
        candidates=("logistic_regression",),
        search_space={"C": (0.5,)},
        primary_metric="roc_auc",
        max_trials=1,
        max_seconds=30,
        max_cpu_seconds=30,
        seed=7,
    )
    result = run_bounded_search(
        search,
        evaluate_trial=evaluate,
        monotonic_clock=lambda: clock[0],
        cpu_clock=lambda: 0.0,
    )

    assert result["status"] == "blocked"
    assert result["selected"] is None
    assert result["reason_code"] == "CLASSIFICATION_SEARCH_BUDGET_EXCEEDED"


def test_bounded_search_trial_count_budget_blocks_before_any_fit() -> None:
    calls: list[dict[str, object]] = []

    def evaluate(_model_id: str, parameters: dict[str, object], _seed: int) -> dict[str, object]:
        calls.append(parameters)
        return _oof_result(0.9)

    result = run_bounded_search(
        _search(search_space={"C": (0.1, 0.9)}, max_trials=1),
        evaluate_trial=evaluate,
    )

    assert result["status"] == "blocked"
    assert result["selected"] is None
    assert result["reason_code"] == "CLASSIFICATION_SEARCH_TRIAL_BUDGET_EXCEEDED"
    assert calls == []


def test_bounded_search_preflights_sequence_lengths_without_iterating_over_budget_space() -> None:
    class NoIterationSequence(Sequence[object]):
        def __init__(self, length: int) -> None:
            self.length = length
            self.iterated = False

        def __len__(self) -> int:
            return self.length

        def __getitem__(self, index: int) -> object:
            raise AssertionError(f"candidate sequence was indexed at {index}")

        def __iter__(self):
            self.iterated = True
            raise AssertionError("candidate sequence was iterated before budget rejection")

    values = NoIterationSequence(10_000)
    result = run_bounded_search(
        _search(search_space={"C": values}, max_trials=1),
        evaluate_trial=lambda _model_id, _parameters, _seed: _oof_result(0.9),
    )

    assert result["status"] == "blocked"
    assert result["selected"] is None
    assert result["reason_code"] == "CLASSIFICATION_SEARCH_TRIAL_BUDGET_EXCEEDED"
    assert result["trials_declared"] > 1
    assert values.iterated is False


def test_bounded_search_trial_failure_is_recorded_and_fail_closed() -> None:
    def evaluate(_model_id: str, _parameters: dict[str, object], _seed: int) -> dict[str, object]:
        raise ContractError("CLASSIFICATION_ADAPTER_FIT_FAILED", "typed fit failed")

    result = run_bounded_search(_search(search_space={"C": (0.5,)}), evaluate_trial=evaluate)

    assert result["status"] == "blocked"
    assert result["selected"] is None
    assert result["trials"][0]["status"] == "failed"
    assert result["trials"][0]["failure_reason"]["code"] == "CLASSIFICATION_ADAPTER_FIT_FAILED"


def test_bounded_search_failure_receipt_does_not_echo_untrusted_exception_text() -> None:
    def evaluate(_model_id: str, _parameters: dict[str, object], _seed: int) -> dict[str, object]:
        raise RuntimeError("provider secret /private/customer/project.csv")

    result = run_bounded_search(_search(search_space={"C": (0.5,)}), evaluate_trial=evaluate)

    assert result["status"] == "blocked"
    assert result["trials"][0]["failure_reason"]["code"] == "CLASSIFICATION_SEARCH_TRIAL_FAILED"
    assert "provider secret" not in json.dumps(result)
    assert "customer/project.csv" not in json.dumps(result)


def test_bounded_search_rejects_trial_result_that_reports_holdout_access() -> None:
    result = run_bounded_search(
        _search(search_space={"C": (0.5,)}),
        evaluate_trial=lambda _model_id, _parameters, _seed: {
            **_oof_result(0.8),
            "holdout_accessed": True,
        },
    )

    assert result["status"] == "blocked"
    assert result["selected"] is None
    assert result["trials"][0]["failure_reason"]["code"] == "CLASSIFICATION_SEARCH_HOLDOUT_ACCESS"


def test_bounded_search_rejects_non_boolean_holdout_access_flag() -> None:
    result = run_bounded_search(
        _search(search_space={"C": (0.5,)}),
        evaluate_trial=lambda _model_id, _parameters, _seed: {
            **_oof_result(0.8),
            "holdout_accessed": "true",
        },
    )

    assert result["status"] == "blocked"
    assert result["selected"] is None
    assert result["trials"][0]["failure_reason"]["code"] == "CLASSIFICATION_SEARCH_HOLDOUT_FLAG_INVALID"


@pytest.mark.parametrize(
    "split_hash",
    [
        "split-a",
        "sha256:" + "A" * 64,
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 65,
    ],
)
def test_bounded_search_rejects_non_canonical_split_hash(split_hash: str) -> None:
    result = run_bounded_search(
        _search(search_space={"C": (0.5,)}),
        evaluate_trial=lambda _model_id, _parameters, _seed: {
            **_oof_result(0.8),
            "split_hash": split_hash,
        },
    )

    assert result["status"] == "blocked"
    assert result["selected"] is None
    assert result["trials"][0]["failure_reason"]["code"] == "CLASSIFICATION_SEARCH_SPLIT_IDENTITY_INVALID"


def test_bounded_search_rejects_unknown_oof_metric_fields_without_persisting_payload() -> None:
    trial_result = _oof_result(0.8)
    trial_result["oof_metrics"]["untrusted"] = "SECRET_PAYLOAD"

    result = run_bounded_search(
        _search(search_space={"C": (0.5,)}),
        evaluate_trial=lambda _model_id, _parameters, _seed: trial_result,
    )

    assert result["status"] == "blocked"
    assert result["selected"] is None
    assert result["trials"][0]["failure_reason"]["code"] == "CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID"
    assert "SECRET_PAYLOAD" not in json.dumps(result)
    assert "oof_metrics" not in result["trials"][0]


def test_bounded_search_rejects_oversized_oof_metric_bundle() -> None:
    trial_result = _oof_result(0.8)
    trial_result["oof_metrics"]["positive_class"] = "x" * 70_000

    result = run_bounded_search(
        _search(search_space={"C": (0.5,)}),
        evaluate_trial=lambda _model_id, _parameters, _seed: trial_result,
    )

    assert result["status"] == "blocked"
    assert result["selected"] is None
    assert result["trials"][0]["failure_reason"]["code"] == "CLASSIFICATION_SEARCH_OOF_METRIC_BUNDLE_INVALID"
    assert "x" * 100 not in json.dumps(result)


def test_bounded_search_accepts_declared_random_forest_parameters() -> None:
    result = run_bounded_search(
        BoundedSearchV1(
            candidates=("random_forest",),
            search_space={"n_estimators": (10,), "max_depth": (1,)},
            primary_metric="roc_auc",
            max_trials=1,
            max_seconds=30,
            max_cpu_seconds=30,
            seed=7,
        ),
        evaluate_trial=lambda _model_id, _parameters, _seed: _oof_result(0.8),
    )

    assert result["status"] == "selected"
    assert result["selected"]["model_id"] == "random_forest"


def test_protocol_search_uses_development_oof_and_keeps_holdout_sealed_until_final_selection() -> None:
    from test_v189_classification_production import _ordered_frame, _ordered_task, _production_dependencies

    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    result = run_classification_protocol(
        frame,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        seed=23,
        bounded_search=_search(search_space={"C": (0.5,)} , max_trials=1),
        **_production_dependencies(),
    )

    assert result["search"]["status"] == "selected"
    assert result["search"]["selection_scope"] == "development_oof"
    assert result["search"]["trials"][0]["sample_scope"] == "development_oof"
    assert result["holdout"]["status"] == "sealed"
    assert result["holdout"]["release_count"] == 0
