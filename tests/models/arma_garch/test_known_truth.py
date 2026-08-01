from __future__ import annotations

import math

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
from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract


def _contract(
    *,
    strategy: str = "sequential",
    mean_p: int = 1,
    mean_q: int = 1,
    variance: dict[str, object] | None = None,
    distribution: str = "normal",
    transform: str = "level",
    semantics: str = "observation_order",
    selection_mode: str = "manual",
) -> ArmaGarchAnalysisContract:
    payload: dict[str, object] = {
        "dataset_ref": "dataset:synthetic-known-truth:v1",
        "time_column": "when",
        "value_column": "value",
        "time_index_semantics": semantics,
        "transform": transform,
        "transform_confirmed": True,
        "selection_mode": selection_mode,
        "estimation_strategy": strategy,
        "innovation_distribution": distribution,
        "validation": {"validation_n": 20},
    }
    if selection_mode == "manual":
        payload["arma"] = {
            "p": mean_p,
            "q": mean_q,
            "constant_mode": "exclude",
        }
        payload["variance"] = variance or {
            "model": "garch",
            "garch_p": 1,
            "garch_q": 1,
        }
    return ArmaGarchAnalysisContract.from_dict(payload)


def _variance_spec(
    model: str, p: int, q: int, distribution: str = "normal"
):
    from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec

    return VarianceCandidateSpec.create(
        model=model,
        p=p,
        q=q,
        distribution=distribution,
    )


def _fit_variance(values: np.ndarray, model: str, p: int, q: int, distribution="normal"):
    from workbench.engine.packs.arma_garch.volatility import fit_variance_candidate

    return fit_variance_candidate(
        values,
        _variance_spec(model, p, q, distribution),
        hold_back=10,
    )


def _diagnostic_p_value(payload: object) -> float:
    assert isinstance(payload, dict)
    assert payload["status"] == "ok"
    value = payload["p_value"]
    assert isinstance(value, float)
    return value


def test_arma11_homoskedastic_recovers_mean_neighborhood_without_false_arch() -> None:
    from workbench.engine.packs.arma_garch.arma import (
        ArmaCandidateSpec,
        fit_arma_candidate,
    )
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics
    from workbench.engine.packs.arma_garch.volatility import select_variance_candidate

    fixture = arma11_homoskedastic()
    fitted = fit_arma_candidate(
        fixture.values,
        ArmaCandidateSpec("known-arma11", p=1, q=1, constant=False),
    )

    assert fitted.failure_code is None
    estimated_ar = 1.0 / float(fitted.ar_roots[0]["real"])
    estimated_ma = -1.0 / float(fitted.ma_roots[0]["real"])
    assert estimated_ar == pytest.approx(fixture.parameters["ar"], abs=0.16)
    assert estimated_ma == pytest.approx(fixture.parameters["ma"], abs=0.25)
    diagnostics = build_mean_diagnostics(
        fixture.values,
        np.asarray(fitted.residuals),
        model_df=2,
    )
    assert _diagnostic_p_value(dict(diagnostics.arch_lm)) > 0.05

    constant = _fit_variance(np.asarray(fitted.residuals), "constant_variance", 0, 0)
    garch = _fit_variance(np.asarray(fitted.residuals), "garch", 1, 1)
    selection = select_variance_candidate((constant, garch))
    assert selection.selected_candidate_id == constant.candidate_id


def test_ar1_garch11_joint_recovers_parameters_and_removes_arch_signal() -> None:
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics
    from workbench.engine.packs.arma_garch.estimation import fit_joint_ar_garch

    fixture = ar1_garch11()
    result = fit_joint_ar_garch(
        fixture.values,
        mean_p=1,
        include_constant=False,
        variance_spec=_variance_spec("garch", 1, 1),
        hold_back=10,
        time_index_semantics="observation_order",
    )

    assert result.converged is True
    assert result.parameters["alpha[1]"] == pytest.approx(0.14, abs=0.08)
    assert result.parameters["beta[1]"] == pytest.approx(0.80, abs=0.10)
    assert result.persistence.persistence == pytest.approx(0.94, abs=0.10)

    standardized = np.asarray(
        [
            value
            for value in result.conditional_series["standardized_residual"]
            if value is not None
        ],
        dtype=float,
    )
    raw_arch = build_mean_diagnostics(
        fixture.innovations,
        fixture.innovations,
    ).arch_lm
    standardized_arch = build_mean_diagnostics(
        standardized,
        standardized,
    ).arch_lm
    raw_p = _diagnostic_p_value(dict(raw_arch))
    standardized_p = _diagnostic_p_value(dict(standardized_arch))
    assert raw_p < 0.01
    assert standardized_p > 0.01
    assert standardized_p > raw_p


