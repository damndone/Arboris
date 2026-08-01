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

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..artifacts import read_json
from ..canonical import canonical_json_v1, sha256_canonical
from ..lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    compute_context_fingerprint,
)

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
    projection_source: dict[str, Any] | None = None
    current_family_head_run_id: str | None = None
    graph_hash: str | None = None
    evidence_pack_refs: list[str] = field(default_factory=list)
    context_profile: str = CONTEXT_PROFILE
    schema_version: str = CONTEXT_SCHEMA_VERSION
    # Optional, bounded output from the domain-memory control plane. It is part
    # of what the Agent saw, but never part of the upstream freshness inputs.
    domain_memory_projection: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Preserve the pre-integration wire shape and hashes for the default
        # off path. The field appears only when the user explicitly enabled
        # memory and a server-owned provider returned a projection.
        if self.domain_memory_projection is None:
            payload.pop("domain_memory_projection", None)
        return payload

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
    "current_family_head_run_id",
    "available_capabilities",
    "user_focus",
    "source_manifest",
)


def freshness_dependency_fingerprint(context: NotebookPlanningContextV1) -> str:
    """Which upstream facts, if changed, force this option to be revalidated.

    Deliberately NOT the whole context. `existing_option_summaries`,
    `evidence_pack_refs`, `budget_report`, `omissions` and `trace_id` describe
    the generation event, not the analysis premises: folding them in would make
    an option stale itself when its siblings or the recommendation's persisted
    evidence subset were written (spec §4.0). Options and recommendation
    decisions pin the exact immutable evidence hashes they consume.
    """

    payload = context.hashable_payload()
    return "fresh1:" + sha256_canonical(
        {field: payload[field] for field in FRESHNESS_DEPENDENCY_FIELDS}
    )


def attach_domain_memory_projection(
    context: NotebookPlanningContextV1,
    projection: dict[str, Any] | None,
) -> NotebookPlanningContextV1:
    """Attach one service-owned, non-authoritative memory projection.

    The compiler accepts only the already-redacted retrieval contract. It does
    not retrieve memory, infer identity, or turn a hint into a capability. The
    explicit field remains inside the generation hash while the freshness
    whitelist above intentionally excludes it.
    """

    if projection is None:
        return context
    if not isinstance(projection, dict):
        raise ValueError("domain memory projection must be an object")
    required = {
        "contract_version",
        "retrieval_ref",
        "scope_ref",
        "outcome",
        "reason",
        "entries",
        "omissions",
        "bounded",
        "preference_ref",
        "memory_authority",
    }
    if set(projection) != required:
        raise ValueError("domain memory projection has an invalid contract shape")
    version = projection["contract_version"]
    if version not in {
        "domain-memory-context-input/v1",
        "domain-memory-context-input/v2",
    }:
        raise ValueError("domain memory projection contract_version is unsupported")
    if projection["memory_authority"] != "non_authoritative":
        raise ValueError("domain memory projection must declare non_authoritative")
    if projection["bounded"] is not True:
        raise ValueError("domain memory projection must be bounded")
    if not isinstance(projection["entries"], list) or not isinstance(projection["omissions"], list):
        raise ValueError("domain memory projection entries and omissions must be lists")
    if len(projection["entries"]) > 32 or len(projection["omissions"]) > 32:
        raise ValueError("domain memory projection exceeds its entry budget")
    entry_fields = {
        "memory_id",
        "revision",
        "content_hash",
        "memory_kind",
        "domain_tags",
        "compact_lesson",
        "recommended_effect_kind",
        "recommended_target_refs",
        "source_summary_refs",
        "match_reason",
        "memory_authority",
    }
    v2_entry_fields = entry_fields | {
        "apply_mode",
        "apply_mode_reason",
        "memory_source",
    }
    for entry in projection["entries"]:
        expected_entry_fields = v2_entry_fields if version == "domain-memory-context-input/v2" else entry_fields
        if not isinstance(entry, dict) or set(entry) != expected_entry_fields:
            raise ValueError("domain memory entry has an invalid contract shape")
        if entry["memory_authority"] != "non_authoritative_hint":
            raise ValueError("domain memory entry must be a non_authoritative_hint")
        if type(entry["revision"]) is not int or entry["revision"] < 1:
            raise ValueError("domain memory entry revision is invalid")
        if not all(isinstance(entry[key], str) and entry[key] for key in (
            "memory_id",
            "content_hash",
            "memory_kind",
            "compact_lesson",
            "recommended_effect_kind",
        )):
            raise ValueError("domain memory entry contains an invalid text field")
        if not all(isinstance(entry[key], list) for key in (
            "domain_tags",
            "recommended_target_refs",
            "source_summary_refs",
            "match_reason",
        )):
            raise ValueError("domain memory entry list fields are invalid")
        if version == "domain-memory-context-input/v2":
            if entry["apply_mode"] not in {"inform_only", "suggest_default"}:
                raise ValueError("domain memory entry apply_mode is invalid")
            if not isinstance(entry["apply_mode_reason"], str) or not entry["apply_mode_reason"]:
                raise ValueError("domain memory entry apply_mode_reason is invalid")
            source = entry["memory_source"]
            if (
                not isinstance(source, dict)
                or set(source) != {"memory_id", "revision"}
                or source["memory_id"] != entry["memory_id"]
                or source["revision"] != entry["revision"]
            ):
                raise ValueError("domain memory entry source is invalid")
    omission_fields = {"memory_id", "revision", "reason"}
    for omission in projection["omissions"]:
        if not isinstance(omission, dict) or set(omission) != omission_fields:
            raise ValueError("domain memory omission has an invalid contract shape")
        if type(omission["revision"]) is not int or omission["revision"] < 1:
            raise ValueError("domain memory omission revision is invalid")
        if not all(isinstance(omission[key], str) and omission[key] for key in omission_fields - {"revision"}):
            raise ValueError("domain memory omission contains an invalid text field")
    if len(canonical_json_v1(projection)) > 8192:
        raise ValueError("domain memory projection exceeds its byte budget")

    attached = replace(context, domain_memory_projection=dict(projection))
    report = dict(context.budget_report)
    if report:
        content_chars = attached.content_chars()
        budget = report.get("content_chars_budget")
        report.update(
            {
                "content_chars": content_chars,
                "within_budget": isinstance(budget, int) and content_chars <= budget,
            }
        )
        attached = replace(attached, budget_report=report)
    return attached


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


