from __future__ import annotations

from dataclasses import replace

import pytest


def _protocol():
    from workbench.capability_factory.validation_protocols import ValidationProtocol

    return ValidationProtocol(
        protocol_id="statistical.standard",
        revision=1,
        check_kinds=(
            "known_truth",
            "boundary_error",
            "trusted_comparison",
            "numerical_stability",
            "repeatability",
            "scale_resource",
            "output_schema",
        ),
        evidence_floor="E1",
        max_attempts=3,
        seed_policy_ref="a" * 64,
        threshold_policy_ref="b" * 64,
        holdout_policy_ref="c" * 64,
    )


def test_protocol_is_registered_and_digest_bound():
    from workbench.capability_factory.validation_protocols import ValidationProtocolRegistry

    protocol = _protocol()
    registry = ValidationProtocolRegistry()
    assert registry.register(protocol) == protocol.content_digest
    assert registry.get(protocol.content_digest) == protocol


def test_protocol_rejects_unknown_checks_and_zero_budget():
    from workbench.capability_factory.validation_protocols import ValidationProtocol, ValidationProtocolError

    with pytest.raises(ValidationProtocolError, match="check"):
        ValidationProtocol(
            protocol_id="bad",
            revision=1,
            check_kinds=("made_up",),
            evidence_floor="E1",
            max_attempts=1,
            seed_policy_ref="a" * 64,
            threshold_policy_ref="b" * 64,
            holdout_policy_ref="c" * 64,
        )

    with pytest.raises(ValidationProtocolError, match="attempt"):
        ValidationProtocol(
            protocol_id="bad-budget",
            revision=1,
            check_kinds=("known_truth",),
            evidence_floor="E1",
            max_attempts=0,
            seed_policy_ref="a" * 64,
            threshold_policy_ref="b" * 64,
            holdout_policy_ref="c" * 64,
        )


def test_protocol_identity_cannot_be_rebound_by_a_new_digest():
    from workbench.capability_factory.validation_protocols import (
        ValidationProtocolError,
        ValidationProtocolRegistry,
    )

    registry = ValidationProtocolRegistry()
    protocol = _protocol()
    registry.register(protocol)
    with pytest.raises(ValidationProtocolError, match="identity"):
        registry.register(replace(protocol, threshold_policy_ref="e" * 64))
