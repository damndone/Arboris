from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.time_series_diagnostics import (
    OperationExecutionEnvelope,
    TimeSeriesDiagnosticFacts,
    TimeSeriesDiagnosticAssessmentPacket,
    TimeSeriesDiagnosticFactsPacket,
    assessment_content_digest,
    derive_assessment,
    facts_content_digest,
)


FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "models" / "time_series_diagnostics"
PACKET_ROOT = FIXTURE_ROOT / "packets"
RAW_ROOT = FIXTURE_ROOT / "raw"
ORACLE_ROOT = FIXTURE_ROOT / "oracle"


def _json_fixture(name: str) -> dict[str, object]:
    with (PACKET_ROOT / name).open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _oracle_fixture() -> dict[str, object]:
    with (ORACLE_ROOT / "independent-diagnostic-oracle.json").open(
        encoding="utf-8"
    ) as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def _evidence_manifest() -> dict[str, object]:
    path = FIXTURE_ROOT / "evidence-manifest.json"
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    assert isinstance(value, dict)
    return value


def test_fixture_catalogue_contains_small_utf8_raw_and_packet_evidence() -> None:
    expected = {
        PACKET_ROOT / name
        for name in {
            "facts-packet.json",
            "assessment-packet.json",
            "policy-facts-matrix.json",
            "envelope-completed.json",
            "envelope-rejected.json",
            "envelope-failed.json",
            "envelope-cancelled.json",
            "envelope-completed-missing-assessment-ref.json",
            "envelope-failed-with-refs.json",
            "stale-pre-run-confirmation.json",
            "post-run-advisory.json",
        }
    }
    expected |= {
        RAW_ROOT / "regular-grid.csv",
        RAW_ROOT / "irregular-grid.csv",
        ORACLE_ROOT / "independent-diagnostic-oracle.json",
        ORACLE_ROOT / "supported-runtime-manifest.json",
        ORACLE_ROOT / "unsupported-dependency-manifest.json",
        ORACLE_ROOT / "resource-limits.json",
    }

    assert expected
    for path in expected:
        assert path.is_file(), path
        assert path.stat().st_size < 32_000, path
        assert path.read_bytes().decode("utf-8")


def test_raw_fixture_transport_is_ordered_small_and_not_mutated() -> None:
    path = RAW_ROOT / "regular-grid.csv"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 24
    assert list(rows[0]) == ["time", "value"]
    assert [int(row["time"]) for row in rows] == list(range(1, 25))
    assert all(row["value"] for row in rows)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_facts_and_assessment_fixtures_parse_and_recompute_their_digests() -> None:
    facts_wire = _json_fixture("facts-packet.json")
    assessment_wire = _json_fixture("assessment-packet.json")

    facts = TimeSeriesDiagnosticFactsPacket.from_dict(facts_wire)
    assessment = TimeSeriesDiagnosticAssessmentPacket.from_dict(
        assessment_wire, facts_packet=facts
    )

    assert facts_content_digest(facts_wire) == facts_wire["facts_content_digest"]
    assert (
        assessment_content_digest(assessment_wire)
        == assessment_wire["assessment_content_digest"]
    )
    assert assessment.facts_packet_id == facts.packet_id
    assert assessment.facts_content_digest == facts.facts_content_digest


def test_policy_facts_matrix_fixture_covers_d02_and_d05_boundaries() -> None:
    path = PACKET_ROOT / "policy-facts-matrix.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert fixture["fixture_id"] == "c1-policy-facts-matrix-v1"
    for case in fixture["cases"]:
        facts = TimeSeriesDiagnosticFacts.from_dict(case["facts"])
        assessment = derive_assessment(facts)
        assert assessment.conclusion == case["expected_conclusion"], case["name"]
        assert [advisory.code for advisory in assessment.advisories] == case[
            "expected_advisories"
        ], case["name"]


@pytest.mark.parametrize(
    "fixture_name",
    [
        "envelope-completed.json",
        "envelope-rejected.json",
        "envelope-failed.json",
        "envelope-cancelled.json",
    ],
)
def test_terminal_envelope_fixtures_are_strictly_parseable(fixture_name: str) -> None:
    envelope = OperationExecutionEnvelope.from_dict(_json_fixture(fixture_name))
    if envelope.operation_status == "completed":
        assert envelope.facts_packet_ref is not None
        assert envelope.assessment_packet_ref is not None
    else:
        assert envelope.facts_packet_ref is None
        assert envelope.assessment_packet_ref is None


@pytest.mark.parametrize(
    ("fixture_name", "message"),
    [
        ("envelope-completed-missing-assessment-ref.json", "completed requires both"),
        ("envelope-failed-with-refs.json", "packet refs require completed"),
    ],
)
def test_terminal_envelope_negative_fixtures_fail_closed(
    fixture_name: str, message: str
) -> None:
    with pytest.raises(ContractError, match=message):
        OperationExecutionEnvelope.from_dict(_json_fixture(fixture_name))


def test_stale_identity_and_advisory_fixtures_are_non_executable() -> None:
    stale = _json_fixture("stale-pre-run-confirmation.json")
    assert stale["status"] == "stale"
    assert stale["execution_available"] is False
    assert "operation_token" not in stale

    advisory = _json_fixture("post-run-advisory.json")
    assert advisory["effect"] == "advisory_only"
    assert advisory["execution_available"] is False
    assert "operation_token" not in advisory
    assert "forecast" not in advisory


