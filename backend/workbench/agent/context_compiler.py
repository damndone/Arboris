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

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..artifacts import read_json
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

    def content_chars(self) -> int:
        """Size of the bundle excluding the budget report itself.

        See the note where budget_report is filled in: a meter that includes
        its own reading is not a fixpoint.
        """

        payload = {k: v for k, v in self.hashable_payload().items() if k != "budget_report"}
        return len(canonical_json_v1(payload))

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


# The freshness whitelist, spelled out rather than derived by subtraction.
# Subtracting a blacklist would silently enrol every field added later, and the
# first such field to be option-derived would resurrect the self-reference bug.
FRESHNESS_DEPENDENCY_FIELDS = (
    "analysis_contract",
    "dataset_profile",
    "run_family_id",
    "active_head_run_id",
    "available_capabilities",
    "user_focus",
    "source_manifest",
)


def freshness_dependency_fingerprint(context: NotebookPlanningContextV1) -> str:
    """Which upstream facts, if changed, force this option to be revalidated.

    Deliberately NOT the whole context. `existing_option_summaries`,
    `budget_report`, `omissions` and `trace_id` describe the generation event,
    not the analysis premises: folding them in would make an option stale itself
    the moment its siblings were written (spec §4.0).
    """

    payload = context.hashable_payload()
    return "fresh1:" + sha256_canonical(
        {field: payload[field] for field in FRESHNESS_DEPENDENCY_FIELDS}
    )


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


# ----------------------------------------------------------------------
# Compilation
# ----------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        return read_json(path)
    except (FileNotFoundError, OSError, ValueError):
        return None


def _digest(value: Any) -> str:
    return "sha256:" + sha256_canonical(value)


def _source(kind: str, source_id: str, payload: Any) -> dict[str, Any]:
    """One manifest entry: what was read, and a hash of exactly what was read."""

    return {"kind": kind, "id": source_id, "hash": _digest(payload)}


