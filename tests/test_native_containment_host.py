from __future__ import annotations

from pathlib import Path


def test_host_assessment_binds_backend_identity_and_canary_revision():
    from workbench.native_containment.host import HostContainmentAssessment, HostIdentity

    identity = HostIdentity(
        os_name="Darwin",
        kernel_release="test-kernel",
        architecture="arm64",
        backend_executable="/usr/bin/sandbox-exec",
        backend_version="1",
        backend_digest="a" * 64,
    )
    assessment = HostContainmentAssessment(
        assessment_id="assessment.alpha",
        host=identity,
        profile_id="strict-readonly-v1",
        canary_suite_ref="b" * 64,
        outcome="unsupported",
        reason_code="NATIVE_CONTAINMENT_RESOURCE_LIMIT_UNAVAILABLE",
        validity_revision=1,
        control_sequence=1,
    )
    assert assessment.content_digest
    assert Path(identity.backend_executable).is_absolute()


def test_host_validity_is_append_only_and_terminal_states_do_not_restore():
    import pytest
    from workbench.native_containment.host import (
        HostContainmentAssessment,
        HostContainmentValidityStore,
        HostIdentity,
        HostAssessmentError,
    )

    assessment = HostContainmentAssessment(
        assessment_id="assessment.validity",
        host=HostIdentity(
            os_name="Darwin",
            kernel_release="test-kernel",
            architecture="arm64",
            backend_executable="/usr/bin/sandbox-exec",
            backend_version="1",
            backend_digest="a" * 64,
        ),
        profile_id="strict-readonly-v1",
        canary_suite_ref="b" * 64,
        outcome="unsupported",
        reason_code="NATIVE_CONTAINMENT_CANARY_FAILED",
        validity_revision=1,
        control_sequence=1,
    )
    store = HostContainmentValidityStore()
    first = store.append(
        assessment=assessment,
        status="unsupported",
        reason_code="NATIVE_CONTAINMENT_CANARY_FAILED",
        authority_ref="c" * 64,
        control_sequence=1,
    )
    assert first.revision == 1
    with pytest.raises(HostAssessmentError, match="terminal"):
        store.append(
            assessment=assessment,
            status="valid",
            reason_code="restored",
            authority_ref="d" * 64,
            control_sequence=2,
        )


def test_host_validity_store_resolves_only_the_current_validity_record():
    import pytest
    from workbench.native_containment.host import (
        HostAssessmentError,
        HostContainmentAssessment,
        HostContainmentValidityStore,
        HostIdentity,
    )

    assessment = HostContainmentAssessment(
        assessment_id="assessment.current",
        host=HostIdentity(
            os_name="Darwin",
            kernel_release="test-kernel",
            architecture="arm64",
            backend_executable="/usr/bin/sandbox-exec",
            backend_version="1",
            backend_digest="a" * 64,
        ),
        profile_id="strict-readonly-v1",
        canary_suite_ref="b" * 64,
        outcome="supported",
        reason_code="NATIVE_CONTAINMENT_CANARY_PASSED",
        validity_revision=1,
        control_sequence=1,
    )
    store = HostContainmentValidityStore()
    current = store.append(
        assessment=assessment,
        status="valid",
        reason_code="canary_passed",
        authority_ref="c" * 64,
        control_sequence=1,
    )
    assert store.require_current(current.content_digest) == current
    store.append(
        assessment=assessment,
        status="expired",
        reason_code="lease_expired",
        authority_ref="d" * 64,
        control_sequence=2,
    )
    with pytest.raises(HostAssessmentError, match="current"):
        store.require_current(current.content_digest)


def test_canary_result_has_a_stable_content_reference():
    from workbench.native_containment.host import CanaryAssertion, CanaryResult

    result = CanaryResult(
        status="unsupported",
        reason_code="NATIVE_CONTAINMENT_CANARY_FAILED",
        assertions=(CanaryAssertion("network_denied", False, "not proven"),),
    )
    assert result.content_digest


def test_assessment_factory_binds_the_complete_canary_result():
    from workbench.native_containment.host import (
        CanaryResult,
        HostContainmentAssessment,
        HostIdentity,
    )

    result = CanaryResult.unsupported("NATIVE_CONTAINMENT_BACKEND_UNAVAILABLE")
    assessment = HostContainmentAssessment.from_canary(
        assessment_id="assessment.factory",
        host=HostIdentity(
            os_name="Darwin",
            kernel_release="test-kernel",
            architecture="arm64",
            backend_executable="/usr/bin/sandbox-exec",
            backend_version="1",
            backend_digest="a" * 64,
        ),
        profile_id="strict-readonly-v1",
        result=result,
        validity_revision=1,
        control_sequence=1,
    )
    assert assessment.canary_suite_ref == result.content_digest
    assert assessment.outcome == "unsupported"