def test_arma11_garch11_is_sequential_and_joint_request_is_explicitly_rejected() -> None:
    from workbench.engine.packs.arma_garch.arma import (
        ArmaCandidateSpec,
        fit_arma_candidate,
    )
    from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
    from workbench.engine.packs.arma_garch.estimation import (
        fit_sequential_arma_garch,
        resolve_estimation_strategy,
    )

    fixture = sequential_arma11_garch11()
    mean = fit_arma_candidate(
        fixture.values,
        ArmaCandidateSpec("known-sequential-arma11", p=1, q=1, constant=False),
    )
    result = fit_sequential_arma_garch(
        fixture.values,
        mean,
        _variance_spec("garch", 1, 1),
        hold_back=10,
        time_index_semantics="observation_order",
    )
    payload = result.to_dict()

    assert result.resolved_strategy == "sequential_arma_garch"
    assert result.joint_likelihood is False
    assert resolve_estimation_strategy("auto", mean_q=1) == "sequential_arma_garch"
    assert not {"aic", "bic", "log_likelihood"}.intersection(payload)
    assert "aic" in payload["mean_stage"]
    assert "aic" in payload["variance_stage"]

    with pytest.raises(ArmaGarchInputError) as exc_info:
        resolve_estimation_strategy("joint", mean_q=1)
    assert exc_info.value.code == "UNSUPPORTED_JOINT_ARMA_GARCH"
    assert exc_info.value.evidence == {"arma_q": 1, "requested_strategy": "joint"}


def test_arch5_evidence_favors_higher_order_over_arch1() -> None:
    fixture = arch5()
    arch1 = _fit_variance(fixture.values, "arch", 1, 0)
    arch3 = _fit_variance(fixture.values, "arch", 3, 0)
    arch5_result = _fit_variance(fixture.values, "arch", 5, 0)

    assert all(item.failure_code is None for item in (arch1, arch3, arch5_result))
    assert float(arch5_result.aicc) < float(arch1.aicc)
    assert float(arch5_result.parameters["alpha[5]"]) > 0.15
    best_neighborhood = min(
        (arch1, arch3, arch5_result),
        key=lambda item: float(item.aicc),
    )
    assert best_neighborhood.p in {3, 5}


def test_student_t_garch_has_better_tail_evidence_and_standardized_quantiles() -> None:
    from workbench.engine.packs.arma_garch.forecast import innovation_quantiles

    fixture = student_t_garch11()
    normal = _fit_variance(fixture.values, "garch", 1, 1, "normal")
    student = _fit_variance(fixture.values, "garch", 1, 1, "student_t")

    assert normal.failure_code is None
    assert student.failure_code is None
    assert float(student.aic) < float(normal.aic)
    assert student.parameters["nu"] == pytest.approx(5.0, rel=0.45)

    probability = 0.01
    normal_quantile = innovation_quantiles(
        distribution="normal",
        probabilities=(probability,),
        fitted_parameters=normal.parameters,
    )[0]
    student_quantile = innovation_quantiles(
        distribution="student_t",
        probabilities=(probability,),
        fitted_parameters=student.parameters,
    )[0]
    empirical_quantile = float(np.quantile(fixture.standardized_shocks, probability))
    assert student_quantile < normal_quantile
    assert abs(student_quantile - empirical_quantile) < abs(
        normal_quantile - empirical_quantile
    )


