"""Profile-bound adapter metadata for CF3.

This module describes an adapter; it never loads, imports, or executes the
referenced implementation.  The entrypoint is a content reference only.
"""

from __future__ import annotations

import hashlib
import base64
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..custom_capability.canonical import domain_digest
from .contracts import (
    CONSUMER_SLOTS,
    TRUST_ORDER,
    ContractError,
    ImplementationRevision,
    _consumer_map,
    _content_digest,
    _digest,
    _positive_int,
    _sequence,
    _text,
)
from .candidate_store import CapabilityCandidate
from .validation_contract import ValidationBundle, ValidationCase


ADAPTER_CONTRACT_SCHEMA_VERSION = "workbench_capability_factory_adapter_v1"
MAX_GENERATED_SOURCE_BYTES = 256 * 1024
MAX_ADAPTER_INPUT_BYTES = 256 * 1024
MAX_ADAPTER_RESULT_BYTES = 4 * 1024 * 1024
PYTHON_ADAPTER_ABI_VERSION = "workbench.python_adapter/v1"

# This is a fixed, trusted harness.  Generated source is supplied only as a
# content-addressed file and is loaded inside the explicitly experimental B1
# executor; the Workbench process never imports it.
PYTHON_ADAPTER_HARNESS = r'''
import importlib.util
import json
import os
from pathlib import Path
import sys

source_path = Path(sys.argv[1]).resolve()
input_path = Path(sys.argv[2]).resolve()
result_path = Path(sys.argv[3]).resolve()
for dependency_root in reversed(sys.argv[4:]):
    sys.path.insert(0, dependency_root)

def reject_constant(value):
    raise ValueError("non-finite JSON number: " + value)

document = json.loads(input_path.read_text(encoding="utf-8"), parse_constant=reject_constant)
module_spec = importlib.util.spec_from_file_location("workbench_generated_adapter", source_path)
if module_spec is None or module_spec.loader is None:
    raise RuntimeError("adapter module cannot be loaded")
module = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(module)
entrypoint = getattr(module, "adapter", None)
if not callable(entrypoint):
    raise RuntimeError("adapter entrypoint is missing")
result = entrypoint(document)
if not isinstance(result, dict):
    raise TypeError("adapter result must be a JSON object")
encoded = json.dumps(
    result,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    allow_nan=False,
).encode("utf-8")
if len(encoded) > 4 * 1024 * 1024:
    raise ValueError("adapter result exceeds the bounded limit")
temporary = result_path.with_name("." + result_path.name + ".tmp")
temporary.write_bytes(encoded)
os.chmod(temporary, 0o644)
os.replace(temporary, result_path)
'''
PYTHON_ADAPTER_LAUNCHER = (
    "exec(__import__('base64').b64decode("
    + repr(base64.b64encode(PYTHON_ADAPTER_HARNESS.encode("utf-8")).decode("ascii"))
    + "))"
)


class AdapterContractError(ContractError):
    """Raised when an adapter is not bound to a compatible CF1 revision."""


class AdapterSourceGenerationError(AdapterContractError):
    """Raised when generated source cannot enter the immutable source store."""


