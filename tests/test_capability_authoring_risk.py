from __future__ import annotations

import pytest


def test_authoring_guard_is_high_risk_and_never_execution():
    from workbench.agent.capability_authoring import CapabilityAuthoringGuard

    guard = CapabilityAuthoringGuard()
    decision = guard.evaluate(candidate_ref="a" * 64, source_kind="authored_implementation")
    assert decision.risk_level == "high"
    assert decision.confirmation_required is True
    assert decision.execution_allowed is False


def test_authoring_guard_rejects_unknown_source_kind():
    from workbench.agent.capability_authoring import CapabilityAuthoringGuard

    with pytest.raises(ValueError, match="source_kind"):
        CapabilityAuthoringGuard().evaluate(candidate_ref="a" * 64, source_kind="unknown")
