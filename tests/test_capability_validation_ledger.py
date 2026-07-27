from __future__ import annotations

import pytest


def test_failed_attempts_are_retained_and_budget_is_hard():
    from workbench.capability_factory.validation_ledger import (
        AttemptBudgetExceeded,
        ValidationAttemptLedger,
    )

    ledger = ValidationAttemptLedger()
    bundle_ref = "a" * 64
    protocol_ref = "b" * 64
    first = ledger.append(
        bundle_ref=bundle_ref,
        protocol_ref=protocol_ref,
        attempt_number=1,
        outcome="failed",
        result_ref="c" * 64,
    )
    assert first.attempt_number == 1
    assert len(ledger.history(bundle_ref, protocol_ref)) == 1

    ledger.append(
        bundle_ref=bundle_ref,
        protocol_ref=protocol_ref,
        attempt_number=2,
        outcome="passed",
        result_ref="d" * 64,
    )
    with pytest.raises(AttemptBudgetExceeded, match="budget"):
        ledger.append(
            bundle_ref=bundle_ref,
            protocol_ref=protocol_ref,
            attempt_number=3,
            outcome="passed",
            result_ref="e" * 64,
            max_attempts=2,
        )
