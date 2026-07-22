"""Gate 2 — the single bounded, deterministic context path for notebook planning.

Spec: `2026-07-22-v1.8.1-agent-notebook-analysis-option.md` §12, DEC-CTX-001.

Why this exists, concretely: on the v1.8.0 machine acceptance an agent turn
asking for a time-series summary got `tool_output_budget_exceeded` three times.
The cause was never missing retrieval — a single run carries 59 artifacts
(22 KB of index alone, 2.7x one tool's budget) and an 11.5 KB model result. The
fix is bounded projection with explicit omissions, applied once here instead of
patched per recipe.

Two hashes, never one (spec §4.0):

- `generation_context_hash` — what the agent actually saw. Used for trace,
  reproduction and debugging. Includes sibling options, budget report, omissions.
- `freshness_dependency_fingerprint` — which upstream facts, if changed, force
  revalidation. Gates `confirm()`.

Merging them is self-referential: the compiled context contains the notebook's
existing options, so a newly generated option would immediately stale itself and
its siblings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..canonical import canonical_json_v1, sha256_canonical

CONTEXT_PROFILE = "notebook-plan/v1"
CONTEXT_SCHEMA_VERSION = "notebook-planning-context.v1"

# Fields that describe *this compilation event* rather than its content. They
# must never enter the canonical hash: including them would make every
# recompilation look like a changed context (spec §12.4).
INCIDENTAL_FIELDS = frozenset(
    {
        "context_id",
        "compiled_at",
        "trace_id",
        "compile_duration_ms",
    }
)


@dataclass(frozen=True)
class NotebookPlanningContextV1:
    """The typed bundle an agent planning pass consumes. Nothing else."""

    context_id: str
    notebook_id: str
    run_family_id: str
    active_head_run_id: str | None
    analysis_contract: dict[str, Any]
    dataset_profile: dict[str, Any]
    active_run_summary: dict[str, Any]
    bounded_lineage: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    artifact_summaries: list[dict[str, Any]]
    artifact_type_counts: dict[str, int]
    available_capabilities: list[str]
    existing_option_summaries: list[dict[str, Any]]
    user_focus: dict[str, Any]
    source_manifest: list[dict[str, Any]]
    omissions: list[dict[str, Any]]
    budget_report: dict[str, Any]
    compiled_at: str
    trace_id: str | None = None
    compile_duration_ms: int | None = None
    context_profile: str = CONTEXT_PROFILE
    schema_version: str = CONTEXT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def hashable_payload(self) -> dict[str, Any]:
        """The content view: everything except this compilation's own metadata."""

        return {
            key: value
            for key, value in self.to_dict().items()
            if key not in INCIDENTAL_FIELDS
        }

    def canonical_json(self) -> str:
        """Deterministic bytes for the content view.

        Reuses `canonical_json_v1` rather than `json.dumps(sort_keys=True)`:
        the repo already relies on it for NFC normalization and canonical float
        formatting, and a second serializer would eventually disagree with the
        first about some number.
        """

        return canonical_json_v1(self.hashable_payload())


def generation_context_hash(context: NotebookPlanningContextV1) -> str:
    """Hash of what the agent actually saw. Never gates execution (spec §4.0)."""

    return "sha256:" + sha256_canonical(context.hashable_payload())


@dataclass(frozen=True)
class BudgetConfig:
    """Defaults calibrated against the real v1.8.0 ARMA-GARCH run (spec §12.3).

    These are per-section caps, not a global truncation: the sections listed in
    `MUST_KEEP_WHOLE` are never trimmed, because a plan built on a truncated
    analysis contract is worse than no plan.
    """

    dataset_columns: int = 30
    lineage_nodes: int = 10
    artifact_summaries: int = 5
    option_summaries: int = 3
    table_preview_rows: int = 20
    total_chars: int = 24576


MUST_KEEP_WHOLE = (
    "analysis_contract",
    "user_focus",
    "run_family_id",
    "active_head_run_id",
    "blocking_diagnostics",
)


def omission(section: str, *, included: int, available: int, reason: str) -> dict[str, Any]:
    """Record a truncation. Silent loss is the failure mode this prevents."""

    return {
        "section": section,
        "included_count": included,
        "available_count": available,
        "reason": reason,
    }


def project_list(
    items: list[dict[str, Any]],
    *,
    section: str,
    limit: int,
    sort_key: Any = None,
    reason: str = "section_budget_exceeded",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Sort deterministically, take `limit`, and report what was dropped.

    Returns (kept, omissions). Sorting before truncating is what makes the
    result reproducible: an unsorted truncation would keep whichever items the
    filesystem happened to yield first.
    """

    ordered = sorted(items, key=sort_key) if sort_key is not None else list(items)
    if len(ordered) <= limit:
        return ordered, []
    return ordered[:limit], [
        omission(section, included=limit, available=len(ordered), reason=reason)
    ]
