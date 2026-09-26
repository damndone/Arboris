"""What may leave this computer in a request to an LLM provider.

Every provider call is built by ``llm.client._chat_request_payload``, which
passes its messages through :func:`guard_outgoing_messages` -- the single
checkpoint. Nothing reaches a provider around it.

A message's content is classified by what produced it. Tool results are
classified by the tool (``TOOL_CONTENT_CLASSES``); a tool with no declared
class is ``unclassified`` and handled as the most restrictive class, so a new
tool leaks nothing until someone decides what it carries. The user's own words
and the server's instructions are sent as written.

The policy decides, per provider, which classes may be sent. Remote providers
by default receive dataset structure, labels, aggregates and model results --
never row-level records. Local providers (localhost) receive everything.
A project may override both, and may declare column sensitivity: values of a
``sensitive`` column are withheld from remote providers, values of a
``restricted`` column from every provider. The column's name stays visible so
the Agent can still reason about it.

Withheld content is replaced by a note telling the model the data stayed on
this computer and that it should compute locally instead of asking again.
Every send is recorded in a JSONL audit log.
"""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import ipaddress
import json
import os
import re
import threading
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

POLICY_VERSION = 1

# Ordered from least to most revealing about individual records.
CONTENT_CLASSES = (
    "workbench_state",  # operations, lineage, contracts, proposals -- no dataset values
    "schema",  # column names and types
    "metadata",  # variable/value labels, missing codes, measurement levels
    "aggregate",  # summary statistics, frequency tables, test statistics
    "model_result",  # coefficients, standard errors, fit statistics
    "rows",  # row-level records
    "unclassified",  # not declared: handled as the most restrictive class
)

SENSITIVITY_LEVELS = ("public", "internal", "sensitive", "restricted")

REMOTE_DEFAULT_ALLOW = frozenset({"workbench_state", "schema", "metadata", "aggregate", "model_result"})
LOCAL_DEFAULT_ALLOW = frozenset(CONTENT_CLASSES)

# One place to review what every Agent tool can put in front of a provider.
# tests/test_egress.py fails when a registered tool is missing from this table.
TOOL_CONTENT_CLASSES: Mapping[str, str] = {
    # Agent (main and chain sessions)
    "propose_analysis_loop": "workbench_state",
    "propose_operation": "workbench_state",
    "submit_analysis_loop_intent": "workbench_state",
    "inspect_completed_operations": "workbench_state",
    "inspect_operation_contract": "workbench_state",
    "inspect_repeated_measures_recipe": "workbench_state",
    "export_dataset": "metadata",
    "list_project_datasets": "metadata",
    "inspect_data_schema": "metadata",
    "inspect_project_dataset_schema": "metadata",
    "inspect_node_context": "metadata",
    "inspect_notebook_workflow_results": "aggregate",
    "inspect_project_notebook_workflow_results": "aggregate",
    "inspect_operation_artifact": "aggregate",
    "inspect_design_advisories": "aggregate",
    "inspect_time_series_summary": "aggregate",
    "inspect_artifact_preview": "aggregate",
    "inspect_project_numeric_summary": "aggregate",
    "inspect_analysis_loop_context": "model_result",
    "inspect_diagnostics": "model_result",
    "inspect_statistical_evidence": "model_result",
    "inspect_project_statistical_evidence": "model_result",
    "inspect_result_summary": "model_result",
    "inspect_project_model_coefficients": "model_result",
    "inspect_project_model_figure_evidence": "model_result",
    "inspect_project_linear_interaction_effects": "model_result",
    "inspect_project_coefficient_transforms": "model_result",
    "show_dataset_rows": "rows",
    # Notebook planning
    "request_notebook_inspections": "aggregate",
    "submit_notebook_option_batch": "workbench_state",
    "decline_notebook_plan": "workbench_state",
}

# Server-built evidence records travel inside user and system messages too
# (Notebook planning puts its evidence pack in the user turn), so they are
# classified by protocol wherever they appear.
EVIDENCE_PROTOCOL_CLASSES: Mapping[str, str] = {
    "profile/v1": "aggregate",
    "quality/v1": "aggregate",
    "time-index/v1": "aggregate",
    "sample/v1": "rows",
    "inspection-error/v1": "workbench_state",
}

