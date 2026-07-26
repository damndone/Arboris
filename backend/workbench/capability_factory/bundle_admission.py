"""Explicit append-only bundle admission transitions."""

from __future__ import annotations

from .dependency_contract import BundleAdmission
from .contracts import _digest


class AdmissionError(ValueError):
    """Raised when a bundle skips or repeats an admission transition."""


class BundleAdmissionController:
    def __init__(self) -> None:
        self._history: dict[str, list[BundleAdmission]] = {}

    def quarantine(self, *, bundle_ref: str) -> BundleAdmission:
        bundle_ref = _digest(bundle_ref, "bundle_ref")
        if self._history.get(bundle_ref):
            raise AdmissionError("bundle already has an admission history")
        return self._append(
            BundleAdmission(
                bundle_ref=bundle_ref,
                status="quarantined",
                scope="project",
                validity_ref=bundle_ref,
                reason_code="quarantine_created",
            )
        )

    def mark_validated(self, *, bundle_ref: str, validation_ref: str) -> BundleAdmission:
        latest = self._latest(bundle_ref)
        if latest.status != "quarantined":
            raise AdmissionError("only quarantined bundles can be validated")
        return self._append(
            BundleAdmission(
                bundle_ref=latest.bundle_ref,
                status="validated",
                scope=latest.scope,
                validity_ref=_digest(validation_ref, "validation_ref"),
                reason_code="offline_validation_passed",
            )
        )

    def admit(self, *, bundle_ref: str, scope: str, validity_ref: str) -> BundleAdmission:
        latest = self._latest(bundle_ref)
        if latest.status != "validated":
            raise AdmissionError("only validated bundles can be admitted")
        return self._append(
            BundleAdmission(
                bundle_ref=latest.bundle_ref,
                status="admitted",
                scope=scope,
                validity_ref=validity_ref,
                reason_code="scope_admission_granted",
            )
        )

    def revoke(self, *, bundle_ref: str, validity_ref: str) -> BundleAdmission:
        latest = self._latest(bundle_ref)
        if latest.status in {"revoked", "rejected"}:
            raise AdmissionError("bundle is already terminal")
        return self._append(
            BundleAdmission(
                bundle_ref=latest.bundle_ref,
                status="revoked",
                scope=latest.scope,
                validity_ref=validity_ref,
                reason_code="admission_revoked",
            )
        )

    def history(self, bundle_ref: str) -> tuple[BundleAdmission, ...]:
        return tuple(self._history.get(_digest(bundle_ref, "bundle_ref"), ()))

    def _latest(self, bundle_ref: str) -> BundleAdmission:
        reference = _digest(bundle_ref, "bundle_ref")
        try:
            return self._history[reference][-1]
        except (KeyError, IndexError) as error:
            raise AdmissionError("bundle is not quarantined") from error

    def _append(self, record: BundleAdmission) -> BundleAdmission:
        self._history.setdefault(record.bundle_ref, []).append(record)
        return record


__all__ = ["AdmissionError", "BundleAdmissionController"]
