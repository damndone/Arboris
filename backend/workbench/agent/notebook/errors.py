"""Structured notebook/option failures.

Every error carries a stable `code` and a `details` mapping, because the HTTP
layer and the UI both have to distinguish "this option is out of date" from
"this option was never valid" — a generic 400 would collapse them.
"""

from __future__ import annotations

from typing import Any


class NotebookOptionError(RuntimeError):
    """Base class. Subclasses pin a machine-readable `code`."""

    code = "NOTEBOOK_ERROR"
    status_code = 400

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.details: dict[str, Any] = dict(details)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": dict(self.details)}


class NotebookNotFound(NotebookOptionError):
    code = "NOTEBOOK_NOT_FOUND"
    status_code = 404


class OptionNotFound(NotebookOptionError):
    code = "OPTION_NOT_FOUND"
    status_code = 404


class NotebookRunFamilyImmutable(NotebookOptionError):
    """spec §2.3: `notebook.run_family_id` cannot change after creation."""

    code = "NOTEBOOK_RUN_FAMILY_IMMUTABLE"
    status_code = 409


class OptionBatchInvalid(NotebookOptionError):
    """A generation batch violated §6. The specific rule is in `code`.

    The code is per-instance rather than per-class because the caller reacts the
    same way to all of them (regenerate), while a human debugging a bad agent
    needs to know which of the four rules it broke.
    """

    code = "OPTION_BATCH_INVALID"
    status_code = 422

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message, **details)
        self.code = code


class OptionValidationFailed(NotebookOptionError):
    """spec §7: an option whose proposal fails its operation validator is refused
    at creation time rather than stored and apologised for days later."""

    code = "OPTION_VALIDATION_FAILED"
    status_code = 422


class OptionRevisionStale(NotebookOptionError):
    """spec §3.3/§4.2 — the fail-closed execution gate."""

    code = "OPTION_REVISION_STALE"
    status_code = 409


class OptionLegacyUnverified(NotebookOptionError):
    """A v1.0 option cannot enter the evidence-backed materialization path."""

    code = "OPTION_LEGACY_UNVERIFIED"
    status_code = 409


class OptionMaterializationRequired(NotebookOptionError):
    """A v1.1 option needs Task 7 Draft provenance before execution."""

    code = "OPTION_MATERIALIZATION_REQUIRED"
    status_code = 409


class OptionLifecycleTransitionInvalid(NotebookOptionError):
    code = "OPTION_LIFECYCLE_TRANSITION_INVALID"
    status_code = 409


class ArtifactSchemaContractUnsupported(NotebookOptionError):
    """spec §5.3 — `schema_ref` is refused, never silently ignored."""

    code = "ARTIFACT_SCHEMA_CONTRACT_UNSUPPORTED"
    status_code = 422


class ArtifactNotDeclarable(NotebookOptionError):
    """spec §5.4 — a required artifact must come from the published vocabulary."""

    code = "ARTIFACT_REQUIRED_NOT_DECLARABLE"
    status_code = 422


__all__ = [
    "ArtifactNotDeclarable",
    "ArtifactSchemaContractUnsupported",
    "NotebookNotFound",
    "NotebookOptionError",
    "NotebookRunFamilyImmutable",
    "OptionBatchInvalid",
    "OptionLifecycleTransitionInvalid",
    "OptionLegacyUnverified",
    "OptionMaterializationRequired",
    "OptionNotFound",
    "OptionRevisionStale",
    "OptionValidationFailed",
]
