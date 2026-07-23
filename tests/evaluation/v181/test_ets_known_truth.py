"""Known-truth acceptance for the v1.8.1 ETS Model Pack.

The oracle is the data-generating process in
``tests/fixtures/evaluation/v181/ets_known_truth.py``: the parameters that
*made* the data, not the parameters some fitter reported. Tolerances and their
numeric justification live in ``tolerances.py``; they may not be widened here.

While the Model Pack Lane has not landed, every test in this module is marked
``xfail(strict=True)``. The body still executes and still fails — it is reported
as ``xfailed``, never as a pass. When the pack lands the marker stops applying
and the tests must pass on their merits.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from tests.evaluation.v181 import capabilities
from tests.evaluation.v181.checks import (
    check_ic_identity,
    format_findings,
    scan_volatility_overclaims,
)
from tests.evaluation.v181.driver import fit_ets, reference_fit
from tests.fixtures.evaluation.v181 import ets_known_truth as oracle
from tests.fixtures.evaluation.v181.tolerances import (
    ETS_PARAM_ABS_TOL,
    ETS_REFERENCE_AIC_ABS,
    ETS_REFERENCE_LLF_ABS,
    ETS_SIGMA2_RTOL,
    IC_IDENTITY_ABS_TOL,
)
from workbench.contracts.model.ets import ETS_MODEL_TYPE, ETSResultContract

_PACK = capabilities.ets_model_pack()
requires_ets_pack = pytest.mark.xfail(
    not _PACK.present, reason=_PACK.reason, strict=True, run=True
)

ORACLE_IDS = [factory().name for factory in oracle.ALL_ORACLES]


def as_ets_result(result: Any) -> dict[str, Any]:
    """Locate the contract-shaped ETS payload inside whatever the pack returned."""

    stack = [result]
    while stack:
        node = stack.pop()
        if isinstance(node, Mapping):
            if node.get("model_type") == ETS_MODEL_TYPE:
                return dict(node)
            stack.extend(value for value in node.values() if isinstance(value, (Mapping, list)))
        elif isinstance(node, list):
            stack.extend(node)
    raise AssertionError(
        f"no payload with model_type={ETS_MODEL_TYPE!r} found in the pack result; "
        f"top-level keys were {sorted(result) if isinstance(result, Mapping) else type(result)}"
    )


@pytest.fixture(params=list(oracle.ALL_ORACLES), ids=ORACLE_IDS)
def known_truth(request) -> oracle.KnownTruthETS:
    return request.param()


# --- the oracle itself -----------------------------------------------------


@pytest.mark.parametrize("factory", oracle.ALL_ORACLES, ids=ORACLE_IDS)
def test_oracle_series_are_reproducible_from_seed(factory) -> None:
    """No lane dependency: the oracle must be regenerable byte-for-byte."""

    truth = factory()
    regenerated = truth.regenerate()
    assert regenerated.shape == truth.values.shape
    assert (regenerated == truth.values).all(), (
        f"{truth.name} is not reproducible from (seed={truth.seed}, n={truth.n}); "
        "a known-truth oracle that cannot be regenerated is not known truth"
    )


@pytest.mark.parametrize("factory", oracle.ALL_ORACLES, ids=ORACLE_IDS)
def test_oracle_truth_is_recoverable_by_an_independent_fit(factory) -> None:
    """Sanity on the oracle, not on the pack.

    If a plain ``statsmodels`` ``ETSModel`` cannot recover the DGP parameters
    inside the tolerance, the tolerance or the sample size is wrong and every
    verdict built on it would be meaningless. This test guards the harness.
    """

    truth = factory()
    fitted = reference_fit(truth.values, truth.spec)
    tolerances = ETS_PARAM_ABS_TOL[truth.name]
    failures = []
    for name, expected in truth.truth.items():
        observed = fitted["params"][name]
        if abs(observed - expected) > tolerances[name]:
            failures.append(
                f"{name}: truth={expected} observed={observed} tol={tolerances[name]}"
            )
    assert not failures, "\n".join(failures)


# --- the pack under evaluation --------------------------------------------


@requires_ets_pack
def test_pack_recovers_known_parameters(known_truth, tmp_path: Path) -> None:
    result, _meta = fit_ets(known_truth.values, known_truth.spec, tmp_path=tmp_path)
    payload = as_ets_result(result)
    parsed = ETSResultContract.from_dict(payload)

    assert parsed.specification.canonical == known_truth.canonical
    assert parsed.convergence_code == "converged"

    tolerances = ETS_PARAM_ABS_TOL[known_truth.name]
    failures = []
    for name, expected in known_truth.truth.items():
        if name not in parsed.params:
            failures.append(f"{name}: absent from reported params {sorted(parsed.params)}")
            continue
        observed = float(parsed.params[name])
        if abs(observed - expected) > tolerances[name]:
            failures.append(
                f"{name}: truth={expected} observed={observed} "
                f"|diff|={abs(observed - expected):.5f} tol={tolerances[name]}"
            )
    assert not failures, (
        f"{known_truth.name} ({known_truth.canonical}, seed={known_truth.seed}, "
        f"n={known_truth.n}):\n" + "\n".join(failures)
    )


@requires_ets_pack
def test_pack_matches_an_independent_reference_fit(known_truth, tmp_path: Path) -> None:
    """Secondary oracle: catches wiring errors parameter recovery would tolerate."""

    result, _meta = fit_ets(known_truth.values, known_truth.spec, tmp_path=tmp_path)
    payload = as_ets_result(result)
    reference = reference_fit(known_truth.values, known_truth.spec)

    assert payload["n_obs"] == reference["n_obs"], (
        "the pack fitted a different sample than the reference"
    )
    assert abs(payload["log_likelihood"] - reference["log_likelihood"]) <= (
        ETS_REFERENCE_LLF_ABS
    ), f"llf {payload['log_likelihood']} vs reference {reference['log_likelihood']}"
    assert abs(payload["aic"] - reference["aic"]) <= ETS_REFERENCE_AIC_ABS, (
        f"aic {payload['aic']} vs reference {reference['aic']}"
    )
    assert abs(payload["bic"] - reference["bic"]) <= ETS_REFERENCE_AIC_ABS, (
        f"bic {payload['bic']} vs reference {reference['bic']}"
    )


@requires_ets_pack
def test_pack_sigma2_matches_the_true_innovation_variance(
    known_truth, tmp_path: Path
) -> None:
    result, _meta = fit_ets(known_truth.values, known_truth.spec, tmp_path=tmp_path)
    payload = as_ets_result(result)
    true_sigma2 = known_truth.sigma**2
    relative = abs(payload["sigma2"] - true_sigma2) / true_sigma2
    assert relative <= ETS_SIGMA2_RTOL, (
        f"sigma2 {payload['sigma2']} vs true {true_sigma2} "
        f"(relative {relative:.3f} > {ETS_SIGMA2_RTOL})"
    )


@requires_ets_pack
def test_pack_information_criteria_are_internally_consistent(
    known_truth, tmp_path: Path
) -> None:
    result, _meta = fit_ets(known_truth.values, known_truth.spec, tmp_path=tmp_path)
    payload = as_ets_result(result)
    findings = check_ic_identity(payload, abs_tol=IC_IDENTITY_ABS_TOL)
    assert findings == [], format_findings(findings)


@requires_ets_pack
def test_pack_result_never_speaks_about_volatility(known_truth, tmp_path: Path) -> None:
    result, _meta = fit_ets(known_truth.values, known_truth.spec, tmp_path=tmp_path)
    findings = scan_volatility_overclaims(result, subject=known_truth.name)
    assert findings == [], format_findings(findings)


@requires_ets_pack
def test_damped_and_undamped_fits_have_distinct_result_identities(tmp_path: Path) -> None:
    """Contract point 2: specification enters result identity."""

    truth = oracle.aadn_damped_trend()
    undamped_spec = {**truth.spec, "damped_trend": False}
    damped, _ = fit_ets(truth.values, truth.spec, tmp_path=tmp_path, run_id="damped")
    undamped, _ = fit_ets(truth.values, undamped_spec, tmp_path=tmp_path, run_id="undamped")
    left = as_ets_result(damped)["result_identity"]
    right = as_ets_result(undamped)["result_identity"]
    assert left != right, (
        "ETS(A,Ad,N) and ETS(A,A,N) fitted to the same series produced the same "
        f"result_identity {left!r}; they are different models, not two fits of one"
    )