@dataclass(frozen=True, slots=True)
class AdapterContract:
    """An immutable, executable-free binding for one adapter revision."""

    adapter_id: str
    revision: int
    implementation_ref: str
    profile_id: str
    profile_revision: int
    profile_digest: str
    input_schema_digest: str
    source_kind: str
    trust_tier: str
    operations: tuple[str, ...]
    consumer_support: Mapping[str, str | None]
    entrypoint_ref: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "adapter_id", _text(self.adapter_id, "adapter_id"))
            object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
            object.__setattr__(self, "implementation_ref", _digest(self.implementation_ref, "implementation_ref"))
            object.__setattr__(self, "profile_id", _text(self.profile_id, "profile_id"))
            object.__setattr__(self, "profile_revision", _positive_int(self.profile_revision, "profile_revision"))
            object.__setattr__(self, "profile_digest", _digest(self.profile_digest, "profile_digest"))
            object.__setattr__(self, "input_schema_digest", _digest(self.input_schema_digest, "input_schema_digest"))
            source_kind = _text(self.source_kind, "source_kind")
            if source_kind not in TRUST_ORDER:
                raise AdapterContractError("source_kind is not a registered capability source")
            if self.trust_tier != source_kind:
                raise AdapterContractError("trust_tier must match source_kind")
            object.__setattr__(self, "source_kind", source_kind)
            object.__setattr__(self, "trust_tier", _text(self.trust_tier, "trust_tier"))
            object.__setattr__(self, "operations", _sequence(self.operations, "operations"))
            object.__setattr__(self, "consumer_support", _consumer_map(self.consumer_support, "consumer_support"))
            object.__setattr__(self, "entrypoint_ref", _digest(self.entrypoint_ref, "entrypoint_ref"))
        except ContractError as error:
            if isinstance(error, AdapterContractError):
                raise
            raise AdapterContractError(str(error)) from error

    @classmethod
    def from_implementation(
        cls,
        *,
        implementation: ImplementationRevision,
        adapter_id: str,
        revision: int,
        entrypoint_ref: str,
        operations: tuple[str, ...],
        consumer_support: Mapping[str, str | None],
    ) -> "AdapterContract":
        if not isinstance(implementation, ImplementationRevision):
            raise AdapterContractError("implementation must be an ImplementationRevision")
        adapter = cls(
            adapter_id=adapter_id,
            revision=revision,
            implementation_ref=implementation.content_digest,
            profile_id=implementation.profile_id,
            profile_revision=implementation.profile_revision,
            profile_digest=implementation.profile_digest,
            input_schema_digest=implementation.input_schema_digest,
            source_kind=implementation.source_kind,
            trust_tier=implementation.trust_tier,
            operations=operations,
            consumer_support=consumer_support,
            entrypoint_ref=entrypoint_ref,
        )
        adapter.validate_against(implementation)
        return adapter

    def validate_against(self, implementation: ImplementationRevision) -> None:
        """Recheck every inherited identity before a consumer can use metadata."""

        if not isinstance(implementation, ImplementationRevision):
            raise AdapterContractError("implementation must be an ImplementationRevision")
        if self.implementation_ref != implementation.content_digest:
            raise AdapterContractError("implementation binding does not match")
        if self.profile_id != implementation.profile_id or self.profile_revision != implementation.profile_revision:
            raise AdapterContractError("profile identity does not match implementation")
        if self.profile_digest != implementation.profile_digest:
            raise AdapterContractError("profile digest does not match implementation")
        if self.input_schema_digest != implementation.input_schema_digest:
            raise AdapterContractError("input schema digest does not match implementation")
        if self.source_kind != implementation.source_kind or self.trust_tier != implementation.trust_tier:
            raise AdapterContractError("trust binding does not match implementation")
        if not set(self.operations) <= set(implementation.operations):
            raise AdapterContractError("adapter operations are not declared by implementation")
        for slot in CONSUMER_SLOTS:
            if implementation.consumer_support[slot] is None and self.consumer_support[slot] is not None:
                raise AdapterContractError(f"{slot} is not declared by implementation")

    @property
    def content_digest(self) -> str:
        return _content_digest(self)

    @property
    def execution_allowed(self) -> bool:
        """Adapter metadata never grants an execution primitive."""

        return False