# Column names that almost always identify a person. A suggestion only: the
# project policy's explicit level for a column always wins.
_PERSONAL_NAME_PATTERNS = (
    r"(full_?|first_?|last_?|given_?|sur|family_?|user_?|real_?)?name",
    r"姓名|名字",
    r"(mobile|cell|tele)?phone(_?(no|number))?|tel|mobile",
    r"手机(号|号码)?|电话(号码)?|联系方式",
    r"e?-?mail(_?address)?",
    r"邮箱|电子邮件",
    r"(home_?|street_?|postal_?)?address|addr",
    r"(家庭|通讯|居住)?地址|住址",
    r"id_?card(_?(no|number))?|ssn|social_security(_number)?|passport(_?(no|number))?|national_id",
    r"身份证(号|号码)?|护照(号|号码)?",
    r"(date_of_)?birth_?date|dob|出生日期",
)
_PERSONAL_NAME_RE = re.compile(r"^(?:" + "|".join(_PERSONAL_NAME_PATTERNS) + r")$", re.IGNORECASE)

WITHHELD = "[withheld: sensitive column]"

# Fields of a column description that say nothing about the column's values.
_COLUMN_ENTRY_SAFE_KEYS = frozenset(
    {"name", "column", "variable", "dtype", "type", "variable_label", "label", "measurement_level",
     "missing_rate", "missing_count", "unique_count", "n", "count", "role", "sensitivity"}
)
_COLUMN_ENTRY_NAME_KEYS = ("name", "column", "variable")


def suggested_sensitivity(column: str) -> str:
    """The heuristic default level for a column name."""

    return "sensitive" if _PERSONAL_NAME_RE.match(column.strip()) else "internal"


def provider_locality(base_url: str) -> str:
    host = (urlparse(base_url).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return "local"
    try:
        return "local" if ipaddress.ip_address(host).is_loopback else "remote"
    except ValueError:
        return "remote"


@dataclass(frozen=True)
class EgressPolicy:
    """A project's data-sharing policy, as stored in ``workbench/egress/policy.json``."""

    providers: Mapping[str, frozenset[str]] = field(default_factory=dict)
    columns: Mapping[str, str] = field(default_factory=dict)
    source: str = "default"

    def allowed_classes(self, *, provider_id: str, locality: str) -> frozenset[str]:
        for key in (provider_id, locality):
            if key and key in self.providers:
                return self.providers[key]
        return LOCAL_DEFAULT_ALLOW if locality == "local" else REMOTE_DEFAULT_ALLOW

    def column_level(self, column: str) -> str:
        return self.columns.get(column) or suggested_sensitivity(column)

    def protected_column(self, column: str, *, locality: str) -> bool:
        level = self.column_level(column)
        return level == "restricted" or (level == "sensitive" and locality == "remote")

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": POLICY_VERSION,
            "providers": {key: {"allow": sorted(value)} for key, value in sorted(self.providers.items())},
            "columns": dict(sorted(self.columns.items())),
        }


class EgressPolicyError(ValueError):
    pass


def parse_policy(document: Mapping[str, Any], *, source: str = "project") -> EgressPolicy:
    if not isinstance(document, Mapping):
        raise EgressPolicyError("policy must be a JSON object")
    version = document.get("version", POLICY_VERSION)
    if version != POLICY_VERSION:
        raise EgressPolicyError(f"unsupported policy version: {version!r}")
    providers: dict[str, frozenset[str]] = {}
    raw_providers = document.get("providers") or {}
    if not isinstance(raw_providers, Mapping):
        raise EgressPolicyError("providers must be an object")
    for key, entry in raw_providers.items():
        allow = entry.get("allow") if isinstance(entry, Mapping) else None
        if not isinstance(allow, list) or not all(isinstance(item, str) for item in allow):
            raise EgressPolicyError(f"providers.{key}.allow must be a list of content classes")
        unknown = sorted(set(allow) - set(CONTENT_CLASSES))
        if unknown:
            raise EgressPolicyError(
                f"providers.{key}.allow has unknown classes {unknown}; known: {list(CONTENT_CLASSES)}"
            )
        providers[str(key)] = frozenset(allow)
    raw_columns = document.get("columns") or {}
    if not isinstance(raw_columns, Mapping):
        raise EgressPolicyError("columns must be an object")
    columns: dict[str, str] = {}
    for column, level in raw_columns.items():
        if level not in SENSITIVITY_LEVELS:
            raise EgressPolicyError(
                f"columns.{column} must be one of {list(SENSITIVITY_LEVELS)}, got {level!r}"
            )
        columns[str(column)] = str(level)
    return EgressPolicy(providers=providers, columns=columns, source=source)


