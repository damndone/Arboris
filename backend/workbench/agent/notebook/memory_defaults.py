"""Server-owned, provenance-bearing application of domain-memory defaults.

Memory content may name a registered target, never a field path or a value.
This module is the only adapter from that opaque target reference to an
editable Draft field.  It is deliberately narrow: a valid current memory may
fill one absent default, but cannot override an explicit choice, alter
evidence, or grant execution authority.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from ...contracts.agent.notebook_option import MemoryDefaultSource
from ..recipe_contracts import RECIPE_CONTRACTS
from .proposal import TypedProposal


DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION = "notebook-memory-defaults-v1"
_CONTEXT_V1 = "domain-memory-context-input/v1"
_CONTEXT_V2 = "domain-memory-context-input/v2"
_CONTEXT_V3 = "domain-memory-context-input/v3"


class MemoryDefaultApplicationError(ValueError):
    """A proposed memory default lacks current, exact server-owned provenance."""


@dataclass(frozen=True)
class DefaultTargetContract:
    """One reviewable, server-owned Draft-default target.

    ``required_model_params`` is an applicability prerequisite, not a value to
    derive.  It keeps a memory suggestion from manufacturing the entity column
    needed by clustered Panel inference.
    """

    target_ref: str
    operation_id: str
    model_type: str
    field_path: tuple[str, ...]
    value: str
    target_label: str
    method_risk: str
    restore_value: str | None
    explicit_value_paths: tuple[tuple[str, ...], ...] = ()
    required_model_params: tuple[str, ...] = ()
    required_model_option_fields: tuple[str, ...] = ()

    def applies_to(self, proposal: TypedProposal) -> bool:
        if proposal.operation_id != self.operation_id:
            return False
        params = proposal.changes.get("model_params")
        return isinstance(params, Mapping) and params.get("model_type") == self.model_type

    def require_preconditions(self, proposal: TypedProposal) -> None:
        params = proposal.changes.get("model_params")
        if not isinstance(params, Mapping):
            raise MemoryDefaultApplicationError("memory default model parameters are invalid")
        for name in self.required_model_params:
            value = params.get(name)
            if not isinstance(value, str) or not value:
                raise MemoryDefaultApplicationError(
                    f"memory default target {self.target_ref} requires {name}"
                )
        if self.required_model_option_fields:
            options = params.get("model_options")
            if not isinstance(options, Mapping):
                raise MemoryDefaultApplicationError(
                    f"memory default target {self.target_ref} requires model_options"
                )
            for name in self.required_model_option_fields:
                value = options.get(name)
                if not isinstance(value, str) or not value:
                    raise MemoryDefaultApplicationError(
                        f"memory default target {self.target_ref} requires model_options.{name}"
                    )

    def source(self, *, memory_id: str, revision: int) -> MemoryDefaultSource:
        return MemoryDefaultSource(
            memory_id=memory_id,
            revision=revision,
            target_ref=self.target_ref,
            target_label=self.target_label,
            method_risk=self.method_risk,
            restore_value=self.restore_value,
        )


def _recipe_time_index_targets() -> tuple[DefaultTargetContract, ...]:
    """Derive only published Recipe targets from their authoritative vocabulary.

    A Recipe must publish an exact target reference for every target it permits.
    This prevents a memory registry addition from silently exposing a hidden
    option, and it prevents a provider-facing list from drifting from the
    write authority.
    """

    result: list[DefaultTargetContract] = []
    for recipe_id, recipe in sorted(RECIPE_CONTRACTS.items()):
        # Future Recipes remain closed by default.  Only a Recipe that
        # explicitly publishes target refs opts into this writable boundary.
        if not recipe.memory_target_refs:
            continue
        fields = recipe.parameter_vocabulary.get("fields")
        if isinstance(fields, Mapping):
            semantics = fields.get("time_index_semantics")
        elif isinstance(fields, list):
            semantics = next(
                (
                    item
                    for item in fields
                    if isinstance(item, Mapping) and item.get("path") == "time_index_semantics"
                ),
                None,
            )
        else:
            raise RuntimeError(f"Recipe {recipe_id} has no field vocabulary")
        if not isinstance(semantics, Mapping):
            raise RuntimeError(f"Recipe {recipe_id} has no time-index vocabulary")
        values = semantics.get("allowed_values", semantics.get("enum"))
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise RuntimeError(f"Recipe {recipe_id} has invalid time-index values")
        expected_refs = tuple(
            f"model.genesis.{recipe_id}.time_index_semantics.{value}" for value in values
        )
        if recipe.memory_target_refs != expected_refs:
            raise RuntimeError(f"Recipe {recipe_id} memory targets do not match its vocabulary")
        result.extend(
            DefaultTargetContract(
                target_ref=target_ref,
                operation_id="model.genesis",
                model_type=recipe_id,
                field_path=("model_params", "model_options", "time_index_semantics"),
                value=value,
                target_label="Time-index interpretation",
                method_risk="high",
                restore_value=None,
                required_model_option_fields=recipe.source_option_fields,
            )
            for target_ref, value in zip(recipe.memory_target_refs, values, strict=True)
        )
    return tuple(result)


# The registry, not a memory's free-text lesson, fixes every writable field,
# literal value, scope-independent precondition, and user-visible explanation.
# Additions require a product-contract review and red-first tests.
DEFAULT_TARGET_CONTRACTS: dict[str, DefaultTargetContract] = {
    target.target_ref: target
    for target in (
        DefaultTargetContract(
            target_ref="model.genesis.ols.covariance.robust",
            operation_id="model.genesis",
            model_type="ols",
            field_path=("model_options", "covariance"),
            value="robust",
            target_label="Covariance estimator",
            method_risk="medium",
            restore_value=None,
            explicit_value_paths=(("model_params", "covariance"),),
        ),
        DefaultTargetContract(
            target_ref="model.genesis.ols.covariance.unadjusted",
            operation_id="model.genesis",
            model_type="ols",
            field_path=("model_options", "covariance"),
            value="unadjusted",
            target_label="Covariance estimator",
            method_risk="medium",
            restore_value=None,
            explicit_value_paths=(("model_params", "covariance"),),
        ),
        DefaultTargetContract(
            target_ref="model.genesis.panel_ols.covariance.robust",
            operation_id="model.genesis",
            model_type="panel_ols",
            field_path=("model_options", "covariance"),
            value="robust",
            target_label="Covariance estimator",
            method_risk="medium",
            restore_value=None,
            explicit_value_paths=(("model_params", "covariance"),),
        ),
        DefaultTargetContract(
            target_ref="model.genesis.panel_ols.covariance.unadjusted",
            operation_id="model.genesis",
            model_type="panel_ols",
            field_path=("model_options", "covariance"),
            value="unadjusted",
            target_label="Covariance estimator",
            method_risk="medium",
            restore_value=None,
            explicit_value_paths=(("model_params", "covariance"),),
        ),
        DefaultTargetContract(
            target_ref="model.genesis.panel_ols.covariance.clustered",
            operation_id="model.genesis",
            model_type="panel_ols",
            field_path=("model_options", "covariance"),
            value="clustered",
            target_label="Covariance estimator",
            method_risk="high",
            restore_value=None,
            explicit_value_paths=(("model_params", "covariance"),),
            required_model_params=("entity_col",),
        ),
        *_recipe_time_index_targets(),
    )
}

# Compatibility name for read-only callers of the prior narrow table.
MEMORY_DEFAULT_TARGETS = DEFAULT_TARGET_CONTRACTS
MemoryDefaultTarget = DefaultTargetContract


def _projection_entries(
    projection: Mapping[str, Any] | None,
) -> tuple[tuple[str, tuple[Mapping[str, Any], ...]], ...]:
    if projection is None:
        return ()
    if not isinstance(projection, Mapping):
        raise MemoryDefaultApplicationError("domain memory projection is invalid")
    version = projection.get("contract_version")
    if version in {_CONTEXT_V1, _CONTEXT_V2}:
        # Historic v1/v2 records remain visible hints, but never become
        # executable defaults: they do not carry the immutable vocabulary and
        # source-scope facts needed for an authority decision.
        return ()
    if version != _CONTEXT_V3:
        raise MemoryDefaultApplicationError("domain memory projection version is unsupported")
    if projection.get("memory_authority") != "non_authoritative":
        raise MemoryDefaultApplicationError("domain memory projection authority is invalid")
    project_scope_ref = projection.get("scope_ref")
    if not isinstance(project_scope_ref, str) or not project_scope_ref:
        raise MemoryDefaultApplicationError("domain memory projection scope is invalid")
    entries = projection.get("entries")
    if not isinstance(entries, list):
        raise MemoryDefaultApplicationError("domain memory projection entries are invalid")
    result: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise MemoryDefaultApplicationError("domain memory entry is invalid")
        result.append(entry)
    return ((project_scope_ref, tuple(result)),)


def _entry_source(
    entry: Mapping[str, Any],
    target: DefaultTargetContract,
) -> tuple[MemoryDefaultSource, str]:
    memory_id = entry.get("memory_id")
    revision = entry.get("revision")
    source = entry.get("memory_source")
    source_scope_ref = entry.get("source_scope_ref")
    if (
        not isinstance(memory_id, str)
        or not memory_id
        or type(revision) is not int
        or revision < 1
        or not isinstance(source, Mapping)
        or source.get("memory_id") != memory_id
        or source.get("revision") != revision
        or not isinstance(source_scope_ref, str)
        or not source_scope_ref
    ):
        raise MemoryDefaultApplicationError("memory default source is incomplete")
    # Scope tier is computed by the caller once it has the server-owned project
    # scope.  The integer itself is never persisted as a client-controlled fact.
    return target.source(memory_id=memory_id, revision=revision), source_scope_ref


def _current_suggested_targets(
    proposal: TypedProposal,
    projection: Mapping[str, Any] | None,
    *,
    respect_explicit_value: bool = True,
) -> tuple[tuple[DefaultTargetContract, MemoryDefaultSource, int], ...]:
    candidates: list[tuple[DefaultTargetContract, MemoryDefaultSource, int]] = []
    for project_scope_ref, entries in _projection_entries(projection):
        for entry in entries:
            if (
                entry.get("apply_mode") != "suggest_default"
                or entry.get("apply_mode_reason") != "verifier_current"
                or entry.get("memory_authority") != "non_authoritative_hint"
                or entry.get("vocabulary_version") != DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION
            ):
                continue
            refs = entry.get("recommended_target_refs")
            if not isinstance(refs, list) or any(
                not isinstance(ref, str) or not ref for ref in refs
            ):
                raise MemoryDefaultApplicationError("memory default target refs are invalid")
            for target_ref in refs:
                target = DEFAULT_TARGET_CONTRACTS.get(target_ref)
                if target is None or not target.applies_to(proposal):
                    continue
                # An explicit Agent/user value ends this target's default path
                # before any memory-only applicability check can reject it.
                if respect_explicit_value and _has_explicit_value(proposal, target):
                    continue
                target.require_preconditions(proposal)
                source, source_scope_ref = _entry_source(entry, target)
                # The local runtime creates only project and explicitly opted-in
                # global entries.  The target adapter merely turns the opaque
                # source scope into an ordering fact relative to this project.
                tier = 0 if source_scope_ref == project_scope_ref else 1
                candidates.append((target, source, tier))
    return tuple(candidates)


def _field_value(proposal: TypedProposal, path: tuple[str, ...]) -> Any:
    current: Any = proposal.changes
    for part in path:
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _has_explicit_value(proposal: TypedProposal, target: DefaultTargetContract) -> bool:
    return any(
        _field_value(proposal, path) is not None
        for path in (target.field_path, *target.explicit_value_paths)
    )


def _with_field(
    proposal: TypedProposal,
    target: DefaultTargetContract,
    sources: tuple[MemoryDefaultSource, ...],
) -> TypedProposal:
    def patch(value: Any, path: tuple[str, ...]) -> dict[str, Any]:
        if not path:
            raise MemoryDefaultApplicationError("memory default target path is invalid")
        if value is None:
            current: dict[str, Any] = {}
        elif isinstance(value, Mapping):
            current = dict(value)
        else:
            raise MemoryDefaultApplicationError("memory default target container is invalid")
        head, *tail = path
        if not tail:
            current[head] = target.value
        else:
            current[head] = patch(current.get(head), tuple(tail))
        return current

    changes = patch(proposal.changes, target.field_path)
    return replace(proposal, changes=changes, memory_default_sources=sources)


def apply_memory_defaults(
    proposal: TypedProposal,
    projection: Mapping[str, Any] | None,
) -> TypedProposal:
    """Return a new proposal only for one unambiguous, current target.

    Priority is explicit value, then project scope, then opted-in global scope.
    A conflict within the winning scope has no hidden winner and leaves the
    proposal untouched.  More than one independent field is also refused.
    """

    if not isinstance(proposal, TypedProposal):
        raise MemoryDefaultApplicationError("typed proposal is required")
    if proposal.memory_default_sources:
        validate_memory_default_sources(proposal, projection)
        if any(not source.has_display_metadata for source in proposal.memory_default_sources):
            raise MemoryDefaultApplicationError(
                "legacy memory default provenance cannot be supplied by a new planner"
            )
        return proposal
    candidates = _current_suggested_targets(proposal, projection)
    by_path: dict[
        tuple[str, ...], list[tuple[DefaultTargetContract, MemoryDefaultSource, int]]
    ] = defaultdict(list)
    for target, source, tier in candidates:
        by_path[target.field_path].append((target, source, tier))
    if not by_path:
        return proposal

    applicable: list[tuple[DefaultTargetContract, tuple[MemoryDefaultSource, ...]]] = []
    for path, items in sorted(by_path.items()):
        target = items[0][0]
        if _has_explicit_value(proposal, target):
            continue
        winning_tier = min(tier for _target, _source, tier in items)
        tier_items = [item for item in items if item[2] == winning_tier]
        values = {item[0].value for item in tier_items}
        if len(values) != 1:
            continue
        target = tier_items[0][0]
        sources = tuple(
            sorted(
                (source for _target, source, _tier in tier_items),
                key=lambda item: (item.memory_id, item.revision, item.target_ref),
            )
        )
        applicable.append((target, sources))
    if len(applicable) != 1:
        return proposal
    target, sources = applicable[0]
    return _with_field(proposal, target, sources)


def validate_memory_default_sources(
    proposal: TypedProposal,
    projection: Mapping[str, Any] | None,
) -> None:
    """Prove a persisted memory-default source still equals a current target."""

    if not isinstance(proposal, TypedProposal):
        raise MemoryDefaultApplicationError("typed proposal is required")
    sources = proposal.memory_default_sources
    if not sources:
        return
    available = {
        (source.memory_id, source.revision, source.target_ref): (target, source)
        for target, source, _tier in _current_suggested_targets(
            proposal,
            projection,
            respect_explicit_value=False,
        )
    }
    for source in sources:
        key = (source.memory_id, source.revision, source.target_ref)
        resolved = available.get(key)
        if resolved is None:
            raise MemoryDefaultApplicationError("memory default source is not current")
        target, expected_source = resolved
        if source.has_display_metadata and source != expected_source:
            raise MemoryDefaultApplicationError("memory default source metadata is not server-owned")
        if _field_value(proposal, target.field_path) != target.value:
            raise MemoryDefaultApplicationError("memory default source does not match the proposal")


__all__ = [
    "DEFAULT_TARGET_CONTRACTS",
    "DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION",
    "MEMORY_DEFAULT_TARGETS",
    "DefaultTargetContract",
    "MemoryDefaultApplicationError",
    "MemoryDefaultTarget",
    "apply_memory_defaults",
    "validate_memory_default_sources",
]
