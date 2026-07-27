"""Server-owned lookup for admitted capability bindings.

The Agent may name a capability, but it never supplies the binding that gives
that name meaning.  This catalog keeps the identity mapping outside the Agent
payload and re-verifies the immutable binding whenever a Notebook consumer
looks it up.  It is deliberately in-memory in this slice; the Capability
Factory authority remains the source that constructs and refreshes it.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from math import isfinite
from types import MappingProxyType
from typing import Any, Callable, Sequence

from .notebook_binding import CapabilityResolutionBinding
from .contracts import CONSUMER_SLOTS, NOTEBOOK_OPTION_PLANNER_CONSUMER
from .store import ContentAddressedStore


class CapabilityBindingCatalogError(ValueError):
    """A server-owned binding could not be registered or resolved."""


CapabilityBindingVerifier = Callable[[CapabilityResolutionBinding], None]
ScopeCandidate = tuple[str, str]
PlannerProjection = Mapping[str, Any]

_PLANNER_PROJECTION_FIELDS = frozenset(
    {
        "key",
        "label",
        "model_type",
        "description",
        "notebook_proposal_adapters",
        "params",
        "artifact_types",
    }
)
_PLANNER_PROJECTION_ADAPTERS = frozenset(
    {"model.custom", "model.genesis", "model.rerun"}
)
_PLANNER_PARAM_FIELDS = frozenset(
    {"key", "kind", "label", "role", "required", "options", "value"}
)
_MAX_PLANNER_PARAMS = 64
_MAX_PLANNER_PARAM_OPTIONS = 32
_MAX_PLANNER_ARTIFACTS = 64
_MAX_PLANNER_TEXT = 500

if NOTEBOOK_OPTION_PLANNER_CONSUMER not in CONSUMER_SLOTS:
    raise RuntimeError("Notebook planner consumer slot is not in the CF contract")


def _capability_id(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CapabilityBindingCatalogError(
            "capability_id must be a non-empty trimmed string"
        )
    return value


def _projection_text(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _MAX_PLANNER_TEXT
        or any(ord(char) < 0x20 for char in value)
    ):
        raise CapabilityBindingCatalogError(
            f"planner_projection.{field} must be a bounded non-empty text value"
        )
    return value


def _planner_params(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_PLANNER_PARAMS:
        raise CapabilityBindingCatalogError(
            "planner_projection.params must be a bounded list"
        )
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise CapabilityBindingCatalogError(
                "planner_projection.params must contain objects"
            )
        unknown = set(item) - _PLANNER_PARAM_FIELDS
        if unknown:
            raise CapabilityBindingCatalogError(
                "planner_projection.params contains unsupported field(s): "
                + ", ".join(sorted(str(field) for field in unknown))
            )
        current: dict[str, Any] = {}
        for field in ("key", "kind", "label", "role"):
            if field in item:
                current[field] = _projection_text(item[field], f"params.{field}")
        if "required" in item:
            if type(item["required"]) is not bool:
                raise CapabilityBindingCatalogError(
                    "planner_projection.params.required must be boolean"
                )
            current["required"] = item["required"]
        if "options" in item:
            options = item["options"]
            if not isinstance(options, (list, tuple)) or len(options) > _MAX_PLANNER_PARAM_OPTIONS:
                raise CapabilityBindingCatalogError(
                    "planner_projection.params.options must be a bounded list"
                )
            current["options"] = [
                _projection_text(option, "params.options") for option in options
            ]
        if "value" in item:
            value_item = item["value"]
            if isinstance(value_item, (list, tuple)):
                if len(value_item) > _MAX_PLANNER_PARAM_OPTIONS or any(
                    not isinstance(option, str) for option in value_item
                ):
                    raise CapabilityBindingCatalogError(
                        "planner_projection.params.value must be scalar or a string list"
                    )
                current["value"] = [
                    _projection_text(option, "params.value") for option in value_item
                ]
            elif value_item is None or type(value_item) in {str, bool, int}:
                current["value"] = (
                    _projection_text(value_item, "params.value")
                    if isinstance(value_item, str)
                    else value_item
                )
            elif isinstance(value_item, float) and isfinite(value_item):
                current["value"] = value_item
            else:
                raise CapabilityBindingCatalogError(
                    "planner_projection.params.value must be scalar or a string list"
                )
        normalized.append(current)
    return normalized


def _planner_projection(
    capability_id: str,
    value: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """Validate the small, Agent-facing projection at the authority seam."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CapabilityBindingCatalogError("planner_projection must be an object")
    unknown = set(value) - _PLANNER_PROJECTION_FIELDS
    if unknown:
        raise CapabilityBindingCatalogError(
            "planner_projection contains unsupported field(s): "
            + ", ".join(sorted(str(item) for item in unknown))
        )
    if value.get("key") != capability_id:
        raise CapabilityBindingCatalogError(
            "planner_projection.key must match capability_id"
        )
    label = _projection_text(value.get("label"), "label")
    model_type = _projection_text(value.get("model_type"), "model_type")
    description = value.get("description")
    if description is not None:
        description = _projection_text(description, "description")
    adapters = value.get("notebook_proposal_adapters", ["model.genesis"])
    if (
        not isinstance(adapters, (list, tuple))
        or not adapters
        or len(adapters) > 2
        or any(
            not isinstance(item, str) or item not in _PLANNER_PROJECTION_ADAPTERS
            for item in adapters
        )
        or len(set(adapters)) != len(adapters)
    ):
        raise CapabilityBindingCatalogError(
            "planner_projection.notebook_proposal_adapters is invalid"
        )
    params = _planner_params(value.get("params", []))
    artifacts = value.get("artifact_types")
    if not isinstance(artifacts, Mapping) or not artifacts:
        raise CapabilityBindingCatalogError(
            "planner_projection.artifact_types must be a non-empty object"
        )
    if len(artifacts) > _MAX_PLANNER_ARTIFACTS:
        raise CapabilityBindingCatalogError(
            "planner_projection.artifact_types is too large"
        )
    normalized_artifacts: dict[str, str] = {}
    for artifact_id, artifact_type in artifacts.items():
        if (
            not isinstance(artifact_id, str)
            or not artifact_id.strip()
            or len(artifact_id) > _MAX_PLANNER_TEXT
            or any(ord(char) < 0x20 for char in artifact_id)
            or not isinstance(artifact_type, str)
            or not artifact_type.strip()
            or len(artifact_type) > _MAX_PLANNER_TEXT
            or any(ord(char) < 0x20 for char in artifact_type)
        ):
            raise CapabilityBindingCatalogError(
                "planner_projection.artifact_types contains an invalid entry"
            )
        normalized_artifacts[artifact_id] = artifact_type
    normalized: dict[str, Any] = {
        "key": capability_id,
        "label": label,
        "model_type": model_type,
        "notebook_proposal_adapters": list(adapters),
        "params": deepcopy(params),
        "artifact_types": normalized_artifacts,
    }
    if description is not None:
        normalized["description"] = description
    return MappingProxyType(normalized)