def egress_dir(project_root: Path) -> Path:
    # Project-local Workbench metadata lives under `workbench/`, outside the
    # runs and graph scanners' inputs.
    return Path(project_root) / "workbench" / "egress"


def policy_path(project_root: Path) -> Path:
    return egress_dir(project_root) / "policy.json"


def audit_path(project_root: Path | None) -> Path:
    if project_root is not None:
        return egress_dir(project_root) / "audit.jsonl"
    override = os.environ.get("WORKBENCH_EGRESS_AUDIT_DIR")
    base = Path(override) if override else Path.home() / ".workbench"
    return base / "egress_audit.jsonl"


def load_policy(project_root: Path | None) -> EgressPolicy:
    """The project's policy, or the default when it has none.

    A policy file that exists but cannot be read is an error, never a silent
    fallback to the more permissive default.
    """

    if project_root is None:
        return EgressPolicy()
    path = policy_path(project_root)
    if not path.is_file():
        return EgressPolicy()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EgressPolicyError(f"cannot read {path}: {exc}") from exc
    return parse_policy(document, source=str(path))


def save_policy(project_root: Path, policy: EgressPolicy) -> None:
    path = policy_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


_PROJECT_SCOPE: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "workbench_egress_project", default=None
)


@contextlib.contextmanager
def egress_project(project_root: Path | str | None) -> Iterator[None]:
    """Attribute provider calls made inside this block to a project.

    Calls outside any project scope still pass the checkpoint under the
    default policy and are audited to the user-level log.
    """

    token = _PROJECT_SCOPE.set(Path(project_root) if project_root is not None else None)
    try:
        yield
    finally:
        _PROJECT_SCOPE.reset(token)


def current_project() -> Path | None:
    return _PROJECT_SCOPE.get()


def tool_content_class(tool_id: str | None) -> str:
    return TOOL_CONTENT_CLASSES.get(tool_id or "", "unclassified")


