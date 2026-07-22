"""v1.8.1 Contract Lock — compatibility tests that pass with no implementation.

ADR-PD-001 §5.4 fixes the order: schema -> canonical fixture -> consumer mock ->
producer implementation. These tests are the gate on the first two steps. They
must be green at the lock commit C1, before any lane branch exists, so that four
parallel lanes can be trusted to have been reading the same contract.

They deliberately assert *semantics*, not just field presence. A lock that only
checked field names would let a producer put the same hash in both fingerprint
fields, which is the exact failure spec §4.0 exists to prevent.
"""
import json
from pathlib import Path

import pytest

from workbench.contracts.agent.notebook_option import (
    ARTIFACT_MATCH_DIMENSIONS,
    ArtifactContract,
    NotebookContractError,
    NotebookOptionRevision,
    OptionExecution,
)
from workbench.contracts.model.ets import (
    ETS_MODEL_TYPE,
    ETSContractError,
    ETSResultContract,
    ETSSpecification,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "v181"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


# ----------------------------------------------------------------------
# NotebookOptionRevision@1.0
# ----------------------------------------------------------------------


def test_option_revision_fixture_round_trips() -> None:
    payload = _fixture("notebook_option_revision")

    revision = NotebookOptionRevision.from_dict(payload)

    assert revision.to_dict() == payload


def test_option_revision_pins_both_hashes_distinctly() -> None:
    """spec §4.0: one value in both fields would stale every fresh option."""
    payload = _fixture("notebook_option_revision")
    payload["freshness_dependency_fingerprint"] = payload["generation_context_hash"]

    with pytest.raises(NotebookContractError) as excinfo:
        NotebookOptionRevision.from_dict(payload)

    assert "different questions" in str(excinfo.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("lifecycle_status", "invented"),
        ("freshness_status", "probably_fine"),
        ("validation_status", "looks_ok"),
        ("risk_level", "extreme"),
    ],
)
def test_option_revision_rejects_invented_states(field: str, value: str) -> None:
    payload = _fixture("notebook_option_revision")
    payload[field] = value

    with pytest.raises(NotebookContractError):
        NotebookOptionRevision.from_dict(payload)


def test_option_revision_requires_a_positive_revision() -> None:
    payload = _fixture("notebook_option_revision")
    payload["option_revision"] = 0

    with pytest.raises(NotebookContractError):
        NotebookOptionRevision.from_dict(payload)


# ----------------------------------------------------------------------
# ArtifactContract@1.0 (DEC-ART-001)
# ----------------------------------------------------------------------


def test_artifact_contract_checks_only_persisted_dimensions() -> None:
    contract = ArtifactContract.from_dict(
        _fixture("notebook_option_revision")["artifact_contract"]
    )

    assert set(ARTIFACT_MATCH_DIMENSIONS) == {"artifact_id", "artifact_type", "count", "step"}
    assert contract.to_dict()["not_evaluated_dimensions"] == ["payload_schema"]
    assert contract.required_ids == ("ets_1",)


def test_artifact_contract_has_no_role_field() -> None:
    """`role` was cut deliberately: the registry persists no such thing, and a
    contract naming an unpersistable field validates nothing."""
    expected = _fixture("notebook_option_revision")["artifact_contract"]["expected"][0]

    assert "role" not in expected
    assert "schema_ref" not in expected


def test_artifact_contract_rejects_duplicate_ids() -> None:
    payload = _fixture("notebook_option_revision")["artifact_contract"]
    payload["expected"].append(dict(payload["expected"][0]))

    with pytest.raises(NotebookContractError):
        ArtifactContract.from_dict(payload)


# ----------------------------------------------------------------------
# OptionExecution@1.0
# ----------------------------------------------------------------------


def test_execution_pins_the_five_tuple() -> None:
    execution = OptionExecution.from_dict(_fixture("option_execution"))

    assert execution.option_id and execution.option_revision
    assert execution.proposal_id and execution.proposal_revision
    assert execution.freshness_dependency_fingerprint.startswith("fresh1:")


def test_execution_fingerprint_matches_the_option_it_executes() -> None:
    """The pin only works if both packets carry the same fingerprint."""
    option = NotebookOptionRevision.from_dict(_fixture("notebook_option_revision"))
    execution = OptionExecution.from_dict(_fixture("option_execution"))

    assert (
        execution.freshness_dependency_fingerprint
        == option.freshness_dependency_fingerprint
    )
    assert execution.option_revision == option.option_revision


# ----------------------------------------------------------------------
# ETSResultContract@1.0
# ----------------------------------------------------------------------


def test_ets_fixture_round_trips() -> None:
    payload = _fixture("ets_result")

    result = ETSResultContract.from_dict(payload)

    assert result.to_dict() == payload
    assert result.model_type == ETS_MODEL_TYPE


def test_ets_canonical_specification_is_readable() -> None:
    spec = ETSSpecification.from_dict(_fixture("ets_result")["specification"])

    assert spec.canonical == "ETS(A,Ad,N)"


def test_ets_refuses_volatility_claims() -> None:
    """ETS models the conditional mean; the v1.8.0 ledger refuses VaR labelling."""
    payload = _fixture("ets_result")
    payload["params"]["value_at_risk"] = 0.05

    with pytest.raises(ETSContractError) as excinfo:
        ETSResultContract.from_dict(payload)

    assert "conditional-mean" in str(excinfo.value)


def test_ets_damped_trend_requires_a_trend() -> None:
    payload = _fixture("ets_result")
    payload["specification"]["trend"] = None

    with pytest.raises(ETSContractError):
        ETSSpecification.from_dict(payload["specification"])


def test_ets_seasonal_requires_periods() -> None:
    payload = _fixture("ets_result")["specification"]
    payload["seasonal"] = "add"
    payload["seasonal_periods"] = None

    with pytest.raises(ETSContractError):
        ETSSpecification.from_dict(payload)


def test_ets_reports_its_exclusions() -> None:
    """Sample changes must be separable from parameter changes in Compare."""
    result = ETSResultContract.from_dict(_fixture("ets_result"))

    assert result.n_excluded == 3
    assert result.exclusion_reasons == {"missing_endog": 3}
