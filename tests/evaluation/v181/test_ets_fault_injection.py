"""Fault injection for the v1.8.1 ETS Model Pack.

The failure mode this suite exists to catch is not "the pack crashed". It is
the opposite: **a plausible number reported for a fit that should never have
been reported**. Contract points 4 and 5 make an interior gap and a
non-converged/degenerate optimisation *blocking*, explicitly "not a warning with
numbers shown".

Pack-bound tests are ``xfail(strict=True)`` while the Model Pack Lane is absent;
their bodies still run and still fail. The fixture self-checks above them have
no lane dependency and must pass today.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.evaluation.v181 import capabilities
from tests.evaluation.v181.driver import (
    ETSOptionsRejected,
    ETSPackUnavailable,
    fit_ets,
)
from tests.evaluation.v181.test_ets_known_truth import as_ets_result
from tests.fixtures.evaluation.v181 import fault_cases
from tests.fixtures.evaluation.v181.fault_cases import (
    DATA_FAULT_CASES,
    ILLEGAL_SPECIFICATIONS,
)

_PACK = capabilities.ets_model_pack()
requires_ets_pack = pytest.mark.xfail(
    not _PACK.present, reason=_PACK.reason, strict=True, run=True
)

CASE_IDS = [factory().name for factory in DATA_FAULT_CASES]

# Parameters that constitute "numbers shown". If a blocked case reports any of
# these, the refusal was cosmetic.
HEADLINE_FIELDS = ("aic", "bic", "log_likelihood", "sigma2")


# --- fixture self-checks (no lane dependency) ------------------------------


@pytest.mark.parametrize("factory", DATA_FAULT_CASES, ids=CASE_IDS)
def test_every_fault_case_actually_contains_its_fault(factory) -> None:
    case = factory()
    values = np.asarray(case.values, dtype=float)
    if case.name == "interior_missing":
        missing = np.isnan(values)
        assert missing.any()
        first, last = np.flatnonzero(~missing)[[0, -1]]
        assert missing[first:last].any(), "the gap is not interior"
    elif case.name == "leading_and_trailing_missing":
        missing = np.isnan(values)
        assert missing[:3].all() and missing[-2:].all()
        assert missing.sum() == 5
        interior = missing[3:-2]
        assert not interior.any(), "this case must have no interior gap"
    elif case.name in {"too_short_for_trend", "too_short_for_seasonal"}:
        assert len(values) < 20
    elif case.name in {"degenerate_constant_series", "degenerate_exact_line"}:
        # zero innovation variance: the one-step-ahead error is identically 0
        differences = np.diff(values)
        assert float(np.std(differences)) == 0.0
    elif case.name == "non_finite_value":
        assert not np.isfinite(values).all()
    elif case.name == "multiplicative_error_on_non_positive_data":
        assert (values <= 0).any(), "a multiplicative error needs y > 0 to be illegal"
    else:  # pragma: no cover - guards against an unclassified new case
        pytest.fail(f"unclassified fault case {case.name!r}")


def test_fault_case_verdicts_are_declared_before_any_implementation_exists() -> None:
    """Every case states its required verdict and the contract clause behind it."""

    for factory in DATA_FAULT_CASES:
        case = factory()
        assert case.verdict in {"blocked", "converged"}
        assert case.contract_basis
    for case in ILLEGAL_SPECIFICATIONS:
        assert case.verdict == "rejected"
        assert case.contract_basis


def test_the_blocking_and_legal_missing_cases_are_not_the_same_series() -> None:
    """An interior gap and edge NaNs must be distinguishable, or neither test means anything."""

    interior = fault_cases.interior_missing().values
    edges = fault_cases.leading_and_trailing_missing().values
    assert not np.array_equal(np.isnan(interior), np.isnan(edges))


# --- pack-bound behaviour --------------------------------------------------


def _observe(case, tmp_path: Path) -> tuple[str, Any]:
    """Run one case through the pack and classify the observed verdict."""

    try:
        result, _meta = fit_ets(
            case.values, case.spec, tmp_path=tmp_path, run_id=f"fault-{case.name}"
        )
    except ETSPackUnavailable:
        raise
    except ETSOptionsRejected as error:
        return "rejected", error
    except Exception as error:  # any refusal that reaches the caller
        return "blocked", error
    return "returned", result


@pytest.mark.parametrize("factory", DATA_FAULT_CASES, ids=CASE_IDS)
@requires_ets_pack
def test_data_fault_produces_the_contracted_verdict(factory, tmp_path: Path) -> None:
    case = factory()
    verdict, observed = _observe(case, tmp_path)

    if case.verdict == "converged":
        assert verdict == "returned", (
            f"{case.name}: a legal series was refused ({observed!r}); "
            f"basis: {case.contract_basis}"
        )
        payload = as_ets_result(observed)
        assert payload["convergence_code"] == "converged"
        assert payload["n_excluded"] == 5, (
            "complete-case exclusions must be counted and reported "
            f"(got n_excluded={payload['n_excluded']})"
        )
        return

    # case.verdict == "blocked"
    if verdict == "blocked":
        return

    assert verdict != "rejected", (
        f"{case.name}: refused at options validation rather than as a blocking "
        "diagnostic; the user sees no reason"
    )

    payload = as_ets_result(observed)
    assert payload["convergence_code"] != "converged", (
        f"{case.name}: the pack reported convergence_code='converged' on a case "
        f"that must block. Basis: {case.contract_basis}. Description: "
        f"{case.description}"
    )
    shown = {
        field: payload[field]
        for field in HEADLINE_FIELDS
        if payload.get(field) not in (None, "")
    }
    assert not shown, (
        f"{case.name}: blocked but still showed numbers {shown}. Contract point 5: "
        "non-convergence is a blocking diagnostic, not a warning with numbers shown."
    )


@pytest.mark.parametrize(
    "case", ILLEGAL_SPECIFICATIONS, ids=lambda case: case.name
)
@requires_ets_pack
def test_illegal_specification_is_refused_before_fitting(case, tmp_path: Path) -> None:
    from tests.fixtures.evaluation.v181.ets_known_truth import ann_local_level

    series = ann_local_level().values[:500]
    verdict, observed = _observe(
        type(case)(
            name=case.name,
            verdict=case.verdict,
            contract_basis=case.contract_basis,
            description=case.description,
            spec=case.spec,
            values=series,
        ),
        tmp_path,
    )
    assert verdict in {"rejected", "blocked"}, (
        f"{case.name}: an illegal specification produced a result. "
        f"Basis: {case.contract_basis}"
    )


@requires_ets_pack
def test_blocked_case_does_not_leave_a_usable_artifact(tmp_path: Path) -> None:
    """A refusal that still writes a deliverable is a refusal the user can ignore."""

    case = fault_cases.interior_missing()
    run_root = tmp_path / "fault-artifact"
    try:
        fit_ets(case.values, case.spec, tmp_path=tmp_path, run_id="fault-artifact")
    except ETSPackUnavailable:
        raise
    except Exception:
        pass
    index = run_root / "artifacts_index.json"
    if index.exists():
        import json

        recorded = json.loads(index.read_text(encoding="utf-8"))["artifacts"]
        model_results = [
            item for item in recorded if item.get("artifact_type") == "model_result"
        ]
        assert not model_results, (
            "a blocked ETS run registered a model_result artifact: "
            f"{model_results}"
        )
    else:
        pytest.fail(
            "the run root has no artifacts_index.json; the driver could not "
            "observe whether a blocked run wrote artifacts"
        )