def _tool_names_by_call_id(messages: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages:
        for call in message.get("tool_calls") or ():
            if not isinstance(call, Mapping):
                continue
            function = call.get("function")
            name = function.get("name") if isinstance(function, Mapping) else call.get("tool_id")
            call_id = call.get("id") or call.get("tool_call_id")
            if call_id and name:
                names[str(call_id)] = str(name)
    return names


def _withheld_note(tool_id: str, content_class: str, payload: Any) -> str:
    # A tool may attach a summary it has declared safe to send (for example
    # "Rows 1-20 of 240 ... are shown to the user in Workbench").
    summary = None
    if isinstance(payload, Mapping):
        output = payload.get("output") if isinstance(payload.get("output"), Mapping) else payload
        candidate = output.get("egress_summary") if isinstance(output, Mapping) else None
        summary = candidate if isinstance(candidate, str) else None
    note: dict[str, Any] = {
        "egress_withheld": True,
        "tool_id": tool_id,
        "content_class": content_class,
        "reason": (
            f"The call succeeded. This project's data-sharing policy keeps {content_class} "
            "content on the user's computer, so it was not sent to the model provider."
        ),
        "guidance": (
            "Never state, guess or reconstruct the withheld values. Answer questions about them "
            "from schema, labels, aggregates or model results, or plan workflow steps that "
            "compute locally."
        ),
    }
    if summary is not None:
        note["shown_to_user"] = summary
        note["guidance"] = (
            "Tell the user what was shown (shown_to_user); they can read it in Workbench. "
            + note["guidance"]
        )
    return json.dumps(note, ensure_ascii=False, sort_keys=True)


_COLUMN_ENTRY_MARKERS = frozenset(
    {"dtype", "type", "variable_label", "measurement_level", "unique_count", "missing_rate", "value_labels", "role"}
)


def _column_entry_name(value: Mapping[str, Any]) -> str | None:
    """The column a dict describes, when it is a column description.

    ``{"name": "age", "dtype": "float64"}`` describes a column; a row record
    ``{"name": "Alice", "age": 30}`` does not -- it has no description field.
    """

    if not (_COLUMN_ENTRY_MARKERS & value.keys()):
        return None
    for key in _COLUMN_ENTRY_NAME_KEYS:
        name = value.get(key)
        if isinstance(name, str) and name:
            return name
    return None


def _observed_columns(value: Any, into: set[str]) -> None:
    if isinstance(value, list):
        for item in value:
            _observed_columns(item, into)
    elif isinstance(value, Mapping):
        name = _column_entry_name(value)
        if name is not None:
            into.add(name)
        for key, item in value.items():
            if key == "columns" and isinstance(item, list):
                into.update(entry for entry in item if isinstance(entry, str))
            _observed_columns(item, into)


class _Redactor:
    """Withholds the values of protected columns wherever a payload carries them.

    ``protected`` is decided once per send: the policy's explicit levels plus
    the name heuristic applied to column names seen in the conversation. The
    heuristic is never applied to arbitrary JSON keys -- ``name`` is a column in
    some datasets and a structural field in every payload.
    """

    def __init__(self, protected: frozenset[str]) -> None:
        self.protected = protected
        self.redacted: set[str] = set()

    def term(self, text: str) -> str:
        # Categorical terms name the category: C(Q('name'))[T.Alice], name[T.Alice].
        if "[" not in text or not self.protected:
            return text

        def replace(match: re.Match[str]) -> str:
            column = match.group("q") or match.group("bare")
            if column in self.protected:
                self.redacted.add(column)
                return match.group("head") + "[withheld]"
            return match.group(0)

        return _TERM_RE.sub(replace, text)

    def walk(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.term(value)
        if isinstance(value, list):
            return [self.walk(item) for item in value]
        if not isinstance(value, Mapping):
            return value
        entry_name = _column_entry_name(value)
        if entry_name is not None:
            if entry_name in self.protected:
                # Keep what the column is; drop what it contains.
                self.redacted.add(entry_name)
                kept = {key: item for key, item in value.items() if key in _COLUMN_ENTRY_SAFE_KEYS}
                kept["values_withheld"] = True
                return kept
            return {key: self.walk(item) for key, item in value.items()}
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in self.protected:
                # Anything keyed by a protected column (value labels, frequency
                # tables, row records) carries its values.
                self.redacted.add(key)
                result[key] = WITHHELD
            else:
                result[self.term(key) if isinstance(key, str) else key] = self.walk(item)
        return result


_TERM_RE = re.compile(
    r"(?P<head>C\(Q\('(?P<q>[^']+)'\)[^\[]*\)|(?P<bare>[A-Za-z_一-鿿][\w一-鿿]*))\[T\.[^\]]*\]"
)


@dataclass
class _Decision:
    index: int
    role: str
    content_class: str
    decision: str
    tool_id: str | None = None
    redacted_columns: tuple[str, ...] = ()
    withheld_protocols: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "index": self.index,
            "role": self.role,
            "content_class": self.content_class,
            "decision": self.decision,
        }
        if self.tool_id:
            entry["tool_id"] = self.tool_id
        if self.redacted_columns:
            entry["redacted_columns"] = list(self.redacted_columns)
        if self.withheld_protocols:
            entry["withheld_protocols"] = list(self.withheld_protocols)
        return entry


_AUDIT_LOCK = threading.Lock()


def guard_outgoing_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    base_url: str,
    provider_id: str = "",
    model: str = "",
) -> list[dict[str, Any]]:
    """Return the messages as they may be sent, and audit the send."""

    project = current_project()
    policy = load_policy(project)
    locality = provider_locality(base_url)
    allowed = policy.allowed_classes(provider_id=provider_id, locality=locality)
    tool_names = _tool_names_by_call_id(messages)
    parsed = [_parse_json(message.get("content")) for message in messages]
    observed: set[str] = set(policy.columns)
    for payload in parsed:
        _observed_columns(payload, observed)
    protected = frozenset(column for column in observed if policy.protected_column(column, locality=locality))
    guarded: list[dict[str, Any]] = []
    decisions: list[_Decision] = []
    for index, message in enumerate(messages):
        outgoing = dict(message)
        role = str(message.get("role", ""))
        content = message.get("content")
        payload = parsed[index]
        tool_id: str | None = None
        if role == "tool":
            tool_id = tool_names.get(str(message.get("tool_call_id", "")))
            content_class = tool_content_class(tool_id)
            if isinstance(payload, Mapping) and payload.get("ok") is False and payload.get("output") is None:
                # A failed call returned no content, only its error. Withholding
                # the error would let the model believe the call succeeded.
                content_class = "workbench_state"
            if content_class not in allowed:
                outgoing["content"] = _withheld_note(tool_id or "unknown", content_class, payload)
                decisions.append(_Decision(index, role, content_class, "withheld", tool_id))
                guarded.append(outgoing)
                continue
        else:
            # The user's words, the model's replies and server instructions.
            # Server-built JSON in them (Workbench context, Notebook evidence)
            # is still filtered below.
            content_class = "conversation" if role in {"user", "assistant"} else "workbench_state"
        outgoing["content"], columns, protocols = _filter(content, payload, protected, allowed)
        decision = "withheld_in_part" if protocols else "redacted" if columns else "sent"
        decisions.append(_Decision(index, role, content_class, decision, tool_id, columns, protocols))
        guarded.append(outgoing)
    _audit(project, policy, locality, provider_id, base_url, model, guarded, decisions)
    return guarded


