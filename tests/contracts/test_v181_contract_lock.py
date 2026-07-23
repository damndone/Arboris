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
    OptionMaterialization,
    OptionExecution,
    RecommendationDecision,
)
from workbench.contracts.common.envelope import ContractError
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
    """Sample changes must be separable from parameter changes in Compare.

    The canonical fixture is a clean trading-day series (n_excluded == 0); this
    injects exclusions to prove they round-trip, since Compare must distinguish
    "the sample shrank" from "the estimate moved".
    """
    payload = _fixture("ets_result")
    payload["n_excluded"] = 3
    payload["exclusion_reasons"] = {"missing_endog": 3}

    result = ETSResultContract.from_dict(payload)

    assert result.n_excluded == 3
    assert result.exclusion_reasons == {"missing_endog": 3}


# ----------------------------------------------------------------------
# ETSResultContract 1.0 -> 1.1 backward compatibility (ADR §5.3)
# ----------------------------------------------------------------------


def test_ets_1_0_packet_without_time_index_still_validates() -> None:
    """A minor bump must keep old consumer fixtures valid, not just claim to.

    The 1.0 fixture predates time_index_semantics; it must load and default to
    regular_calendar, preserving 1.0 behaviour exactly.
    """
    from workbench.contracts.model.ets import DEFAULT_TIME_INDEX_SEMANTICS

    payload = _fixture("ets_result")
    payload["contract_version"] = "1.0"
    payload.pop("time_index_semantics", None)

    result = ETSResultContract.from_dict(payload)

    assert result.contract_version == "1.0"
    assert result.time_index_semantics == DEFAULT_TIME_INDEX_SEMANTICS


def test_ets_trading_day_semantics_is_expressible() -> None:
    """A trading-day series is not missing data on weekends (the VIXCLS case)."""
    payload = _fixture("ets_result")
    payload["contract_version"] = "1.1"
    payload["time_index_semantics"] = "business_or_trading_observations"

    result = ETSResultContract.from_dict(payload)

    assert result.time_index_semantics == "business_or_trading_observations"


def test_ets_rejects_an_invented_time_index_semantics() -> None:
    payload = _fixture("ets_result")
    payload["contract_version"] = "1.1"
    payload["time_index_semantics"] = "whenever"

    with pytest.raises(ETSContractError):
        ETSResultContract.from_dict(payload)


def test_option_revision_refuses_unknown_fields() -> None:
    """Lane D finding F-2: the option packet must reject smuggled fields, not
    drop them silently, matching the other two packets (ADR §11)."""
    payload = _fixture("notebook_option_revision")
    payload["conditional_volatility_forecast"] = 3.9

    with pytest.raises(NotebookContractError) as excinfo:
        NotebookOptionRevision.from_dict(payload)

    assert "unknown field" in str(excinfo.value)


# ----------------------------------------------------------------------
# Notebook option evidence and materialization contracts (v1.1)
# ----------------------------------------------------------------------


def test_legacy_option_revision_projects_as_unverified_and_cannot_materialize() -> None:
    legacy = NotebookOptionRevision.from_dict(_fixture("notebook_option_revision"))

    assert legacy.contract_version == "1.0"
    assert legacy.lifecycle_projection == "legacy_unverified"
    assert legacy.materializable is False


def test_unversioned_v10_option_revision_defaults_optional_fields() -> None:
    payload = _fixture("notebook_option_revision")
    payload.pop("contract_version")
    payload.pop("rationale")
    payload.pop("assumptions")
    payload.pop("supersedes_option_revision")

    revision = NotebookOptionRevision.from_dict(payload)

    assert revision.contract_version == "1.0"
    assert revision.rationale == ""
    assert revision.assumptions == ()
    assert revision.supersedes_option_revision is None


def test_v10_option_revision_rejects_materialized_lifecycle() -> None:
    payload = _fixture("notebook_option_revision")
    payload["lifecycle_status"] = "materialized"

    with pytest.raises(NotebookContractError):
        NotebookOptionRevision.from_dict(payload)


def test_public_legacy_constructors_remain_writable_until_new_writers_migrate() -> None:
    option_payload = _fixture("notebook_option_revision")
    option_payload["artifact_contract"] = ArtifactContract.from_dict(
        option_payload["artifact_contract"]
    )
    execution_payload = _fixture("option_execution")

    revision = NotebookOptionRevision(**option_payload)
    execution = OptionExecution(**execution_payload)

    assert revision.contract_version == "1.0"
    assert execution.contract_version == "1.0"


def test_v11_option_revision_fixture_round_trips_with_evidence_and_recommendation() -> None:
    payload = _fixture("notebook_option_revision_v11")

    revision = NotebookOptionRevision.from_dict(payload)

    assert revision.to_dict() == payload
    assert revision.contract_version == "1.1"
    assert revision.lifecycle_status == "materialized"
    assert revision.materializable is True
    assert revision.evidence_refs[0].result_hash.startswith("sha256:")
    assert revision.recommendation_status == "recommended"


