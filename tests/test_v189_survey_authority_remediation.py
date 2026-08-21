from __future__ import annotations

from pathlib import Path

import pytest

from workbench.evidence import survey_projection_adapter as survey_adapter
from workbench.predictive_research.contracts import ContractError
from workbench.services import survey_consumer_service as survey_service


def _metadata() -> dict[str, object]:
    return {
        "artifact_id": "forged-artifact",
        "artifact_sha256": "a" * 64,
        "receipt_digest": "b" * 64,
        "server_identity": {"run_id": "forged-run"},
    }


def test_receipt_factory_requires_internal_server_issuer() -> None:
    with pytest.raises(ContractError, match="server issuer"):
        survey_adapter._authorize_survey_source_receipt(_metadata())


def test_run_capability_requires_persisted_server_manifest(tmp_path: Path) -> None:
    run_root = tmp_path / "runs" / "run-without-manifest"
    run_root.mkdir(parents=True)

    with pytest.raises(ContractError, match="artifact manifest"):
        survey_service.issue_survey_run_capability(tmp_path, run_root.name)


def test_unsupported_family_preserves_persisted_status_reason_and_design(
    tmp_path: Path,
) -> None:
    from test_v189_survey_central_consumer import (
        _materialize_survey_run,
        _rewrite_bound_artifact,
    )

    project_root, run_root = _materialize_survey_run(tmp_path)

    def mark_unsupported(payload: dict[str, object]) -> None:
        payload["model_type"] = "ordinal"
        payload["survey_evidence_status"] = "unavailable"
        payload["survey_unavailable_reason"] = "SURVEY_TEST_UNAVAILABLE"

    _rewrite_bound_artifact(run_root, mark_unsupported)

    capability = survey_service.issue_survey_run_capability(
        project_root, run_root.name
    )
    projection = survey_service.read_survey_consumer_projection(capability, "agent")

    assert projection["status"] == "unavailable"
    assert projection["reason"] == "SURVEY_MODEL_FAMILY_UNSUPPORTED"
    assert projection["source_status"] == "unavailable"
    assert projection["source_reason"] == "SURVEY_TEST_UNAVAILABLE"
    assert projection["survey_design"]["variance_method"]


def test_malformed_model_family_is_typed_unavailable(tmp_path: Path) -> None:
    from test_v189_survey_central_consumer import (
        _materialize_survey_run,
        _rewrite_bound_artifact,
    )

    project_root, run_root = _materialize_survey_run(tmp_path)

    def mark_malformed(payload: dict[str, object]) -> None:
        payload["model_type"] = ["ordinal"]

    _rewrite_bound_artifact(run_root, mark_malformed)

    capability = survey_service.issue_survey_run_capability(
        project_root, run_root.name
    )
    projection = survey_service.read_survey_consumer_projection(capability, "agent")

    assert projection["status"] == "unavailable"
    assert projection["reason"] == "SURVEY_MODEL_FAMILY_UNSUPPORTED"
    assert projection["source_status"] == "validated"
    assert projection["survey_design"]["variance_method"]
