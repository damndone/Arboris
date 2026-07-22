"""Meta-tests: prove each adversarial checker catches the bug it claims to.

These tests never touch a feature lane, so they must pass today. They are the
reason the other suites' green (or xfail) results mean anything: a checker that
has only seen clean input is not evidence.
"""

from __future__ import annotations

import math

import pytest

from tests.evaluation.v181.checks import (
    check_ic_identity,
    scan_batch_self_reference,
    scan_cross_family_ic_claims,
    scan_option_hash_merge,
    scan_volatility_overclaims,
)
from tests.fixtures.evaluation.v181 import packets
from tests.fixtures.evaluation.v181.tolerances import IC_IDENTITY_ABS_TOL


# --- volatility / VaR overclaim -------------------------------------------


def test_clean_ets_result_has_no_volatility_vocabulary() -> None:
    assert scan_volatility_overclaims(packets.clean_ets_result()) == []


@pytest.mark.parametrize(
    "factory",
    [packets.volatility_overclaim_result, packets.var_overclaim_result],
    ids=["conditional_volatility_field", "value_at_risk_narration"],
)
def test_volatility_scanner_catches_overclaims(factory) -> None:
    findings = scan_volatility_overclaims(factory())
    assert findings, "the scanner missed an ETS result making a volatility claim"


@pytest.mark.parametrize(
    "payload",
    [
        {"params": {"var": 1.0}},
        {"params": {"conditional_variance": [1.0, 2.0]}},
        {"summary": "ETS gives the 95% VaR directly."},
        {"summary": "the GARCH component absorbs the spike"},
        {"deliverables": [{"title": "Volatility term structure"}]},
    ],
    ids=["var_field", "cond_variance_field", "var_prose", "garch_prose", "nested_title"],
)
def test_volatility_scanner_reaches_every_smuggling_route(payload) -> None:
    assert scan_volatility_overclaims(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"params": {"variance_of_residuals": 1.0}},
        {"summary": "the variance of the innovations is reported as sigma2"},
        {"specification": {"canonical": "ETS(A,Ad,N)"}},
    ],
    ids=["variance_word", "innovation_variance_prose", "canonical_spec"],
)
def test_volatility_scanner_does_not_fire_on_legitimate_mean_model_language(payload) -> None:
    assert scan_volatility_overclaims(payload) == []


# --- cross-family IC comparison -------------------------------------------


def test_cross_family_scanner_rejects_an_aic_verdict() -> None:
    findings = scan_cross_family_ic_claims(packets.cross_family_aic_claim())
    checks = {finding.check for finding in findings}
    assert checks == {"cross_family_ic_not_comparable"}
    assert len(findings) >= 3, [str(item) for item in findings]


def test_cross_family_scanner_accepts_the_honest_refusal() -> None:
    assert scan_cross_family_ic_claims(packets.honest_cross_family_compare()) == []


def test_cross_family_scanner_ignores_within_family_comparison() -> None:
    within = {
        "left": {"model_type": "time_series.ets", "aic": 12043.7},
        "right": {"model_type": "time_series.ets", "aic": 12010.2},
        "comparability": "full",
        "verdict": "The damped specification has the lower AIC and is preferred.",
    }
    assert scan_cross_family_ic_claims(within) == []


# --- option hashes --------------------------------------------------------


def test_hash_scanner_catches_a_producer_that_merged_both_fields() -> None:
    findings = scan_option_hash_merge(packets.merged_hash_packet())
    assert findings and findings[0].check == "hashes_not_merged"


def test_hash_scanner_accepts_the_canonical_fixture() -> None:
    canonical = packets.load_contract_fixture("notebook_option_revision")
    assert scan_option_hash_merge(canonical) == []


# --- batch self-reference -------------------------------------------------


def test_healthy_batch_of_three_is_clean() -> None:
    assert scan_batch_self_reference(packets.healthy_batch(3)) == []


def test_batch_scanner_catches_options_that_stale_themselves() -> None:
    findings = scan_batch_self_reference(packets.self_staling_batch(3))
    checks = {finding.check for finding in findings}
    assert "batch_all_fresh" in checks
    assert "batch_single_freshness_fingerprint" in checks


def test_batch_scanner_catches_a_context_that_moved_mid_generation() -> None:
    findings = scan_batch_self_reference(packets.divergent_batch_context())
    assert "batch_single_generation_context" in {item.check for item in findings}


def test_batch_scanner_rejects_an_empty_batch() -> None:
    assert scan_batch_self_reference([])


# --- information-criterion arithmetic -------------------------------------


def test_ic_identity_accepts_an_internally_coherent_result() -> None:
    # Built here, not loaded: the integration-owned fixture is itself
    # inconsistent (finding F-1, see test_contract_validation.py).
    llf = -6015.86
    k = 6
    n = 2610
    coherent = {
        "aic": -2 * llf + 2 * k,
        "bic": -2 * llf + k * math.log(n),
        "log_likelihood": llf,
        "n_obs": n,
    }
    assert check_ic_identity(coherent, abs_tol=IC_IDENTITY_ABS_TOL) == []


def test_ic_identity_catches_a_composite_information_criterion() -> None:
    result = packets.clean_ets_result()
    # A "composite IC" of the kind the v1.8.0 ledger refuses: AIC and BIC that
    # do not come from one likelihood and one k.
    result["bic"] = result["aic"] + 100.0
    findings = check_ic_identity(result, abs_tol=IC_IDENTITY_ABS_TOL)
    assert findings and findings[0].check == "ic_identity"


def test_ic_identity_catches_a_non_integer_parameter_count() -> None:
    result = packets.clean_ets_result()
    result["aic"] = result["aic"] + 0.75
    findings = check_ic_identity(result, abs_tol=IC_IDENTITY_ABS_TOL)
    assert any("implied k" in finding.observed for finding in findings)