class CapabilityBindingCatalog:
    """Map registered capability ids to immutable, currently usable bindings.

    Construction and registration belong to the trusted Workbench side.  The
    verifier is also trusted and normally delegates to the Capability Factory
    admission controller plus its current validity stores.  Lookup is the
    boundary used by NotebookService, so revocation or validity drift fails
    closed before an Option revision is constructed.
    """

    def __init__(self, *, verifier: CapabilityBindingVerifier) -> None:
        if not callable(verifier):
            raise TypeError("verifier must be callable")
        self._verifier = verifier
        self._bindings = ContentAddressedStore[CapabilityResolutionBinding]()
        self._refs: dict[str, str] = {}
        self._planner_projections: dict[str, Mapping[str, Any]] = {}

    def register(
        self,
        capability_id: str,
        binding: CapabilityResolutionBinding,
        *,
        planner_projection: Mapping[str, Any] | None = None,
    ) -> str:
        capability_id = _capability_id(capability_id)
        if not isinstance(binding, CapabilityResolutionBinding):
            raise CapabilityBindingCatalogError(
                "binding must be a CapabilityResolutionBinding"
            )
        if binding.execution_allowed:
            raise CapabilityBindingCatalogError(
                "capability binding cannot grant execution"
            )
        normalized_projection = _planner_projection(capability_id, planner_projection)
        digest = binding.content_digest
        previous = self._refs.get(capability_id)
        if previous is not None and previous != digest:
            raise CapabilityBindingCatalogError(
                f"capability_id {capability_id!r} is already bound to another digest"
            )
        previous_projection = self._planner_projections.get(capability_id)
        if previous is not None and previous_projection != normalized_projection:
            raise CapabilityBindingCatalogError(
                f"capability_id {capability_id!r} has an immutable planner projection"
            )
        self._verify(binding)
        self._bindings.put(binding)
        self._refs[capability_id] = digest
        if normalized_projection is not None:
            self._planner_projections[capability_id] = normalized_projection
        return digest

    def resolve(
        self,
        capability_id: str,
        *,
        scope_candidates: Sequence[ScopeCandidate] | None = None,
    ) -> CapabilityResolutionBinding | None:
        """Return a current binding, or ``None`` for an unregistered native id."""

        capability_id = _capability_id(capability_id)
        digest = self._refs.get(capability_id)
        if digest is None:
            return None
        try:
            binding = self._bindings.get(digest)
        except KeyError as error:
            raise CapabilityBindingCatalogError(
                f"binding reference for {capability_id!r} is unavailable"
            ) from error
        if scope_candidates is not None and binding.scope_kind != "release_builtin":
            if (binding.scope_kind, binding.scope_ref) not in set(scope_candidates):
                raise CapabilityBindingCatalogError(
                    f"binding scope is not valid for capability {capability_id!r}"
                )
        self._verify(binding)
        return binding

    def require(
        self,
        capability_id: str,
        *,
        scope_candidates: Sequence[ScopeCandidate] | None = None,
    ) -> CapabilityResolutionBinding:
        binding = self.resolve(capability_id, scope_candidates=scope_candidates)
        if binding is None:
            raise CapabilityBindingCatalogError(
                f"no server-owned binding is registered for {capability_id!r}"
            )
        return binding

    def capability_id_for_reference(
        self,
        reference: str,
        *,
        scope_candidates: Sequence[ScopeCandidate] | None = None,
    ) -> str | None:
        """Recover a persisted capability id only after current verification."""

        matches = [
            capability_id
            for capability_id, digest in self._refs.items()
            if digest == reference
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise CapabilityBindingCatalogError(
                "a binding reference resolves to multiple capability ids"
            )
        self.resolve(matches[0], scope_candidates=scope_candidates)
        return matches[0]

    def planner_projections(
        self,
        *,
        scope_candidates: Sequence[ScopeCandidate] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return current, bounded declarations without authority internals."""

        projections: list[dict[str, Any]] = []
        for capability_id in sorted(self._planner_projections):
            projection = self.planner_projection(
                capability_id,
                scope_candidates=scope_candidates,
            )
            if projection is not None:
                projections.append(deepcopy(dict(projection)))
        return tuple(projections)

    def planner_projection(
        self,
        capability_id: str,
        *,
        scope_candidates: Sequence[ScopeCandidate] | None = None,
    ) -> dict[str, Any] | None:
        """Return one current Agent declaration after binding verification."""

        capability_id = _capability_id(capability_id)
        projection = self._planner_projections.get(capability_id)
        if projection is None:
            return None
        binding = self.resolve(capability_id, scope_candidates=scope_candidates)
        if binding is None or "fit" not in binding.allowed_operations:
            raise CapabilityBindingCatalogError(
                f"capability {capability_id!r} is not authorized for the fit operation"
            )
        if NOTEBOOK_OPTION_PLANNER_CONSUMER not in binding.allowed_consumers:
            raise CapabilityBindingCatalogError(
                f"capability {capability_id!r} is not authorized for the "
                f"{NOTEBOOK_OPTION_PLANNER_CONSUMER} consumer"
            )
        return deepcopy(dict(projection))

    def planner_artifact_types(
        self,
        capability_id: str,
        *,
        scope_candidates: Sequence[ScopeCandidate] | None = None,
    ) -> Mapping[str, str] | None:
        """Return dynamic artifact types for a currently registered capability."""

        projection = self.planner_projection(
            capability_id,
            scope_candidates=scope_candidates,
        )
        if projection is None:
            return None
        artifacts = projection["artifact_types"]
        return MappingProxyType(dict(artifacts))

    def assert_current_reference(self, reference: str) -> None:
        """Re-verify a persisted binding digest before a later consumer step."""

        try:
            binding = self._bindings.get(reference)
        except KeyError as error:
            raise CapabilityBindingCatalogError(
                "persisted capability binding reference is unavailable"
            ) from error
        self._verify(binding)

    def _verify(self, binding: CapabilityResolutionBinding) -> None:
        try:
            self._verifier(binding)
        except Exception as error:
            raise CapabilityBindingCatalogError(
                "server-owned capability binding is not currently usable"
            ) from error


__all__ = [
    "CapabilityBindingCatalog",
    "CapabilityBindingCatalogError",
    "CapabilityBindingVerifier",
    "NOTEBOOK_OPTION_PLANNER_CONSUMER",
    "PlannerProjection",
    "ScopeCandidate",
]
