from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _censored_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "duration": [1.0, 2.0, 3.0, 4.0],
            "event": [1, 0, 1, 0],
        }
    )


def _tied_group_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "duration": [1.0, 2.0, 4.0, 5.0, 1.0, 3.0, 4.0, 6.0],
            "event": [1, 0, 1, 0, 1, 1, 0, 0],
            "group": ["A", "A", "A", "A", "B", "B", "B", "B"],
        }
    )


def _r_numeric_vector(value: str) -> list[float]:
    return [float(item) for item in value.strip().split(",") if item.strip()]


def _run_survival_oracle(script: str) -> dict[str, list[float] | float]:
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript is unavailable")
    completed = subprocess.run(
        ["Rscript", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result: dict[str, list[float] | float] = {}
    for line in completed.stdout.splitlines():
        key, _, raw = line.partition("=")
        if not key:
            continue
        values = _r_numeric_vector(raw)
        result[key] = values[0] if len(values) == 1 else values
    return result


def _event_rows(payload: dict[str, object]) -> list[dict[str, object]]:
    return [
        row
        for row in payload["curves"][0]["event_table"]  # type: ignore[index]
        if row["events"] > 0
    ]


def test_survival_contract_closes_operations_and_round_trips_versioned_envelopes() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.survival_analysis import (
        SURVIVAL_ANALYSIS_CONTRACT,
        SURVIVAL_ANALYSIS_CONTRACT_VERSION,
        SURVIVAL_ANALYSIS_OPERATION_IDS,
        SurvivalAnalysisRequest,
        SurvivalAnalysisResultEnvelope,
    )
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier

    assert SURVIVAL_ANALYSIS_OPERATION_IDS == frozenset(
        {"survival.kaplan_meier", "survival.log_rank", "survival.rmst"}
    )
    request = SurvivalAnalysisRequest.from_mapping(
        {
            "duration_column": "duration",
            "event_column": "event",
            "entry_column": None,
            "group_column": None,
            "ci_method": "log_log",
            "confidence_level": 0.95,
            "tie_policy": "hypergeometric",
            "tau": 4.0,
        }
    )
    assert request.duration_column == "duration"
    result = fit_kaplan_meier(
        _censored_frame(),
        duration_column="duration",
        event_column="event",
        ci_method="log_log",
        tau=4.0,
    )
    envelope = SurvivalAnalysisResultEnvelope(
        operation_id="survival.kaplan_meier",
        result=result["result"],
    )
    value = envelope.to_dict()
    assert value["contract"] == SURVIVAL_ANALYSIS_CONTRACT
    assert value["contract_version"] == SURVIVAL_ANALYSIS_CONTRACT_VERSION
    assert SurvivalAnalysisResultEnvelope.from_dict(value).to_dict() == value
    assert json.loads(json.dumps(value, allow_nan=False)) == value

    with pytest.raises(ContractError, match="declared survival operation"):
        SurvivalAnalysisResultEnvelope(operation_id="survival.cox", result=result["result"])
    with pytest.raises(ContractError, match="unknown survival result field"):
        SurvivalAnalysisResultEnvelope.from_dict({**value, "extra": True})
    with pytest.raises(ContractError, match="mapping keys must be strings"):
        SurvivalAnalysisRequest.from_mapping({1: "duration", "event_column": "event"})
    with pytest.raises(ContractError, match="reason_code must match completed status"):
        SurvivalAnalysisResultEnvelope(
            operation_id="survival.kaplan_meier",
            result={**result["result"], "reason_code": "SURVIVAL_NO_EVENTS"},
        )


def test_kaplan_meier_reports_censoring_greenwood_intervals_median_and_rmst() -> None:
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier

    result = fit_kaplan_meier(
        _censored_frame(),
        duration_column="duration",
        event_column="event",
        ci_method="log_log",
        confidence_level=0.95,
        tau=4.0,
    )
    payload = result["result"]
    curve = payload["curves"][0]
    rows = curve["event_table"]

    assert result["operation_id"] == "survival.kaplan_meier"
    assert payload["estimator"] == "kaplan_meier"
    assert payload["nobs"] == 4
    assert payload["event_count"] == 2
    assert [row["risk_set"] for row in rows] == [4, 3, 2, 1]
    assert [row["events"] for row in rows] == [1, 0, 1, 0]
    assert [row["censored"] for row in rows] == [0, 1, 0, 1]
    assert [row["survival"] for row in rows] == pytest.approx([0.75, 0.75, 0.375, 0.375])
    assert [row["greenwood_se"] for row in rows] == pytest.approx(
        [math.sqrt(0.75 * 0.25 / 4.0), math.sqrt(0.75 * 0.25 / 4.0),
         0.375 * math.sqrt(1.0 / 12.0 + 1.0 / 2.0),
         0.375 * math.sqrt(1.0 / 12.0 + 1.0 / 2.0)]
    )
    assert curve["median"]["estimate"] == pytest.approx(3.0)
    assert curve["median"]["reason"] is None
    assert curve["rmst"]["tau"] == pytest.approx(4.0)
    assert curve["rmst"]["estimate"] == pytest.approx(2.875)
    assert curve["rmst"]["tail_policy"] == "reject_beyond_last_observation"
    assert payload["policy"]["ci_method"] == "log_log"
    for row in rows:
        assert set(row["confidence_intervals"]) == {"plain", "log_log"}
        for interval in row["confidence_intervals"].values():
            assert 0.0 <= interval["lower"] <= interval["upper"] <= 1.0


def test_kaplan_meier_delayed_entry_changes_risk_sets_without_echoing_rows() -> None:
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier

    frame = pd.DataFrame(
        {
            "entry": [0.0, 1.0, 2.0, 4.0],
            "duration": [2.0, 3.0, 4.0, 5.0],
            "event": [1, 1, 0, 0],
            "subject": ["s1", "s2", "s3", "s4"],
        }
    )
    result = fit_kaplan_meier(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
    )
    payload = result["result"]
    rows = payload["curves"][0]["event_table"]
    assert [row["risk_set"] for row in rows] == [2, 2, 1, 1]
    assert payload["entry_column"] == "entry"
    assert "subject" not in json.dumps(result)
    assert payload["policy"]["entry_semantics"] == "left_truncation_entry_before_time_r_compatible"


def test_kaplan_meier_all_censored_returns_unidentified_median() -> None:
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier

    result = fit_kaplan_meier(
        pd.DataFrame({"duration": [1.0, 2.0, 3.0], "event": [0, 0, 0]}),
        duration_column="duration",
        event_column="event",
    )
    curve = result["result"]["curves"][0]
    assert curve["median"] == {"estimate": None, "reason": "no_events"}
    assert all(row["survival"] == 1.0 for row in curve["event_table"])
    assert all(row["greenwood_se"] == 0.0 for row in curve["event_table"])


def test_kaplan_meier_all_at_risk_event_returns_null_greenwood_ci_with_reason() -> None:
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier

    result = fit_kaplan_meier(
        pd.DataFrame({"duration": [1, 1], "event": [1, 1]}),
        duration_column="duration",
        event_column="event",
    )
    row = result["result"]["curves"][0]["event_table"][0]
    assert row["survival"] == 0.0
    assert row["greenwood_se"] is None
    assert row["confidence_intervals"] == {"plain": None, "log_log": None}
    assert row["selected_confidence_interval"] is None
    assert row["confidence_interval_reason"] == "SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS"


def test_survival_preserves_large_integer_duration_and_entry_ordering() -> None:
    from workbench.engine.packs.survival_analysis import SurvivalAnalysisPackError, fit_kaplan_meier

    base = 2**53
    result = fit_kaplan_meier(
        pd.DataFrame(
            {
                "entry": [base, base + 1],
                "duration": [base + 1, base + 2],
                "event": [0, 1],
            }
        ),
        duration_column="duration",
        event_column="event",
        entry_column="entry",
    )
    rows = result["result"]["curves"][0]["event_table"]
    assert [row["time"] for row in rows] == [base + 1, base + 2]
    assert [type(row["time"]) for row in rows] == [int, int]
    assert [row["risk_set"] for row in rows] == [1, 1]
    assert [row["events"] for row in rows] == [0, 1]

    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_NON_EXACT_TIME"):
        fit_kaplan_meier(
            pd.DataFrame({"duration": [float(base), float(base + 2)], "event": [0, 1]}),
            duration_column="duration",
            event_column="event",
        )


def test_rmst_preserves_exact_large_integer_area_or_fails_closed() -> None:
    from workbench.engine.packs.survival_analysis import SurvivalAnalysisPackError, fit_rmst

    base = 2**53
    exact = fit_rmst(
        pd.DataFrame(
            {
                "duration": [base + 1, base + 2],
                "event": [0, 0],
            }
        ),
        duration_column="duration",
        event_column="event",
        tau=base + 2,
    )["result"]
    assert exact["group_results"][0]["estimate"] == base + 2
    assert type(exact["group_results"][0]["estimate"]) is int

    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_RMST_NON_EXACT"):
        fit_rmst(
            pd.DataFrame(
                {
                    "duration": [base + 1, base + 2],
                    "event": [1, 0],
                }
            ),
            duration_column="duration",
            event_column="event",
            tau=base + 2,
        )


def test_rmst_rejects_large_float_tau_for_integer_duration_precision() -> None:
    from workbench.engine.packs.survival_analysis import SurvivalAnalysisPackError, fit_rmst

    base = 2**53
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_RMST_NON_EXACT"):
        fit_rmst(
            pd.DataFrame(
                {
                    "duration": [base + 1, base + 2],
                    "event": [0, 0],
                }
            ),
            duration_column="duration",
            event_column="event",
            tau=float(base + 2),
        )


def test_kaplan_meier_fails_closed_before_nonzero_survival_underflow() -> None:
    from workbench.engine.packs.survival_analysis import SurvivalAnalysisPackError, fit_kaplan_meier

    event_count = 1_100
    frame = pd.DataFrame(
        {
            "entry": [0, *range(event_count)],
            "duration": [event_count + 1, *range(1, event_count + 1)],
            "event": [0, *([1] * event_count)],
        }
    )
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_NUMERIC_UNDERFLOW"):
        fit_kaplan_meier(
            frame,
            duration_column="duration",
            event_column="event",
            entry_column="entry",
        )


def test_kaplan_meier_rejects_invalid_columns_values_and_scale() -> None:
    from workbench.engine.packs.survival_analysis import (
        SurvivalAnalysisPackError,
        fit_kaplan_meier,
    )

    def rejected(frame: pd.DataFrame, **kwargs: object) -> str:
        with pytest.raises(SurvivalAnalysisPackError) as caught:
            fit_kaplan_meier(frame, **kwargs)
        return caught.value.reason_code

    base = {"duration_column": "duration", "event_column": "event"}
    assert rejected(pd.DataFrame({"duration": [1.0], "event": [2]}), **base) == "SURVIVAL_EVENT_NOT_BINARY"
    assert rejected(pd.DataFrame({"duration": [np.nan], "event": [0]}), **base) == "SURVIVAL_NONFINITE_INPUT"
    assert rejected(pd.DataFrame({"duration": [-1.0], "event": [0]}), **base) == "SURVIVAL_DURATION_NEGATIVE"
    assert rejected(
        pd.DataFrame({"duration": [1.0], "event": [1], "entry": [2.0]}),
        **base,
        entry_column="entry",
    ) == "SURVIVAL_ENTRY_AFTER_DURATION"
    assert rejected(
        pd.DataFrame({"duration": [1.0], "event": [1]}),
        duration_column="missing",
        event_column="event",
    ) == "SURVIVAL_MISSING_COLUMN"


def test_rmst_requires_explicit_tau_and_rejects_out_of_support_tau() -> None:
    from workbench.engine.packs.survival_analysis import (
        SurvivalAnalysisPackError,
        fit_rmst,
    )

    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_TAU_REQUIRED"):
        fit_rmst(_censored_frame(), duration_column="duration", event_column="event")
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_TAU_REQUIRED"):
        fit_rmst(_censored_frame(), duration_column="duration", event_column="event", tau=None)
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_TAU_OUT_OF_SUPPORT"):
        fit_rmst(_censored_frame(), duration_column="duration", event_column="event", tau=4.1)
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_TAU_NONFINITE"):
        fit_rmst(_censored_frame(), duration_column="duration", event_column="event", tau=float("nan"))


def test_log_rank_reports_tied_hypergeometric_observed_expected_covariance_and_p() -> None:
    from workbench.engine.packs.survival_analysis import fit_log_rank

    result = fit_log_rank(
        _tied_group_frame(),
        duration_column="duration",
        event_column="event",
        group_column="group",
        tie_policy="hypergeometric",
    )
    payload = result["result"]
    assert result["operation_id"] == "survival.log_rank"
    assert payload["groups"] == ["A", "B"]
    assert payload["tie_policy"] == "hypergeometric"
    assert payload["degrees_of_freedom"] == 1
    assert payload["df"] == 1
    assert payload["p"] == pytest.approx(payload["p_value"])
    assert len(payload["observed"]) == len(payload["expected"]) == 2
    assert np.asarray(payload["covariance"]).shape == (2, 2)
    assert payload["chi_square"] >= 0.0
    assert 0.0 <= payload["p_value"] <= 1.0
    assert sum(payload["observed"]) == pytest.approx(4.0)
    assert payload["policy"]["ties"] == "hypergeometric_at_event_time"


def test_log_rank_breslow_policy_has_distinct_declared_numerical_result() -> None:
    from workbench.engine.packs.survival_analysis import fit_log_rank

    payload = fit_log_rank(
        _tied_group_frame(),
        duration_column="duration",
        event_column="event",
        group_column="group",
        tie_policy="breslow",
    )["result"]
    assert payload["tie_policy"] == "breslow"
    assert payload["policy"]["ties"] == "breslow_event_time"
    assert payload["covariance"][0][0] == pytest.approx(0.99)
    assert payload["chi_square"] == pytest.approx(0.01010101010101012)
    assert payload["p_value"] == pytest.approx(0.9199443808170074)


def test_delayed_entry_log_rank_and_rmst_preserve_entry_policy_and_values() -> None:
    from workbench.engine.packs.survival_analysis import fit_log_rank, fit_rmst

    frame = pd.DataFrame(
        {
            "entry": [0, 1, 2, 0, 1, 3],
            "duration": [2, 4, 5, 3, 4, 6],
            "event": [1, 1, 0, 0, 1, 0],
            "group": ["A", "A", "A", "B", "B", "B"],
        }
    )
    log_rank = fit_log_rank(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
        group_column="group",
    )["result"]
    assert log_rank["policy"]["entry_semantics"] == "left_truncation_entry_before_time_r_compatible"
    assert [record["risk_set"] for record in log_rank["risk_sets"]] == [4, 4]
    assert log_rank["observed"] == pytest.approx([2.0, 1.0])

    rmst = fit_rmst(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
        group_column="group",
        tau=4,
    )["result"]
    assert [row["group"] for row in rmst["group_results"]] == ["A", "B"]
    assert [row["estimate"] for row in rmst["group_results"]] == pytest.approx([3.0, 4.0])
    assert all(row["tail_policy"] == "reject_beyond_last_observation" for row in rmst["group_results"])


def test_delayed_entry_uses_r_compatible_strict_left_truncation_policy() -> None:
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier, fit_log_rank, fit_rmst

    frame = pd.DataFrame(
        {
            "entry": [0, 1, 2],
            "duration": [2, 3, 4],
            "event": [1, 0, 1],
            "group": ["A", "B", "A"],
        }
    )
    km = fit_kaplan_meier(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
    )["result"]
    assert [row["risk_set"] for row in km["curves"][0]["event_table"]] == [2, 2, 1]
    assert km["policy"]["entry_semantics"] == "left_truncation_entry_before_time_r_compatible"

    rmst = fit_rmst(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
        tau=4,
    )["result"]
    assert rmst["group_results"][0]["estimate"] == pytest.approx(3.0)
    assert rmst["policy"]["entry_semantics"] == "left_truncation_entry_before_time_r_compatible"

    log_rank = fit_log_rank(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
        group_column="group",
    )["result"]
    assert [record["risk_set"] for record in log_rank["risk_sets"]] == [2, 1]
    assert log_rank["policy"]["entry_semantics"] == "left_truncation_entry_before_time_r_compatible"


def test_delayed_entry_matches_fixed_input_r_survfit_oracle() -> None:
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier

    frame = pd.DataFrame(
        {
            "entry": [0, 1, 2],
            "duration": [2, 3, 4],
            "event": [1, 0, 1],
        }
    )
    result = fit_kaplan_meier(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
        tau=4,
    )
    oracle = _run_survival_oracle(
        """
        library(survival)
        start <- c(0, 1, 2)
        stop <- c(2, 3, 4)
        event <- c(1, 0, 1)
        f <- survfit(Surv(start, stop, event) ~ 1)
        s <- summary(f, rmean=4)
        cat('time=', paste(f$time, collapse=','), '\\n', sep='')
        cat('risk=', paste(f$n.risk, collapse=','), '\\n', sep='')
        cat('events=', paste(f$n.event, collapse=','), '\\n', sep='')
        cat('survival=', paste(f$surv, collapse=','), '\\n', sep='')
        cat('rmst=', unname(s$table['rmean']), '\\n', sep='')
        """
    )
    curve = result["result"]["curves"][0]
    rows = curve["event_table"]
    assert [row["time"] for row in rows] == pytest.approx(oracle["time"])  # type: ignore[arg-type]
    assert [row["risk_set"] for row in rows] == pytest.approx(oracle["risk"])  # type: ignore[arg-type]
    assert [row["events"] for row in rows] == pytest.approx(oracle["events"])  # type: ignore[arg-type]
    assert [row["survival"] for row in rows] == pytest.approx(oracle["survival"])  # type: ignore[arg-type]
    assert curve["rmst"]["estimate"] == pytest.approx(oracle["rmst"])  # type: ignore[arg-type]


def test_delayed_entry_after_all_events_keeps_zero_survival_and_greenwood_reason() -> None:
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier, fit_rmst

    frame = pd.DataFrame(
        {
            "entry": [0, 2, 2],
            "duration": [1, 3, 3],
            "event": [1, 1, 0],
        }
    )
    result = fit_kaplan_meier(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
        tau=3,
    )["result"]
    rows = result["curves"][0]["event_table"]
    assert [row["risk_set"] for row in rows] == [1, 2]
    assert [row["events"] for row in rows] == [1, 1]
    assert [row["censored"] for row in rows] == [0, 1]
    assert [row["survival"] for row in rows] == [0.0, 0.0]
    assert all(
        row["confidence_interval_reason"] == "SURVIVAL_GREENWOOD_UNDEFINED_ALL_EVENTS"
        for row in rows
    )
    assert result["curves"][0]["rmst"]["estimate"] == pytest.approx(1.0)

    rmst = fit_rmst(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
        tau=3,
    )["result"]
    assert rmst["group_results"][0]["estimate"] == pytest.approx(1.0)


def test_delayed_entry_after_all_events_matches_fixed_input_r_survfit_oracle() -> None:
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier

    frame = pd.DataFrame(
        {
            "entry": [0, 2, 2],
            "duration": [1, 3, 3],
            "event": [1, 1, 0],
        }
    )
    result = fit_kaplan_meier(
        frame,
        duration_column="duration",
        event_column="event",
        entry_column="entry",
        tau=3,
    )["result"]
    oracle = _run_survival_oracle(
        """
        library(survival)
        start <- c(0, 2, 2)
        stop <- c(1, 3, 3)
        event <- c(1, 1, 0)
        f <- survfit(Surv(start, stop, event) ~ 1)
        s <- summary(f, rmean=3)
        cat('time=', paste(f$time, collapse=','), '\\n', sep='')
        cat('risk=', paste(f$n.risk, collapse=','), '\\n', sep='')
        cat('events=', paste(f$n.event, collapse=','), '\\n', sep='')
        cat('survival=', paste(f$surv, collapse=','), '\\n', sep='')
        cat('rmst=', unname(s$table['rmean']), '\\n', sep='')
        """
    )
    curve = result["curves"][0]
    rows = curve["event_table"]
    assert [row["time"] for row in rows] == pytest.approx(oracle["time"])  # type: ignore[arg-type]
    assert [row["risk_set"] for row in rows] == pytest.approx(oracle["risk"])  # type: ignore[arg-type]
    assert [row["events"] for row in rows] == pytest.approx(oracle["events"])  # type: ignore[arg-type]
    assert [row["survival"] for row in rows] == pytest.approx(oracle["survival"])  # type: ignore[arg-type]
    assert curve["rmst"]["estimate"] == pytest.approx(oracle["rmst"])  # type: ignore[arg-type]


def test_delayed_entry_equal_duration_is_rejected_by_all_survival_operations() -> None:
    from workbench.engine.packs.survival_analysis import SurvivalAnalysisPackError, fit_kaplan_meier, fit_log_rank, fit_rmst

    frame = pd.DataFrame(
        {
            "entry": [1, 0],
            "duration": [1, 2],
            "event": [1, 1],
            "group": ["A", "B"],
        }
    )
    operations = (
        lambda: fit_kaplan_meier(
            frame,
            duration_column="duration",
            event_column="event",
            entry_column="entry",
        ),
        lambda: fit_log_rank(
            frame,
            duration_column="duration",
            event_column="event",
            entry_column="entry",
            group_column="group",
        ),
        lambda: fit_rmst(
            frame,
            duration_column="duration",
            event_column="event",
            entry_column="entry",
            tau=2,
        ),
    )
    for operation in operations:
        with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_ENTRY_AT_DURATION"):
            operation()


def test_log_rank_supports_bounded_multigroup_and_rejects_no_information() -> None:
    from workbench.engine.packs.survival_analysis import (
        SurvivalAnalysisPackError,
        fit_log_rank,
    )

    frame = pd.DataFrame(
        {
            "duration": [1, 2, 3, 1, 2, 3, 1, 2, 3],
            "event": [1, 0, 0, 0, 1, 0, 0, 0, 1],
            "group": ["A"] * 3 + ["B"] * 3 + ["C"] * 3,
        }
    )
    payload = fit_log_rank(
        frame,
        duration_column="duration",
        event_column="event",
        group_column="group",
    )["result"]
    assert payload["groups"] == ["A", "B", "C"]
    assert payload["degrees_of_freedom"] == 2
    assert len(payload["covariance"]) == 3

    no_event = frame.assign(event=0)
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_NO_EVENTS"):
        fit_log_rank(
            no_event,
            duration_column="duration",
            event_column="event",
            group_column="group",
        )
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_GROUP_REQUIRED"):
        fit_log_rank(_censored_frame(), duration_column="duration", event_column="event")


def test_dispatcher_rejects_unknown_kwargs_and_missing_required_fields() -> None:
    from workbench.engine.packs.survival_analysis import (
        SurvivalAnalysisPackError,
        run_survival_operation,
    )

    frame = _censored_frame()
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_INVALID_OPTION"):
        run_survival_operation(
            "survival.kaplan_meier",
            frame,
            duration_column="duration",
            event_column="event",
            unknown_option=True,
        )
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_REQUIRED_FIELD"):
        run_survival_operation(
            "survival.kaplan_meier",
            frame,
            event_column="event",
        )


def test_dispatcher_rejects_operation_inapplicable_parameters_but_accepts_typed_defaults() -> None:
    from workbench.contracts.model.survival_analysis import SurvivalAnalysisRequest
    from workbench.engine.packs.survival_analysis import SurvivalAnalysisPackError, run_survival_operation

    frame = _tied_group_frame()
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_INVALID_OPTION"):
        run_survival_operation(
            "survival.log_rank",
            frame,
            duration_column="duration",
            event_column="event",
            group_column="group",
            tau=4,
        )
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_INVALID_OPTION"):
        run_survival_operation(
            "survival.kaplan_meier",
            frame,
            duration_column="duration",
            event_column="event",
            tie_policy="breslow",
        )
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_INVALID_OPTION"):
        run_survival_operation(
            "survival.rmst",
            frame,
            duration_column="duration",
            event_column="event",
            tau=4,
            tie_policy="breslow",
        )

    typed_default = SurvivalAnalysisRequest(
        duration_column="duration",
        event_column="event",
        group_column="group",
    )
    assert run_survival_operation("survival.log_rank", frame, request=typed_default)["operation_id"] == "survival.log_rank"

    typed_non_default = SurvivalAnalysisRequest(
        duration_column="duration",
        event_column="event",
        tie_policy="breslow",
    )
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_INVALID_OPTION"):
        run_survival_operation("survival.kaplan_meier", _censored_frame(), request=typed_non_default)


def test_malformed_policy_values_are_stable_pack_errors() -> None:
    from workbench.engine.packs.survival_analysis import SurvivalAnalysisPackError, fit_kaplan_meier, fit_log_rank

    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_INVALID_OPTION"):
        fit_kaplan_meier(
            _censored_frame(),
            duration_column="duration",
            event_column="event",
            ci_method=[],
        )
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_INVALID_OPTION"):
        fit_log_rank(
            _tied_group_frame(),
            duration_column="duration",
            event_column="event",
            group_column="group",
            tie_policy={},
        )


def test_huge_confidence_and_tau_values_are_stable_pack_or_contract_errors() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.survival_analysis import SurvivalAnalysisRequest
    from workbench.engine.packs.survival_analysis import SurvivalAnalysisPackError, fit_kaplan_meier, fit_rmst

    huge_integer = 10**1000
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_CONFIDENCE_INVALID"):
        fit_kaplan_meier(
            _censored_frame(),
            duration_column="duration",
            event_column="event",
            confidence_level=huge_integer,
        )
    with pytest.raises(SurvivalAnalysisPackError, match="SURVIVAL_TAU_OUT_OF_SUPPORT"):
        fit_rmst(
            _censored_frame(),
            duration_column="duration",
            event_column="event",
            tau=huge_integer,
        )
    with pytest.raises(ContractError):
        SurvivalAnalysisRequest(
            duration_column="duration",
            event_column="event",
            confidence_level=huge_integer,
        )
    with pytest.raises(ContractError):
        SurvivalAnalysisRequest(
            duration_column="duration",
            event_column="event",
            tau=huge_integer,
        )


def test_survival_curve_uses_preaggregated_time_work_within_declared_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.engine.packs.survival_analysis as pack

    frame = pd.DataFrame(
        {
            "duration": np.arange(128, dtype=np.int64),
            "event": np.tile([0, 1], 64),
        }
    )
    calls = 0
    original_count_nonzero = pack.np.count_nonzero

    def counted_count_nonzero(*args: object, **kwargs: object) -> int:
        nonlocal calls
        calls += 1
        return original_count_nonzero(*args, **kwargs)

    monkeypatch.setattr(pack.np, "count_nonzero", counted_count_nonzero)
    result = pack.fit_kaplan_meier(
        frame,
        duration_column="duration",
        event_column="event",
    )
    assert len(result["result"]["event_table"]) == 128
    assert calls <= 4
    assert result["result"]["policy"]["complexity"] == "preaggregated_event_table_sorted_risk_sweep"


def test_survival_pack_rejects_excessive_rows_groups_and_time_points(monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.engine.packs.survival_analysis as pack

    frame = pd.DataFrame({"duration": [1.0, 2.0, 3.0], "event": [1, 0, 1]})
    monkeypatch.setattr(pack, "MAX_SURVIVAL_ROWS", 2)
    with pytest.raises(pack.SurvivalAnalysisPackError, match="SURVIVAL_TOO_MANY_ROWS"):
        pack.fit_kaplan_meier(frame, duration_column="duration", event_column="event")

    monkeypatch.setattr(pack, "MAX_SURVIVAL_ROWS", 100)
    monkeypatch.setattr(pack, "MAX_SURVIVAL_GROUPS", 2)
    grouped = pd.DataFrame(
        {
            "duration": [1.0, 2.0, 3.0],
            "event": [1, 1, 1],
            "group": ["A", "B", "C"],
        }
    )
    with pytest.raises(pack.SurvivalAnalysisPackError, match="SURVIVAL_TOO_MANY_GROUPS"):
        pack.fit_kaplan_meier(
            grouped,
            duration_column="duration",
            event_column="event",
            group_column="group",
        )

    monkeypatch.setattr(pack, "MAX_SURVIVAL_GROUPS", 32)
    monkeypatch.setattr(pack, "MAX_SURVIVAL_TIME_POINTS", 2)
    with pytest.raises(pack.SurvivalAnalysisPackError, match="SURVIVAL_TOO_MANY_TIME_POINTS"):
        pack.fit_kaplan_meier(frame, duration_column="duration", event_column="event")


def test_survival_runtime_is_pure_python_and_does_not_embed_external_execution() -> None:
    import workbench.engine.packs.survival_analysis as pack

    source = Path(pack.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "Rscript" not in source
    assert "os.system" not in source
    assert "shell=True" not in source


def test_kaplan_meier_matches_fixed_input_r_survfit_oracle() -> None:
    from workbench.engine.packs.survival_analysis import fit_kaplan_meier

    frame = _censored_frame()
    result = fit_kaplan_meier(
        frame,
        duration_column="duration",
        event_column="event",
        ci_method="log_log",
        tau=4.0,
    )
    oracle = _run_survival_oracle(
        """
        library(survival)
        d <- c(1, 2, 3, 4)
        e <- c(1, 0, 1, 0)
        f <- survfit(Surv(d, e) ~ 1, conf.type = 'log-log')
        i <- which(f$n.event > 0)
        cat('time=', paste(f$time[i], collapse=','), '\\n', sep='')
        cat('risk=', paste(f$n.risk[i], collapse=','), '\\n', sep='')
        cat('events=', paste(f$n.event[i], collapse=','), '\\n', sep='')
        cat('survival=', paste(f$surv[i], collapse=','), '\\n', sep='')
        cat('greenwood_se=', paste(f$std.err[i] * f$surv[i], collapse=','), '\\n', sep='')
        cat('lower=', paste(f$lower[i], collapse=','), '\\n', sep='')
        cat('upper=', paste(f$upper[i], collapse=','), '\\n', sep='')
        s <- summary(f)
        cat('median=', unname(s$table['median']), '\\n', sep='')
        """
    )
    rows = _event_rows(result["result"])
    assert [row["time"] for row in rows] == pytest.approx(oracle["time"])  # type: ignore[arg-type]
    assert [row["risk_set"] for row in rows] == pytest.approx(oracle["risk"])  # type: ignore[arg-type]
    assert [row["events"] for row in rows] == pytest.approx(oracle["events"])  # type: ignore[arg-type]
    assert [row["survival"] for row in rows] == pytest.approx(oracle["survival"])  # type: ignore[arg-type]
    assert [row["greenwood_se"] for row in rows] == pytest.approx(oracle["greenwood_se"])  # type: ignore[arg-type]
    assert [row["confidence_intervals"]["log_log"]["lower"] for row in rows] == pytest.approx(oracle["lower"])  # type: ignore[arg-type]
    assert [row["confidence_intervals"]["log_log"]["upper"] for row in rows] == pytest.approx(oracle["upper"])  # type: ignore[arg-type]
    assert result["result"]["curves"][0]["median"]["estimate"] == pytest.approx(oracle["median"])  # type: ignore[arg-type]


def test_log_rank_matches_fixed_input_r_survdiff_oracle() -> None:
    from workbench.engine.packs.survival_analysis import fit_log_rank

    frame = _tied_group_frame()
    result = fit_log_rank(
        frame,
        duration_column="duration",
        event_column="event",
        group_column="group",
        tie_policy="hypergeometric",
    )
    oracle = _run_survival_oracle(
        """
        library(survival)
        d <- c(1, 2, 4, 5, 1, 3, 4, 6)
        e <- c(1, 0, 1, 0, 1, 1, 0, 0)
        g <- factor(c('A', 'A', 'A', 'A', 'B', 'B', 'B', 'B'), levels=c('A','B'))
        f <- survdiff(Surv(d, e) ~ g, rho=0)
        cat('observed=', paste(f$obs, collapse=','), '\\n', sep='')
        cat('expected=', paste(f$exp, collapse=','), '\\n', sep='')
        cat('variance=', paste(as.vector(f$var), collapse=','), '\\n', sep='')
        cat('chi_square=', f$chisq, '\\n', sep='')
        """
    )
    payload = result["result"]
    assert payload["observed"] == pytest.approx(oracle["observed"])  # type: ignore[arg-type]
    assert payload["expected"] == pytest.approx(oracle["expected"])  # type: ignore[arg-type]
    np.testing.assert_allclose(payload["covariance"], np.asarray(oracle["variance"]).reshape(2, 2))  # type: ignore[arg-type]
    assert payload["chi_square"] == pytest.approx(oracle["chi_square"])  # type: ignore[arg-type]
