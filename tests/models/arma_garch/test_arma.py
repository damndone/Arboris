from __future__ import annotations

from dataclasses import replace
import json
import math

import numpy as np
import pandas as pd
import pytest

from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input
from workbench.engine.packs.arma_garch.split import freeze_train_validation_split
from workbench.engine.packs.arma_garch.transforms import TRANSFORMED_VALUE_COLUMN


def _contract(
    *,
    selection_mode: str = "auto",
    p: int | None = None,
    q: int | None = None,
    constant_mode: str = "auto",
    validation_n: int = 20,
) -> ArmaGarchAnalysisContract:
    payload: dict[str, object] = {
        "dataset_ref": "dataset:arma:1",
        "time_column": "when",
        "value_column": "value",
        "time_index_semantics": "business_or_trading_observations",
        "transform": "level",
        "transform_confirmed": True,
        "selection_mode": selection_mode,
        "arma": {
            "p": p,
            "q": q,
            "constant_mode": constant_mode,
        },
        "validation": {"validation_n": validation_n},
    }
    if selection_mode == "manual":
        payload["variance"] = {"model": "constant_variance"}
    return ArmaGarchAnalysisContract.from_dict(payload)


def _split(*, validation_sentinel: float | None = None):
    rng = np.random.default_rng(20260720)
    values = rng.normal(size=140)
    if validation_sentinel is not None:
        values[-20:] = validation_sentinel
    source = pd.DataFrame(
        {
            "when": pd.bdate_range("2025-01-02", periods=len(values)),
            "value": values,
        }
    )
    contract = _contract()
    prepared = prepare_arma_garch_input(source, contract)
    return freeze_train_validation_split(prepared.transformed_view, contract), contract


def _candidate_result(
    spec,
    *,
    aicc: float | None = 100.0,
    bic: float = 101.0,
    converged: bool = True,
    stationary: bool = True,
    invertible: bool = True,
    finite_parameters: bool = True,
    failure_code: str | None = None,
    ljung_box_p_value: float = 0.5,
):
    from workbench.engine.packs.arma_garch.arma import ArmaCandidateResult

    return ArmaCandidateResult(
        candidate_id=spec.candidate_id,
        p=spec.p,
        q=spec.q,
        constant=spec.constant,
        nobs=120,
        effective_sample=120,
        converged=converged,
        convergence_details={"converged": converged},
        stationary=stationary,
        invertible=invertible,
        ar_roots=(),
        ma_roots=(),
        finite_parameters=finite_parameters,
        log_likelihood=-45.0,
        parameter_count=spec.p + spec.q + int(spec.constant) + 1,
        aic=99.0,
        aicc=aicc,
        bic=bic,
        residual_variance=1.0,
        ljung_box_results=(
            {"lag": 10, "statistic": 5.0, "p_value": ljung_box_p_value},
        ),
        warnings=(),
        failure_code=failure_code,
        elapsed_seconds=0.01,
        residuals=tuple(np.linspace(-1.0, 1.0, 120)),
    )


def test_auto_candidate_enumeration_is_bounded_and_stable() -> None:
    from workbench.engine.packs.arma_garch.arma import enumerate_arma_candidates

    first = enumerate_arma_candidates(_contract())
    second = enumerate_arma_candidates(_contract())

    assert len(first) == 26
    assert first == second
    assert len({candidate.candidate_id for candidate in first}) == len(first)
    assert {(candidate.p, candidate.q) for candidate in first} == {
        (p, q) for p in range(4) for q in range(4) if p + q <= 4
    }
    assert {candidate.constant for candidate in first} == {False, True}


@pytest.mark.parametrize(
    ("constant_mode", "expected_constants"),
    [
        ("auto", {False, True}),
        ("include", {True}),
        ("exclude", {False}),
    ],
)
def test_manual_candidate_keeps_fixed_orders_and_requested_constant_mode(
    constant_mode: str,
    expected_constants: set[bool],
) -> None:
    from workbench.engine.packs.arma_garch.arma import enumerate_arma_candidates

    candidates = enumerate_arma_candidates(
        _contract(
            selection_mode="manual",
            p=4,
            q=2,
            constant_mode=constant_mode,
        )
    )

    assert {(candidate.p, candidate.q) for candidate in candidates} == {(4, 2)}
    assert {candidate.constant for candidate in candidates} == expected_constants