@dataclass(frozen=True, slots=True)
class AdapterSourceArtifact:
    source_ref: str
    entrypoint_ref: str
    language: str
    size_bytes: int
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ref", _digest(self.source_ref, "source_ref"))
        object.__setattr__(self, "entrypoint_ref", _digest(self.entrypoint_ref, "entrypoint_ref"))
        if self.language != "python":
            raise AdapterSourceGenerationError("only the versioned Python adapter ABI is supported")
        if not isinstance(self.size_bytes, int) or self.size_bytes < 1 or self.size_bytes > MAX_GENERATED_SOURCE_BYTES:
            raise AdapterSourceGenerationError("generated source size is outside the bound")
        path = Path(self.path)
        if not path.is_absolute() or path.name != f"{self.source_ref}.py":
            raise AdapterSourceGenerationError("generated source path is not content-addressed")
        if path.is_symlink() or not path.is_file():
            raise AdapterSourceGenerationError("generated source artifact is not a regular file")
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise AdapterSourceGenerationError("generated source artifact cannot be read") from error
        if len(raw) != self.size_bytes or hashlib.sha256(raw).hexdigest() != self.source_ref:
            raise AdapterSourceGenerationError("generated source artifact content does not match its reference")
        object.__setattr__(self, "path", path)

    @property
    def execution_allowed(self) -> bool:
        """A source artifact is not an execution authorization."""

        return False


class PythonAdapterExecutionError(AdapterContractError):
    """Raised when a Python adapter invocation cannot be safely prepared."""