def _parse_json(content: Any) -> Any:
    if not isinstance(content, str):
        return None
    stripped = content.lstrip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None


def _withhold_evidence(value: Any, allowed: frozenset[str], withheld: set[str]) -> Any:
    if isinstance(value, list):
        return [_withhold_evidence(item, allowed, withheld) for item in value]
    if not isinstance(value, Mapping):
        return value
    protocol = value.get("protocol_version")
    if isinstance(protocol, str) and "observations" in value:
        content_class = EVIDENCE_PROTOCOL_CLASSES.get(protocol, "unclassified")
        if content_class not in allowed:
            withheld.add(protocol)
            kept = {key: item for key, item in value.items() if key not in {"observations", "metrics"}}
            kept["observations"] = {
                "egress_withheld": True,
                "content_class": content_class,
                "reason": (
                    f"{content_class} evidence stays on the user's computer under this "
                    "project's data-sharing policy; plan from the other evidence records."
                ),
            }
            kept["metrics"] = {}
            return kept
        return value
    return {key: _withhold_evidence(item, allowed, withheld) for key, item in value.items()}


def _filter(
    content: Any, payload: Any, protected: frozenset[str], allowed: frozenset[str]
) -> tuple[Any, tuple[str, ...], tuple[str, ...]]:
    """Withhold disallowed evidence and protected column values from one message."""

    if payload is None:
        if isinstance(content, str) and protected:
            redactor = _Redactor(protected)
            return redactor.term(content), tuple(sorted(redactor.redacted)), ()
        return content, (), ()
    withheld: set[str] = set()
    filtered = _withhold_evidence(payload, allowed, withheld)
    redacted: set[str] = set()
    if protected:
        redactor = _Redactor(protected)
        filtered = redactor.walk(filtered)
        redacted = redactor.redacted
    if not withheld and not redacted:
        return content, (), ()
    return (
        json.dumps(filtered, ensure_ascii=False, sort_keys=True),
        tuple(sorted(redacted)),
        tuple(sorted(withheld)),
    )


def _audit(
    project: Path | None,
    policy: EgressPolicy,
    locality: str,
    provider_id: str,
    base_url: str,
    model: str,
    guarded: Sequence[Mapping[str, Any]],
    decisions: Sequence[_Decision],
) -> None:
    serialized = json.dumps(guarded, ensure_ascii=False, sort_keys=True).encode("utf-8")
    record = {
        "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "project_root": str(project) if project is not None else None,
        "provider_id": provider_id,
        "provider_host": urlparse(base_url).hostname or "",
        "provider_locality": locality,
        "model": model,
        "policy_source": policy.source,
        "message_count": len(guarded),
        "withheld_count": sum(1 for item in decisions if item.decision.startswith("withheld")),
        "redacted_columns": sorted({column for item in decisions for column in item.redacted_columns}),
        "payload_bytes": len(serialized),
        "payload_sha256": hashlib.sha256(serialized).hexdigest(),
        # Decisions for tool and redacted messages; plain conversation turns are counted only.
        "decisions": [item.to_dict() for item in decisions if item.role == "tool" or item.decision != "sent"],
    }
    path = audit_path(project)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with _AUDIT_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line)


def read_audit(project_root: Path | None, *, limit: int = 50) -> list[dict[str, Any]]:
    path = audit_path(project_root)
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    records = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(records))
