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

    def restore(self, history: tuple[BundleAdmission, ...] | list[BundleAdmission]) -> None:
        """Rehydrate one persisted history without bypassing transition rules.

        The controller is intentionally in-memory, while the dependency store
        is durable.  A new process must therefore restore the already-written
        prefix before it can append the next transition.  This method accepts
        only a complete, ordered history and never permits a caller to replace
        a different history for the same bundle.
        """

        records = tuple(history)
        if not records or any(not isinstance(item, BundleAdmission) for item in records):
            raise AdmissionError("admission history must contain BundleAdmission records")
        bundle_ref = records[0].bundle_ref
        if any(item.bundle_ref != bundle_ref for item in records):
            raise AdmissionError("admission history contains another bundle")
        if len({item.content_digest for item in records}) != len(records):
            raise AdmissionError("admission history contains a duplicate transition")
        if records[0].status != "quarantined":
            raise AdmissionError("admission history must begin with quarantine")
        transitions = {
            "quarantined": frozenset({"validated", "rejected", "revoked"}),
            "validated": frozenset({"admitted", "rejected", "revoked"}),
            "admitted": frozenset({"revoked"}),
        }
        for previous, current in zip(records, records[1:]):
            allowed = transitions.get(previous.status, frozenset())
            if current.status not in allowed:
                raise AdmissionError(
                    f"invalid persisted transition {previous.status} -> {current.status}"
                )
        existing = self._history.get(bundle_ref)
        if existing is not None and tuple(existing) != records:
            raise AdmissionError("bundle admission history is already bound differently")
        self._history[bundle_ref] = list(records)

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
