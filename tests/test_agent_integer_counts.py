"""Explicit sample counts require exact evidence, including small integers."""

from __future__ import annotations

import gzip
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from workbench.agent import numeric_grounding as grounding


def _evidence(value: object) -> list[dict]:
    return [{"role": "tool", "name": "inspect_operation_artifact", "content": json.dumps(value)}]


# Scalar excerpt from the recorded dev task ts_garch.open.r1, session entry 83.
# Coverage and lower-quantile exceptions use different thresholds, not complementary events.
RECORDED_VALIDATION = {
    "coverage_count": 233, "exception_count": 19, "exception_rate": 0.076,
    "interval_coverage": 0.932, "successful_forecast_n": 250, "validation_n": 250,
}


@pytest.mark.parametrize("reply", [
    "样本量为176。", "观测数为176。", "参与者人数为176。", "样本176人。",
    "共176个观测。", "176名参与者。", "Sample size is 176.",
    "Number of observations: 176.", "176 participants.", "N = 176.",
])
def test_unsupported_explicit_small_counts_are_found(reply: str) -> None:
    assert [f.text for f in grounding.check(reply, _evidence({"validation_n": 250}))] == ["176"]


def test_recorded_validation_excerpt_does_not_support_an_invented_sample_count() -> None:
    messages = _evidence(RECORDED_VALIDATION)
    assert not grounding.evidence_from_messages(messages).supports(Decimal("2024"))
    assert [f.text for f in grounding.check("本次样本量为2024个观测。", messages)] == ["2024"]


def test_real_development_request_rejects_a_controlled_sample_count() -> None:
    tape = (Path(__file__).resolve().parents[1] / "local/agent-eval/baseline-v190/tasks"
            / "ts_garch.open.r1/provider_tape.jsonl")
    compacted = tape.with_suffix(".jsonl.gz")
    if tape.is_file():
        raw = tape.read_bytes()
    elif compacted.is_file():
        raw = gzip.decompress(compacted.read_bytes())
    else:
        pytest.skip("local development recording is not included in the repository")
    assert hashlib.sha256(raw).hexdigest() == "89148bca5baac2a622861bb006d282f6f4c8aafa1234224179dfdd125a59e468"
    messages = json.loads(raw.splitlines()[15])["request"]["messages"]
    assert len(messages) == 87
    assert not grounding.evidence_from_messages(messages).supports(Decimal("2024"))
    assert [f.text for f in grounding.check("本次样本量为2024个观测。", messages)] == ["2024"]


@pytest.mark.parametrize(("reply", "value"), [
    ("样本量为176。", 176), ("观测数为0。", 0), ("参与者人数为2024。", 2024),
    ("Sample size: 1,250.", 1250), ("250 observations.", 250.0),
])
def test_supported_counts_pass_exactly(reply: str, value: object) -> None:
    assert grounding.check(reply, _evidence({"n": value})) == ()


@pytest.mark.parametrize(("reply", "value", "bad"), [
    ("样本量为176。", 175.6, "176"),  # Rounding cannot supply a count.
    ("观测数为176。", 1.76, "176"),  # Nor can percentage scaling.
    ("参与者人数为1200。", 1249, "1200"),  # Trailing zeros are exact.
])
def test_counts_cannot_round_or_scale_other_numbers(reply: str, value: object, bad: str) -> None:
    assert [f.text for f in grounding.check(reply, _evidence({"value": value}))] == [bad]


@pytest.mark.parametrize("reply", [
    "GSS 2022 的数据。", "在2024年收集样本。", "编号176，3个检验。",
    "在5%水平检验，p < 0.05。", "Model 176 uses specification 3.",
])
def test_ordinary_years_identifiers_and_thresholds_keep_their_behavior(reply: str) -> None:
    assert grounding.check(reply, []) == ()


def test_numeric_bag_still_does_not_bind_a_count_to_a_field() -> None:
    # This limitation is explicit: the pilot does not authenticate field semantics.
    assert grounding.check("样本量为176。", _evidence({"unrelated_code": 176})) == ()


def test_recorded_exception_count_is_evidence_and_the_two_metrics_need_not_be_complements() -> None:
    from types import SimpleNamespace
    from workbench.engine.packs.arma_garch.forecast import calculate_forecast_metrics

    # An interval's lower boundary and the separately configured lower
    # quantile differ. Two observations can be covered AND quantile exceptions.
    values = [0.0] * 17 + [1.0] * 2 + [2.0] * 231
    rows = [SimpleNamespace(fit_status="ok", observed_value=value, conditional_mean=2.0,
                            lower_bound=0.5, upper_bound=3.0, lower_quantile=1.5,
                            interval_covered=0.5 <= value <= 3.0, quantile_exception=value < 1.5)
            for value in values]
    metrics = calculate_forecast_metrics(rows, 0.05).to_dict()
    assert metrics["coverage_count"] == RECORDED_VALIDATION["coverage_count"] == 233
    assert metrics["exception_count"] == RECORDED_VALIDATION["exception_count"] == 19
    assert metrics["interval_coverage"] == 0.932
    assert metrics["exception_rate"] == 0.076
    assert grounding.check("例外19/250。", _evidence(RECORDED_VALIDATION)) == ()
