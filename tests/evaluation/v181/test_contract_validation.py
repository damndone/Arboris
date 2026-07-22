"""ADR §12.2(1): every public packet must validate against the locked schema.

The contracts are read-only here. Where a locked artefact is itself wrong, this
suite fails loudly and the failure is an evaluation *finding* against the
Contract Sprint — the evaluation lane does not repair it (ADR §7D).
"""

from __future__ import annotations

import math

import pytest

from tests.evaluation.v181.checks import (
    check_ic_identity,
    format_findings,
    scan_option_hash_merge,
    scan_volatility_overclaims,
)
from tests.fixtures.evaluation.v181 import packets
from tests.fixtures.evaluation.v181.fault_cases import ILLEGAL_SPECIFICATIONS
from tests.fixtures.evaluation.v181.tolerances import IC_IDENTITY_ABS_TOL
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.agent.notebook_option import (
    NotebookContractError,
    NotebookOptionRevision,
    OptionExecution,
)
from workbench.contracts.model.ets import (
    ETSContractError,
    ETSResultContract,
    ETSSpecification,
)


# --- canonical fixtures round-trip ----------------------------------------


@pytest.mark.parametrize(
    "name, contract",
    [
        ("ets_result", ETSResultContract),
        ("notebook_option_revision", NotebookOptionRevision),
        ("option_execution", OptionExecution),
    ],
)
def test_canonical_fixture_validates_and_round_trips(name, contract) -> None:
    payload = packets.load_contract_fixture(name)
    parsed = contract.from_dict(payload)
    assert parsed.to_dict() == payload, (
        f"{name}.json does not round-trip through {contract.__name__}; a fixture "
        "that cannot be re-serialised byte-for-byte is not canonical"
    )


def test_option_execution_pins_match_the_option_revision_fixture() -> None:
    """A user confirming revision 2 must not be able to execute revision 3."""

    option = packets.load_contract_fixture("notebook_option_revision")
    execution = packets.load_contract_fixture("option_execution")
    for option_field, execution_field in (
        ("option_id", "option_id"),
        ("option_revision", "option_revision"),
        ("typed_proposal_id", "proposal_id"),
        ("typed_proposal_revision", "proposal_revision"),
        ("freshness_dependency_fingerprint", "freshness_dependency_fingerprint"),
        ("generation_context_id", "generation_context_id"),
    ):
        assert option[option_field] == execution[execution_field], (
            f"execution pin {execution_field!r} does not match the option's "
            f"{option_field!r}"
        )


# --- the merged-hash producer must be caught ------------------------------


def test_contract_rejects_a_producer_that_merged_both_hash_fields() -> None:
    packet = packets.merged_hash_packet()
    with pytest.raises(NotebookContractError) as caught:
        NotebookOptionRevision.from_dict(packet)
    assert "must not" in str(caught.value)
    # and the harness's own scanner agrees, so a packet that never reaches the
    # dataclass (e.g. one serialised straight to the UI) is still caught.
    assert scan_option_hash_merge(packet)


@pytest.mark.parametrize(
    "field, value",
    [
        ("generation_context_hash", "aaaa"),
        ("generation_context_hash", "fresh1:" + "a" * 64),
        ("freshness_dependency_fingerprint", "sha256:" + "b" * 64),
        ("freshness_dependency_fingerprint", "bbbb"),
    ],
)
def test_contract_rejects_swapped_or_unprefixed_fingerprints(field, value) -> None:
    packet = packets.option_packet(rank=1)
    packet[field] = value
    with pytest.raises(NotebookContractError):
        NotebookOptionRevision.from_dict(packet)


@pytest.mark.parametrize(
    "field",
    ["lifecycle_status", "freshness_status", "validation_status", "risk_level"],
)
def test_contract_rejects_unknown_enum_members(field) -> None:
    packet = packets.option_packet(rank=1)
    packet[field] = "definitely_not_a_member"
    with pytest.raises(NotebookContractError):
        NotebookOptionRevision.from_dict(packet)


def test_artifact_contract_rejects_duplicate_artifact_ids() -> None:
    packet = packets.option_packet(rank=1)
    duplicate = dict(packet["artifact_contract"]["expected"][0])
    packet["artifact_contract"]["expected"] = [
        packet["artifact_contract"]["expected"][0],
        duplicate,
    ]
    with pytest.raises(NotebookContractError):
        NotebookOptionRevision.from_dict(packet)


def test_artifact_contract_rejects_undeclarable_dimensions() -> None:
    """DEC-ART-001: no ``role``, no ``schema_ref``; the registry persists neither."""

    packet = packets.option_packet(rank=1)
    packet["artifact_contract"]["expected"][0]["role"] = "primary"
    with pytest.raises(ContractError):
        NotebookOptionRevision.from_dict(packet)


# --- ETS specification identity -------------------------------------------


