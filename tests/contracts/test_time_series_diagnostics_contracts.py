from __future__ import annotations

import pytest

from workbench.contracts.common.envelope import ContractError
from workbench.contracts.model.time_series_diagnostics import (
    OperationExecutionEnvelope,
)


def _envelope(
    *,
    operation_status: str,
    reason_code: str = "ASSESSMENT_COMPLETED",
    facts_packet_ref: str | None = None,
    assessment_packet_ref: str | None = None,
) -> dict[str, object]:
    return {
        "operation_status": operation_status,
        "reason_code": reason_code,
        "facts_packet_ref": facts_packet_ref,
        "assessment_packet_ref": assessment_packet_ref,
    }


@pytest.mark.parametrize(
    ("operation_status", "reason_code", "facts_packet_ref", "assessment_packet_ref"),
    [
        ("completed", "ASSESSMENT_COMPLETED", "facts:fixture", "assessment:fixture"),
        ("completed", "HARD_DATA_INPUT", "facts:fixture", "assessment:fixture"),
        ("rejected", "USER_REJECTED", None, None),
        ("failed", "EXECUTOR_TIMEOUT", None, None),
        ("failed", "EXECUTOR_OOM", None, None),
        ("failed", "TERMINATED_EXECUTOR", None, None),
        ("failed", "CORRUPT_PACK_OUTPUT", None, None),
        ("cancelled", "USER_CANCELLED", None, None),
    ],
)
def test_execution_envelope_allows_only_legal_status_reference_combinations(
    operation_status: str,
    reason_code: str,
    facts_packet_ref: str | None,
    assessment_packet_ref: str | None,
) -> None:
    envelope = OperationExecutionEnvelope.from_dict(
        _envelope(
            operation_status=operation_status,
            reason_code=reason_code,
            facts_packet_ref=facts_packet_ref,
            assessment_packet_ref=assessment_packet_ref,
        )
    )

    assert envelope.operation_status == operation_status
    assert envelope.to_dict() == _envelope(
        operation_status=operation_status,
        reason_code=reason_code,
        facts_packet_ref=facts_packet_ref,
        assessment_packet_ref=assessment_packet_ref,
    )


@pytest.mark.parametrize(
    ("operation_status", "reason_code"),
    [
        ("rejected", "USER_REJECTED"),
        ("failed", "EXECUTOR_TIMEOUT"),
        ("cancelled", "USER_CANCELLED"),
    ],
)
def test_non_completed_execution_envelope_rejects_packet_references(
    operation_status: str,
    reason_code: str,
) -> None:
    with pytest.raises(ContractError, match="packet refs require completed"):
        OperationExecutionEnvelope.from_dict(
            _envelope(
                operation_status=operation_status,
                reason_code=reason_code,
                facts_packet_ref="facts:forbidden",
                assessment_packet_ref="assessment:forbidden",
            )
        )


@pytest.mark.parametrize(
    ("facts_packet_ref", "assessment_packet_ref"),
    [(None, "assessment:fixture"), ("facts:fixture", None), (None, None)],
)
def test_completed_execution_envelope_requires_both_packet_references(
    facts_packet_ref: str | None,
    assessment_packet_ref: str | None,
) -> None:
    with pytest.raises(ContractError, match="completed requires both packet refs"):
        OperationExecutionEnvelope.from_dict(
            _envelope(
                operation_status="completed",
                facts_packet_ref=facts_packet_ref,
                assessment_packet_ref=assessment_packet_ref,
            )
        )


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"unknown": True}, "unknown operation execution envelope field"),
        ({"operation_status": "queued"}, "operation_status"),
        ({"reason_code": "UNDECLARED_REASON"}, "reason_code"),
    ],
)
def test_execution_envelope_rejects_unknown_fields_statuses_and_reasons(
    override: dict[str, object], message: str
) -> None:
    with pytest.raises(ContractError, match=message):
        OperationExecutionEnvelope.from_dict(
            {
                **_envelope(
                    operation_status="completed",
                    facts_packet_ref="facts:fixture",
                    assessment_packet_ref="assessment:fixture",
                ),
                **override,
            }
        )


def test_execution_envelope_rejects_fixture_identity_as_a_public_reason() -> None:
    with pytest.raises(ContractError, match="reason_code"):
        OperationExecutionEnvelope.from_dict(
            _envelope(
                operation_status="completed",
                reason_code="FIXTURE_STATE",
                facts_packet_ref="facts:fixture",
                assessment_packet_ref="assessment:fixture",
            )
        )


@pytest.mark.parametrize(
    ("operation_status", "reason_code", "facts_packet_ref", "assessment_packet_ref"),
    [
        ("completed", "EXECUTOR_TIMEOUT", "facts:fixture", "assessment:fixture"),
        ("failed", "HARD_DATA_INPUT", None, None),
    ],
)
def test_execution_envelope_rejects_reason_codes_for_another_terminal_status(
    operation_status: str,
    reason_code: str,
    facts_packet_ref: str | None,
    assessment_packet_ref: str | None,
) -> None:
    with pytest.raises(
        ContractError, match="reason_code is not allowed for operation_status"
    ):
        OperationExecutionEnvelope.from_dict(
            _envelope(
                operation_status=operation_status,
                reason_code=reason_code,
                facts_packet_ref=facts_packet_ref,
                assessment_packet_ref=assessment_packet_ref,
            )
        )