def resolve_registered_artifact(
    run_root: Path,
    artifact_id: str,
) -> tuple[str, str | None, dict[str, Any]] | None:
    """Resolve one registered JSON artifact without accepting a caller path.

    The compiler owns artifact-index reads.  Agent tools may request only a
    durable artifact id, then apply their own public result projection to this
    server-resolved payload.  A missing, malformed, escaping, or non-JSON
    artifact remains unavailable rather than becoming an alternate file-read
    capability.
    """

    index = _read_json(run_root / "artifacts_index.json")
    entries = index.get("artifacts") if isinstance(index, dict) else None
    if not isinstance(entries, list):
        return None
    entry = next(
        (
            item
            for item in entries
            if isinstance(item, dict) and item.get("artifact_id") == artifact_id
        ),
        None,
    )
    if entry is None:
        return None
    artifact_type = entry.get("artifact_type")
    artifact_path = entry.get("path")
    if not isinstance(artifact_type, str) or not isinstance(artifact_path, str):
        return None
    try:
        resolved_root = run_root.resolve()
        resolved_path = (run_root / artifact_path).resolve()
        resolved_path.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    if not resolved_path.is_file():
        return None
    payload = _read_json(resolved_path)
    if not isinstance(payload, dict):
        return None
    sha256 = entry.get("sha256")
    return artifact_type, (sha256 if isinstance(sha256, str) else None), payload


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
    "post_estimation": 3,
    "profile": 4,
    "table_export": 5,
    "report": 6,
    "figure": 7,
    "time_series_manifest": 8,
    "processed_data": 9,
    "metadata": 10,
    "time_series_json": 11,
    "raw_data": 12,
}


