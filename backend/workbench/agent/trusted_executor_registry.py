"""Server-composed provider runtime bindings for Agent/Notebook cutover.

Provider manifests are deliberately declarative.  This module is the only
place in the cutover seam where an opaque manifest executor reference can be
joined to a callable.  A manifest can never import a module, provide a path,
or mint an execution authority marker.
"""

from __future__ import annotations

import inspect
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.provider import AdapterDeclarationV1, ProviderContributionV1


_EXECUTOR_ID = re.compile(r"executor:[A-Za-z0-9][A-Za-z0-9_.:-]{0,191}")
_FORBIDDEN_KEYS = frozenset(
    {
        "raw_prompt",
        "prompt",
        "secret",
        "password",
        "api_key",
        "access_token",
        "private_key",
        "module",
        "module_path",
        "import_path",
        "callable_path",
        "url",
        "path",
        "code",
    }
)
_FORBIDDEN_VALUE_MARKERS = ("://", "../", "..\\", "file:", "module:", "import:")


class TrustedExecutorRegistryError(ValueError):
    """A provider/runtime join or dispatch failed closed."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise TrustedExecutorRegistryError("RUNTIME_TEXT_INVALID", f"{name} must be a non-empty string")
    return value


def _executor_ref(value: object) -> str:
    if type(value) is not str or _EXECUTOR_ID.fullmatch(value) is None:
        raise TrustedExecutorRegistryError(
            "RUNTIME_EXECUTOR_OPAQUE_REQUIRED",
            "executor reference must be an opaque executor:<id> value",
        )
    if any(marker in value.casefold() for marker in _FORBIDDEN_VALUE_MARKERS):
        raise TrustedExecutorRegistryError("RUNTIME_EXECUTOR_OPAQUE_REQUIRED")
    return value


def _validate_callable(value: object, name: str, arity: int) -> Callable[..., Any]:
    if not callable(value):
        raise TrustedExecutorRegistryError("RUNTIME_CALLABLE_REQUIRED", f"{name} must be a callable")
    try:
        signature = inspect.signature(value)
        parameters = tuple(signature.parameters.values())
    except (TypeError, ValueError) as exc:
        raise TrustedExecutorRegistryError("RUNTIME_CALLABLE_SIGNATURE_INVALID", name) from exc
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        raise TrustedExecutorRegistryError("RUNTIME_CALLABLE_SIGNATURE_INVALID", name)
    positional = tuple(
        parameter
        for parameter in parameters
        if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
    )
    required_keyword_only = tuple(
        parameter
        for parameter in parameters
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        and parameter.default is inspect.Parameter.empty
    )
    if required_keyword_only or len(positional) != arity:
        raise TrustedExecutorRegistryError(
            "RUNTIME_CALLABLE_SIGNATURE_INVALID",
            f"{name} must accept exactly {arity} positional arguments",
        )
    return value  # type: ignore[return-value]


def _json_safe(value: object, *, path: str = "payload", depth: int = 0) -> None:
    if depth > 8:
        raise TrustedExecutorRegistryError("RUNTIME_PAYLOAD_TOO_DEEP", path)
    if isinstance(value, Mapping):
        for key, child in value.items():
            if type(key) is not str or not key or key.casefold() in _FORBIDDEN_KEYS:
                raise TrustedExecutorRegistryError("RUNTIME_UNSAFE_PAYLOAD", f"unsafe key at {path}")
            _json_safe(child, path=f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _json_safe(child, path=f"{path}[{index}]", depth=depth + 1)
        return
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and any(marker in value.casefold() for marker in _FORBIDDEN_VALUE_MARKERS):
            raise TrustedExecutorRegistryError("RUNTIME_UNSAFE_PAYLOAD", path)
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TrustedExecutorRegistryError("RUNTIME_NONFINITE_PAYLOAD", path)
        return
    raise TrustedExecutorRegistryError("RUNTIME_UNSAFE_PAYLOAD", path)


@dataclass(frozen=True)
class ProviderRuntimeContextV1:
    """Server-bound context supplied to a registered provider callable."""

    compilation_record_id: str
    execution_instance_hash: str
    actor_ref: str
    session_ref: str
    project_ref: str
    effect: str
    evidence_required: bool = True

    def __post_init__(self) -> None:
        for name in (
            "compilation_record_id",
            "execution_instance_hash",
            "actor_ref",
            "session_ref",
            "project_ref",
            "effect",
        ):
            _text(getattr(self, name), name)
        if type(self.evidence_required) is not bool:
            raise TrustedExecutorRegistryError("RUNTIME_CONTEXT_INVALID", "evidence_required must be boolean")


@dataclass(frozen=True)
class ProviderRuntimeContributionV1:
    """One server-composed, contract-pinned provider implementation."""

    provider_id: str
    adapter_id: str
    executor_ref: str
    owner: str
    signature: str
    effect: str
    request_contract_ref: ContractRefV1
    result_contract_refs: tuple[ContractRefV1, ...]
    executor: Callable[[ProviderRuntimeContextV1, Mapping[str, Any]], Mapping[str, Any]]
    request_validator: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    result_validator: Callable[[Mapping[str, Any]], None]
    execution_allowed: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider_id")
        _text(self.adapter_id, "adapter_id")
        _executor_ref(self.executor_ref)
        _text(self.owner, "owner")
        _text(self.signature, "signature")
        _text(self.effect, "effect")
        if type(self.request_contract_ref) is not ContractRefV1:
            raise TrustedExecutorRegistryError("RUNTIME_CONTRACT_REF_REQUIRED", "request contract ref is required")
        if type(self.result_contract_refs) is not tuple or not self.result_contract_refs:
            raise TrustedExecutorRegistryError("RUNTIME_CONTRACT_REF_REQUIRED", "result contract refs are required")
        if any(type(ref) is not ContractRefV1 for ref in self.result_contract_refs):
            raise TrustedExecutorRegistryError("RUNTIME_CONTRACT_REF_REQUIRED", "result contract refs are invalid")
        _validate_callable(self.executor, "executor", 2)
        _validate_callable(self.request_validator, "request_validator", 1)
        _validate_callable(self.result_validator, "result_validator", 1)
        if type(self.execution_allowed) is not bool:
            raise TrustedExecutorRegistryError("RUNTIME_POLICY_INVALID", "execution_allowed must be boolean")
        if not isinstance(self.metadata, Mapping):
            raise TrustedExecutorRegistryError("RUNTIME_METADATA_INVALID", "metadata must be a mapping")
        _json_safe(self.metadata, path="metadata")

    def binding_payload(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "executor_ref": self.executor_ref,
            "owner": self.owner,
            "signature": self.signature,
            "effect": self.effect,
            "request_contract_ref": self.request_contract_ref.to_dict(),
            "result_contract_refs": [ref.to_dict() for ref in self.result_contract_refs],
            "execution_allowed": self.execution_allowed,
            "metadata": dict(self.metadata),
        }


class TrustedExecutorRegistry:
    """Immutable-by-convention server registry for opaque executor IDs."""

    def __init__(self, contributions: list[ProviderRuntimeContributionV1] | tuple[ProviderRuntimeContributionV1, ...]):
        if type(contributions) not in {list, tuple}:
            raise TrustedExecutorRegistryError("RUNTIME_CONTRIBUTIONS_INVALID")
        values: dict[str, ProviderRuntimeContributionV1] = {}
        for contribution in contributions:
            if type(contribution) is not ProviderRuntimeContributionV1:
                raise TrustedExecutorRegistryError("RUNTIME_CONTRIBUTION_REQUIRED")
            if contribution.executor_ref in values:
                raise TrustedExecutorRegistryError("RUNTIME_DUPLICATE_EXECUTOR", contribution.executor_ref)
            values[contribution.executor_ref] = contribution
        self._contributions = values
        self._bound_catalog_digest: str | None = None

    @property
    def executor_refs(self) -> tuple[str, ...]:
        return tuple(sorted(self._contributions))

    def require(self, executor_ref: str) -> ProviderRuntimeContributionV1:
        _executor_ref(executor_ref)
        try:
            return self._contributions[executor_ref]
        except KeyError as exc:
            raise TrustedExecutorRegistryError("RUNTIME_EXECUTOR_UNREGISTERED", executor_ref) from exc

    def bind_catalog(self, catalog: object) -> None:
        """Require a one-to-one declaration/code join before dispatch."""

        if not hasattr(catalog, "providers") or not hasattr(catalog, "catalog_digest"):
            raise TrustedExecutorRegistryError("RUNTIME_CATALOG_REQUIRED")
        expected: dict[str, tuple[str, str, ContractRefV1, tuple[ContractRefV1, ...]]] = {}
        for provider in catalog.providers:
            if type(provider) is not ProviderContributionV1:
                raise TrustedExecutorRegistryError("RUNTIME_CATALOG_INVALID")
            for declaration in provider.adapter_declarations:
                if type(declaration) is not AdapterDeclarationV1:
                    raise TrustedExecutorRegistryError("RUNTIME_ADAPTER_DECLARATION_INVALID")
                if declaration.executor_ref in expected:
                    raise TrustedExecutorRegistryError("RUNTIME_DUPLICATE_DECLARATION", declaration.executor_ref)
                expected[declaration.executor_ref] = (
                    provider.provider_id,
                    declaration.adapter_id,
                    declaration.request_schema_ref,
                    declaration.output_refs,
                )
        actual = set(self._contributions)
        missing = sorted(set(expected) - actual)
        extra = sorted(actual - set(expected))
        if missing:
            raise TrustedExecutorRegistryError(
                "RUNTIME_CONTRIBUTION_MISSING",
                f"missing runtime contributions: {', '.join(missing)}",
            )
        if extra:
            raise TrustedExecutorRegistryError(
                "RUNTIME_CONTRIBUTION_EXTRA",
                f"extra runtime contributions: {', '.join(extra)}",
            )
        for executor_ref, expected_row in expected.items():
            contribution = self._contributions[executor_ref]
            provider_id, adapter_id, request_ref, result_refs = expected_row
            if (contribution.provider_id, contribution.adapter_id) != (provider_id, adapter_id):
                raise TrustedExecutorRegistryError("RUNTIME_CONTRIBUTION_ID_MISMATCH", executor_ref)
            if contribution.request_contract_ref != request_ref:
                raise TrustedExecutorRegistryError("RUNTIME_REQUEST_CONTRACT_MISMATCH", executor_ref)
            if contribution.result_contract_refs != result_refs:
                raise TrustedExecutorRegistryError("RUNTIME_RESULT_CONTRACT_MISMATCH", executor_ref)
        self._bound_catalog_digest = str(catalog.catalog_digest)

    def dispatch(
        self,
        executor_ref: str,
        context: ProviderRuntimeContextV1,
        request: Mapping[str, Any],
        *,
        catalog_digest: str | None = None,
    ) -> dict[str, Any]:
        if self._bound_catalog_digest is None:
            raise TrustedExecutorRegistryError("RUNTIME_CATALOG_NOT_BOUND")
        if catalog_digest is not None and catalog_digest != self._bound_catalog_digest:
            raise TrustedExecutorRegistryError("RUNTIME_CATALOG_CHANGED")
        contribution = self.require(executor_ref)
        if not contribution.execution_allowed:
            raise TrustedExecutorRegistryError("RUNTIME_EXECUTION_BLOCKED", executor_ref)
        if type(context) is not ProviderRuntimeContextV1:
            raise TrustedExecutorRegistryError("RUNTIME_CONTEXT_REQUIRED")
        if not isinstance(request, Mapping):
            raise TrustedExecutorRegistryError("RUNTIME_REQUEST_REQUIRED")
        _json_safe(request, path="request")
        try:
            normalized = contribution.request_validator(dict(request))
        except TrustedExecutorRegistryError:
            raise
        except Exception as exc:
            raise TrustedExecutorRegistryError("RUNTIME_REQUEST_INVALID", str(exc)) from exc
        if not isinstance(normalized, Mapping):
            raise TrustedExecutorRegistryError("RUNTIME_REQUEST_INVALID", "validator must return a mapping")
        _json_safe(normalized, path="normalized_request")
        try:
            result = contribution.executor(context, dict(normalized))
        except TrustedExecutorRegistryError:
            raise
        except Exception as exc:
            raise TrustedExecutorRegistryError("RUNTIME_EXECUTION_FAILED", str(exc)) from exc
        if not isinstance(result, Mapping):
            raise TrustedExecutorRegistryError("RUNTIME_RESULT_INVALID", "executor must return a mapping")
        _json_safe(result, path="result")
        try:
            contribution.result_validator(dict(result))
        except TrustedExecutorRegistryError:
            raise
        except Exception as exc:
            raise TrustedExecutorRegistryError("RUNTIME_RESULT_INVALID", str(exc)) from exc
        return dict(result)


__all__ = [
    "ProviderRuntimeContextV1",
    "ProviderRuntimeContributionV1",
    "TrustedExecutorRegistry",
    "TrustedExecutorRegistryError",
]