def test_statsmodels_candidate_fit_records_required_fields() -> None:
    from workbench.engine.packs.arma_garch.arma import (
        ArmaCandidateSpec,
        fit_arma_candidate,
    )

    values = np.random.default_rng(73).normal(size=240)
    candidate = fit_arma_candidate(
        values,
        ArmaCandidateSpec(candidate_id="arma-p0-q0-n", p=0, q=0, constant=False),
    )

    assert candidate.failure_code is None
    assert candidate.nobs == 240
    assert candidate.effective_sample == 240
    assert candidate.converged is True
    assert candidate.convergence_details["converged"] is True
    assert candidate.stationary is True
    assert candidate.invertible is True
    assert candidate.ar_roots == ()
    assert candidate.ma_roots == ()
    assert candidate.finite_parameters is True
    assert candidate.parameter_count == 1
    assert set(candidate.parameters) == {"sigma2"}
    assert math.isfinite(candidate.parameters["sigma2"])
    assert candidate.to_dict()["parameters"] == dict(candidate.parameters)
    assert all(
        math.isfinite(value)
        for value in (
            candidate.log_likelihood,
            candidate.aic,
            candidate.aicc,
            candidate.bic,
            candidate.residual_variance,
            candidate.elapsed_seconds,
        )
    )
    assert candidate.ljung_box_results
    assert isinstance(candidate.warnings, tuple)
    assert len(candidate.residuals) == candidate.effective_sample


def test_candidate_fit_failure_is_structured_instead_of_raising() -> None:
    from workbench.engine.packs.arma_garch.arma import (
        ArmaCandidateSpec,
        fit_arma_candidate,
    )

    candidate = fit_arma_candidate(
        np.array([1.0, np.nan, 2.0]),
        ArmaCandidateSpec(candidate_id="bad", p=1, q=1, constant=True),
    )

    assert candidate.failure_code == "ARMA_FIT_FAILED"
    assert candidate.converged is False
    assert candidate.warnings
    assert candidate.elapsed_seconds >= 0.0


def test_candidate_with_undefined_aicc_records_a_diagnostic_warning() -> None:
    from workbench.engine.packs.arma_garch.arma import (
        ArmaCandidateSpec,
        fit_arma_candidate,
    )

    candidate = fit_arma_candidate(
        np.array([1.0, 2.0, 1.5, 2.5]),
        ArmaCandidateSpec(candidate_id="short", p=1, q=0, constant=True),
    )

    assert candidate.parameter_count == 3
    assert candidate.effective_sample == 4
    assert candidate.aicc is None
    assert "AICC_UNDEFINED" in candidate.warnings


def test_search_reads_only_frozen_training_values_and_selects_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.arma_garch.arma as arma_module

    split, contract = _split(validation_sentinel=999_999.0)
    observed_inputs: list[np.ndarray] = []
    checkpoints: list[None] = []

    def fake_fit(values: np.ndarray, spec):
        observed_inputs.append(values.copy())
        return _candidate_result(spec)

    monkeypatch.setattr(arma_module, "fit_arma_candidate", fake_fit)

    result = arma_module.search_arma_candidates(
        split,
        contract,
        checkpoint=lambda: checkpoints.append(None),
    )

    expected_count = len(arma_module.enumerate_arma_candidates(contract))
    assert len(observed_inputs) == expected_count
    assert len(checkpoints) == expected_count
    assert all(999_999.0 not in values for values in observed_inputs)
    assert all(len(values) == split.n_train for values in observed_inputs)
    assert result.training_row_ids == split.training_row_ids
    assert result.split_hash == split.split_hash
    assert result.selection_repeated_during_validation is False
    assert len(observed_inputs) != expected_count * split.validation_n


def test_one_candidate_failure_does_not_abort_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.arma_garch.arma as arma_module

    split, contract = _split()
    failed_id = arma_module.enumerate_arma_candidates(contract)[0].candidate_id

    def fake_fit(values: np.ndarray, spec):
        if spec.candidate_id == failed_id:
            raise RuntimeError("optimizer exploded")
        return _candidate_result(spec)

    monkeypatch.setattr(arma_module, "fit_arma_candidate", fake_fit)

    result = arma_module.search_arma_candidates(split, contract)

    by_id = {candidate.candidate_id: candidate for candidate in result.candidates}
    assert len(by_id) == 26
    assert by_id[failed_id].failure_code == "ARMA_FIT_FAILED"
    assert result.selected_candidate_id != failed_id


