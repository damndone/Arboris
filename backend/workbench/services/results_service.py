"""Model-results reading + issue-stream normalization.

Reads the ``model_results/*.json`` a run produced and reconciles the stored
guardrail issues with the final preprocessing state (e.g. surfacing
auto-dummy-coding as an INFO issue). Pure functions over a run directory and
plain dicts — no HTTP, no filesystem writes.

Extracted verbatim from ``api.py`` in v1.6.10 (D1 decomposition, Phase 2).
"""
from __future__ import annotations

import os
import re
import weakref
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

from ..artifacts import read_json
from ..canonical import sha256_canonical
from ..domain import GuardrailIssue, Severity
from ..evidence.authority import (
    EvidenceHostAuthorityError,
    build_authority_request,
    issue_host_proof,
    validate_host_proof,
)
from ..term_parser import is_q_quoted_dummy, parse_term
from .lmm_result_adapter import read_lmm_public_results


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
    PersistedEvidenceEnvelopeV1,
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
_REPORT_OWNER_ADMISSIONS_LOCK = RLock()


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
            canonical_record = PersistedEvidenceEnvelopeV1(
                commit_id=binding.commit_id,
                artifact_ref=artifact.artifact_id,
                envelope_ref=f"evidence-envelope:{artifact.envelope_digest}",
                sensitivity="public",
                binding=binding,
                envelope=artifact.envelope.envelope,
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
        self._canonical_artifact = artifact
        self._report_authority_marker = object()
        with _REPORT_OWNER_ADMISSIONS_LOCK:
            _REPORT_OWNER_ADMISSIONS[self] = self

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
        """Return only the request identity created during host admission."""

        self._require_report_authority()
        if candidate is not None and candidate is not self._report_request_identity:
            raise EvidenceProjectionError(
                "EVIDENCE_OWNER_REQUEST_REQUIRED",
                "Report request identity must be the exact owner-bound server identity",
            )
        return self._report_request_identity

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

        projection = default_projection_registry().project(
            self._canonical_record,
            consumer_id="report",
            destination="local",
        )
        return build_persisted_evidence_report_view(
            projection,
            owner=self,
            artifact_admission=self._canonical_artifact,
        )

    def _canonical_report_artifact(self) -> ArtifactAdmissionV1:
        """Return the exact C0 artifact admission used by Report projection."""

        self._require_report_authority()
        if type(self._canonical_artifact) is not ArtifactAdmissionV1:
            raise EvidenceProjectionError(
                "EVIDENCE_PROVENANCE_REQUIRED",
                "Report provenance is not bound to an admitted artifact",
            )
        return self._canonical_artifact

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

        from ..report_export import EvidenceProjectionV1, ReportEvidenceWriterV1

        self._require_report_authority()
        if type(projection) is not EvidenceProjectionV1:
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

        from ..report_export import EvidenceProjectionV1
        from ..reporting import ReportDocumentWriterV1

        self._require_report_authority()
        if not isinstance(view_model, Mapping):
            raise TypeError("Report document payload must be server-produced")
        if type(projection) is not EvidenceProjectionV1:
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
    ) -> PersistedEvidenceEnvelopeV1:
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
            envelope = artifact.envelope.envelope
            record = PersistedEvidenceEnvelopeV1(
                commit_id=binding.commit_id,
                artifact_ref=artifact.artifact_id,
                envelope_ref=f"evidence-envelope:{artifact.envelope_digest}",
                sensitivity="public",
                binding=binding,
                envelope=envelope,
            )
            if envelope_digest is not None and record.envelope_digest != envelope_digest:
                raise EvidenceProjectionError(
                    "PROJECTION_DIGEST_MISMATCH",
                    "persisted envelope digest differs from the requested commit",
                )
            return record
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

    capability = _REPORT_EVIDENCE_PERSISTENCE
    if type(capability) is not ServerOwnedReportEvidencePersistenceV1:
        return None
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


__all__ = [
    "PersistedEvidenceResultsFacadeV1",
    "ReportEvidenceRequestIdentityV1",
    "ServerOwnedReportEvidencePersistenceV1",
    "UnavailableReportEvidenceCapabilityV1",
    "configure_report_evidence_persistence",
    "current_report_evidence_persistence",
]
