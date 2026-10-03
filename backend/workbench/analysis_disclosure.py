"""The analysis path behind a report, as the report discloses it.

A report shows the results someone chose to show. The disclosure shows what
else was done to the same data: how many tests were run, how many models were
estimated, which data and metadata changes were made and which runs were
deleted -- by the user or the Agent, and who authorized each. It is written
by Workbench from the analysis ledger, never by the language model.

Scope: every ledger entry about a run whose source upload is the one behind
the report's run. That is "the same data": forks, reruns, derived datasets
and Agent workflows on it, and nothing from unrelated datasets in the project.

Whether exported reports include it, and at what detail, is a project setting
(``workbench/report_disclosure.json``). It is on by default.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from . import analysis_ledger

Detail = Literal["summary", "full"]
DEFAULT_SETTINGS: dict[str, Any] = {"include_in_exports": True, "detail": "summary"}
_FULL_LIST_LIMIT = 200


def settings_path(project_root: Path | str) -> Path:
    return Path(project_root) / "workbench" / "report_disclosure.json"


def read_settings(project_root: Path | str) -> dict[str, Any]:
    path = settings_path(project_root)
    if not path.is_file():
        return dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)
    return {
        "include_in_exports": bool(stored.get("include_in_exports", True)),
        "detail": "full" if stored.get("detail") == "full" else "summary",
    }


def write_settings(project_root: Path | str, *, include_in_exports: bool, detail: Detail) -> dict[str, Any]:
    path = settings_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = {"include_in_exports": include_in_exports, "detail": detail}
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return value


def disclosure(project_root: Path | str, run_id: str) -> dict[str, Any]:
    root = Path(project_root)
    source = analysis_ledger.upload_sha(root, run_id)
    cache: dict[str, str | None] = {}

    def same_data(entry: Mapping[str, Any]) -> bool:
        if source is not None and entry.get("source_upload_sha256") == source:
            return True
        if not any(entry.get(key) for key in ("run_id", "produced_run_id", "source_upload_sha256")):
            # Project-wide actions -- such as changing this disclosure setting
            # -- concern every report in the project.
            return True
        for key in ("run_id", "produced_run_id"):
            value = entry.get(key)
            if not value:
                continue
            if value not in cache:
                cache[value] = analysis_ledger.upload_sha(root, str(value))
            if source is not None and cache[value] == source:
                return True
            if source is None and value == run_id:
                return True
        return False

    entries = [entry for entry in analysis_ledger.read(root) if same_data(entry)]
    completed = [entry for entry in entries if entry.get("status") == "completed"]
    step_counts: Counter[str] = Counter()
    tests_by_authority: Counter[str] = Counter()
    for entry in completed:
        for step in entry.get("steps") or ():
            # A by-group step ran one analysis per group.
            step_counts[str(step.get("category"))] += int(step.get("tests") or 1)
        # A model run estimated by group is one model per estimated group; how
        # many is known only once the run has executed, so it is read here.
        groups = _estimated_groups(root, entry.get("produced_run_id"))
        if groups > 1:
            step_counts["model"] += groups - 1
        who = "agent_without_confirmation" if entry.get("authorized_by") == "read_only_policy" else (
            "agent_confirmed_by_user" if entry.get("actor") == "agent" else "user"
        )
        tests_by_authority[who] += int(entry.get("inferential_steps") or 0)
    return {
        "run_id": run_id,
        "source_upload_sha256": source,
        "first_at": entries[0]["at"] if entries else None,
        "last_at": entries[-1]["at"] if entries else None,
        "counts": {
            "inferential_tests": step_counts["inferential"],
            "descriptive_analyses": step_counts["descriptive"],
            "models": step_counts["model"],
            "data_changes": step_counts["data_change"],
            "metadata_changes": step_counts["metadata_change"],
            "run_deletions": step_counts["deletion"],
            "failed_actions": len(entries) - len(completed),
        },
        "inferential_tests_by": dict(tests_by_authority),
        "changes": [_line(entry) for entry in completed if entry.get("changes_data")],
        "entries": [_line(entry) for entry in entries[-_FULL_LIST_LIMIT:]],
        "entries_omitted": max(len(entries) - _FULL_LIST_LIMIT, 0),
        "settings": read_settings(root),
    }


def _estimated_groups(root: Path, run_id: Any) -> int:
    if not run_id:
        return 0
    path = Path(root) / "runs" / str(run_id) / "model_results" / "collections" / "by_group.json"
    try:
        collection = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    except (OSError, ValueError):
        return 0
    members = collection.get("members") if isinstance(collection, dict) else None
    return sum(1 for member in members or () if isinstance(member, dict) and member.get("status") == "estimated")


def _who(entry: Mapping[str, Any]) -> str:
    if entry.get("authorized_by") == "read_only_policy":
        return "Agent (read-only, no confirmation)"
    return "Agent (confirmed by user)" if entry.get("actor") == "agent" else "User"


def _line(entry: Mapping[str, Any]) -> dict[str, Any]:
    steps: Sequence[Mapping[str, Any]] = entry.get("steps") or ()
    return {
        "at": entry.get("at"),
        "who": _who(entry),
        "status": entry.get("status"),
        "what": ", ".join(str(step.get("operation_id")) for step in steps) or str(entry.get("source")),
        "categories": sorted({str(step.get("category")) for step in steps}),
        "run_id": entry.get("run_id"),
        "produced_run_id": entry.get("produced_run_id"),
        "summary": entry.get("summary") or "",
    }


def markdown(value: Mapping[str, Any], *, detail: Detail) -> str:
    counts = value["counts"]
    by = value.get("inferential_tests_by") or {}
    lines = [
        "## Analysis path disclosure",
        "",
        "Recorded by Workbench from its analysis ledger for the data behind this report"
        + (f" (source upload {str(value['source_upload_sha256'])[:12]})" if value.get("source_upload_sha256") else "")
        + (f", {value['first_at'][:10]} to {value['last_at'][:10]}." if value.get("first_at") else "."),
        "",
        f"- Inferential tests run on this data: {counts['inferential_tests']}"
        + (
            f" (Agent without confirmation: {by.get('agent_without_confirmation', 0)}; "
            f"Agent, confirmed by the user: {by.get('agent_confirmed_by_user', 0)}; "
            f"user: {by.get('user', 0)})"
            if counts["inferential_tests"] else ""
        ),
        f"- Models estimated: {counts['models']}",
        f"- Descriptive analyses: {counts['descriptive_analyses']}",
        f"- Data changes: {counts['data_changes']}; metadata changes: {counts['metadata_changes']}; "
        f"runs deleted: {counts['run_deletions']}",
        "",
        "Every test run on this data is counted, whether or not its result appears in this report. "
        "The more tests bear on one question, the likelier it is that one of them is significant by chance.",
    ]
    changes = value.get("changes") or []
    if changes:
        lines += ["", "Data changes, in order:", ""]
        lines += [f"- {item['at'][:16].replace('T', ' ')} · {item['who']} · {item['what']}"
                  + (f" · {item['summary']}" if item.get("summary") else "") for item in changes]
    if detail == "full" and value.get("entries"):
        lines += ["", "Full analysis log:", "", "| When | Who | What | Status |", "|---|---|---|---|"]
        lines += [
            f"| {item['at'][:16].replace('T', ' ')} | {item['who']} | {item['what']} | {item['status']} |"
            for item in value["entries"]
        ]
        if value.get("entries_omitted"):
            lines.append(f"\n({value['entries_omitted']} earlier entries omitted.)")
    return "\n".join(lines) + "\n"