def test_no_arch_series_does_not_force_conditional_variance_model() -> None:
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics
    from workbench.engine.packs.arma_garch.volatility import select_variance_candidate

    fixture = no_arch()
    constant = _fit_variance(fixture.values, "constant_variance", 0, 0)
    arch1 = _fit_variance(fixture.values, "arch", 1, 0)
    garch11 = _fit_variance(fixture.values, "garch", 1, 1)
    selection = select_variance_candidate((constant, arch1, garch11))

    assert selection.selected_candidate_id == constant.candidate_id
    assert _diagnostic_p_value(
        dict(build_mean_diagnostics(fixture.values, fixture.values).arch_lm)
    ) > 0.05


def test_near_unit_persistence_emits_warning_and_stable_half_life() -> None:
    from workbench.engine.packs.arma_garch.volatility import calculate_persistence

    fixture = near_unit_garch11()
    persistence = float(fixture.parameters["persistence"])
    result = calculate_persistence(
        model="garch",
        p=1,
        q=1,
        parameters={"alpha[1]": 0.04, "beta[1]": 0.955},
        time_index_semantics="observation_order",
    )

    assert np.isfinite(fixture.values).all()
    assert result.persistence == pytest.approx(persistence)
    assert result.half_life == pytest.approx(math.log(0.5) / math.log(persistence))
    assert result.half_life is not None and result.half_life > 100.0
    assert "GARCH_HIGH_PERSISTENCE" in result.warnings


@pytest.mark.parametrize(
    ("alpha", "beta", "expected_warning"),
    [
        (0.20, 0.80, "GARCH_NONSTATIONARY_PERSISTENCE"),
        (0.30, 0.80, "GARCH_NONSTATIONARY_PERSISTENCE"),
        (-0.10, 0.70, "GARCH_INVALID_VARIANCE_PARAMETERS"),
    ],
)
def test_nonstationary_or_illegal_persistence_has_no_finite_half_life(
    alpha: float, beta: float, expected_warning: str
) -> None:
    from workbench.engine.packs.arma_garch.volatility import (
        calculate_persistence,
        validate_variance_parameters,
    )

    parameters = {"omega": 0.1, "alpha[1]": alpha, "beta[1]": beta}
    validation = validate_variance_parameters(
        model="garch",
        p=1,
        q=1,
        distribution="normal",
        parameters=parameters,
    )
    persistence = calculate_persistence(
        model="garch",
        p=1,
        q=1,
        parameters=parameters,
        time_index_semantics="observation_order",
    )

    assert validation.valid is False
    assert persistence.half_life is None
    assert expected_warning in persistence.warnings
    if alpha + beta >= 1.0:
        assert validation.failure_code == "GARCH_NONSTATIONARY_PERSISTENCE"
    else:
        assert "INVALID_PARAMETER:alpha[1]:>= 0" in validation.failure_reasons


def test_observation_order_split_preserves_datetime_boundary_without_numeric_coercion() -> None:
    """Observation order may use a datetime-labelled source without inferring cadence."""

    from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input
    from workbench.engine.packs.arma_garch.split import freeze_train_validation_split

    frame = pd.DataFrame(
        {
            # CSV uploads carry date labels as strings; this is the path the
            # Notebook Recipe executes rather than an already-datetime frame.
            "when": pd.date_range("2025-01-01", periods=80, freq="D").strftime("%Y-%m-%d"),
            "value": np.linspace(10.0, 20.0, 80),
        }
    )
    contract = _contract(
        mean_q=0,
        variance={"model": "constant_variance"},
        semantics="observation_order",
    )

    prepared = prepare_arma_garch_input(frame, contract)
    frozen = freeze_train_validation_split(prepared.transformed_view, contract)

    assert frozen.split_timestamp == "2025-03-01T00:00:00Z"
    assert frozen.training_row_ids[-1] == "source-row:0000000059"


