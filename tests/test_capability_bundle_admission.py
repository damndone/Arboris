from __future__ import annotations

import pytest


def test_bundle_admission_requires_validation_before_scope_admission():
    from workbench.capability_factory.bundle_admission import BundleAdmissionController

    controller = BundleAdmissionController()
    bundle_ref = "a" * 64
    quarantine = controller.quarantine(bundle_ref=bundle_ref)
    assert quarantine.status == "quarantined"

    validated = controller.mark_validated(bundle_ref=bundle_ref, validation_ref="b" * 64)
    admitted = controller.admit(bundle_ref=bundle_ref, scope="project", validity_ref="c" * 64)

    assert validated.status == "validated"
    assert admitted.status == "admitted"


def test_bundle_admission_rejects_direct_admit_and_keeps_revocation_history():
    from workbench.capability_factory.bundle_admission import AdmissionError, BundleAdmissionController

    controller = BundleAdmissionController()
    with pytest.raises(AdmissionError):
        controller.admit(bundle_ref="a" * 64, scope="project", validity_ref="c" * 64)
    controller.quarantine(bundle_ref="a" * 64)
    controller.mark_validated(bundle_ref="a" * 64, validation_ref="b" * 64)
    controller.admit(bundle_ref="a" * 64, scope="project", validity_ref="c" * 64)
    revoked = controller.revoke(bundle_ref="a" * 64, validity_ref="d" * 64)

    assert revoked.status == "revoked"
    assert [item.status for item in controller.history("a" * 64)] == [
        "quarantined", "validated", "admitted", "revoked"
    ]