def test_v11_option_revision_rejects_a_bare_comparative_claim_string() -> None:
    payload = _fixture("notebook_option_revision_v11")
    payload["comparative_claims"] = "claim"

    with pytest.raises(NotebookContractError):
        NotebookOptionRevision.from_dict(payload)


@pytest.mark.parametrize(
    "field",
    [
        "contract_version",
        "evidence_refs",
        "comparative_claims",
        "recommendation_decision_id",
        "recommendation_status",
    ],
)
def test_v11_option_revision_requires_its_version_and_evidence_fields(field: str) -> None:
    payload = _fixture("notebook_option_revision_v11")
    payload.pop(field)

    with pytest.raises((NotebookContractError, ContractError)):
        NotebookOptionRevision.from_dict(payload)


def test_v10_option_revision_rejects_v11_only_fields() -> None:
    payload = _fixture("notebook_option_revision")
    payload["evidence_refs"] = []

    with pytest.raises(NotebookContractError) as excinfo:
        NotebookOptionRevision.from_dict(payload)

    assert "unknown field" in str(excinfo.value)


def test_recommendation_decision_fixture_round_trips() -> None:
    payload = _fixture("recommendation_decision_v1")

    decision = RecommendationDecision.from_dict(payload)

    assert decision.to_dict() == payload
    assert decision.recommended_option_id == "opt_7f3a1c"


@pytest.mark.parametrize(
    "outcome,recommended_option_id",
    [
        ("recommended", None),
        ("tied", "opt_7f3a1c"),
        ("insufficient_evidence", "opt_7f3a1c"),
    ],
)
def test_recommendation_decision_rejects_invalid_outcome_selection(
    outcome: str, recommended_option_id: str | None
) -> None:
    payload = _fixture("recommendation_decision_v1")
    payload["outcome"] = outcome
    payload["recommended_option_id"] = recommended_option_id

    with pytest.raises(NotebookContractError):
        RecommendationDecision.from_dict(payload)


def test_recommendation_decision_rejects_recommended_id_outside_candidates() -> None:
    payload = _fixture("recommendation_decision_v1")
    payload["recommended_option_id"] = "opt_not_a_candidate"

    with pytest.raises(NotebookContractError):
        RecommendationDecision.from_dict(payload)


@pytest.mark.parametrize(
    "field",
    [
        "evidence_pack_hashes",
        "comparison_protocol_refs",
        "candidate_option_ids",
        "reason_refs",
    ],
)
def test_recommendation_decision_rejects_bare_string_collections(field: str) -> None:
    payload = _fixture("recommendation_decision_v1")
    payload[field] = "not-a-list"

    with pytest.raises(NotebookContractError):
        RecommendationDecision.from_dict(payload)


def test_materialization_fixture_round_trips_for_a_rerun_child() -> None:
    payload = _fixture("option_materialization_v1")

    materialization = OptionMaterialization.from_dict(payload)

    assert materialization.to_dict() == payload
    assert materialization.draft_execution_mode == "rerun_child"
    assert materialization.dataset_upload_sha256 is None


def test_materialization_fixture_round_trips_for_genesis() -> None:
    payload = _fixture("option_materialization_genesis_v1")

    materialization = OptionMaterialization.from_dict(payload)

    assert materialization.to_dict() == payload
    assert materialization.draft_execution_mode == "genesis"
    assert materialization.source_run_id is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("dataset_upload_sha256", "sha256:uploaded-dataset"),
        ("source_run_id", None),
    ],
)
def test_materialization_rejects_invalid_rerun_child_xor(field: str, value: object) -> None:
    payload = _fixture("option_materialization_v1")
    payload[field] = value

    with pytest.raises(NotebookContractError):
        OptionMaterialization.from_dict(payload)


def test_materialization_rejects_genesis_source_pins() -> None:
    payload = _fixture("option_materialization_genesis_v1")
    payload["source_run_id"] = "run_002"

    with pytest.raises(NotebookContractError):
        OptionMaterialization.from_dict(payload)


@pytest.mark.parametrize(
    "fixture_name,parser,field",
    [
        ("option_materialization_v1", OptionMaterialization.from_dict, "source_run_id"),
        (
            "option_materialization_genesis_v1",
            OptionMaterialization.from_dict,
            "dataset_upload_sha256",
        ),
        ("option_execution", OptionExecution.from_dict, "run_id"),
    ],
)
def test_optional_string_pins_reject_empty_values(
    fixture_name: str, parser: object, field: str
) -> None:
    payload = _fixture(fixture_name)
    payload[field] = ""

    with pytest.raises(NotebookContractError):
        parser(payload)  # type: ignore[operator]