def _project_dataset(profile: Any, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(profile, dict):
        return {}, []
    columns = profile.get("columns")
    if not isinstance(columns, list):
        return dict(profile), []
    kept, omissions = project_list(
        [c for c in columns if isinstance(c, dict)],
        section="dataset_profile.columns",
        limit=limit,
        sort_key=lambda c: str(c.get("name", "")),
    )
    projected = {k: v for k, v in profile.items() if k != "columns"}
    projected["columns"] = kept
    return projected, omissions


def _project_artifacts(
    index: Any, limit: int
) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    """Count every artifact by type; summarize only a few in detail.

    The measured reason for the split (spec §12.3): a real run carries 59
    artifacts, 36 of them mechanical per-series JSON. Summarizing 5 of 59 and
    saying nothing about the rest hides most of what the run produced; counting
    all of them costs almost nothing and answers "what exists" directly.
    """

    artifacts = index.get("artifacts") if isinstance(index, dict) else None
    if not isinstance(artifacts, list):
        return [], {}, []
    records = [a for a in artifacts if isinstance(a, dict)]
    counts: dict[str, int] = {}
    for record in records:
        artifact_type = str(record.get("artifact_type", "unknown"))
        counts[artifact_type] = counts.get(artifact_type, 0) + 1

    kept, omissions = project_list(
        records,
        section="artifact_summaries",
        limit=limit,
        sort_key=lambda a: (
            _ARTIFACT_TYPE_RANK.get(str(a.get("artifact_type", "")), len(_ARTIFACT_TYPE_RANK)),
            str(a.get("step", "")),
            str(a.get("artifact_id", "")),
        ),
    )
    summaries = [
        {
            "artifact_id": a.get("artifact_id"),
            "artifact_type": a.get("artifact_type"),
            "step": a.get("step"),
        }
        for a in kept
    ]
    return summaries, dict(sorted(counts.items())), omissions


# Which artifacts a planner needs to see in detail. Model results and
# diagnostics carry the conclusions; raw snapshots and per-series files are
# adequately represented by their type count.
_ARTIFACT_TYPE_RANK = {
    "model_result": 0,
    "model_diagnostic": 1,
    "statistical_test": 2,
    "profile": 3,
    "table_export": 4,
    "report": 5,
    "figure": 6,
    "time_series_manifest": 7,
    "processed_data": 8,
    "metadata": 9,
    "time_series_json": 10,
    "raw_data": 11,
}


def _project_lineage(graph: Any, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, dict):
        return [], []
    records = [
        {
            "node_id": node.get("id", key),
            "kind": node.get("kind"),
            "stage": node.get("stage"),
            "summary": node.get("summary"),
            "trust": node.get("trust"),
        }
        for key, node in nodes.items()
        if isinstance(node, dict)
    ]
    return project_list(
        records,
        section="bounded_lineage",
        limit=limit,
        sort_key=lambda n: (str(n.get("stage") or ""), str(n.get("node_id") or "")),
    )


def _project_diagnostics(
    issues: Any, supplied: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Blocking diagnostics are never truncated (spec §12.3 must-keep list).

    Non-blocking ones are sorted by severity then code so the order is stable,
    but they are not dropped either: diagnostics are small, and losing the one
    that explains why a model is invalid would be the worst possible omission.
    """

    records: list[dict[str, Any]] = []
    if isinstance(issues, dict) and isinstance(issues.get("issues"), list):
        records.extend(i for i in issues["issues"] if isinstance(i, dict))
    if supplied:
        records.extend(supplied)
    return sorted(
        records,
        key=lambda d: (
            0 if str(d.get("severity", "")) == "blocking" else 1,
            str(d.get("code", "")),
        ),
    )


def _project_run_summary(manifest: Any) -> dict[str, Any]:
    """A projection, never the raw model result.

    Measured: `model_results/*.json` is 11.5 KB on the real run -- one file
    already exceeds a single tool's 8192-char budget.
    """

    if not isinstance(manifest, dict):
        return {}
    return {
        key: manifest.get(key)
        for key in ("run_id", "mode", "status", "y", "x", "requested_model_type")
        if key in manifest
    }


def compile_notebook_planning_context(
    project_root: Path | str,
    *,
    notebook_id: str,
    run_family_id: str,
    active_head_run_id: str | None,
    analysis_contract: dict[str, Any],
    user_focus: dict[str, Any] | None = None,
    existing_option_summaries: list[dict[str, Any]] | None = None,
    available_capabilities: list[str] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
    budget: BudgetConfig | None = None,
    trace_id: str | None = None,
) -> NotebookPlanningContextV1:
    """The one path from project state to what a planning agent sees.

    Deterministic by construction: every section is sorted before it is cut, no
    absolute path enters the payload, and the compilation's own metadata is
    excluded from the hash.
    """

    project_root = Path(project_root)
    budget = budget or BudgetConfig()
    run_root = (
        project_root / "runs" / active_head_run_id if active_head_run_id else None
    )

    manifest = _read_json(run_root / "run_manifest.json") if run_root else None
    index = _read_json(run_root / "artifacts_index.json") if run_root else None
    graph = _read_json(run_root / "graph.json") if run_root else None
    profile = _read_json(run_root / "staged" / "data_profile.json") if run_root else None
    issues = _read_json(run_root / "errors.json") if run_root else None

    omissions: list[dict[str, Any]] = []
    dataset_profile, dataset_omissions = _project_dataset(profile, budget.dataset_columns)
    omissions.extend(dataset_omissions)
    artifact_summaries, artifact_type_counts, artifact_omissions = _project_artifacts(
        index, budget.artifact_summaries
    )
    omissions.extend(artifact_omissions)
    bounded_lineage, lineage_omissions = _project_lineage(graph, budget.lineage_nodes)
    omissions.extend(lineage_omissions)
    options, option_omissions = project_list(
        list(existing_option_summaries or []),
        section="existing_option_summaries",
        limit=budget.option_summaries,
        sort_key=lambda o: (
            str(o.get("batch", "")),
            int(o.get("rank", 0) or 0),
            str(o.get("option_id", "")),
        ),
    )
    omissions.extend(option_omissions)

    source_manifest: list[dict[str, Any]] = []
    if active_head_run_id:
        source_manifest.append(_source("run", active_head_run_id, manifest))
        source_manifest.append(_source("artifact_index", active_head_run_id, index))
        source_manifest.append(_source("graph", active_head_run_id, graph))
        source_manifest.append(_source("dataset_profile", active_head_run_id, profile))
    source_manifest.sort(key=lambda entry: (entry["kind"], entry["id"]))

    context = NotebookPlanningContextV1(
        context_id=f"ctx_{uuid4().hex}",
        notebook_id=notebook_id,
        run_family_id=run_family_id,
        active_head_run_id=active_head_run_id,
        analysis_contract=dict(analysis_contract),
        dataset_profile=dataset_profile,
        active_run_summary=_project_run_summary(manifest),
        bounded_lineage=bounded_lineage,
        diagnostics=_project_diagnostics(issues, diagnostics),
        artifact_summaries=artifact_summaries,
        artifact_type_counts=artifact_type_counts,
        available_capabilities=sorted(available_capabilities or []),
        existing_option_summaries=options,
        user_focus=dict(user_focus or {}),
        source_manifest=source_manifest,
        omissions=omissions,
        budget_report={},
        compiled_at=datetime.now(timezone.utc).isoformat(),
        trace_id=trace_id,
    )

    # The meter cannot measure a payload that contains the meter: writing the
    # size into budget_report changes the size. So `content_chars` measures the
    # bundle *without* budget_report, and the name says so rather than calling
    # an approximation "total". The report itself is a fixed handful of fields.
    return replace(
        context,
        budget_report={
            "content_chars": context.content_chars(),
            "content_chars_budget": budget.total_chars,
            "within_budget": context.content_chars() <= budget.total_chars,
            "sections_truncated": sorted({o["section"] for o in omissions}),
        },
    )


def notebook_planning_workbench_context(
    context: NotebookPlanningContextV1,
) -> dict[str, Any]:
    """The model-facing projection, ready for `ContextBuilder(workbench_context=...)`.

    `context_id` and `generation_context_hash` ride alongside the content rather
    than inside it: the agent needs them to cite which bundle it answered from,
    but folding them into the hashed content would make the hash depend on
    itself.

    The omissions travel with the content on purpose. An agent told "here are 5
    artifacts" will reason as if there are five; an agent told "here are 5 of 59,
    36 of which are per-series JSON" can ask for the right thing instead.
    """

    return {
        "context_profile": context.context_profile,
        "context_id": context.context_id,
        "generation_context_hash": generation_context_hash(context),
        "freshness_dependency_fingerprint": freshness_dependency_fingerprint(context),
        "omissions": list(context.omissions),
        "artifact_type_counts": dict(context.artifact_type_counts),
        "budget_report": dict(context.budget_report),
        "content": {
            key: value
            for key, value in context.hashable_payload().items()
            if key not in {"omissions", "artifact_type_counts", "budget_report"}
        },
    }
