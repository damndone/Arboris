from __future__ import annotations

import pytest

from workbench.agent.context_tools import (
    AnalysisLoopContextError,
    inspect_analysis_loop_context,
)
from workbench.analysis_loop.validation import ValidationCheck, ValidationPacket


def _source() -> dict[str, object]:
    return {
        "run_id": "run-source",
        "status": "completed",
        "model": "ols",
        "covariance": "unadjusted",
        "primary_target": "coef:treatment",
        "diagnostics": {"status": "available"},
    }


def _validation() -> ValidationPacket:
    return ValidationPacket(
        status="complete",
        overall_status="passed",
        terminal=True,
        checks=(
            ValidationCheck(
                check_id="execution.integrity",
                status="pass",
                severity="info",
                expected=True,
                observed=True,
            ),
        ),
        logical_key="validation:one",
        child_run_id="run-child",
        source_run_id="run-source",
        plan_hash="plan-hash",
        executed_payload_hash="payload-hash",
        artifact_manifest_hash="artifact-hash",
        validation_policy_version="validation_policy_v1",
        schema_version="validation_packet_v1",
    )


def test_context_tool_returns_only_declared_inspect_scope() -> None:
    result = inspect_analysis_loop_context(source_context=_source(), scope="inspect")

    assert result["status"] == "available"
    assert result["source"]["run_id"] == "run-source"
    assert "filesystem_path" not in result


def test_context_tool_exposes_packet_status_without_recomputing_it() -> None:
    result = inspect_analysis_loop_context(
        source_context=_source(), scope="validation", validation_packet=_validation()
    )

    assert result["status"] == "complete"
    assert result["packet"]["logical_key"] == "validation:one"


def test_context_tool_reports_absent_and_rejects_unknown_scope_or_secret_fields() -> None:
    result = inspect_analysis_loop_context(source_context=_source(), scope="compare")
    assert result["status"] == "not_available"
    assert result["packet"] is None

    with pytest.raises(AnalysisLoopContextError) as scope_error:
        inspect_analysis_loop_context(source_context=_source(), scope="execute")
    assert scope_error.value.code == "CONTEXT_SCOPE_UNSUPPORTED"

    with pytest.raises(AnalysisLoopContextError) as field_error:
        inspect_analysis_loop_context(
            source_context={**_source(), "api_key": "secret"}, scope="inspect"
        )
    assert field_error.value.code == "SOURCE_CONTEXT_SCOPE_VIOLATION"