def test_v11_execution_fixture_round_trips_with_materialization_pins() -> None:
    payload = _fixture("option_execution_v11")

    execution = OptionExecution.from_dict(payload)

    assert execution.to_dict() == payload
    assert execution.contract_version == "1.1"
    assert execution.run_id == "run_003"
    assert execution.materialization_id == "mat_6bca12"


@pytest.mark.parametrize(
    "field",
    ["materialization_id", "draft_id", "draft_hash", "source_run_id", "run_id"],
)
def test_v11_execution_requires_every_materialization_pin(field: str) -> None:
    payload = _fixture("option_execution_v11")
    payload[field] = None

    with pytest.raises(NotebookContractError):
        OptionExecution.from_dict(payload)


def test_v10_execution_refuses_v11_materialization_fields() -> None:
    payload = _fixture("option_execution")
    payload["materialization_id"] = "mat_6bca12"

    with pytest.raises((NotebookContractError, ContractError)) as excinfo:
        OptionExecution.from_dict(payload)

    assert "unknown option_execution field" in str(excinfo.value)


@pytest.mark.parametrize(
    "fixture_name,parser,field",
    [
        ("notebook_option_revision", NotebookOptionRevision.from_dict, "option_revision"),
        ("notebook_option_revision", NotebookOptionRevision.from_dict, "typed_proposal_revision"),
        ("notebook_option_revision", NotebookOptionRevision.from_dict, "rank"),
        ("notebook_option_revision_v11", NotebookOptionRevision.from_dict, "option_revision"),
        (
            "notebook_option_revision_v11",
            NotebookOptionRevision.from_dict,
            "typed_proposal_revision",
        ),
        ("notebook_option_revision_v11", NotebookOptionRevision.from_dict, "rank"),
        ("option_materialization_v1", OptionMaterialization.from_dict, "option_revision"),
        ("option_materialization_v1", OptionMaterialization.from_dict, "proposal_revision"),
        ("option_execution", OptionExecution.from_dict, "option_revision"),
        ("option_execution", OptionExecution.from_dict, "proposal_revision"),
        ("option_execution_v11", OptionExecution.from_dict, "option_revision"),
        ("option_execution_v11", OptionExecution.from_dict, "proposal_revision"),
    ],
)
@pytest.mark.parametrize("value", [0, -1])
def test_contract_positive_integer_fields_reject_zero_and_negatives(
    fixture_name: str, parser: object, field: str, value: int
) -> None:
    payload = _fixture(fixture_name)
    payload[field] = value

    with pytest.raises(NotebookContractError):
        parser(payload)  # type: ignore[operator]


@pytest.mark.parametrize(
    "parser,fixture_name",
    [
        (NotebookOptionRevision.from_dict, "notebook_option_revision_v11"),
        (RecommendationDecision.from_dict, "recommendation_decision_v1"),
        (OptionMaterialization.from_dict, "option_materialization_v1"),
        (OptionExecution.from_dict, "option_execution_v11"),
    ],
)
def test_v11_packets_reject_unknown_fields(parser: object, fixture_name: str) -> None:
    payload = _fixture(fixture_name)
    payload["unversioned_extra"] = True

    with pytest.raises((NotebookContractError, ContractError)):
        parser(payload)  # type: ignore[operator]


@pytest.mark.parametrize(
    "parser,fixture_name",
    [
        (NotebookOptionRevision.from_dict, "notebook_option_revision_v11"),
        (RecommendationDecision.from_dict, "recommendation_decision_v1"),
        (OptionMaterialization.from_dict, "option_materialization_v1"),
        (OptionExecution.from_dict, "option_execution_v11"),
    ],
)
def test_new_packet_parsers_reject_unknown_versions(parser: object, fixture_name: str) -> None:
    payload = _fixture(fixture_name)
    payload["contract_version"] = "2.0"

    with pytest.raises(NotebookContractError):
        parser(payload)  # type: ignore[operator]


@pytest.mark.parametrize(
    "parser,packet",
    [
        (NotebookOptionRevision.from_dict, "notebook_option_revision"),
        (OptionExecution.from_dict, "option_execution"),
    ],
)
@pytest.mark.parametrize("value", [[], "scalar", None])
def test_public_version_dispatchers_reject_non_mapping_wires(
    parser: object, packet: str, value: object
) -> None:
    with pytest.raises(NotebookContractError, match=rf"{packet} must be a mapping"):
        parser(value)  # type: ignore[operator]


@pytest.mark.parametrize(
    "parser",
    [
        NotebookOptionRevision.from_dict,
        RecommendationDecision.from_dict,
        OptionMaterialization.from_dict,
        OptionExecution.from_dict,
    ],
)
@pytest.mark.parametrize("value", [[], "scalar", None])
def test_packet_parsers_do_not_leak_attribute_error_for_non_mappings(
    parser: object, value: object
) -> None:
    with pytest.raises(ContractError):
        parser(value)  # type: ignore[operator]