def _project_lineage(
    graph: Any,
    node_index: Any,
    limit: int,
    *,
    runs_root: Path | None = None,
    active_head_run_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, dict):
        return [], []
    indexed_nodes = node_index if isinstance(node_index, dict) else {}

    def context_fingerprint(node_id: str, node_hash: str | None, forest_key: str) -> str | None:
        if not (runs_root and active_head_run_id and node_hash):
            return None
        try:
            request = NodeWriteOperationRequestV1(
                request_id="notebook_context_compiler",
                operation="rerun",
                context_version="node-operation-context/v1",
                context_fingerprint="pending",
                owner_run_id=active_head_run_id,
                op_node_id=node_id,
                node_hash=node_hash,
                forest_node_key=forest_key,
                owner_resolution="single_candidate",
                active_head_run_id=active_head_run_id,
            )
            return compute_context_fingerprint(runs_root, request)
        except (OSError, ValueError, KeyError):
            return None

    def project_node(key: str, node: dict[str, Any]) -> dict[str, Any]:
        node_id = node.get("id", key)
        indexed = indexed_nodes.get(node_id)
        node_hash = indexed.get("node_hash") if isinstance(indexed, dict) else None
        cas_ref = indexed.get("cas_ref") if isinstance(indexed, dict) else None
        artifact_id = cas_ref.get("artifact") if isinstance(cas_ref, dict) else None
        forest_key = f"{node_hash}::{node_id}" if node_hash else node_id
        projected = {
            "node_id": node_id,
            "kind": node.get("kind"),
            "stage": node.get("stage"),
            "summary": node.get("summary"),
            "trust": node.get("trust"),
            "node_hash": node_hash,
            "forest_node_key": forest_key,
            "context_fingerprint": context_fingerprint(node_id, node_hash, forest_key),
        }
        # ``cas_ref.artifact`` is a repository-relative artifact identity, not
        # a filesystem path.  A typed workflow needs that identity to bind its
        # raw source; withholding it would force a planner to invent one.
        if isinstance(artifact_id, str) and artifact_id:
            projected["artifact_id"] = artifact_id
        # A graph CAS reference may name the original upload rather than the
        # artifact registry entry owned by the dataset stage.  Workflows bind
        # to the latter, because the statistical source resolver validates
        # ownership by registry artifact ID.  Publish that server-resolved ID
        # separately so presentation lineage does not become an execution
        # authority.
        if (
            node.get("kind") == "dataset_stage"
            and node.get("stage") == "source"
            and runs_root is not None
            and active_head_run_id is not None
            and isinstance(node_id, str)
        ):
            try:
                from ..data_operations import resolve_data_column_cast_context

                source = resolve_data_column_cast_context(
                    runs_root.parent,
                    source_run_id=active_head_run_id,
                    source_node_id=node_id,
                )
                source_artifact_id = source.get("source_artifact_id")
                if isinstance(source_artifact_id, str) and source_artifact_id:
                    projected["workflow_artifact_id"] = source_artifact_id
            except (OSError, ValueError, KeyError):
                pass
        return projected

    records = [
        project_node(key, node)
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
    projection_source: dict[str, Any] | None = None,
    current_family_head_run_id: str | None = None,
    dataset_profile_override: dict[str, Any] | None = None,
    evidence_pack_refs: list[str] | None = None,
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
    node_index = _read_json(run_root / "node_index.json") if run_root else None
    graph = _read_json(run_root / "graph.json") if run_root else None
    profile = _read_json(run_root / "staged" / "data_profile.json") if run_root else None
    issues = _read_json(run_root / "errors.json") if run_root else None

    omissions: list[dict[str, Any]] = []
    dataset_profile, dataset_omissions = _project_dataset(profile, budget.dataset_columns)
    if dataset_profile_override is not None:
        dataset_profile = dict(dataset_profile_override)
        dataset_omissions = []
    omissions.extend(dataset_omissions)
    artifact_summaries, artifact_type_counts, artifact_omissions = _project_artifacts(
        index, budget.artifact_summaries
    )
    omissions.extend(artifact_omissions)
    bounded_lineage, lineage_omissions = _project_lineage(
        graph,
        node_index,
        budget.lineage_nodes,
        runs_root=(project_root / "runs") if active_head_run_id else None,
        active_head_run_id=active_head_run_id,
    )
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
        source_manifest.append(_source("errors", active_head_run_id, issues))
    elif projection_source is not None and projection_source.get("kind") == "dataset":
        source_manifest.append(
            {
                "kind": "dataset_upload",
                "id": str(projection_source["upload_sha256"]),
                "sha256": str(projection_source["upload_sha256"]),
            }
        )
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
        projection_source=dict(projection_source) if projection_source is not None else None,
        current_family_head_run_id=current_family_head_run_id,
        graph_hash=("sha256:" + sha256_canonical(graph)) if isinstance(graph, dict) else None,
        evidence_pack_refs=sorted(set(evidence_pack_refs or [])),
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
