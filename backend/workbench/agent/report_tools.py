"""The Agent reads and writes a run's report through the same versioned store a person uses.

A saved version is a new immutable record: the report's evidence, the run and every earlier
version stay as they are. Prose may only show values through markers bound to the run's facts,
including a fitted model's sample size. Other numbers must already be in this conversation.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from . import numeric_grounding
from .session import JsonlSessionRepository
from .tools import ToolDefinition, ToolVisibleError
from ..api_errors import WorkbenchAPIError

_MARKER = re.compile(r"\[\[[^\]\n]*\]\]")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_RUN_ID = {"type": "string", "minLength": 1, "maxLength": 200, "description": "The run the report belongs to."}
#: Enough to write from; the Agent can read any single result in full with its other tools.
_MAX_FACTS = 300
_MAX_TEXT = 40_000
_MODEL_BINDING_FIELDS = {"model/id", "model/nobs", "inference/nobs_basis"}


def _version(record: dict[str, Any]) -> dict[str, Any]:
    return {"report_id": record["id"], "kind": "written", "author": record["author"], "created_at": record["created_at"],
            "revision_number": record["revision_number"], "title": record["title"], "characters": len(record["text"])}


def _generated(record: dict[str, Any]) -> dict[str, Any]:
    return {"report_id": record.get("id"), "kind": "generated", "author": record.get("model") or "report writer",
            "created_at": record.get("generatedAt"), "characters": len(record.get("text") or "")}


def _fact(fact: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "label", "value")
    if fact.get("field") in _MODEL_BINDING_FIELDS:
        keys += ("field", "source")
    return {key: fact[key] for key in keys if key in fact}


def _report_store():
    """Imported when a tool runs: importing the report service here, while the tool registry loads,
    builds the workflow step registry before the imputation methods have registered themselves."""
    from ..report_store import list_ai_reports
    from ..repository.run_repository import _resolve_run_root
    from ..services import manual_reports
    return SimpleNamespace(list_ai_reports=list_ai_reports, resolve=_resolve_run_root, manual=manual_reports)


def report_read_tool(project_root, *, session_id: str) -> ToolDefinition:
    def read_reports(arguments: dict[str, Any], context) -> dict[str, Any]:
        if context.session_id != session_id:
            raise ToolVisibleError("REPORT_SESSION_MISMATCH: use the current session's tools.")
        store = _report_store()
        run_root = store.resolve(str(project_root), arguments["run_id"])
        written = store.manual.list_manual_reports(run_root)
        generated = store.list_ai_reports(run_root)
        versions = sorted([*map(_version, written), *map(_generated, generated)],
                          key=lambda item: str(item["created_at"]), reverse=True)
        wanted = arguments.get("report_id")
        chosen = next((r for r in [*written, *generated] if r.get("id") == wanted), None) if wanted else None
        if wanted and chosen is None:
            raise ToolVisibleError(f"REPORT_NOT_FOUND: no version {wanted} in this run.")
        draft = store.manual.build_manual_report_draft(run_root)
        latest = chosen or (written[0] if written else (generated[-1] if generated else None))
        text = latest["text"] if latest else draft["text"]
        facts = sorted(draft["facts"], key=lambda fact: fact.get("field") not in _MODEL_BINDING_FIELDS)
        return {"versions": versions, "evidence_changed": bool(written) and written[0]["source_fingerprint"] != draft["source_fingerprint"],
                "report_id": latest.get("id") if latest else None, "title": (latest or draft).get("title"),
                "text": text[:_MAX_TEXT], "text_omitted": max(0, len(text) - _MAX_TEXT),
                "facts": [_fact(fact) for fact in facts[:_MAX_FACTS]],
                "facts_omitted": max(0, len(facts) - _MAX_FACTS),
                "limitations": (latest or draft).get("limitations", draft["limitations"])}

    return ToolDefinition(
        tool_id="read_reports", version="v1", side_effect="none",
        scope_requirements=("project",), max_output_budget=48_000,
        description="Read a run's report: every saved version, the text of the newest or a named one (a draft from the "
                    "computed evidence when none is saved), and the facts it can cite. A value in report text is written "
                    "as its marker, [[v:<fact id>]]. Sample sizes use the fitted model's model/nobs fact and its recorded basis.",
        input_schema={"type": "object", "required": ["run_id"], "additionalProperties": False, "properties": {
            "run_id": _RUN_ID, "report_id": {"type": "string", "minLength": 1, "maxLength": 200}}},
        handler=read_reports)


def report_save_tool(project_root, *, session_id: str) -> ToolDefinition:
    def save_report_version(arguments: dict[str, Any], context) -> dict[str, Any]:
        if context.session_id != session_id:
            raise ToolVisibleError("REPORT_SESSION_MISMATCH: use the current session's tools.")
        store = _report_store()
        run_root = store.resolve(str(project_root), arguments["run_id"])
        repository = JsonlSessionRepository(Path(project_root) / "workbench")
        messages = [entry.payload for entry in repository.get_branch(session_id)
                    if entry.entry_type in {"message", "custom_message"}]
        prose = _MARKER.sub("", arguments["text"])
        if "[v:" in prose:
            raise ToolVisibleError("REPORT_MARKER_MALFORMED: a value marker has two brackets on each side, [[v:<fact id>]]. "
                                   "Nothing was saved.")
        if _TABLE_ROW.search(prose):
            raise ToolVisibleError("REPORT_TABLE_UNSUPPORTED: report text has headings, paragraphs and bullet lists; "
                                   "write each estimate as a bullet. Nothing was saved.")
        findings = numeric_grounding.check(prose, messages)
        unverified = [finding.text for finding in findings if finding.kind != "group_comparison"]
        if unverified:
            raise ToolVisibleError("REPORT_NUMBER_UNVERIFIED: these numbers are in no result of this conversation: "
                                   + ", ".join(unverified[:12]) + ". Read them first, or write them as [[v:<fact id>]].")
        try:
            draft = store.manual.build_manual_report_draft(run_root)
            written = store.manual.list_manual_reports(run_root)
            # A revision keeps its parent's evidence; after the evidence changes, a new report starts.
            parent = next((r for r in written if r["source_fingerprint"] == draft["source_fingerprint"]), None)
            saved = store.manual.save_manual_report(run_root, store.manual.ManualReportRequest(
                id=f"mrpt_{uuid4().hex}", source_fingerprint=draft["source_fingerprint"], title=arguments["title"],
                text=arguments["text"], parent_report_id=parent["id"] if parent else None,
                fact_ids=[fact["id"] for fact in (parent or draft)["facts"]],
                figure_ids=[figure["artifact_id"] for figure in (parent or draft)["figures"]]), author="agent")
        except WorkbenchAPIError as exc:
            raise ToolVisibleError(f"{exc.code}: {exc.message}") from exc
        record = saved["record"]
        return {"saved": True, "report_id": record["id"], "revision_number": record["revision_number"],
                "note": "The person sees this version in Report review; earlier versions stay available."}

    return ToolDefinition(
        tool_id="save_report_version", version="v1", side_effect="report_version",
        scope_requirements=("project", "chain"), max_output_budget=2_000,
        description="Save report text as a new version of this run's report, when the person asks to write or revise it. "
                    "Start from read_reports. Use headings, paragraphs and bullet lists, no tables. Show results through "
                    "[[v:<fact id>]] markers. For a sample size, put the fitted model's model/nobs marker in the body. "
                    "Use the recorded nobs_basis for its label, such as units for unit-based estimates. "
                    "With multiple models, put the corresponding model/id marker on the same line as each sample size. "
                    "Other numbers must already be in a result you received. The person sees the new version in Report review.",
        input_schema={"type": "object", "required": ["run_id", "title", "text"], "additionalProperties": False, "properties": {
            "run_id": _RUN_ID, "title": {"type": "string", "minLength": 1, "maxLength": 300},
            "text": {"type": "string", "minLength": 1, "maxLength": 200_000}}},
        handler=save_report_version)