def test_changed_packet_content_changes_only_the_appropriate_digest() -> None:
    facts = _json_fixture("facts-packet.json")
    assessment = _json_fixture("assessment-packet.json")
    facts_changed = {**facts, "facts": {"adf": {"p_value": 0.2}}}
    assessment_changed = {**assessment, "conclusion": "suitable_with_caveats"}

    assert facts_content_digest(facts_changed) != facts["facts_content_digest"]
    assert (
        assessment_content_digest(assessment_changed)
        != assessment["assessment_content_digest"]
    )


def test_oracle_is_independent_and_binds_to_a_frozen_runtime_manifest() -> None:
    oracle = _oracle_fixture()
    manifest_path = ORACLE_ROOT / "supported-runtime-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert oracle["source_kind"] == "independent_reference_calculation"
    assert oracle["calculation_status"] == "precomputed_not_production_runtime"
    assert oracle["supported_runtime_manifest_digest"] == sha256_canonical(manifest)
    methods = oracle["methods"]
    assert isinstance(methods, dict)
    assert set(methods) == {"adf", "kpss", "acf", "pacf"}
    for method in methods.values():
        assert isinstance(method, dict)
        assert isinstance(method["expected"], list)
        assert method["tolerance"] > 0


def test_unsupported_manifest_is_a_pre_execution_rejection_fixture() -> None:
    path = ORACLE_ROOT / "unsupported-dependency-manifest.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert fixture == {
        "status": "rejected",
        "reason_code": "UNSUPPORTED_DEPENDENCY_MANIFEST",
        "execution_available": False,
        "operation_token": None,
    }


def test_resource_limits_are_finite_positive_and_fail_closed() -> None:
    path = ORACLE_ROOT / "resource-limits.json"
    limits = json.loads(path.read_text(encoding="utf-8"))
    assert limits["execution_authority"] == "none_in_c1"
    assert limits["on_limit"] == "reject_before_execution"
    for key in (
        "max_input_rows",
        "max_lag_steps",
        "max_packet_bytes",
        "max_reference_runtime_seconds",
    ):
        assert type(limits[key]) is int
        assert limits[key] > 0


def test_evidence_manifest_binds_fixture_bytes_and_test_sources() -> None:
    manifest = _evidence_manifest()
    files = manifest["files"]
    assert isinstance(files, list)
    repo_root = Path(__file__).parents[2]

    for entry in files:
        assert isinstance(entry, dict)
        relative_path = entry["path"]
        assert isinstance(relative_path, str)
        path = repo_root / relative_path
        assert path.is_file(), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]

    unsigned = {key: value for key, value in manifest.items() if key != "evidence_sha256"}
    assert manifest["evidence_sha256"] == sha256_canonical(unsigned)


def test_c1_capability_remains_absent_from_existing_discoverability_surfaces() -> None:
    from workbench.engine.capabilities import build_capabilities
    from workbench.engine.pack import REGISTERED_PACKS
    from workbench.engine.registry import MODEL_REGISTRY
    from workbench.agent.operations import OperationRegistry
    from workbench.app import app

    forbidden_fragments = ("time_series_diagnostics", "time-series-diagnostics")
    assert not any(
        any(fragment in key.lower() for fragment in forbidden_fragments)
        for key in MODEL_REGISTRY
    )
    assert not any(
        any(fragment in pack.pack_id.lower() for fragment in forbidden_fragments)
        for pack in REGISTERED_PACKS
    )
    assert not any(
        fragment in json.dumps(build_capabilities(), sort_keys=True).lower()
        for fragment in forbidden_fragments
    )
    assert not any(
        any(fragment in operation_id.lower() for fragment in forbidden_fragments)
        for operation_id in OperationRegistry().operation_ids()
    )
    assert not any(
        any(fragment in getattr(route, "path", "").lower() for fragment in forbidden_fragments)
        for route in app.routes
    )

    feature_registry = (
        Path(__file__).parents[2]
        / "frontend"
        / "src"
        / "workbench"
        / "agent"
        / "featureRegistry.ts"
    ).resolve()
    section_registry = (
        Path(__file__).parents[2]
        / "frontend"
        / "src"
        / "workbench"
        / "registry"
        / "sectionRegistry.ts"
    ).resolve()
    for source in (feature_registry, section_registry):
        assert source.is_file(), source
        text = source.read_text(encoding="utf-8").lower()
        assert not any(fragment in text for fragment in forbidden_fragments)

    compare_root = feature_registry.parents[2] / "lineage" / "compare"
    compare_sources = sorted(compare_root.glob("*.ts")) + sorted(
        compare_root.glob("*.tsx")
    )
    assert compare_sources
    assert all(
        not any(fragment in source.read_text(encoding="utf-8").lower() for fragment in forbidden_fragments)
        for source in compare_sources
    )


def test_legacy_generic_runner_is_not_mistaken_for_c1_registration() -> None:
    runner = (
        Path(__file__).parents[2]
        / "backend"
        / "workbench"
        / "econometrics"
        / "runner.py"
    ).resolve()
    assert runner.is_file()
    runner_text = runner.read_text(encoding="utf-8")
    assert "run_time_series_diagnostics" in runner_text
    assert "time_series_diagnostics.facts" not in runner_text
    assert "time_series_diagnostics.assessment" not in runner_text