@pytest.mark.parametrize(
    "case", ILLEGAL_SPECIFICATIONS, ids=lambda case: case.name
)
def test_illegal_specifications_are_refused_by_the_contract(case) -> None:
    with pytest.raises((ETSContractError, KeyError, TypeError)):
        ETSSpecification.from_dict(case.spec)


@pytest.mark.parametrize(
    "spec, canonical",
    [
        ({"error": "add", "trend": None, "seasonal": None, "seasonal_periods": None,
          "damped_trend": False}, "ETS(A,N,N)"),
        ({"error": "add", "trend": "add", "seasonal": None, "seasonal_periods": None,
          "damped_trend": False}, "ETS(A,A,N)"),
        ({"error": "add", "trend": "add", "seasonal": None, "seasonal_periods": None,
          "damped_trend": True}, "ETS(A,Ad,N)"),
        ({"error": "add", "trend": "add", "seasonal": "add", "seasonal_periods": 12,
          "damped_trend": False}, "ETS(A,A,A)"),
        ({"error": "mul", "trend": "mul", "seasonal": "mul", "seasonal_periods": 4,
          "damped_trend": True}, "ETS(M,Md,M)"),
    ],
)
def test_canonical_specification_string_separates_distinct_models(spec, canonical) -> None:
    assert ETSSpecification.from_dict(spec).canonical == canonical


def test_damped_and_undamped_are_not_the_same_model() -> None:
    base = {"error": "add", "trend": "add", "seasonal": None, "seasonal_periods": None}
    undamped = ETSSpecification.from_dict({**base, "damped_trend": False})
    damped = ETSSpecification.from_dict({**base, "damped_trend": True})
    assert undamped.canonical != damped.canonical


def test_ets_contract_refuses_smuggled_volatility_parameters() -> None:
    payload = packets.clean_ets_result()
    payload["params"] = {**payload["params"], "conditional_variance": 3.2}
    with pytest.raises(ETSContractError):
        ETSResultContract.from_dict(payload)


# --- findings against the locked artefacts --------------------------------


def test_canonical_ets_fixture_information_criteria_are_arithmetically_consistent() -> None:
    """FINDING F-1 (Contract Sprint, not a feature lane).

    ``tests/fixtures/contracts/v181/ets_result.json`` carries
    ``aic=12043.72``, ``log_likelihood=-6015.86``, ``n_obs=2610``,
    ``bic=12078.11``. AIC implies exactly ``k = (aic + 2*llf)/2 = 6``. With
    ``k = 6``, ``bic`` must be ``-2*llf + 6*ln(2610) = 12078.92``; with the
    published ``bic``, ``k = 5.897`` — not an integer.

    The canonical fixture is what every lane mocks against (ADR §5.4), so a
    fixture whose numbers cannot come from one likelihood teaches three lanes to
    accept an incoherent packet. Reported, not repaired: the fixture is
    integration-owned and read-only for this lane.
    """

    findings = check_ic_identity(packets.clean_ets_result(), abs_tol=IC_IDENTITY_ABS_TOL)
    assert findings == [], format_findings(findings)


def test_canonical_ets_fixture_is_free_of_volatility_language() -> None:
    findings = scan_volatility_overclaims(packets.clean_ets_result())
    assert findings == [], format_findings(findings)


def test_notebook_option_revision_rejects_unknown_fields() -> None:
    """FINDING F-2 (Contract Sprint).

    ``ETSResultContract.from_dict`` and ``OptionExecution.from_dict`` both call
    ``require_exact_keys``, so an unversioned extra field is refused.
    ``NotebookOptionRevision.from_dict`` does not: it reads named keys off the
    payload and silently drops everything else.

    That asymmetry is exactly the anti-pattern ADR §11 names — "在 payload 偷塞
    未版本化字段". A lane can ship a field, the packet still validates, the field
    disappears on round-trip, and nothing in the wave notices. Reported, not
    repaired: the contract is integration-owned.
    """

    payload = packets.option_packet(rank=1)
    payload["conditional_volatility_forecast"] = 3.9
    with pytest.raises((ContractError, NotebookContractError)):
        NotebookOptionRevision.from_dict(payload)


def test_ets_result_identity_covers_the_specification() -> None:
    """Contract point 2: two specifications are two models, not two fits."""

    payload = packets.clean_ets_result()
    parsed = ETSResultContract.from_dict(payload)
    assert parsed.specification.canonical in parsed.result_identity, (
        "result_identity must include the canonical specification, otherwise "
        "ETS(A,A,N) and ETS(A,Ad,N) can collide in the artifact registry"
    )


def test_sigma2_is_finite_and_positive_in_the_canonical_fixture() -> None:
    payload = packets.clean_ets_result()
    assert math.isfinite(payload["sigma2"]) and payload["sigma2"] > 0
