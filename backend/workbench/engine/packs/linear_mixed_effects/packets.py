"""Pack-local constructors for the C1-locked LMM packet envelopes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from workbench.contracts.common.envelope import PacketEnvelope
from workbench.contracts.model.linear_mixed_effects import LMM_CONTRACT_VERSION


LMM_PRODUCER_VERSION = "linear_mixed_effects@1.0"


def _packet(contract: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build one of the existing C1 packet contracts, never a new contract."""

    return PacketEnvelope(
        contract=contract,
        contract_version=LMM_CONTRACT_VERSION,
        producer_version=LMM_PRODUCER_VERSION,
        payload=payload,
    ).to_dict()


def build_lmm_result_packet(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Envelope the public result payload, including its data-only figure facts."""

    return _packet("linear_mixed_effects.result", payload)


def build_lmm_diagnostic_packet(
    *, status: str, diagnostics: Sequence[Mapping[str, object]]
) -> dict[str, Any]:
    """Envelope normalized terminal or non-terminal diagnostic facts."""

    return _packet(
        "linear_mixed_effects.diagnostic",
        {
            "status": status,
            "diagnostics": [dict(diagnostic) for diagnostic in diagnostics],
        },
    )

def build_lmm_recovery_packet(
    action_candidate: Mapping[str, object],
) -> dict[str, Any]:
    """Envelope the only C1-locked, confirmation-required recovery proposal."""

    return _packet(
        "linear_mixed_effects.recovery_proposal",
        {
            "proposal_status": "pending_confirmation",
            "action_candidate": dict(action_candidate),
        },
    )
