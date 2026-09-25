"""Model-results reading + issue-stream normalization.

Reads the ``model_results/*.json`` a run produced and reconciles the stored
guardrail issues with the final preprocessing state (e.g. surfacing
auto-dummy-coding as an INFO issue). Pure functions over a run directory and
plain dicts — no HTTP, no filesystem writes.

Extracted verbatim from ``api.py`` in v1.6.10 (D1 decomposition, Phase 2).
"""
from __future__ import annotations

import json
import os
import re
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from ..artifacts import read_json
from ..canonical import canonical_json_v1, sha256_canonical
from ..domain import GuardrailIssue, Severity
from ..evidence.authority import (
    EvidenceHostAuthorityError,
    build_authority_request,
    issue_host_proof,
    validate_host_proof,
)
from ..term_parser import is_q_quoted_dummy, parse_term
from .lmm_result_adapter import read_lmm_public_results
from .classification_consumer_service import read_classification_report_evidence


def _delivery_wire_size(value: object) -> int:
    # Match JSONResponse bytes; canonical JSON normalizes identity strings to
    # NFC for hashing, but the transport must preserve the exact owner value.
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))


def read_classification_evidence_for_report(
    capability: object,
) -> dict[str, object]:
    """Expose Report classification evidence through the central service."""

    return read_classification_report_evidence(capability)


_OLS_RESULT_CONTRACT_RE = re.compile(r"^ols_result_contract_v(\d+)$")


def validate_result_contract(result: Mapping[str, object]) -> dict[str, object]:
    """Read and validate the additive OLS contract without label inference."""
    if not isinstance(result, Mapping):
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: result must be an object")
    version = result.get("contract_version")
    match = _OLS_RESULT_CONTRACT_RE.fullmatch(version) if isinstance(version, str) else None
    if match is None or int(match.group(1)) < 1:
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: missing or unsupported OLS contract")
    if result.get("model") != "ols" or result.get("model_type") not in {
        "ols",
        "ols_robust",
        "ols_clustered",
    }:
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: result is not an OLS result")
    stable_ids = result.get("stable_result_ids")
    candidates = result.get("candidate_result_ids")
    coefficients = result.get("coefficients")
    if (
        not isinstance(stable_ids, list)
        or not stable_ids
        or any(not isinstance(item, str) or not item for item in stable_ids)
        or len(set(stable_ids)) != len(stable_ids)
        or candidates != stable_ids
        or not isinstance(coefficients, Mapping)
    ):
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: unstable OLS result IDs")
    coefficient_ids = {
        coefficient.get("result_id")
        for coefficient in coefficients.values()
        if isinstance(coefficient, Mapping)
    }
    if coefficient_ids != set(stable_ids):
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: coefficient IDs do not match result IDs")
    return dict(result)


def read_coefficient_by_result_id(
    result: Mapping[str, object], result_id: str
) -> dict[str, object] | None:
    """Resolve an OLS coefficient by its stored stable ID, never by display label."""
    validated = validate_result_contract(result)
    coefficients = validated["coefficients"]
    if not isinstance(coefficients, Mapping) or not isinstance(result_id, str):
        return None
    for coefficient in coefficients.values():
        if isinstance(coefficient, Mapping) and coefficient.get("result_id") == result_id:
            return dict(coefficient)
    return None


def read_model_results(run_root: Path) -> list[dict]:
    model_dir = run_root / "model_results"
    results: list[dict] = []
    if model_dir.is_dir():
        for path in sorted(model_dir.glob("*.json")):
            data = read_json(path)
            if isinstance(data, dict) and isinstance(data.get("coefficients"), dict):
                results.append(data)
    # ``exists()`` follows links and returns False for a dangling index
    # symlink.  A lexical entry is an untrusted versioned-result boundary and
    # must reach the pinned reader, which rejects it fail-closed.
    if os.path.lexists(run_root / "artifacts_index.json"):
        results.extend(read_lmm_public_results(run_root))
    return results


def _model_results(run_root: Path) -> list[dict]:
    """Compatibility wrapper for the existing HTTP route import."""

    return read_model_results(run_root)


def _normalize_issue_stream(errors: dict, model_results: list[dict]) -> dict:
    """Align legacy/stored issues with the final model preprocessing state."""
    issues = errors.get("issues", [])
    if not isinstance(issues, list):
        return {"issues": []}
    dummy_coded = _dummy_coded_columns(model_results)
    if not dummy_coded:
        return {"issues": issues}

    normalized: list[dict] = []
    emitted_auto: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            normalized.append(issue)
            continue
        evidence = issue.get("evidence", {})
        column = evidence.get("column") if isinstance(evidence, dict) else None
        if issue.get("code") == "CATEGORICAL_CANDIDATE" and column in dummy_coded:
            if column not in emitted_auto:
                normalized.append(_auto_dummy_coded_issue(column))
                emitted_auto.add(column)
            continue
        normalized.append(issue)

    existing_auto = {
        issue.get("evidence", {}).get("column")
        for issue in normalized
        if isinstance(issue, dict)
        and issue.get("code") == "CATEGORICAL_AUTO_DUMMY_CODED"
        and isinstance(issue.get("evidence"), dict)
    }
    for column in sorted(dummy_coded - existing_auto - emitted_auto):
        normalized.append(_auto_dummy_coded_issue(column))
    return {"issues": normalized}


def _dummy_coded_columns(model_results: list[dict]) -> set[str]:
    columns: set[str] = set()
    for result in model_results:
        coefficients = result.get("coefficients", {})
        if not isinstance(coefficients, dict):
            continue
        for term in coefficients:
            if not isinstance(term, str):
                continue
            if is_q_quoted_dummy(term):
                columns.add(parse_term(term).source_id)
    return columns


def _auto_dummy_coded_issue(column: str) -> dict:
    return GuardrailIssue(
        Severity.INFO,
        "CATEGORICAL_AUTO_DUMMY_CODED",
        f"Column '{column}' was detected as categorical and automatically dummy-coded.",
        evidence={"column": column, "preprocessing": "dummy_coded"},
        affected_stage="data_cleaning",
        variables=[column],
        template_key="categorical_auto_dummy",
    ).to_dict()


# v1.8.9 consumer projection seam.  It is intentionally appended to the
# legacy results reader: the old run-directory readers remain compatibility
# code, while Report evidence is owned exclusively by the C0 persistence
# capability below.
from ..contracts.evidence.persistence import EvidenceCommitBindingV1
from ..evidence.consumer_adapters import (
    EvidenceProjectionError,
    ServerOwnedEvidenceProjectionSourceV1,
    ServerOwnedEvidenceSensitivityPolicyV1,
)
from ..evidence.contracts import ArtifactAdmissionV1
from ..evidence.persistence import (
    EvidencePacketStoreV1,
    EvidencePersistenceAdmissionV1,
    EvidencePersistenceError,
)
from ..evidence.registry import (
    EvidenceRegistryError,
    EvidenceRegistryReceiptV1,
    EvidenceRegistryV1,
    validate_registry_persistence_receipt,
)


class PersistedEvidenceResultsFacadeV1:
    """Retired compatibility name; arbitrary ``.load`` ports are not authority.

    The import remains only as a typed rejection for old callers.  It has no
    load/read contract and can never construct a trusted envelope.
    """

    __slots__ = ()

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise EvidenceProjectionError(
            "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
            "PersistedEvidenceResultsFacadeV1 is retired; use the server-owned C0 EvidencePacketStoreV1 capability",
        )


@dataclass(frozen=True, slots=True)
class ReportEvidenceRequestIdentityV1:
    """Server-observed identity used at the HTTP-to-Report boundary."""

    actor_ref: str
    project_ref: str
    session_ref: str
    scope_ref: str
    run_id: str
    model_run_id: str
    confirmation_ref: str


_REPORT_OWNER_ADMISSIONS: weakref.WeakKeyDictionary[object, object] = weakref.WeakKeyDictionary()
_REPORT_OWNER_SOURCE_BINDINGS: weakref.WeakKeyDictionary[object, ServerOwnedEvidenceProjectionSourceV1] = weakref.WeakKeyDictionary()
_REPORT_OWNER_ADMISSIONS_LOCK = RLock()
_REPORT_REQUEST_IDENTITY_ADMISSIONS: dict[tuple[int, int], ReportEvidenceRequestIdentityV1] = {}


def _report_owner_payload_digest(
    *,
    actor_ref: str,
    project_ref: str,
    session_ref: str,
    scope_ref: str,
    run_id: str,
    model_run_id: str,
    artifact_id: str,
    commit_id: str,
    confirmation_ref: str,
    artifact_file_sha256: str,
    canonical_project_root: Path | str | None,
    root_device: int,
    root_inode: int,
) -> str:
    return sha256_canonical(
        {
            "actor_ref": actor_ref,
            "project_ref": project_ref,
            "session_ref": session_ref,
            "scope_ref": scope_ref,
            "run_id": run_id,
            "model_run_id": model_run_id,
            "artifact_id": artifact_id,
            "commit_id": commit_id,
            "confirmation_ref": confirmation_ref,
            "artifact_file_sha256": artifact_file_sha256,
            "canonical_project_root": (
                None
                if canonical_project_root is None
                else str(Path(canonical_project_root).expanduser().resolve(strict=False))
            ),
            "persistence_root": {
                "device": root_device,
                "inode": root_inode,
            },
        }
    )


