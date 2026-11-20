"""Notebook planning context from domain memory: projection, recipe-default and generic retrievals and their merge."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
import json
from pathlib import Path
from typing import Any
from fastapi import Request

from ..canonical import canonical_json_v1
from ..agent.context_compiler import NotebookPlanningContextV1
from ..agent.notebook.memory_defaults import (
    DEFAULT_TARGET_CONTRACTS,
    DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
)
from ..agent.recipe_contracts import RECIPE_CONTRACTS
from ..agent.notebook import NotebookService
from ..domain_memory.local_runtime import (
    LocalDomainMemoryRuntime,
    LocalDomainMemoryRuntimeError,
)
from ..domain_memory.retrieval import DomainMemoryRetrieval
from ..api_errors import WorkbenchAPIError


_DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES = 8


_DOMAIN_MEMORY_CONTEXT_MAX_BYTES = 8192


_DOMAIN_MEMORY_CONTEXT_MAX_OMISSIONS = 32


_RECIPE_DEFAULT_SCAN_INCOMPLETE_REASONS = frozenset({"entry_budget", "byte_budget"})


def _domain_memory_projection(
    request: Request | None,
    root: Path,
    service: NotebookService,
    notebook_id: str,
    *,
    context: NotebookPlanningContextV1 | None = None,
) -> dict[str, Any] | None:
    """Ask only the server-owned provider for an already-bounded projection.

    Compilation is deliberately complete before this call.  A deployment
    provider may therefore build/read a Project/RunFamily index from the
    canonical Notebook context before it retrieves approved cross-project
    hints; the memory result cannot retroactively change capability inputs or
    freshness dependencies.
    """

    provider = getattr(request.app.state, "domain_memory_context_provider", None) if request else None
    runtime = getattr(request.app.state, "domain_memory_runtime", None) if request else None
    if isinstance(runtime, LocalDomainMemoryRuntime):
        if context is None:
            raise WorkbenchAPIError(
                status_code=503,
                code="DOMAIN_MEMORY_CONTEXT_UNAVAILABLE",
                message="A compiled Notebook context is required before memory retrieval.",
            )
        try:
            now = datetime.now(timezone.utc).isoformat()
            facts = _domain_memory_facts(context)
            generic_result = runtime.retrieve_for_project(
                root,
                facts=facts,
                now=now,
                max_entries=_DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES,
                max_bytes=_DOMAIN_MEMORY_CONTEXT_MAX_BYTES,
                vocabulary_version=DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
            )
            if generic_result.outcome == "not_used":
                return None
            generic_result = _generic_fallback_retrieval(generic_result)
            default_results = [
                _registered_default_retrieval(
                    runtime.retrieve_for_project(
                        root,
                        facts={
                            **facts,
                            "analysis_family": recipe_id,
                            "model_family": recipe.model_family,
                        },
                        now=now,
                        max_entries=_DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES,
                        max_bytes=_DOMAIN_MEMORY_CONTEXT_MAX_BYTES,
                        vocabulary_version=DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
                    ),
                    model_type=recipe_id,
                    target_refs=frozenset(recipe.memory_target_refs),
                )
                for recipe_id, recipe in sorted(RECIPE_CONTRACTS.items())
                if _recipe_default_targets_are_published(recipe_id, recipe.memory_target_refs)
            ]
            native_default_model_types = sorted(
                {
                    target.model_type
                    for target_ref, target in DEFAULT_TARGET_CONTRACTS.items()
                    if not _is_published_recipe_default_target(target_ref)
                }
            )
            default_results.extend(
                _registered_default_retrieval(
                    runtime.retrieve_for_project(
                        root,
                        facts={
                            **facts,
                            "analysis_family": model_type,
                            "model_family": model_type,
                        },
                        now=now,
                        max_entries=_DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES,
                        max_bytes=_DOMAIN_MEMORY_CONTEXT_MAX_BYTES,
                        vocabulary_version=DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
                    ),
                    model_type=model_type,
                    target_refs=frozenset(
                        target_ref
                        for target_ref, target in DEFAULT_TARGET_CONTRACTS.items()
                        if target.model_type == model_type
                        and not _is_published_recipe_default_target(target_ref)
                    ),
                )
                for model_type in native_default_model_types
            )
            result = _merge_recipe_default_retrievals(
                generic_result=generic_result,
                recipe_results=default_results,
            )
        except LocalDomainMemoryRuntimeError as error:
            raise WorkbenchAPIError(
                status_code=503,
                code="DOMAIN_MEMORY_UNAVAILABLE",
                message="The local memory runtime is unavailable.",
            ) from error
        # Default-off is intentionally invisible to planning. The absence of a
        # projection means no memory participated; an enabled-but-empty library
        # remains observable as a bounded empty projection.
        return result.to_context_projection()
    if provider is None:
        # A legacy service object has no local preference authority. Do not let
        # its mere presence implicitly turn memory on for every project.
        return None
    projection = provider(
        request=request,
        project_root=root,
        notebook_service=service,
        notebook_id=notebook_id,
        context=context,
    )
    if projection is not None and not isinstance(projection, dict):
        raise WorkbenchAPIError(
            status_code=503,
            code="DOMAIN_MEMORY_PROVIDER_INVALID",
            message="The server-owned domain-memory provider returned an invalid projection.",
        )
    return projection


def _domain_memory_facts(context: NotebookPlanningContextV1) -> dict[str, Any]:
    """Project a small, server-compiled applicability vocabulary for retrieval."""

    facts: dict[str, Any] = {}
    for source in (context.analysis_contract, context.user_focus):
        for key in ("analysis_family", "model_family", "goal", "domain", "data_kind"):
            value = source.get(key)
            if isinstance(value, str) and value and len(value) <= 128:
                facts.setdefault(key, value)
    return facts


def _recipe_default_targets_are_published(
    recipe_id: str,
    target_refs: tuple[str, ...],
) -> bool:
    """Admit only a Recipe's exact registry-owned suggestion surface.

    The planner has not selected a Recipe yet, so this bridge may broaden the
    *server-derived lookup facts* to each published Recipe.  It must not turn
    an opaque memory target into a writable field or accept a target that the
    current Recipe did not publish.
    """

    if not target_refs:
        return False
    for target_ref in target_refs:
        target = DEFAULT_TARGET_CONTRACTS.get(target_ref)
        if target is None or target.model_type != recipe_id:
            return False
    return True


def _registered_default_retrieval(
    result: DomainMemoryRetrieval,
    *,
    model_type: str,
    target_refs: frozenset[str],
) -> DomainMemoryRetrieval:
    """Keep only current default targets owned by one model family.

    A generic memory predicate can truthfully match a server-derived family
    fact while its target reference belongs to a different family. Such a
    hint must never enter this preselection bridge: final proposal application
    would reject it too, but filtering it here prevents irrelevant model
    advice from influencing the provider before a model is chosen.
    """

    # A retrieval truncation hides a candidate value.  Keeping the visible
    # entries would make a high-risk default depend on result ordering, so the
    # exact Recipe path fails closed until the candidate set is complete.
    if any(
        omission.reason in _RECIPE_DEFAULT_SCAN_INCOMPLETE_REASONS
        for omission in result.omissions
    ):
        return replace(
            result,
            outcome="empty",
            reason="recipe_default_scan_incomplete",
            entries=(),
        )

    kept = []
    for entry in result.entries:
        refs = entry.recommended_target_refs
        is_current_default = (
            entry.apply_mode == "suggest_default"
            and entry.apply_mode_reason == "verifier_current"
            and entry.vocabulary_version == DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION
        )
        is_exact_recipe_target = is_current_default and bool(refs) and all(
            ref in target_refs
            and (target := DEFAULT_TARGET_CONTRACTS.get(ref)) is not None
            and target.model_type == model_type
            for ref in refs
        )
        if is_exact_recipe_target:
            kept.append(entry)
    if len(kept) == len(result.entries):
        return result
    return replace(
        result,
        outcome="used" if kept else "empty",
        reason="retrieved" if kept else "no_eligible_memory",
        entries=tuple(kept),
    )


def _recipe_default_retrieval(
    result: DomainMemoryRetrieval,
    *,
    recipe_id: str,
    target_refs: frozenset[str],
) -> DomainMemoryRetrieval:
    """Compatibility wrapper for Recipe-specific callers and tests."""

    return _registered_default_retrieval(
        result, model_type=recipe_id, target_refs=target_refs
    )


def _is_published_recipe_default_target(target_ref: str) -> bool:
    """Return whether a target belongs to a Recipe-specific default surface."""

    target = DEFAULT_TARGET_CONTRACTS.get(target_ref)
    if target is None:
        return False
    recipe = RECIPE_CONTRACTS.get(target.model_type)
    return recipe is not None and target_ref in recipe.memory_target_refs


def _is_published_default_target(target_ref: str) -> bool:
    """Return whether a target belongs to the server-owned default registry."""

    return target_ref in DEFAULT_TARGET_CONTRACTS


def _generic_fallback_retrieval(
    result: DomainMemoryRetrieval,
) -> DomainMemoryRetrieval:
    """Keep generic hints, but never leak Recipe default targets through them.

    A Recipe target is admissible only through its own lookup, where current
    verifier status, target ownership, and scan completeness have been
    checked.  This preserves ordinary generic-memory guidance (including OLS
    defaults outside a Recipe) without letting a declared or guessed family
    bypass the Recipe-specific authority boundary.
    """

    entries = tuple(
        entry
        for entry in result.entries
        if not any(
            _is_published_default_target(target_ref)
            for target_ref in entry.recommended_target_refs
        )
    )
    if len(entries) == len(result.entries):
        return result
    return replace(
        result,
        outcome="used" if entries else "empty",
        reason="retrieved" if entries else "no_eligible_memory",
        entries=entries,
    )


def _merge_recipe_default_retrievals(
    *,
    generic_result: DomainMemoryRetrieval,
    recipe_results: list[DomainMemoryRetrieval],
) -> DomainMemoryRetrieval:
    """Merge a bounded default preselection without expanding omissions.

    The generic lookup remains the public explanation of memory omissions.
    Per-Recipe lookups exist only to make an exact registered default visible
    before the provider selects a model, so their internal predicate and
    entry-budget misses must not multiply the public context packet. Exact
    Recipe defaults take the bounded entry slots first; generic hints retain
    their historic fallback role and cannot displace one.
    """

    entries_with_origin: list[tuple[Any, str | None]] = []
    selected_ids: set[tuple[str, int]] = set()
    used_bytes = 0

    def encoded_size(entry: Any) -> int:
        return len(
            json.dumps(
                entry.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )

    # A Recipe result is an atomic default candidate group.  Filling the
    # global entry budget one entry at a time could hide a later conflicting
    # target from the same Recipe, so admit the group whole or not at all.
    for result in recipe_results:
        group: list[Any] = []
        group_ids: set[tuple[str, int]] = set()
        group_bytes = 0
        for entry in result.entries:
            identity = (entry.memory_id, entry.revision)
            if identity in selected_ids or identity in group_ids:
                group = []
                break
            entry_bytes = encoded_size(entry)
            if entry_bytes > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES:
                group = []
                break
            group_ids.add(identity)
            group.append(entry)
            group_bytes += entry_bytes
        if not group:
            continue
        recipe_id = _default_model_type_for_entry(group[0])
        if recipe_id is None or any(
            _default_model_type_for_entry(entry) != recipe_id for entry in group
        ):
            continue
        if (
            len(entries_with_origin) + len(group) > _DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES
            or used_bytes + group_bytes > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES
        ):
            continue
        selected_ids.update(group_ids)
        entries_with_origin.extend((entry, recipe_id) for entry in group)
        used_bytes += group_bytes

    # Generic entries have no published Recipe-default target, so they cannot
    # materialize a model setting and may use any remaining bounded slots.
    for entry in generic_result.entries:
        identity = (entry.memory_id, entry.revision)
        if identity in selected_ids or len(entries_with_origin) >= _DOMAIN_MEMORY_CONTEXT_MAX_ENTRIES:
            continue
        entry_bytes = encoded_size(entry)
        if (
            entry_bytes > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES
            or used_bytes + entry_bytes > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES
        ):
            continue
        selected_ids.add(identity)
        entries_with_origin.append((entry, None))
        used_bytes += entry_bytes
    omissions = list(
        omission
        for omission in generic_result.omissions
        if (omission.memory_id, omission.revision) not in selected_ids
    )[:_DOMAIN_MEMORY_CONTEXT_MAX_OMISSIONS]

    def result() -> DomainMemoryRetrieval:
        entries = tuple(entry for entry, _origin in entries_with_origin)
        return DomainMemoryRetrieval(
            retrieval_ref=generic_result.retrieval_ref,
            scope_ref=generic_result.scope_ref,
            outcome="used" if entries else "empty",
            reason="retrieved" if entries else "no_eligible_memory",
            entries=entries,
            omissions=tuple(omissions),
            bounded=True,
            preference_ref=generic_result.preference_ref,
        )

    # ``LocalDomainMemoryRuntime`` budgets entry bytes, while this API projects
    # an envelope that also contains identifiers/reasons for omitted entries.
    # Enforce the real, complete context budget here.  Omission detail is
    # discarded first; if entries must be removed, generic hints are weakest.
    # Recipe defaults are removed as an entire Recipe group, never partially,
    # so a byte budget cannot manufacture a false unambiguous default.
    while (
        len(canonical_json_v1(result().to_context_projection()).encode("utf-8"))
        > _DOMAIN_MEMORY_CONTEXT_MAX_BYTES
    ):
        if omissions:
            omissions.pop()
            continue
        generic_index = next(
            (
                index
                for index in range(len(entries_with_origin) - 1, -1, -1)
                if entries_with_origin[index][1] is None
            ),
            None,
        )
        if generic_index is not None:
            entries_with_origin.pop(generic_index)
            continue
        recipe_ids = [
            origin
            for _entry, origin in entries_with_origin
            if origin is not None
        ]
        if not recipe_ids:
            break
        recipe_id = recipe_ids[-1]
        entries_with_origin[:] = [
            (entry, origin)
            for entry, origin in entries_with_origin
            if origin != recipe_id
        ]
    return result()


def _default_model_type_for_entry(entry: Any) -> str | None:
    """Return one server-registered model family for an exact default entry."""

    refs = getattr(entry, "recommended_target_refs", ())
    if not isinstance(refs, tuple):
        return None
    recipe_ids = {
        DEFAULT_TARGET_CONTRACTS[target_ref].model_type
        for target_ref in refs
        if _is_published_default_target(target_ref)
    }
    if len(recipe_ids) != 1:
        return None
    return next(iter(recipe_ids))


def _recipe_id_for_default_entry(entry: Any) -> str | None:
    """Return a published Recipe id only for an exact Recipe default entry."""

    model_type = _default_model_type_for_entry(entry)
    return model_type if model_type in RECIPE_CONTRACTS else None