def test_search_returns_structured_blocking_diagnostic_when_no_candidate_is_eligible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.arma_garch.arma as arma_module

    split, contract = _split()

    def fake_fit(values: np.ndarray, spec):
        return _candidate_result(
            spec,
            converged=False,
            failure_code="ARMA_NOT_CONVERGED",
        )

    monkeypatch.setattr(arma_module, "fit_arma_candidate", fake_fit)

    result = arma_module.search_arma_candidates(split, contract)

    assert result.selected_candidate_id is None
    assert result.blocking_diagnostic is not None
    diagnostic = result.blocking_diagnostic.to_dict()
    assert diagnostic["severity"] == "blocking"
    assert diagnostic["code"] == "NO_ARMA_CANDIDATE_CONVERGED"
    assert diagnostic["evidence"]["candidate_count"] == 26
    assert diagnostic["evidence"]["failure_counts"] == {
        "ARMA_NOT_CONVERGED": 26
    }
    assert diagnostic["impact"]
    assert diagnostic["recommended_actions"]
    assert diagnostic["recommended_actions"][0]["operation"] == "graph.fork"
    assert diagnostic["recommended_actions"][0]["required_confirmation"] is True
    assert "arma" not in diagnostic["recommended_actions"][0].get("patch", {})


def test_selection_filters_invalid_candidates_then_prefers_simplicity_within_delta_two() -> None:
    from workbench.engine.packs.arma_garch.arma import (
        ArmaCandidateSpec,
        select_arma_candidate,
    )

    complex_best = ArmaCandidateSpec("complex", p=2, q=1, constant=True)
    simple_close = ArmaCandidateSpec("simple", p=0, q=1, constant=False)
    nonstationary = ArmaCandidateSpec("nonstationary", p=1, q=0, constant=True)
    autocorrelated = ArmaCandidateSpec("autocorrelated", p=0, q=0, constant=False)
    undefined_aicc = ArmaCandidateSpec("undefined", p=0, q=0, constant=True)
    candidates = (
        _candidate_result(complex_best, aicc=100.0, bic=104.0),
        _candidate_result(simple_close, aicc=101.8, bic=102.0),
        _candidate_result(nonstationary, aicc=90.0, stationary=False),
        _candidate_result(autocorrelated, aicc=89.0, ljung_box_p_value=0.001),
        _candidate_result(undefined_aicc, aicc=None, bic=90.0),
    )

    selection = select_arma_candidate(candidates)

    assert selection.selected_candidate_id == "simple"
    assert selection.shortlist_candidate_ids == ("complex", "simple")
    assert selection.excluded_candidate_ids == (
        "autocorrelated",
        "nonstationary",
        "undefined",
    )
    assert selection.best_aicc == 100.0
    assert selection.delta_aicc_threshold == 2.0
    assert selection.selected_bic == 102.0


def test_selection_does_not_choose_nonfinite_or_unconverged_candidate() -> None:
    from workbench.engine.packs.arma_garch.arma import (
        ArmaCandidateSpec,
        select_arma_candidate,
    )

    valid = ArmaCandidateSpec("valid", p=0, q=0, constant=False)
    unconverged = ArmaCandidateSpec("unconverged", p=1, q=0, constant=False)
    nonfinite = ArmaCandidateSpec("nonfinite", p=0, q=1, constant=False)

    selection = select_arma_candidate(
        (
            _candidate_result(valid, aicc=101.0),
            _candidate_result(unconverged, aicc=80.0, converged=False),
            _candidate_result(nonfinite, aicc=70.0, finite_parameters=False),
        )
    )

    assert selection.selected_candidate_id == "valid"


def test_candidate_result_payload_keeps_metrics_structured() -> None:
    from workbench.engine.packs.arma_garch.arma import ArmaCandidateSpec

    candidate = _candidate_result(
        ArmaCandidateSpec("payload", p=1, q=1, constant=True)
    )
    payload = candidate.to_dict()

    assert payload["candidate_id"] == "payload"
    assert payload["ljung_box_results"][0]["lag"] == 10
    assert "residuals" not in payload
    assert replace(candidate, aicc=101.0).aicc == 101.0


def test_candidate_payload_never_emits_nonfinite_roots() -> None:
    from workbench.engine.packs.arma_garch.arma import (
        ArmaCandidateSpec,
        fit_arma_candidate,
    )

    candidate = fit_arma_candidate(
        np.zeros(40),
        ArmaCandidateSpec(candidate_id="zero-ar", p=1, q=0, constant=False),
    )

    json.dumps(candidate.to_dict(), allow_nan=False)
    assert candidate.ar_roots[0]["modulus"] is None


def test_candidate_nested_results_are_immutable() -> None:
    from workbench.engine.packs.arma_garch.arma import ArmaCandidateSpec

    candidate = _candidate_result(
        ArmaCandidateSpec("immutable", p=1, q=0, constant=False)
    )

    with pytest.raises(TypeError):
        candidate.ljung_box_results[0]["p_value"] = 0.0
    with pytest.raises(TypeError):
        candidate.convergence_details["converged"] = False