@dataclass(frozen=True, slots=True)
class PythonAdapterExecutionBinding:
    """Trusted preparation of one offline Python adapter invocation.

    The binding creates a fresh input document and a read-only copy of the
    generated source inside the trusted input root.  It produces only a
    ``DarwinExecutionSpec``; process creation remains owned by B1.
    """

    bundle_ref: str
    output_namespace_ref: str
    adapter: AdapterContract
    source_artifact: AdapterSourceArtifact
    operation: str
    payload: Mapping[str, object]
    input_root: Path
    output_root: Path
    interpreter: Path = Path(sys.executable)
    dependency_roots: tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "bundle_ref", _digest(self.bundle_ref, "bundle_ref"))
        object.__setattr__(self, "output_namespace_ref", _digest(self.output_namespace_ref, "output_namespace_ref"))
        if not isinstance(self.adapter, AdapterContract):
            raise PythonAdapterExecutionError("adapter is invalid")
        if not isinstance(self.source_artifact, AdapterSourceArtifact):
            raise PythonAdapterExecutionError("source_artifact is invalid")
        if self.adapter.entrypoint_ref != self.source_artifact.entrypoint_ref:
            raise PythonAdapterExecutionError("adapter entrypoint is not bound to source artifact")
        operation = _text(self.operation, "operation")
        if operation not in self.adapter.operations:
            raise PythonAdapterExecutionError("operation is not declared by adapter")
        object.__setattr__(self, "operation", operation)
        if not isinstance(self.payload, Mapping):
            raise PythonAdapterExecutionError("payload must be a JSON object")
        payload = dict(self.payload)
        try:
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise PythonAdapterExecutionError("payload is not finite JSON") from error
        if len(encoded) > MAX_ADAPTER_INPUT_BYTES:
            raise PythonAdapterExecutionError("payload exceeds the bounded input limit")
        object.__setattr__(self, "payload", payload)
        interpreter_value = self.interpreter.resolve() if isinstance(self.interpreter, Path) else self.interpreter
        interpreter = self._regular_absolute_path(interpreter_value, "interpreter", must_exist=True)
        object.__setattr__(self, "interpreter", interpreter)
        roots = tuple(self.dependency_roots)
        if len(roots) > 32:
            raise PythonAdapterExecutionError("dependency roots exceed the bounded limit")
        normalized_roots = tuple(
            self._regular_absolute_path(root, "dependency_root", must_exist=True, directory=True)
            for root in roots
        )
        if len(set(normalized_roots)) != len(normalized_roots):
            raise PythonAdapterExecutionError("dependency roots must be unique")
        object.__setattr__(self, "dependency_roots", normalized_roots)
        input_root = self._regular_absolute_path(self.input_root, "input_root", must_exist=False)
        output_root = self._regular_absolute_path(self.output_root, "output_root", must_exist=False)
        if input_root == output_root:
            raise PythonAdapterExecutionError("input and output roots must be distinct")
        object.__setattr__(self, "input_root", input_root)
        object.__setattr__(self, "output_root", output_root)

    @property
    def result_path(self) -> Path:
        return self.output_root / "result.json"

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.python_adapter_execution_binding/v1",
            {
                "bundle_ref": self.bundle_ref,
                "output_namespace_ref": self.output_namespace_ref,
                "adapter_ref": self.adapter.content_digest,
                "source_ref": self.source_artifact.source_ref,
                "operation": self.operation,
                "payload": dict(self.payload),
                "input_root": str(self.input_root),
                "output_root": str(self.output_root),
                "interpreter": str(self.interpreter),
                "dependency_roots": [str(root) for root in self.dependency_roots],
            },
        )

    def prepare(self, request: Any):
        from ..native_containment.contracts import ContainmentRequest
        from ..native_containment.executor_darwin import DarwinExecutionSpec

        if not isinstance(request, ContainmentRequest):
            raise PythonAdapterExecutionError("request is invalid")
        if request.input_bundle_ref != self.bundle_ref:
            raise PythonAdapterExecutionError("request input is not bound to the adapter bundle")
        if request.output_namespace_ref != self.output_namespace_ref:
            raise PythonAdapterExecutionError("request output is not bound to the adapter namespace")
        self._prepare_root(self.input_root)
        self._prepare_root(self.output_root)
        source_destination = self.input_root / f"{self.source_artifact.source_ref}.py"
        request_path = self.input_root / "request.json"
        allowed_input_paths = {source_destination, request_path}
        unexpected = [path for path in self.input_root.iterdir() if path not in allowed_input_paths]
        if unexpected:
            raise PythonAdapterExecutionError("input root contains undeclared files")
        self._write_immutable(source_destination, self.source_artifact.path.read_bytes())
        document = {
            "abi": PYTHON_ADAPTER_ABI_VERSION,
            "adapter_ref": self.adapter.content_digest,
            "bundle_ref": self.bundle_ref,
            "request_id": request.request_id,
            "attempt_id": request.attempt_id,
            "operation": self.operation,
            "payload": dict(self.payload),
        }
        try:
            encoded = json.dumps(
                document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise PythonAdapterExecutionError("adapter invocation is not finite JSON") from error
        if len(encoded) > MAX_ADAPTER_INPUT_BYTES:
            raise PythonAdapterExecutionError("adapter invocation exceeds the bounded input limit")
        self._write_immutable(request_path, encoded)
        executable_digest = hashlib.sha256(self.interpreter.read_bytes()).hexdigest()
        return DarwinExecutionSpec(
            input_bundle_ref=self.bundle_ref,
            output_namespace_ref=self.output_namespace_ref,
            executable=self.interpreter,
            executable_digest=executable_digest,
            arguments=(
                "-I",
                "-c",
                PYTHON_ADAPTER_LAUNCHER,
                str(source_destination),
                str(request_path),
                str(self.result_path),
                *(str(root) for root in self.dependency_roots),
            ),
            input_root=self.input_root,
            output_root=self.output_root,
            read_roots=self.dependency_roots,
        )

    def read_result(self, request: Any, report: Any) -> dict[str, Any]:
        """Read one completed, request-bound adapter result for trusted mapping.

        This is the only server-side result read seam.  It returns bounded
        finite JSON after rechecking the request/report identity; it does not
        turn the payload into Workbench artifacts or grant execution rights.
        A server-owned completion factory must perform that semantic mapping.
        """

        from ..native_containment.contracts import ContainmentReport, ContainmentRequest

        if not isinstance(request, ContainmentRequest) or not isinstance(report, ContainmentReport):
            raise PythonAdapterExecutionError("adapter result binding is invalid")
        if report.status != "completed":
            raise PythonAdapterExecutionError("adapter result is not completed")
        if report.attempt_id != request.attempt_id or report.request_digest != request.content_digest:
            raise PythonAdapterExecutionError("adapter result report is not bound to request")
        path = self.result_path
        if path.is_symlink() or not path.is_file():
            raise PythonAdapterExecutionError("adapter result file is missing")
        raw = path.read_bytes()
        if len(raw) > MAX_ADAPTER_RESULT_BYTES:
            raise PythonAdapterExecutionError("adapter result exceeds the bounded limit")
        try:
            result = json.loads(raw.decode("utf-8"), parse_constant=self._reject_json_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise PythonAdapterExecutionError("adapter result is not finite JSON") from error
        if not isinstance(result, dict):
            raise PythonAdapterExecutionError("adapter result must be a JSON object")
        return result

    def validate_result(self, request: Any, report: Any) -> None:
        from ..native_containment.contracts import ContainmentReport, ContainmentRequest

        if not isinstance(request, ContainmentRequest) or not isinstance(report, ContainmentReport):
            raise PythonAdapterExecutionError("adapter result binding is invalid")
        if report.status != "completed":
            return
        self.read_result(request, report)

    @staticmethod
    def _reject_json_constant(value: str) -> None:
        raise ValueError("non-finite JSON number: " + value)

    @staticmethod
    def _prepare_root(path: Path) -> None:
        PythonAdapterExecutionBinding._assert_no_symlink_ancestors(path)
        if path.exists() and path.is_symlink():
            raise PythonAdapterExecutionError("execution root must not be a symlink")
        path.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise PythonAdapterExecutionError("execution root is not a directory")

    @staticmethod
    def _write_immutable(path: Path, raw: bytes) -> None:
        if path.exists() and path.is_symlink():
            raise PythonAdapterExecutionError("execution input must not be a symlink")
        if path.exists():
            if not path.is_file() or path.read_bytes() != raw:
                raise PythonAdapterExecutionError("execution input is already bound to other bytes")
            return
        descriptor, temporary_name = tempfile.mkstemp(prefix=".adapter-input-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o444)
            os.replace(temporary, path)
            os.chmod(path, 0o444)
        except OSError as error:
            raise PythonAdapterExecutionError("execution input write failed") from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _regular_absolute_path(
        value: Any,
        field: str,
        *,
        must_exist: bool,
        directory: bool = False,
    ) -> Path:
        if not isinstance(value, Path) or not value.is_absolute():
            raise PythonAdapterExecutionError(f"{field} must be absolute")
        PythonAdapterExecutionBinding._assert_no_symlink_ancestors(value)
        if value.is_symlink():
            raise PythonAdapterExecutionError(f"{field} must not be a symlink")
        if must_exist and (not value.exists() or not value.is_file() and not (directory and value.is_dir())):
            raise PythonAdapterExecutionError(f"{field} is unavailable")
        if directory and must_exist and not value.is_dir():
            raise PythonAdapterExecutionError(f"{field} must be a directory")
        return value.resolve()

    @staticmethod
    def _assert_no_symlink_ancestors(path: Path) -> None:
        current = path
        while True:
            if current.is_symlink():
                raise PythonAdapterExecutionError("execution path contains a symlink ancestor")
            if current.parent == current:
                return
            current = current.parent


class PythonAdapterExecutionGateway:
    """Validate adapter output around a trusted B1 executor, never fallback."""

    execution_allowed = False

    def __init__(self, *, binding: PythonAdapterExecutionBinding, executor: Any) -> None:
        if not isinstance(binding, PythonAdapterExecutionBinding):
            raise PythonAdapterExecutionError("binding is invalid")
        if not callable(executor) or not callable(getattr(executor, "spawn", None)) or not callable(
            getattr(executor, "terminate", None)
        ):
            raise PythonAdapterExecutionError("executor lacks trusted lifecycle")
        self.binding = binding
        self.executor = executor

    def __call__(self, request: Any, policy: Any, canary: Any):
        from ..native_containment.contracts import ContainmentReport, ContainmentRequest

        if not isinstance(request, ContainmentRequest):
            raise PythonAdapterExecutionError("request is invalid")
        try:
            report = self.executor(request, policy, canary)
        except Exception:
            return ContainmentReport(
                attempt_id=request.attempt_id,
                request_digest=request.content_digest,
                status="failed",
                reason_code="NATIVE_CONTAINMENT_EXECUTOR_FAILED",
            )
        if not isinstance(report, ContainmentReport):
            return ContainmentReport(
                attempt_id=request.attempt_id,
                request_digest=request.content_digest,
                status="failed",
                reason_code="NATIVE_CONTAINMENT_EXECUTOR_FAILED",
            )
        if report.status == "completed":
            try:
                self.binding.validate_result(request, report)
            except PythonAdapterExecutionError:
                return ContainmentReport(
                    attempt_id=request.attempt_id,
                    request_digest=request.content_digest,
                    status="failed",
                    reason_code="NATIVE_CONTAINMENT_ADAPTER_OUTPUT_INVALID",
                )
        return report

    def spawn(self, request: Any, policy: Any, canary: Any):
        self.binding.prepare(request)
        return self.executor.spawn(request, policy, canary)

    def terminate(self, spawned: Any):
        return self.executor.terminate(spawned)


class AdapterSourceGenerator:
    """Store Agent-produced source as an untrusted, content-addressed artifact."""

    def generate(
        self,
        *,
        implementation: ImplementationRevision,
        provider: Callable[[Mapping[str, object]], str | bytes],
        output_root: Path | str,
    ) -> AdapterSourceArtifact:
        if not isinstance(implementation, ImplementationRevision):
            raise AdapterSourceGenerationError("implementation must be an ImplementationRevision")
        if not callable(provider):
            raise AdapterSourceGenerationError("source provider must be callable")
        context = {
            "profile_ref": implementation.profile_digest,
            "input_schema_ref": implementation.input_schema_digest,
            "operations": list(implementation.operations),
            "implementation_ref": implementation.content_digest,
        }
        try:
            generated = provider(context)
        except Exception as error:
            raise AdapterSourceGenerationError("source provider failed") from error
        if isinstance(generated, str):
            raw = generated.encode("utf-8")
        elif isinstance(generated, bytes):
            raw = generated
        else:
            raise AdapterSourceGenerationError("source provider must return UTF-8 text or bytes")
        if not raw or len(raw) > MAX_GENERATED_SOURCE_BYTES or b"\x00" in raw:
            raise AdapterSourceGenerationError("generated source is empty, oversized, or contains NUL")
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise AdapterSourceGenerationError("generated source is not valid UTF-8") from error
        root = Path(output_root)
        if not root.is_absolute() or root.exists() and root.is_symlink():
            raise AdapterSourceGenerationError("source output root must be absolute and not a symlink")
        self._assert_no_symlink_ancestors(root)
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise AdapterSourceGenerationError("source output root is not a directory")
        source_ref = hashlib.sha256(raw).hexdigest()
        entrypoint_ref = domain_digest(
            "workbench.capability_factory.adapter_entrypoint/v1",
            {"source_ref": source_ref, "symbol": "adapter"},
        )
        destination = root / f"{source_ref}.py"
        if destination.is_symlink():
            raise AdapterSourceGenerationError("source destination must not be a symlink")
        if destination.exists():
            if destination.read_bytes() != raw:
                raise AdapterSourceGenerationError("source reference is already bound to other bytes")
            return AdapterSourceArtifact(source_ref, entrypoint_ref, "python", len(raw), destination)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".adapter-", suffix=".tmp", dir=root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o444)
            os.replace(temporary, destination)
            os.chmod(destination, 0o444)
        except OSError as error:
            raise AdapterSourceGenerationError("generated source write failed") from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return AdapterSourceArtifact(source_ref, entrypoint_ref, "python", len(raw), destination)

    @staticmethod
    def _assert_no_symlink_ancestors(path: Path) -> None:
        current = path
        while True:
            if current.is_symlink():
                raise AdapterSourceGenerationError("source output path contains a symlink ancestor")
            parent = current.parent
            if parent == current:
                return
            current = parent


@dataclass(frozen=True, slots=True)
class GeneratedAdapterCandidate:
    """The untrusted, not-yet-validated output of adapter generation."""

    candidate: CapabilityCandidate
    adapter: AdapterContract
    validation_bundle: ValidationBundle

    @property
    def execution_allowed(self) -> bool:
        return False

    @property
    def source_eligible(self) -> bool:
        return False

    @property
    def promotion_state(self) -> str:
        """Generated candidates always begin in the experimental state."""

        return "experimental"


class AdapterCandidateFactory:
    """Turn a typed generation request into metadata-only CF3 candidates.

    The caller supplies content references for generated code and its
    entrypoint.  This factory never receives source text, imports a module, or
    calls the entrypoint.  The resulting ValidationBundle intentionally has no
    evidence; only the later B1/CF3 validation path can append server-assessed
    evidence.
    """

    def generate(
        self,
        *,
        implementation: ImplementationRevision,
        adapter_id: str,
        adapter_revision: int,
        entrypoint_ref: str,
        operations: tuple[str, ...],
        consumer_support: Mapping[str, str | None],
        candidate_id: str,
        capability_kind: str,
        source_ref: str,
        author_lineage_ref: str,
        validation_bundle_id: str,
        validation_cases: tuple[ValidationCase, ...],
        source_artifact: AdapterSourceArtifact | None = None,
    ) -> GeneratedAdapterCandidate:
        if not isinstance(implementation, ImplementationRevision):
            raise AdapterContractError("implementation must be an ImplementationRevision")
        if implementation.source_kind != "generated_adapter":
            raise AdapterContractError("adapter generation requires generated_adapter trust tier")
        if source_artifact is None:
            raise AdapterContractError(
                "source_artifact is required to bind generated adapter source"
            )
        if not isinstance(validation_cases, (tuple, list)) or not validation_cases:
            raise AdapterContractError("adapter generation requires bounded validation cases")
        if any(not isinstance(item, ValidationCase) for item in validation_cases):
            raise AdapterContractError("validation_cases must contain ValidationCase values")
        if not isinstance(source_artifact, AdapterSourceArtifact):
            raise AdapterContractError("source_artifact must be an AdapterSourceArtifact")
        if source_ref != source_artifact.source_ref:
            raise AdapterContractError("candidate source_ref does not match generated source")
        if entrypoint_ref != source_artifact.entrypoint_ref:
            raise AdapterContractError("candidate entrypoint_ref does not match generated source")
        adapter = AdapterContract.from_implementation(
            implementation=implementation,
            adapter_id=adapter_id,
            revision=adapter_revision,
            entrypoint_ref=entrypoint_ref,
            operations=operations,
            consumer_support=consumer_support,
        )
        candidate = CapabilityCandidate(
            candidate_id=candidate_id,
            capability_kind=capability_kind,
            source_kind="generated_adapter",
            implementation_ref=implementation.content_digest,
            source_ref=source_ref,
            author_lineage_ref=author_lineage_ref,
            risk_level="high",
        )
        validation_bundle = ValidationBundle(
            bundle_id=validation_bundle_id,
            revision=1,
            adapter_ref=adapter.content_digest,
            cases=tuple(validation_cases),
        )
        return GeneratedAdapterCandidate(
            candidate=candidate,
            adapter=adapter,
            validation_bundle=validation_bundle,
        )


__all__ = [
    "ADAPTER_CONTRACT_SCHEMA_VERSION",
    "AdapterCandidateFactory",
    "AdapterContract",
    "AdapterContractError",
    "AdapterSourceArtifact",
    "AdapterSourceGenerationError",
    "AdapterSourceGenerator",
    "GeneratedAdapterCandidate",
    "MAX_ADAPTER_INPUT_BYTES",
    "MAX_ADAPTER_RESULT_BYTES",
    "PYTHON_ADAPTER_ABI_VERSION",
    "PythonAdapterExecutionBinding",
    "PythonAdapterExecutionError",
    "PythonAdapterExecutionGateway",
]