def test_data_failure_contracts_are_structured_and_never_silently_repaired() -> None:
    from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
    from workbench.engine.packs.arma_garch.input import (
        audit_time_value_input,
        prepare_arma_garch_input,
    )

    base = pd.DataFrame(
        {
            "when": pd.date_range("2025-01-01", periods=50, freq="D"),
            "value": np.linspace(10.0, 20.0, 50),
        }
    )
    cases: list[tuple[str, pd.DataFrame, str]] = []

    duplicate = base.copy()
    duplicate.loc[1, "when"] = duplicate.loc[0, "when"]
    cases.append(("duplicate", duplicate, "DUPLICATE_TIMESTAMP"))
    bad_date = base.copy()
    bad_date["when"] = bad_date["when"].astype(object)
    bad_date.loc[0, "when"] = "not-a-date"
    cases.append(("bad_date", bad_date, "TIME_PARSE_FAILED"))
    text_value = base.copy()
    text_value["value"] = text_value["value"].astype(object)
    text_value.loc[0, "value"] = "polluted"
    cases.append(("text_value", text_value, "VALUE_PARSE_FAILED"))
    missing_value = base.copy()
    missing_value.loc[0, "value"] = np.nan
    cases.append(("missing_value", missing_value, "VALUE_PARSE_FAILED"))
    infinite_value = base.copy()
    infinite_value.loc[0, "value"] = np.inf
    cases.append(("infinite_value", infinite_value, "NONFINITE_VALUES"))
    gap = base.drop(index=25).reset_index(drop=True)
    cases.append(("calendar_gap", gap, "INTERNAL_GAPS_UNCONFIRMED"))
    irregular = base.copy()
    irregular["when"] = pd.Timestamp("2025-01-01") + pd.to_timedelta(
        np.cumsum([0, *([24, 36] * 24), 24]), unit="h"
    )
    cases.append(("irregular", irregular, "IRREGULAR_INDEX_UNCONFIRMED"))
    short = base.iloc[:2].copy()
    cases.append(("short", short, "INSUFFICIENT_OBSERVATIONS"))
    constant = base.copy()
    constant["value"] = 3.0
    cases.append(("constant", constant, "CONSTANT_SERIES"))

    contract = _contract(
        mean_q=0,
        variance={"model": "constant_variance"},
        semantics="regular_calendar",
    )
    for case_name, frame, expected_code in cases:
        with pytest.raises(ArmaGarchInputError) as exc_info:
            prepare_arma_garch_input(frame, contract)
        assert exc_info.value.code == expected_code, case_name
        assert exc_info.value.evidence, case_name
        assert exc_info.value.impact, case_name

    nonpositive = base.copy()
    nonpositive.loc[10, "value"] = 0.0
    nonpositive.loc[11, "value"] = -1.0
    log_contract = _contract(
        mean_q=0,
        variance={"model": "constant_variance"},
        transform="log_return_pct",
        semantics="regular_calendar",
    )
    with pytest.raises(ArmaGarchInputError) as exc_info:
        prepare_arma_garch_input(nonpositive, log_contract)
    assert exc_info.value.code == "LOG_REQUIRES_POSITIVE_VALUES"

    extreme = base.copy()
    extreme.loc[0, "value"] = 1e13
    extreme_audit = audit_time_value_input(extreme, contract)
    extreme_diagnostic = next(
        item for item in extreme_audit.diagnostics if item.code == "EXTREME_SCALE"
    )
    assert extreme_diagnostic.severity == "warning"
    assert extreme_diagnostic.evidence


def test_all_variance_candidates_failing_returns_one_blocking_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.arma_garch.volatility as volatility

    def fail_candidate(
        values,
        spec,
        *,
        hold_back,
        mean_candidate_id,
        mean_order,
        mean_constant,
    ):
        return volatility.failed_variance_candidate(
            spec,
            total_observations=len(values),
            hold_back=hold_back,
            warning="known-truth forced optimizer failure",
            mean_candidate_id=mean_candidate_id,
            mean_order=mean_order,
            mean_constant=mean_constant,
        )

    monkeypatch.setattr(volatility, "fit_variance_candidate", fail_candidate)
    result = volatility.search_variance_candidates(
        no_arch().values,
        _contract(
            mean_q=0,
            variance={"model": "constant_variance"},
        ),
        mean_candidate_id="known-mean",
        mean_order=(1, 0),
        mean_constant=False,
    )

    assert result.selected_candidate_id is None
    assert result.selection_status == "blocked"
    assert result.blocking_diagnostic is not None
    assert result.blocking_diagnostic.code == "NO_VOLATILITY_CANDIDATE_CONVERGED"
    assert result.blocking_diagnostic.evidence["candidate_count"] == 1
    assert result.blocking_diagnostic.recommended_actions