class ServerOwnedReportEvidencePersistenceV1:
    """Read Report evidence through the real C0 store, registry, and receipt."""

    __slots__ = (
        "_evidence_store",
        "_registry",
        "_receipt",
        "_actor_ref",
        "_project_ref",
        "_session_ref",
        "_scope_ref",
        "_run_id",
        "_model_run_id",
        "_artifact_id",
        "_commit_id",
        "_envelope_digest",
        "_confirmation_ref",
        "_artifact_file_sha256",
        "_canonical_project_root",
        "_project_file_store",
        "_canonical_record",
        "_authority_handle",
        "_authority_request",
        "_authority_proof",
        "_report_request_identity",
        "_canonical_artifact",
        "_report_authority_marker",
        "__weakref__",
    )

    def __init__(
        self,
        evidence_store: EvidencePacketStoreV1,
        registry: EvidenceRegistryV1,
        receipt: EvidenceRegistryReceiptV1,
        *,
        actor_ref: str,
        project_ref: str,
        session_ref: str,
        scope_ref: str,
        run_id: str,
        model_run_id: str,
        artifact_id: str,
        commit_id: str,
        confirmation_ref: str,
        artifact_file_sha256: str,
        canonical_project_root: Path | str | None = None,
        project_file_store: object | None = None,
        authority_handle: object | None = None,
    ) -> None:
        if authority_handle is None:
            raise EvidenceProjectionError(
                "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                "Report evidence owner construction requires a host-issued C0 capability",
            )
        if type(evidence_store) is not EvidencePacketStoreV1:
            raise EvidenceProjectionError(
                "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
                "Report evidence requires the server-owned EvidencePacketStoreV1",
            )
        if type(registry) is not EvidenceRegistryV1 or type(receipt) is not EvidenceRegistryReceiptV1:
            raise EvidenceProjectionError(
                "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
                "Report evidence requires a registry-issued persistence receipt",
            )
        if type(run_id) is not str or not run_id.strip():
            raise EvidenceProjectionError(
                "EVIDENCE_RUN_ID_REQUIRED",
                "Report evidence requires a server-owned run identity",
            )
        if type(model_run_id) is not str or not model_run_id.strip():
            raise EvidenceProjectionError(
                "EVIDENCE_MODEL_RUN_ID_REQUIRED",
                "Report evidence requires a server-owned model run identity",
            )
        for name, value in (
            ("actor_ref", actor_ref),
            ("project_ref", project_ref),
            ("session_ref", session_ref),
            ("scope_ref", scope_ref),
            ("artifact_id", artifact_id),
            ("commit_id", commit_id),
            ("confirmation_ref", confirmation_ref),
            ("artifact_file_sha256", artifact_file_sha256),
        ):
            if type(value) is not str or not value.strip():
                raise EvidenceProjectionError(
                    "EVIDENCE_OWNER_CONTEXT_REQUIRED",
                    f"Report evidence requires a server-owned {name}",
                )
        if (
            len(artifact_file_sha256) != 64
            or any(char not in "0123456789abcdef" for char in artifact_file_sha256)
        ):
            raise EvidenceProjectionError(
                "EVIDENCE_ARTIFACT_FILE_HASH_REQUIRED",
                "Report evidence requires a canonical artifact file hash",
            )
        authority_request, authority_proof = self._issue_report_authority(
            evidence_store,
            registry,
            authority_handle,
            actor_ref=actor_ref,
            project_ref=project_ref,
            session_ref=session_ref,
            scope_ref=scope_ref,
            run_id=run_id,
            model_run_id=model_run_id,
            artifact_id=artifact_id,
            commit_id=commit_id,
            confirmation_ref=confirmation_ref,
            artifact_file_sha256=artifact_file_sha256,
            canonical_project_root=canonical_project_root,
        )
        try:
            if registry.scope_ref != scope_ref:
                raise EvidenceProjectionError(
                    "EVIDENCE_OWNER_CONTEXT_MISMATCH",
                    "owner scope is not the scope of the server-owned registry",
                )
            admitted = registry.get(artifact_id, scope_ref=scope_ref)
            validate_registry_persistence_receipt(
                admitted,
                receipt,
                registry=registry,
            )
            binding = evidence_store.load(
                commit_id,
                registry=registry,
                receipt=receipt,
            )
            artifact = evidence_store.load_packet(
                commit_id,
                registry=registry,
                receipt=receipt,
            )
            if (
                binding.commit_id != commit_id
                or binding.artifact_admission_ref != artifact_id
                or artifact.artifact_id != artifact_id
                or artifact.to_dict() != admitted.to_dict()
            ):
                raise EvidenceProjectionError(
                    "EVIDENCE_ADMISSION_NOT_FOUND",
                    "owner capability is not bound to the requested canonical commit and admission",
                )
            sensitivity_policy = ServerOwnedEvidenceSensitivityPolicyV1._from_host(
                scope_ref=scope_ref,
                artifact_id=artifact.artifact_id,
                commit_id=binding.commit_id,
                envelope_digest=binding.envelope_digest,
                sensitivity="unknown",
                authority_handle=authority_handle,
            )
            canonical_record = ServerOwnedEvidenceProjectionSourceV1(
                evidence_store,
                registry,
                receipt,
                scope_ref=scope_ref,
                artifact_id=artifact.artifact_id,
                commit_id=binding.commit_id,
                sensitivity_policy=sensitivity_policy,
                envelope_digest=binding.envelope_digest,
                authority_handle=authority_handle,
                project_file_store=project_file_store,
                project_ref=project_ref,
                run_id=run_id,
                canonical_project_root=canonical_project_root,
            )
        except EvidenceProjectionError:
            raise
        except (EvidencePersistenceError, EvidenceRegistryError, TypeError, ValueError, KeyError) as exc:
            raise EvidenceProjectionError(
                "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
                "owner capability is not backed by the canonical registry receipt and packet store",
            ) from exc
        self._evidence_store = evidence_store
        self._registry = registry
        self._receipt = receipt
        self._actor_ref = actor_ref
        self._project_ref = project_ref
        self._session_ref = session_ref
        self._scope_ref = scope_ref
        self._run_id = run_id
        self._model_run_id = model_run_id
        self._artifact_id = artifact_id
        self._commit_id = commit_id
        self._envelope_digest = binding.envelope_digest
        self._confirmation_ref = confirmation_ref
        self._artifact_file_sha256 = artifact_file_sha256
        self._canonical_project_root = (
            Path(canonical_project_root).expanduser().resolve(strict=False)
            if canonical_project_root is not None
            else None
        )
        self._project_file_store = project_file_store
        self._canonical_record = canonical_record
        self._authority_handle = authority_handle
        self._authority_request = authority_request
        self._authority_proof = authority_proof
        self._report_request_identity = ReportEvidenceRequestIdentityV1(
            actor_ref=self._actor_ref,
            project_ref=self._project_ref,
            session_ref=self._session_ref,
            scope_ref=self._scope_ref,
            run_id=self._run_id,
            model_run_id=self._model_run_id,
            confirmation_ref=self._confirmation_ref,
        )
        _REPORT_REQUEST_IDENTITY_ADMISSIONS[(id(self), id(self._report_request_identity))] = (
            self._report_request_identity
        )
        self._canonical_artifact = artifact
        self._report_authority_marker = object()
        with _REPORT_OWNER_ADMISSIONS_LOCK:
            _REPORT_OWNER_ADMISSIONS[self] = self
            _REPORT_OWNER_SOURCE_BINDINGS[self] = canonical_record

    @staticmethod
    def _issue_report_authority(
        evidence_store: EvidencePacketStoreV1,
        registry: EvidenceRegistryV1,
        authority_handle: object,
        *,
        actor_ref: str,
        project_ref: str,
        session_ref: str,
        scope_ref: str,
        run_id: str,
        model_run_id: str,
        artifact_id: str,
        commit_id: str,
        confirmation_ref: str,
        artifact_file_sha256: str,
        canonical_project_root: Path | str | None,
    ) -> tuple[object, str]:
        """Admit a Report owner only through the live C0 host capability."""

        try:
            if type(evidence_store) is not EvidencePacketStoreV1:
                raise EvidenceProjectionError(
                    "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
                    "Report evidence requires the server-owned EvidencePacketStoreV1",
                )
            if type(registry) is not EvidenceRegistryV1:
                raise EvidenceProjectionError(
                    "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
                    "Report evidence requires the server-owned EvidenceRegistryV1",
                )
            admission = evidence_store.admission
            if type(admission) is not EvidencePersistenceAdmissionV1:
                raise EvidenceProjectionError(
                    "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                    "Report owner admission requires the C0 persistence authority",
                )
            admitted_handle = getattr(admission, "_authority_handle", None)
            if authority_handle is not admitted_handle:
                raise EvidenceProjectionError(
                    "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                    "Report owner authority must be the C0 admission's exact host handle",
                )
            admission._validate_authority()
            registry_handle = registry._host_authority_handle()
            if registry_handle is not authority_handle:
                raise EvidenceProjectionError(
                    "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                    "Report owner authority is not bound to the C0 registry",
                )
            root_fd = admission._require_open()
            root_device = int(admission._root_dev)
            root_inode = int(admission._root_ino)
            payload_digest = _report_owner_payload_digest(
                actor_ref=actor_ref,
                project_ref=project_ref,
                session_ref=session_ref,
                scope_ref=scope_ref,
                run_id=run_id,
                model_run_id=model_run_id,
                artifact_id=artifact_id,
                commit_id=commit_id,
                confirmation_ref=confirmation_ref,
                artifact_file_sha256=artifact_file_sha256,
                canonical_project_root=canonical_project_root,
                root_device=root_device,
                root_inode=root_inode,
            )
            request = build_authority_request(
                authority_handle,
                purpose="evidence.report.owner",
                scope_ref=scope_ref,
                subject_id=id(evidence_store),
                payload_digest=payload_digest,
                root_fd=root_fd,
            )
            proof = issue_host_proof(authority_handle, request)
            validate_host_proof(authority_handle, request, proof)
            return request, proof
        except EvidenceProjectionError:
            raise
        except EvidenceHostAuthorityError as exc:
            raise EvidenceProjectionError(exc.code, str(exc)) from exc
        except (EvidencePersistenceError, EvidenceRegistryError, AttributeError, TypeError, ValueError) as exc:
            raise EvidenceProjectionError(
                "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                "Report owner authority is not backed by the live C0 host capability",
            ) from exc

    def _require_report_authority(self) -> None:
        """Revalidate the exact admitted owner before every Report boundary."""

        with _REPORT_OWNER_ADMISSIONS_LOCK:
            if _REPORT_OWNER_ADMISSIONS.get(self) is not self:
                raise EvidenceProjectionError(
                    "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                    "Report owner is not the exact host-admitted capability",
                )
        try:
            evidence_store = self._evidence_store
            registry = self._registry
            admission = evidence_store.admission
            handle = self._authority_handle
            if type(admission) is not EvidencePersistenceAdmissionV1:
                raise ValueError("persistence admission type changed")
            if getattr(admission, "_authority_handle", None) is not handle:
                raise ValueError("persistence authority handle changed")
            if registry._host_authority_handle() is not handle:
                raise ValueError("registry authority handle changed")
            if self._authority_request.subject_id != id(evidence_store):
                raise ValueError("Report owner subject binding changed")
            if self._authority_request.scope_ref != self._scope_ref:
                raise ValueError("Report owner scope binding changed")
            expected_payload = _report_owner_payload_digest(
                actor_ref=self._actor_ref,
                project_ref=self._project_ref,
                session_ref=self._session_ref,
                scope_ref=self._scope_ref,
                run_id=self._run_id,
                model_run_id=self._model_run_id,
                artifact_id=self._artifact_id,
                commit_id=self._commit_id,
                confirmation_ref=self._confirmation_ref,
                artifact_file_sha256=self._artifact_file_sha256,
                canonical_project_root=self._canonical_project_root,
                root_device=int(admission._root_dev),
                root_inode=int(admission._root_ino),
            )
            if self._authority_request.payload_digest != expected_payload:
                raise ValueError("Report owner payload binding changed")
            # The cached record is not authority and may be discarded/rebuilt.
            # Retain the originally issued host binding outside mutable caches.
            with _REPORT_OWNER_ADMISSIONS_LOCK:
                source = _REPORT_OWNER_SOURCE_BINDINGS[self]
            source._require_source_authority()
            if (source._project_file_store is not self._project_file_store
                    or source._project_ref != self._project_ref
                    or source._run_id != self._run_id
                    or source._canonical_project_root != self._canonical_project_root):
                raise ValueError("Report owner host context differs from its issued source")
            admission._validate_authority()
            validate_host_proof(handle, self._authority_request, self._authority_proof)
        except EvidenceProjectionError:
            raise
        except EvidenceHostAuthorityError as exc:
            raise EvidenceProjectionError(exc.code, str(exc)) from exc
        except (EvidencePersistenceError, EvidenceRegistryError, AttributeError, TypeError, ValueError) as exc:
            raise EvidenceProjectionError(
                "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                "Report owner authority is no longer a live C0 capability",
            ) from exc

    def __copy__(self):
        raise TypeError("host-bound Report evidence owner capabilities cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("host-bound Report evidence owner capabilities cannot be copied")

    def __reduce__(self):
        raise TypeError("host-bound Report evidence owner capabilities cannot be serialized")

    def _require_report_request_identity(
        self,
        candidate: ReportEvidenceRequestIdentityV1 | None,
    ) -> ReportEvidenceRequestIdentityV1:
        """Return the request identity rebuilt from the live owner binding."""

        self._require_report_authority()
        expected = ReportEvidenceRequestIdentityV1(
            actor_ref=self._actor_ref,
            project_ref=self._project_ref,
            session_ref=self._session_ref,
            scope_ref=self._scope_ref,
            run_id=self._run_id,
            model_run_id=self._model_run_id,
            confirmation_ref=self._confirmation_ref,
        )
        cached = getattr(self, "_report_request_identity", None)
        if (
            type(cached) is not ReportEvidenceRequestIdentityV1
            or cached != expected
            or _REPORT_REQUEST_IDENTITY_ADMISSIONS.get((id(self), id(cached))) is not cached
        ):
            cached = expected
            object.__setattr__(self, "_report_request_identity", cached)
            _REPORT_REQUEST_IDENTITY_ADMISSIONS[(id(self), id(cached))] = cached
        if candidate is not None and candidate is not cached:
            raise EvidenceProjectionError(
                "EVIDENCE_OWNER_REQUEST_REQUIRED",
                "Report request identity must be the exact owner-issued server identity",
            )
        return cached

    @classmethod
    def _from_host(cls, *args: object, **kwargs: object) -> "ServerOwnedReportEvidencePersistenceV1":
        """Construct only with the C0 host-issued capability supplied by the server."""

        return cls(*args, **kwargs)  # type: ignore[arg-type]

    @property
    def project_ref(self) -> str:
        return self._project_ref

    @property
    def actor_ref(self) -> str:
        return self._actor_ref

    @property
    def session_ref(self) -> str:
        return self._session_ref

    @property
    def scope_ref(self) -> str:
        return self._scope_ref

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def model_run_id(self) -> str:
        return self._model_run_id

    @property
    def artifact_id(self) -> str:
        return self._artifact_id

    @property
    def commit_id(self) -> str:
        return self._commit_id

    @property
    def confirmation_ref(self) -> str:
        return self._confirmation_ref

    @property
    def artifact_file_sha256(self) -> str:
        return self._artifact_file_sha256

    @property
    def canonical_project_root(self) -> Path | None:
        return self._canonical_project_root

    def accepts_project_root(self, project_root: Path | str) -> bool:
        """Check the server-owned root binding before any artifact is read."""

        try:
            self._require_report_authority()
        except EvidenceProjectionError:
            return False
        if self._canonical_project_root is None:
            return False
        try:
            return Path(project_root).expanduser().resolve(strict=False) == self._canonical_project_root
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def accepts_canonical_run_root(self, run_root: Path | str) -> bool:
        """Check the server-owned project root plus this exact run identity."""

        try:
            self._require_report_authority()
        except EvidenceProjectionError:
            return False
        if self._canonical_project_root is None:
            return False
        try:
            expected = self._canonical_project_root / "runs" / self._run_id
            return Path(run_root).expanduser().resolve(strict=False) == expected.resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def _canonical_report_wire(self) -> dict[str, object]:
        self._require_report_authority()
        from ..evidence.consumer_adapters import default_projection_registry
        from ..report_view_model import build_persisted_evidence_report_view

        source, artifact = self._canonical_report_source_and_artifact()
        projection = default_projection_registry().project(
            source,
            consumer_id="report",
            destination="local",
        )
        return build_persisted_evidence_report_view(
            projection,
            owner=self,
            artifact_admission=artifact,
        )

    def _canonical_report_artifact(self) -> ArtifactAdmissionV1:
        """Return the exact C0 artifact admission used by Report projection."""

        _source, artifact = self._canonical_report_source_and_artifact()
        return artifact

    def _canonical_report_source_and_artifact(
        self,
    ) -> tuple[ServerOwnedEvidenceProjectionSourceV1, ArtifactAdmissionV1]:
        """Reload the canonical source from live C0 store, registry and receipt."""

        self._require_report_authority()
        try:
            admitted = self._registry.get(self._artifact_id, scope_ref=self._scope_ref)
            validate_registry_persistence_receipt(
                admitted,
                self._receipt,
                registry=self._registry,
            )
            binding = self._evidence_store.load(
                self._commit_id,
                registry=self._registry,
                receipt=self._receipt,
            )
            artifact = self._evidence_store.load_packet(
                self._commit_id,
                registry=self._registry,
                receipt=self._receipt,
            )
            if type(artifact) is not ArtifactAdmissionV1:
                raise ValueError("stored evidence packet did not return an admitted artifact")
            if (
                artifact.to_dict() != admitted.to_dict()
                or artifact.artifact_id != self._artifact_id
                or artifact.scope_ref != self._scope_ref
                or binding.commit_id != self._commit_id
                or binding.artifact_admission_ref != artifact.artifact_id
                or binding.envelope_digest != artifact.envelope_digest
            ):
                raise EvidenceProjectionError(
                    "EVIDENCE_ADMISSION_NOT_FOUND",
                    "Report owner canonical source is not bound to the live packet store",
                )
            sensitivity_policy = ServerOwnedEvidenceSensitivityPolicyV1._from_host(
                scope_ref=self._scope_ref,
                artifact_id=artifact.artifact_id,
                commit_id=binding.commit_id,
                envelope_digest=binding.envelope_digest,
                sensitivity="unknown",
                authority_handle=self._authority_handle,
            )
            source = ServerOwnedEvidenceProjectionSourceV1(
                self._evidence_store,
                self._registry,
                self._receipt,
                scope_ref=self._scope_ref,
                artifact_id=artifact.artifact_id,
                commit_id=binding.commit_id,
                sensitivity_policy=sensitivity_policy,
                envelope_digest=binding.envelope_digest,
                authority_handle=self._authority_handle,
                project_file_store=self._project_file_store,
                project_ref=self._project_ref,
                run_id=self._run_id,
                canonical_project_root=self._canonical_project_root,
            )
            return source, admitted
        except EvidenceProjectionError:
            raise
        except (EvidencePersistenceError, EvidenceRegistryError, TypeError, ValueError, KeyError) as exc:
            raise EvidenceProjectionError(
                "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
                "Report owner canonical source is not backed by the live C0 store and registry",
            ) from exc

    def read_result_section_directory(
        self, *, consumer_id: str,
        request_identity: ReportEvidenceRequestIdentityV1 | None = None,
        max_wire_bytes: int | None = None,
    ) -> dict[str, object]:
        """Bounded LOCAL discovery; reading a directory does not read its results."""
        from ..evidence.consumer_adapters import default_projection_registry, ProjectionStatus
        from ..contracts.evidence.result_pages import MAX_PAGE_BYTES
        from ..contracts.evidence.result_sections import RESULT_SECTIONS_CONTRACT_DIGEST

        self._require_report_authority()
        identity = self._require_report_request_identity(request_identity)
        source, _artifact = self._canonical_report_source_and_artifact()
        fields, _sensitivity, policy, extended, deliver = default_projection_registry()._prepare_selection(
            source, consumer_id=consumer_id, destination="local")
        if (not extended or not deliver or not fields["sections"]
                or fields["status"] not in {ProjectionStatus.AVAILABLE, ProjectionStatus.DEGRADED}):
            raise EvidenceProjectionError(fields["audit"].restriction_reason or "RESULT_DIRECTORY_UNAVAILABLE",
                                          "source-bound section directory is unavailable")
        limit = min(MAX_PAGE_BYTES, policy.max_token_budget * 4)
        if max_wire_bytes is not None:
            if type(max_wire_bytes) is not int or not 0 < max_wire_bytes <= limit:
                raise EvidenceProjectionError("RESULT_PAGE_BUDGET_EXCEEDED", "directory budget exceeds policy")
            limit = max_wire_bytes
        sections = [{key: s.to_dict()[key] for key in (
            "section_id", "section_type", "status", "reason_codes")} for s in fields["sections"]]
        wire = dict(schema_version=1, authority="server-owned", consumer_id=consumer_id,
            destination="local", identity={key: getattr(identity, key) for key in (
                "actor_ref", "project_ref", "session_ref", "scope_ref", "run_id", "model_run_id", "confirmation_ref")},
            artifact_ref=self.artifact_id, commit_id=self.commit_id, envelope_digest=self._envelope_digest,
            section_contract_digest=RESULT_SECTIONS_CONTRACT_DIGEST,
            read_completeness="PARTIAL", completion_scope="run", sections=sections,
            directory_digest=sha256_canonical(sections))
        wire["receipt"] = dict(schema_version=1, kind=f"evidence.{consumer_id}.directory-receipt.v1",
                               wire_digest=sha256_canonical(wire))
        if (_delivery_wire_size(wire) > limit
                or len(sections) > policy.max_row_budget):
            raise EvidenceProjectionError("RESULT_PAGE_BUDGET_EXCEEDED", "complete directory exceeds policy")
        return wire

    def read_result_section_page(
        self, *, consumer_id: str, section_id: str, offset: int,
        request_identity: ReportEvidenceRequestIdentityV1 | None = None,
        max_wire_bytes: int | None = None,
    ) -> dict[str, object]:
        """Deliver a locally admitted fragment, never a complete Report claim.

        Routes must resolve this owner on the server. Caller offsets and page
        digests do not create authority; the receiver proves complete coverage.
        This receipt binds local delivery only and cannot authorize remote egress.
        """
        from ..evidence.consumer_adapters import default_projection_registry, _local_structured_spec
        from ..contracts.common.envelope import thaw_json
        from ..contracts.evidence.result_pages import MAX_PAGE_BYTES

        if type(consumer_id) is not str or not consumer_id.strip():
            raise EvidenceProjectionError("PROJECTION_CONSUMER_INVALID", "page consumer must be a nonempty string")
        self._require_report_authority()
        identity = self._require_report_request_identity(request_identity)
        source, _artifact = self._canonical_report_source_and_artifact()
        registry = default_projection_registry()
        declared = registry.resolve(consumer_id)
        if declared is None:
            raise EvidenceProjectionError("PROJECTION_CONSUMER_UNKNOWN", "unknown page consumer")
        policy = _local_structured_spec(declared, "local")
        limit = min(MAX_PAGE_BYTES, policy.max_token_budget * 4)
        if max_wire_bytes is not None:
            if type(max_wire_bytes) is not int or not 0 < max_wire_bytes <= limit:
                raise EvidenceProjectionError("RESULT_PAGE_BUDGET_EXCEEDED", "page delivery budget is outside policy")
            limit = max_wire_bytes
        bound_identity = {key: getattr(identity, key) for key in (
            "actor_ref", "project_ref", "session_ref", "scope_ref", "run_id", "model_run_id", "confirmation_ref")}
        wire = dict(schema_version=1, authority="server-owned", consumer_id=consumer_id,
            destination="local", identity=bound_identity, artifact_ref=self.artifact_id,
            commit_id=self.commit_id, envelope_digest=self._envelope_digest,
            read_completeness="PARTIAL", completion_scope="section", delivery={},
            audit={"token_budget": 0, "row_budget": 0})
        receipt = dict(schema_version=1, kind=f"evidence.{consumer_id}.page-receipt.v1",
            identity=dict(bound_identity), provenance={"artifact_ref": self.artifact_id,
                "commit_id": self.commit_id, "envelope_digest": self._envelope_digest},
            payload_digest="0" * 64, wire_digest="0" * 64)
        # Both count fields may grow from zero to their policy maximum. Reserve
        # their entire width, not a guessed small constant or a raised budget.
        reserve = _delivery_wire_size({**wire, "receipt": receipt}) - 2
        reserve += len(str(policy.max_token_budget)) + len(str(policy.max_row_budget))
        admission = registry.prepare_local_result_page_admission(source,
            consumer_id=consumer_id, section_id=section_id)
        delivery = thaw_json(admission.page(offset=offset, max_wire_bytes=limit,
                                            envelope_reserve_bytes=reserve))
        if (delivery["artifact_ref"] != self.artifact_id or delivery["commit_id"] != self.commit_id
                or delivery["envelope_digest"] != self._envelope_digest):
            raise EvidenceProjectionError("RESULT_PAGE_BINDING_CHANGED", "page differs from its current owner")
        wire["delivery"] = delivery
        wire["audit"]["row_budget"] = delivery["audit"]["row_budget"]
        receipt["payload_digest"] = delivery["wire_digest"]
        while True:
            receipt["wire_digest"] = sha256_canonical(wire)
            final = {**wire, "receipt": dict(receipt)}
            size = _delivery_wire_size(final)
            charge = (size + 3) // 4
            if (size > limit or charge > policy.max_token_budget
                    or wire["audit"]["row_budget"] > policy.max_row_budget):
                raise EvidenceProjectionError("RESULT_PAGE_BUDGET_EXCEEDED", "final owner page exceeds policy")
            if wire["audit"]["token_budget"] == charge:
                return final
            wire["audit"]["token_budget"] = charge

    def _canonical_complete_report_wire(self, collection) -> dict[str, object]:
        from ..evidence.result_collections import validate_server_owned_local_result_collection
        from ..report_view_model import build_persisted_evidence_report_view

        validate_server_owned_local_result_collection(collection, owner=self)
        return build_persisted_evidence_report_view(collection, owner=self,
            artifact_admission=self._canonical_report_artifact())

    def issue_complete_report_collection(self):
        """Assemble bounded local pages; never issue an oversized projection."""
        from ..evidence.result_collections import collect_server_owned_local_results
        from ..report_export import LocalReportCollectionV1

        collection = collect_server_owned_local_results(self)
        wire = self._canonical_complete_report_wire(collection)
        return LocalReportCollectionV1._from_server_collection(wire, owner=self, collection=collection)

    def issue_report_projection(self, wire: Mapping[str, object]):
        """Issue an opaque Report projection only for this exact C0 owner."""

        from ..report_export import EvidenceProjectionV1

        self._require_report_authority()
        if not isinstance(wire, Mapping):
            raise TypeError("Report projection wire must be a server-produced mapping")
        expected = {
            "actorRef": self._actor_ref,
            "projectRef": self._project_ref,
            "sessionRef": self._session_ref,
            "scopeRef": self._scope_ref,
            "runId": self._run_id,
            "modelRunId": self._model_run_id,
            "artifactRef": self._artifact_id,
            "commitId": self._commit_id,
            "confirmationRef": self._confirmation_ref,
            "envelopeDigest": self._envelope_digest,
        }
        if any(wire.get(key) != value for key, value in expected.items()):
            raise EvidenceProjectionError(
                "EVIDENCE_OWNER_CONTEXT_MISMATCH",
                "Report projection identity is not owned by this server capability",
            )
        canonical_wire = self._canonical_report_wire()
        if dict(wire) != canonical_wire:
            raise EvidenceProjectionError(
                "REPORT_EVIDENCE_CANONICAL_MISMATCH",
                "Report projection facts and digest must match the server-owned evidence envelope",
            )
        return EvidenceProjectionV1._from_server_wire(wire, owner=self)

    def issue_report_evidence_writer(
        self,
        projection: object,
        *,
        sections: tuple[str, ...] = ("facts",),
        table_rows: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    ):
        """Construct the opaque XLSX writer from this owner-issued projection."""

        from ..report_export import EvidenceProjectionV1, LocalReportCollectionV1, ReportEvidenceWriterV1

        self._require_report_authority()
        if type(projection) not in (EvidenceProjectionV1, LocalReportCollectionV1):
            raise TypeError("Report writer requires an owner-issued projection")
        if table_rows is not None:
            raise TypeError("ReportEvidenceWriterV1 rejects caller-owned raw tables")
        return ReportEvidenceWriterV1._from_server_projection(
            projection,
            owner=self,
            sections=sections,
        )

    def issue_report_document_writer(
        self,
        view_model: Mapping[str, object],
        projection: object,
        *,
        canonical_run_root: Path,
    ):
        """Construct the HTML document writer only inside the C0 owner seam."""

        from ..report_export import EvidenceProjectionV1, LocalReportCollectionV1
        from ..reporting import ReportDocumentWriterV1

        self._require_report_authority()
        if not isinstance(view_model, Mapping):
            raise TypeError("Report document payload must be server-produced")
        if type(projection) not in (EvidenceProjectionV1, LocalReportCollectionV1):
            raise TypeError("Report document requires an owner-issued projection")
        if getattr(projection, "_owner", None) is not self:
            raise TypeError("Report document requires an owner-issued projection")
        if not self.accepts_canonical_run_root(canonical_run_root):
            raise TypeError("Report document canonical run root is not bound to this owner")
        return ReportDocumentWriterV1._from_server_view_model(
            view_model,
            projection,
            owner=self,
            canonical_run_root=canonical_run_root,
        )

    def read_bound(
        self,
        commit_id: str,
        *,
        actor_ref: str,
        project_ref: str,
        session_ref: str,
        scope_ref: str,
        artifact_id: str,
        run_id: str,
        model_run_id: str,
        content_hash: str,
        admission_ref: str,
        confirmation_ref: str,
        artifact_file_sha256: str,
        envelope_digest: str | None = None,
    ) -> ServerOwnedEvidenceProjectionSourceV1:
        """Load only the registry-owned artifact bound to this commit context."""

        self._require_report_authority()
        if (
            actor_ref != self._actor_ref
            or confirmation_ref != self._confirmation_ref
            or
            project_ref != self._project_ref
            or session_ref != self._session_ref
            or scope_ref != self._scope_ref
        ):
            raise EvidenceProjectionError(
                "EVIDENCE_OWNER_CONTEXT_MISMATCH",
                "the requested project/session/scope is outside the owner capability scope",
            )
        if run_id != self._run_id or model_run_id != self._model_run_id:
            raise EvidenceProjectionError(
                "EVIDENCE_RUN_ID_MISMATCH",
                "the requested run identity is outside the owner capability scope",
            )
        if artifact_id != self._artifact_id or commit_id != self._commit_id:
            raise EvidenceProjectionError(
                "EVIDENCE_ADMISSION_NOT_FOUND",
                "the requested artifact or commit is outside the owner capability scope",
            )
        if artifact_file_sha256 != self._artifact_file_sha256:
            raise EvidenceProjectionError(
                "EVIDENCE_ARTIFACT_FILE_HASH_MISMATCH",
                "the requested artifact file is not the server-owned canonical file",
            )
        if self._registry.scope_ref != self._scope_ref:
            raise EvidenceProjectionError(
                "EVIDENCE_OWNER_CONTEXT_MISMATCH",
                "the owner scope is not the scope of the server-owned registry",
            )
        try:
            # Resolve the requested identity first.  A copied pair must not be
            # allowed to select the canonical packet merely because its fields
            # are self-consistent; the registry must have admitted this exact
            # artifact and the receipt must be for that admission.
            requested = self._registry.get(
                artifact_id,
                scope_ref=self._scope_ref,
            )
            validate_registry_persistence_receipt(
                requested,
                self._receipt,
                registry=self._registry,
            )
            binding = self._evidence_store.load(
                commit_id,
                registry=self._registry,
                receipt=self._receipt,
            )
            artifact = self._evidence_store.load_packet(
                commit_id,
                registry=self._registry,
                receipt=self._receipt,
            )
            if type(artifact) is not ArtifactAdmissionV1:
                raise ValueError("stored evidence packet did not return an admitted artifact")
            admitted = self._registry.resolve(
                artifact.artifact_id,
                scope_ref=self._scope_ref,
            )
            validate_registry_persistence_receipt(
                admitted,
                self._receipt,
                registry=self._registry,
            )
            if binding.commit_id != commit_id or binding.artifact_admission_ref != artifact.artifact_id:
                raise EvidenceProjectionError(
                    "EVIDENCE_ADMISSION_NOT_FOUND",
                    "commit is not bound to the requested server-owned artifact admission",
                )
            if (
                requested.to_dict() != artifact.to_dict()
                or admitted.to_dict() != artifact.to_dict()
                or artifact.artifact_id != artifact_id
                or binding.commit_id != self._commit_id
            ):
                raise EvidenceProjectionError(
                    "EVIDENCE_ADMISSION_NOT_FOUND",
                    "commit is not bound to the requested server-owned artifact admission",
                )
            if artifact.content_hash != content_hash:
                raise EvidenceProjectionError(
                    "EVIDENCE_ARTIFACT_CONTENT_HASH_MISMATCH",
                    "requested content hash differs from the registry-owned artifact",
                )
            if admission_ref != binding.artifact_admission_ref:
                raise EvidenceProjectionError(
                    "EVIDENCE_ARTIFACT_ADMISSION_MISMATCH",
                    "requested admission ref differs from the committed binding",
                )
            sensitivity_policy = ServerOwnedEvidenceSensitivityPolicyV1._from_host(
                scope_ref=self._scope_ref,
                artifact_id=artifact.artifact_id,
                commit_id=binding.commit_id,
                envelope_digest=binding.envelope_digest,
                sensitivity="unknown",
                authority_handle=self._authority_handle,
            )
            source = ServerOwnedEvidenceProjectionSourceV1(
                self._evidence_store,
                self._registry,
                self._receipt,
                scope_ref=self._scope_ref,
                artifact_id=artifact.artifact_id,
                commit_id=binding.commit_id,
                sensitivity_policy=sensitivity_policy,
                envelope_digest=binding.envelope_digest,
                authority_handle=self._authority_handle,
                project_file_store=self._project_file_store,
                project_ref=self._project_ref,
                run_id=self._run_id,
                canonical_project_root=self._canonical_project_root,
            )
            if envelope_digest is not None and binding.envelope_digest != envelope_digest:
                raise EvidenceProjectionError(
                    "PROJECTION_DIGEST_MISMATCH",
                    "persisted envelope digest differs from the requested commit",
                )
            return source
        except EvidenceProjectionError:
            raise
        except (EvidencePersistenceError, EvidenceRegistryError, TypeError, ValueError, KeyError) as exc:
            raise EvidenceProjectionError(
                "EVIDENCE_ADMISSION_NOT_FOUND",
                "the requested Report evidence is not bound to the server-owned registry",
            ) from exc


class UnavailableReportEvidenceCapabilityV1:
    """Typed server bootstrap result when no host C0 owner is configured."""

    __slots__ = ("reason_code",)

    def __init__(self, reason_code: str = "EVIDENCE_HOST_AUTHORITY_UNAVAILABLE") -> None:
        if type(reason_code) is not str or not reason_code.strip():
            raise TypeError("reason_code must be a non-empty string")
        self.reason_code = reason_code


_REPORT_EVIDENCE_PERSISTENCE: ServerOwnedReportEvidencePersistenceV1 | UnavailableReportEvidenceCapabilityV1 = UnavailableReportEvidenceCapabilityV1()
_REPORT_EVIDENCE_OWNER_REHYDRATOR: Callable[..., object] | None = None
_REPORT_EVIDENCE_OWNER_CATALOG: dict[
    tuple[str, str, str, str, str, str, str],
    ServerOwnedReportEvidencePersistenceV1,
] = {}
_REPORT_EVIDENCE_OWNER_CATALOG_LOCK = RLock()


def _report_owner_key(owner: ServerOwnedReportEvidencePersistenceV1) -> tuple[str, str, str, str, str, str, str]:
    return (
        owner.actor_ref,
        owner.project_ref,
        owner.session_ref,
        owner.scope_ref,
        owner.run_id,
        owner.model_run_id,
        owner.confirmation_ref,
    )


def register_report_evidence_owner(
    owner: ServerOwnedReportEvidencePersistenceV1,
) -> None:
    """Register one host-created owner without replacing another run's owner."""

    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        raise TypeError("Report owner catalog accepts only the server-owned capability")
    owner._require_report_authority()
    key = _report_owner_key(owner)
    with _REPORT_EVIDENCE_OWNER_CATALOG_LOCK:
        existing = _REPORT_EVIDENCE_OWNER_CATALOG.get(key)
        if existing is not None and existing is not owner:
            raise EvidenceProjectionError(
                "EVIDENCE_OWNER_CONTEXT_CONFLICT",
                "the exact Report owner identity is already bound to another capability",
            )
        _REPORT_EVIDENCE_OWNER_CATALOG[key] = owner


def _catalog_report_evidence_owner(
    *,
    actor_ref: str,
    run_id: str,
    project_ref: str,
    session_ref: str,
    scope_ref: str,
    model_run_id: str,
    confirmation_ref: str,
) -> ServerOwnedReportEvidencePersistenceV1 | None:
    key = (
        actor_ref,
        project_ref,
        session_ref,
        scope_ref,
        run_id,
        model_run_id,
        confirmation_ref,
    )
    with _REPORT_EVIDENCE_OWNER_CATALOG_LOCK:
        owner = _REPORT_EVIDENCE_OWNER_CATALOG.get(key)
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        return None
    try:
        owner._require_report_authority()
    except (AttributeError, TypeError, ValueError, EvidenceProjectionError):
        return None
    return owner


def _catalog_report_evidence_owner_for_identity(
    *,
    actor_ref: str,
    run_id: str,
    project_ref: str,
    session_ref: str,
    scope_ref: str,
    model_run_id: str,
    confirmation_ref: str,
) -> tuple[ServerOwnedReportEvidencePersistenceV1 | None, bool]:
    """Resolve an exact catalog owner without allowing a run-level fallback.

    The catalog is authoritative once a run has an entry.  A missing exact
    identity therefore means a typed conflict, not permission to consult the
    deployment-wide owner.
    """

    key = (
        actor_ref,
        project_ref,
        session_ref,
        scope_ref,
        run_id,
        model_run_id,
        confirmation_ref,
    )
    with _REPORT_EVIDENCE_OWNER_CATALOG_LOCK:
        exact = _REPORT_EVIDENCE_OWNER_CATALOG.get(key)
        run_entries = [
            candidate
            for candidate in _REPORT_EVIDENCE_OWNER_CATALOG.values()
            if getattr(candidate, "run_id", None) == run_id
        ]
    if len(run_entries) != 1 or exact is not run_entries[0]:
        return None, bool(run_entries) or exact is not None
    if type(exact) is not ServerOwnedReportEvidencePersistenceV1:
        return None, True
    try:
        exact._require_report_authority()
    except (AttributeError, TypeError, ValueError, EvidenceProjectionError):
        return None, True
    return exact, False


def _catalog_report_evidence_owner_for_run(
    *,
    run_id: str,
    project_root: Path | str,
) -> tuple[ServerOwnedReportEvidencePersistenceV1 | None, bool]:
    """Resolve the one catalog owner for an internal consumer run.

    Agent and Notebook consumers intentionally do not supply HTTP identity
    fields.  They may still use the host-created per-run catalog, but only
    when exactly one live owner matches the run and canonical project root.
    The boolean distinguishes "no catalog entry" (where the legacy global
    owner may still be used) from an ambiguous or stale catalog entry (which
    must fail closed).
    """

    try:
        canonical_root = Path(project_root).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None, True
    with _REPORT_EVIDENCE_OWNER_CATALOG_LOCK:
        run_entries = [
            owner
            for owner in _REPORT_EVIDENCE_OWNER_CATALOG.values()
            if getattr(owner, "run_id", None) == run_id
        ]
    if not run_entries:
        return None, False
    # A run-level catalog entry is authoritative even when it is no longer
    # live.  Filtering stale entries before deciding whether the catalog is
    # empty would let the deployment-wide compatibility owner become a
    # confused-run fallback.  Preserve the run's existence first, then admit
    # exactly one live owner bound to the exact project root.
    if len(run_entries) != 1:
        return None, True
    owner = run_entries[0]
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        return None, True
    if not owner.accepts_project_root(canonical_root):
        return None, True
    try:
        owner._require_report_authority()
    except (AttributeError, TypeError, ValueError, EvidenceProjectionError):
        return None, True
    return owner, False


def configure_report_evidence_persistence(
    persistence: ServerOwnedReportEvidencePersistenceV1 | UnavailableReportEvidenceCapabilityV1 | None,
) -> None:
    """Install the owner-issued Report persistence capability at server bootstrap."""

    if persistence is None:
        persistence = UnavailableReportEvidenceCapabilityV1()
    if type(persistence) not in {
        ServerOwnedReportEvidencePersistenceV1,
        UnavailableReportEvidenceCapabilityV1,
    }:
        raise TypeError("persistence must be a server-owned Report capability or None")
    if type(persistence) is ServerOwnedReportEvidencePersistenceV1:
        persistence._require_report_authority()
    global _REPORT_EVIDENCE_PERSISTENCE
    _REPORT_EVIDENCE_PERSISTENCE = persistence
    if type(persistence) is UnavailableReportEvidenceCapabilityV1:
        with _REPORT_EVIDENCE_OWNER_CATALOG_LOCK:
            _REPORT_EVIDENCE_OWNER_CATALOG.clear()


def configure_report_evidence_owner_rehydrator(
    rehydrator: Callable[..., object] | None,
) -> None:
    """Install the deployment-owned restart seam for durable Report owners."""

    if rehydrator is not None and not callable(rehydrator):
        raise TypeError("Report evidence owner rehydrator must be callable or None")
    global _REPORT_EVIDENCE_OWNER_REHYDRATOR
    _REPORT_EVIDENCE_OWNER_REHYDRATOR = rehydrator


def _rehydrate_report_evidence_owner(
    *,
    project_root: Path | str,
    run_id: str,
) -> ServerOwnedReportEvidencePersistenceV1 | None:
    rehydrator = _REPORT_EVIDENCE_OWNER_REHYDRATOR
    if rehydrator is None:
        return None
    try:
        candidate = rehydrator(project_root=project_root, run_id=run_id)
    except Exception:
        # A durable row that cannot be revalidated is unavailable.  The
        # callback is a host seam; HTTP input never gets to replace it.
        return None
    return candidate if type(candidate) is ServerOwnedReportEvidencePersistenceV1 else None


def current_report_evidence_persistence(
    *,
    actor_ref: str | None,
    run_id: str | None,
    project_ref: str | None,
    session_ref: str | None,
    scope_ref: str | None,
    model_run_id: str | None,
    artifact_id: str | None,
    commit_id: str | None,
    confirmation_ref: str | None,
    artifact_file_sha256: str | None,
    project_root: Path | str | None = None,
) -> ServerOwnedReportEvidencePersistenceV1 | None:
    """Return only the capability bound to a server-owned Report identity.

    The artifact/commit/file triple has two modes.  A complete triple verifies
    a specific indexed artifact.  Three explicit ``None`` values perform the
    earlier run-owner admission used by HTTP entrances, before they read an
    artifact index or hash a file.  Partial triples remain invalid.
    """

    context = (
        run_id,
        actor_ref,
        project_ref,
        session_ref,
        scope_ref,
        model_run_id,
        confirmation_ref,
    )
    if not all(type(value) is str and value.strip() for value in context):
        return None
    artifact_fields = (artifact_id, commit_id, artifact_file_sha256)
    if not (
        all(value is None for value in artifact_fields)
        or all(type(value) is str and value.strip() for value in artifact_fields)
    ):
        return None
    capability, catalog_conflict = _catalog_report_evidence_owner_for_identity(
        actor_ref=actor_ref,
        run_id=run_id,
        project_ref=project_ref,
        session_ref=session_ref,
        scope_ref=scope_ref,
        model_run_id=model_run_id,
        confirmation_ref=confirmation_ref,
    )
    if catalog_conflict:
        return None
    if capability is None:
        capability = _REPORT_EVIDENCE_PERSISTENCE
    if type(capability) is not ServerOwnedReportEvidencePersistenceV1 and not catalog_conflict:
        if project_root is not None:
            capability = _rehydrate_report_evidence_owner(
                project_root=project_root,
                run_id=run_id,
            )
    if type(capability) is not ServerOwnedReportEvidencePersistenceV1:
        return None
    if (
        capability.actor_ref != actor_ref
        or capability.run_id != run_id
        or capability.project_ref != project_ref
        or capability.session_ref != session_ref
        or capability.scope_ref != scope_ref
        or capability.model_run_id != model_run_id
        or capability.confirmation_ref != confirmation_ref
        or (
            project_root is not None
            and not capability.accepts_project_root(project_root)
        )
    ):
        return None
    try:
        capability._require_report_authority()
    except (AttributeError, TypeError, ValueError, EvidenceProjectionError):
        return None
    if all(value is None for value in artifact_fields):
        return capability
    if (
        capability.artifact_id != artifact_id
        or capability.commit_id != commit_id
        or capability.artifact_file_sha256 != artifact_file_sha256
    ):
        return None
    return capability


def _unavailable_consumer_evidence(
    consumer_id: str,
    reason_code: str,
    *,
    status: str = "unavailable",
) -> dict[str, object]:
    """Return one uniform, typed failure shape for every consumer surface."""

    return {
        "schema_version": 1,
        "consumer_id": consumer_id,
        "consumer_version": "1.0",
        "status": status,
        "availability": "unavailable",
        "execution_status": "unavailable",
        "completeness_status": "unavailable",
        "authority": "server-owned",
        "source": "persisted-typed-evidence",
        "facts": [],
        "projection_digest": None,
        "reason_code": reason_code,
        "receipt": None,
    }


def _central_consumer_projection_digest(evidence: Mapping[str, object]) -> str:
    """Hash the shared typed source projection, not its surface metadata.

    Agent and Notebook may render the same persisted facts differently, but
    their source digest must prove that both read the same owner-bound
    envelope through the same registry.  Consumer ids, renderer refs, policy
    refs, and audit transport metadata are deliberately excluded because they
    are surface selection details rather than statistical evidence.
    """

    return sha256_canonical(
        {
            "schema_version": evidence.get("schema_version"),
            "authority": evidence.get("authority"),
            "source": evidence.get("source"),
            "artifact_ref": evidence.get("artifact_ref"),
            "commit_id": evidence.get("commit_id"),
            "envelope_ref": evidence.get("envelope_ref"),
            "envelope_digest": evidence.get("envelope_digest"),
            "data_snapshot_ref": evidence.get("data_snapshot_ref"),
            "data_snapshot_digest": evidence.get("data_snapshot_digest"),
            "result_identity": evidence.get("result_identity"),
            "execution_status": evidence.get("execution_status"),
            "availability": evidence.get("availability"),
            "completeness_status": evidence.get("completeness_status"),
            "numerical_method": evidence.get("numerical_method"),
            "inference_basis": evidence.get("inference_basis"),
            "evaluation_design": evidence.get("evaluation_design"),
            "validation_summary": evidence.get("validation_summary"),
            "facts": evidence.get("facts"),
            "sections": evidence.get("sections"),
            "result_dependencies": evidence.get("result_dependencies"),
            **({"semantic_selection": evidence["semantic_selection"]} if "semantic_selection" in evidence else {}),
            **({"fact_selection": evidence["fact_selection"]} if "fact_selection" in evidence else {}),
            "section_audit": {
                key: evidence.get("audit", {}).get(key)
                for key in ("requested_section_ids", "selected_section_ids", "omitted_section_ids",
                            "redacted_section_ids", "restriction_reason")
            },
            "status": evidence.get("status"),
            "lineage_refs": evidence.get("lineage_refs"),
            "identity": evidence.get("identity"),
        }
    )


def _project_server_owned_consumer_evidence(
    *,
    consumer_id: str,
    run_root: Path,
    request_identity: ReportEvidenceRequestIdentityV1 | None,
    project_root: Path | str | None,
    requested_fact_ids: Sequence[str] | None = None,
    requested_section_ids: Sequence[str] | None = None,
    coefficient_selection: object | None = None,
    provenance_selection: object | None = None,
    requested_section_types: Sequence[str] | None = None,
    _section_fact_page: tuple[str, int, int, str | None] | None = None,
) -> dict[str, object]:
    """Read and project one C0 packet without accepting a caller-owned source."""

    if type(request_identity) is not ReportEvidenceRequestIdentityV1:
        return _unavailable_consumer_evidence(
            consumer_id,
            "EVIDENCE_OWNER_REQUEST_REQUIRED",
        )
    if request_identity.run_id != run_root.name:
        return _unavailable_consumer_evidence(
            consumer_id,
            "EVIDENCE_OWNER_CONTEXT_MISMATCH",
        )

    owner = current_report_evidence_persistence(
        actor_ref=request_identity.actor_ref,
        run_id=run_root.name,
        project_ref=request_identity.project_ref,
        session_ref=request_identity.session_ref,
        scope_ref=request_identity.scope_ref,
        model_run_id=request_identity.model_run_id,
        artifact_id=None,
        commit_id=None,
        confirmation_ref=request_identity.confirmation_ref,
        artifact_file_sha256=None,
        project_root=project_root,
    )
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        return _unavailable_consumer_evidence(
            consumer_id,
            "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
        )

    try:
        owner._require_report_authority()
        owner._require_report_request_identity(request_identity)
        if not owner.accepts_canonical_run_root(run_root):
            raise EvidenceProjectionError(
                "EVIDENCE_SCOPE_ROOT_MISMATCH",
                "consumer evidence owner is not bound to this canonical run root",
            )
        source, _artifact = owner._canonical_report_source_and_artifact()
        from ..evidence.consumer_adapters import default_projection_registry, _spec_for_audit_policy

        registry = default_projection_registry()
        fact_selection = None
        section_dependencies = None
        if _section_fact_page is not None:
            if any(value is not None for value in (requested_fact_ids, requested_section_ids,
                    coefficient_selection, provenance_selection, requested_section_types)):
                raise EvidenceProjectionError("semantic_selection_mixed", "fact page cannot mix selectors")
            section_id, offset, limit, expected_digest = _section_fact_page
            # Admission validates the selected section's entire dependency
            # closure, but does not deliver its oversized tree or qualifiers.
            admitted, _, policy, _, deliver = registry._prepare_selection(source,
                consumer_id=consumer_id, destination="local", requested_fact_ids=(),
                requested_section_ids=(section_id,))
            if (not deliver or admitted["status"].value not in {"available", "degraded"}
                    or len(admitted["sections"]) != 1):
                raise EvidenceProjectionError(admitted["audit"].restriction_reason or
                    "RESULT_FACT_SECTION_UNAVAILABLE", "section is not admitted")
            section = admitted["sections"][0]
            if section.to_dict()["status"] not in {"available", "degraded"}:
                raise EvidenceProjectionError("RESULT_FACT_SECTION_UNAVAILABLE", "section is closed")
            if expected_digest is not None and admitted["envelope_digest"] != expected_digest:
                raise EvidenceProjectionError("RESULT_FACT_SNAPSHOT_MISMATCH", "source snapshot changed")
            if limit > policy.max_row_budget:
                raise EvidenceProjectionError("RESULT_FACT_SELECTOR_INVALID", "limit exceeds declared rows")
            total = len(section.fact_refs)
            if offset >= total:
                raise EvidenceProjectionError("RESULT_FACT_OFFSET_INVALID", "offset is outside section facts")
            requested_fact_ids = section.fact_refs[offset:offset + limit]
            requested_section_ids = ()
            fact_selection = dict(section_id=section.section_id,
                section_type=section.to_dict()["section_type"], section_digest=sha256_canonical(section.to_dict()),
                scope="section_numeric_facts", read_completeness="PARTIAL", numeric_only=True,
                full_section_read=False, offset=offset, limit=limit, total_facts=total,
                next_offset=offset + len(requested_fact_ids) if offset + len(requested_fact_ids) < total else None,
                warning="Numeric facts only; section text, warnings and qualifications have not been read. "
                        "Do not treat this as a complete result or inferential conclusion.")
            section_dependencies = admitted["result_dependencies"]
        projection = registry.project(
            source,
            consumer_id=consumer_id,
            destination="local",
            requested_fact_ids=requested_fact_ids,
            requested_section_ids=requested_section_ids,
            coefficient_selection=coefficient_selection,
            provenance_selection=provenance_selection,
            requested_section_types=requested_section_types,
        )
        evidence = projection.to_dict()
        if fact_selection is not None:
            if (evidence["status"] not in {"available", "degraded"}
                    or {fact["fact_id"] for fact in evidence["facts"]} != set(requested_fact_ids)
                    or evidence["envelope_digest"] != admitted["envelope_digest"]):
                return _unavailable_consumer_evidence(consumer_id,
                    evidence["audit"].get("restriction_reason") or "RESULT_FACT_SELECTION_UNAVAILABLE")
            # Both selections were admitted from this owner-bound snapshot.
            # Preserve the full parent dependency closure and bind all paging
            # metadata BEFORE calculating either digest or the owner receipt.
            evidence["result_dependencies"] = section_dependencies
            evidence["fact_selection"] = fact_selection
        evidence["schema_version"] = 1
        # Final delivery includes owner/transport metadata and the receipt.
        # Its complete UTF-8 wire must fit the same declared projection policy.
        evidence["identity"] = {
            "actor_ref": owner.actor_ref,
            "project_ref": owner.project_ref,
            "session_ref": owner.session_ref,
            "scope_ref": owner.scope_ref,
            "run_id": owner.run_id,
            "model_run_id": owner.model_run_id,
            "confirmation_ref": owner.confirmation_ref,
        }
        evidence["authority"] = "server-owned"
        evidence["source"] = "persisted-typed-evidence"
        spec = registry.resolve(consumer_id)
        spec = _spec_for_audit_policy(spec, "local", projection.audit.policy_ref)
        if fact_selection is not None:
            from ..evidence.consumer_adapters import _structured_row_count
            # Charge the additional parent dependencies and the selection
            # record, not just the smaller facts-only projection's rows.
            rows = _structured_row_count(evidence["facts"], (), section_dependencies) + 1
            if rows > spec.max_row_budget:
                return _unavailable_consumer_evidence(consumer_id, "consumer_delivery_budget_exceeded")
            evidence["audit"]["row_budget"] = rows
        while True:
            # Reissue after adjusting the serialized audit count. Hashes have
            # fixed width, so only the count's decimal width needs to settle.
            evidence.pop("projection_digest", None)
            evidence.pop("receipt", None)
            if consumer_id in {"agent", "notebook"}:
                evidence["projection_digest"] = _central_consumer_projection_digest(evidence)
            else:
                evidence["projection_digest"] = sha256_canonical(evidence)
            evidence["receipt"] = _consumer_evidence_receipt(evidence)
            tokens = (len(canonical_json_v1(evidence).encode("utf-8")) + 3) // 4
            if tokens > spec.max_token_budget:
                return _unavailable_consumer_evidence(consumer_id, "consumer_delivery_budget_exceeded")
            if fact_selection is not None and len(json.dumps(
                    {"persisted_evidence": evidence}, ensure_ascii=False, sort_keys=True,
                    allow_nan=False).encode("utf-8")) > min(8192, spec.max_token_budget * 4):
                return _unavailable_consumer_evidence(consumer_id, "tool_output_budget_exceeded")
            if evidence["audit"]["token_budget"] == tokens:
                break
            evidence["audit"]["token_budget"] = tokens
        if fact_selection is not None:
            # The facts-only central projection checks its direct sources.
            # Recheck the whole parent closure at the final delivery boundary
            # as well; a sibling model dependency may have changed meanwhile.
            final, _, _, _, deliver = registry._prepare_selection(source,
                consumer_id=consumer_id, destination="local", requested_fact_ids=(),
                requested_section_ids=(fact_selection["section_id"],))
            if (not deliver or final["status"].value not in {"available", "degraded"}
                    or len(final["sections"]) != 1):
                return _unavailable_consumer_evidence(consumer_id,
                    final["audit"].restriction_reason or "RESULT_FACT_SECTION_UNAVAILABLE")
            if (final["envelope_digest"] != evidence["envelope_digest"]
                    or sha256_canonical(final["sections"][0].to_dict()) != fact_selection["section_digest"]
                    or final["result_dependencies"] != section_dependencies):
                return _unavailable_consumer_evidence(consumer_id, "RESULT_FACT_SNAPSHOT_MISMATCH")
        return evidence
    except EvidenceProjectionError as exc:
        return _unavailable_consumer_evidence(consumer_id, exc.code)
    except (
        AttributeError,
        EvidencePersistenceError,
        EvidenceRegistryError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return _unavailable_consumer_evidence(
            consumer_id,
            "EVIDENCE_PROJECTION_UNAVAILABLE",
        )


def _consumer_evidence_receipt(
    evidence: Mapping[str, object],
) -> dict[str, object] | None:
    """Issue a typed local receipt only for a complete consumer projection."""

    digest = evidence.get("projection_digest")
    consumer_id = evidence.get("consumer_id")
    if (
        evidence.get("status") not in {"available", "degraded"}
        or not isinstance(consumer_id, str)
        or not consumer_id.strip()
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        return None
    identity = evidence.get("identity")
    if not isinstance(identity, Mapping):
        return None
    required_identity = (
        "actor_ref",
        "project_ref",
        "session_ref",
        "scope_ref",
        "run_id",
        "model_run_id",
        "confirmation_ref",
    )
    if any(
        not isinstance(identity.get(key), str) or not identity.get(key, "").strip()
        for key in required_identity
    ):
        return None
    return {
        "schema_version": 1,
        "kind": f"evidence.{consumer_id}.server-receipt.v1",
        "projection_digest": digest,
        "wire_digest": sha256_canonical({key: value for key, value in evidence.items() if key != "receipt"}),
        "identity": dict(identity),
        "provenance": {
            "artifact_ref": evidence.get("artifact_ref"),
            "commit_id": evidence.get("commit_id"),
            "envelope_digest": evidence.get("envelope_digest"),
        },
    }


def read_persisted_consumer_evidence_for_run(
    *,
    consumer_id: str,
    project_root: Path | str,
    run_id: str,
    requested_fact_ids: Sequence[str] | None = None,
    requested_section_ids: Sequence[str] | None = None,
    coefficient_selection: object | None = None,
    provenance_selection: object | None = None,
    requested_section_types: Sequence[str] | None = None,
) -> dict[str, object]:
    """Read one consumer projection from the server-configured owner.

    Agent and Notebook do not receive actor/session/model identities from the
    model.  They resolve the identity from the server-installed C0 owner, then
    use this same projection path.  A missing owner or a different run is an
    explicit unavailable result, never a fallback to ``model_results`` files.
    """

    if type(consumer_id) is not str or not consumer_id.strip():
        return _unavailable_consumer_evidence("unknown", "EVIDENCE_CONSUMER_REQUIRED")
    if type(run_id) is not str or not run_id.strip():
        return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_RUN_ID_REQUIRED")
    catalog_owner, catalog_conflict = _catalog_report_evidence_owner_for_run(
        run_id=run_id,
        project_root=project_root,
    )
    if catalog_conflict:
        return _unavailable_consumer_evidence(
            consumer_id,
            "EVIDENCE_OWNER_CONTEXT_CONFLICT",
        )
    configured = catalog_owner or _REPORT_EVIDENCE_PERSISTENCE
    if type(configured) is not ServerOwnedReportEvidencePersistenceV1 and not catalog_conflict:
        configured = _rehydrate_report_evidence_owner(
            project_root=project_root,
            run_id=run_id,
        )
    if type(configured) is not ServerOwnedReportEvidencePersistenceV1:
        return _unavailable_consumer_evidence(
            consumer_id,
            "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED",
        )
    try:
        identity = configured._require_report_request_identity(None)
    except (AttributeError, EvidenceProjectionError, TypeError, ValueError):
        return _unavailable_consumer_evidence(
            consumer_id,
            "EVIDENCE_OWNER_REQUEST_REQUIRED",
        )
    return _project_server_owned_consumer_evidence(
        consumer_id=consumer_id,
        run_root=Path(project_root).expanduser().resolve(strict=False) / "runs" / run_id,
        request_identity=identity,
        project_root=project_root,
        requested_fact_ids=requested_fact_ids,
        requested_section_ids=requested_section_ids,
        coefficient_selection=coefficient_selection,
        provenance_selection=provenance_selection,
        requested_section_types=requested_section_types,
    )


def read_persisted_consumer_result_facts_for_run(
    *, consumer_id: str, project_root: Path | str, run_id: str, section_id: str,
    offset: int = 0, limit: int = 1, expected_envelope_digest: str | None = None,
) -> dict[str, object]:
    """LOCAL numeric-only selection; offsets and digests grant no authority.

    Each call resolves the current owner and revalidates the parent section.
    Continuations must bind the preceding snapshot. The exact requested slice
    is either delivered in full under the conversational budget or rejected;
    this is not byte transport or a complete section/read claim.
    """
    if type(consumer_id) is not str or consumer_id not in {"agent", "notebook"}:
        return _unavailable_consumer_evidence("unknown", "PROJECTION_CONSUMER_UNKNOWN")
    if (type(run_id) is not str or not run_id.strip() or run_id in {".", ".."}
            or any(char in run_id for char in ("/", "\\", "\x00"))):
        return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_RUN_ID_REQUIRED")
    if (type(section_id) is not str or not section_id or len(section_id) > 200
            or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 64
            or (expected_envelope_digest is not None and (type(expected_envelope_digest) is not str
                or re.fullmatch(r"[0-9a-f]{64}", expected_envelope_digest) is None))):
        return _unavailable_consumer_evidence(consumer_id, "RESULT_FACT_SELECTOR_INVALID")
    if offset > 0 and expected_envelope_digest is None:
        return _unavailable_consumer_evidence(consumer_id, "RESULT_FACT_SNAPSHOT_REQUIRED")
    try:
        owner, conflict = _catalog_report_evidence_owner_for_run(run_id=run_id, project_root=project_root)
        if conflict:
            return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_OWNER_CONTEXT_CONFLICT")
        owner = owner or _REPORT_EVIDENCE_PERSISTENCE
        if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
            owner = _rehydrate_report_evidence_owner(project_root=project_root, run_id=run_id)
        if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
            return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED")
        identity = owner._require_report_request_identity(None)
        run_root = Path(project_root).expanduser().resolve(strict=False) / "runs" / run_id
        if (owner.run_id != run_id or not owner.accepts_project_root(project_root)
                or not owner.accepts_canonical_run_root(run_root)):
            return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_OWNER_CONTEXT_MISMATCH")
        return _project_server_owned_consumer_evidence(consumer_id=consumer_id, run_root=run_root,
            request_identity=identity, project_root=project_root,
            _section_fact_page=(section_id, offset, limit, expected_envelope_digest))
    except EvidenceProjectionError as exc:
        return _unavailable_consumer_evidence(consumer_id, exc.code)
    except (AttributeError, EvidenceHostAuthorityError, EvidencePersistenceError,
            EvidenceRegistryError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_PROJECTION_UNAVAILABLE")


def read_persisted_consumer_result_page_for_run(
    *,
    consumer_id: str,
    project_root: Path | str,
    run_id: str,
    section_id: str,
    offset: int,
    max_wire_bytes: int | None = None,
) -> dict[str, object]:
    """Read a local PARTIAL page using only the host-resolved run owner.

    Selectors grant no identity or destination authority. Catalog conflicts
    cannot fall back to the deployment owner or restart seam, and the owner
    retains all source checks and final page budgets.
    """
    from ..evidence.consumer_adapters import default_projection_registry

    if type(consumer_id) is not str or not consumer_id.strip():
        return _unavailable_consumer_evidence("unknown", "EVIDENCE_CONSUMER_REQUIRED")
    if default_projection_registry().resolve(consumer_id) is None:
        return _unavailable_consumer_evidence(consumer_id, "PROJECTION_CONSUMER_UNKNOWN")
    if (type(run_id) is not str or not run_id.strip() or run_id in {".", ".."}
            or any(char in run_id for char in ("/", "\\", "\x00"))):
        return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_RUN_ID_REQUIRED")
    try:
        owner, conflict = _catalog_report_evidence_owner_for_run(
            run_id=run_id, project_root=project_root,
        )
        if conflict:
            return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_OWNER_CONTEXT_CONFLICT")
        owner = owner or _REPORT_EVIDENCE_PERSISTENCE
        if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
            owner = _rehydrate_report_evidence_owner(project_root=project_root, run_id=run_id)
        if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
            return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_PERSISTENCE_CAPABILITY_REQUIRED")
        owner._require_report_authority()
        run_root = Path(project_root).expanduser().resolve(strict=False) / "runs" / run_id
        if (owner.run_id != run_id or not owner.accepts_project_root(project_root)
                or not owner.accepts_canonical_run_root(run_root)):
            return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_OWNER_CONTEXT_MISMATCH")
        return owner.read_result_section_page(
            consumer_id=consumer_id, section_id=section_id, offset=offset,
            max_wire_bytes=max_wire_bytes,
        )
    except EvidenceProjectionError as exc:
        return _unavailable_consumer_evidence(consumer_id, exc.code)
    except (AttributeError, EvidenceHostAuthorityError, EvidencePersistenceError,
            EvidenceRegistryError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        return _unavailable_consumer_evidence(consumer_id, "EVIDENCE_PROJECTION_UNAVAILABLE")


def report_evidence_request_identity_for_run(
    *,
    project_root: Path | str,
    run_id: str,
) -> ReportEvidenceRequestIdentityV1 | None:
    """Resolve a route identity from the exact host-created catalog owner."""

    owner, conflict = _catalog_report_evidence_owner_for_run(
        run_id=run_id,
        project_root=project_root,
    )
    if conflict:
        return None
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        owner = _rehydrate_report_evidence_owner(
            project_root=project_root,
            run_id=run_id,
        )
    if type(owner) is not ServerOwnedReportEvidencePersistenceV1:
        return None
    try:
        return owner._require_report_request_identity(None)
    except (AttributeError, EvidenceProjectionError, TypeError, ValueError, RuntimeError):
        return None


def project_persisted_results_evidence(
    *,
    run_root: Path,
    request_identity: ReportEvidenceRequestIdentityV1 | None,
    project_root: Path | str | None,
) -> dict[str, object]:
    """Project the server-owned C0 packet for the central Run results surface."""
    return _project_server_owned_consumer_evidence(
        consumer_id="results",
        run_root=run_root,
        request_identity=request_identity,
        project_root=project_root,
    )


def results_evidence_server_receipt(
    evidence: Mapping[str, object],
) -> dict[str, object] | None:
    """Build the transport receipt only for a non-empty typed projection."""

    digest = evidence.get("projection_digest")
    if (
        evidence.get("status") not in {"available", "degraded"}
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        return None
    identity = {
        "artifactRef": evidence.get("artifact_ref"),
        "commitId": evidence.get("commit_id"),
        "envelopeDigest": evidence.get("envelope_digest"),
    }
    if any(not isinstance(value, str) or not value.strip() for value in identity.values()):
        return None
    return {
        "schemaVersion": 1,
        "kind": "evidence.results.server-receipt.v1",
        "projectionDigest": digest,
        "identity": identity,
        "provenance": {
            "artifactRef": identity["artifactRef"],
            "commitId": identity["commitId"],
            "envelopeDigest": identity["envelopeDigest"],
        },
    }


__all__ = [
    "PersistedEvidenceResultsFacadeV1",
    "ReportEvidenceRequestIdentityV1",
    "ServerOwnedReportEvidencePersistenceV1",
    "UnavailableReportEvidenceCapabilityV1",
    "configure_report_evidence_persistence",
    "configure_report_evidence_owner_rehydrator",
    "register_report_evidence_owner",
    "current_report_evidence_persistence",
    "read_persisted_consumer_evidence_for_run",
    "read_persisted_consumer_result_page_for_run",
    "read_persisted_consumer_result_facts_for_run",
    "report_evidence_request_identity_for_run",
    "project_persisted_results_evidence",
    "results_evidence_server_receipt",
]
