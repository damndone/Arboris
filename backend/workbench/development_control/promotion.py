"""Deterministic, evidence-bound 1/2/3 development-rule promotion.

This module derives promotion records from already validated devline events.  It
never edits events or AGENTS.md: the only mutable control-plane output is an
append-only candidate/ledger pair and the enabled mechanical-rule snapshot.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Literal

from .events import EventValidationError, validate_event


PROMOTABLE_EVENT_TYPES = frozenset({"FAILURE", "ERROR", "GAP", "GATE"})
_SHA256_LENGTH = 64
_CANDIDATE_FILE = "candidate-rules.jsonl"
_LEDGER_FILE = "promotion-ledger.jsonl"
_GLOBAL_FILE = "global-rules.json"


class PromotionError(ValueError):
    """Raised when promotion input or a durable promotion record is invalid."""


@dataclass(frozen=True)
class PromotionPolicy:
    """The pre-approved handling boundary for one normalized lesson key."""

    lesson_key: str
    rule_id: str
    kind: Literal["mechanical", "behavior"]
    scope: str
    enforcement_point: str
    false_positive_risk: str
    verification_method: str
    test_marker: str | None = None
    behavior_proposal: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "lesson_key",
            "rule_id",
            "scope",
            "enforcement_point",
            "false_positive_risk",
            "verification_method",
        ):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise PromotionError(f"{field} must be non-empty text")
        if self.kind not in {"mechanical", "behavior"}:
            raise PromotionError("policy kind must be mechanical or behavior")
        if self.kind == "mechanical" and self.test_marker is None:
            raise PromotionError("mechanical policies require a test_marker")
        if self.kind == "behavior" and self.behavior_proposal is None:
            raise PromotionError("behavior policies require a behavior_proposal")
        if self.test_marker is not None:
            if not isinstance(self.test_marker, str) or not self.test_marker.strip() or "\x00" in self.test_marker:
                raise PromotionError("test_marker must be non-empty text")
        if self.behavior_proposal is not None:
            if not isinstance(self.behavior_proposal, str) or not self.behavior_proposal.strip() or "\x00" in self.behavior_proposal:
                raise PromotionError("behavior_proposal must be non-empty text")


DEFAULT_PROMOTION_POLICIES = (
    PromotionPolicy(
        lesson_key="filesystem-persistence-capability-bypass",
        rule_id="require-capability-bounded-persistence",
        kind="mechanical",
        scope="development-control persistence changes",
        enforcement_point="focused containment test gate",
        false_positive_risk="only applies to persistence capability changes",
        verification_method="run the frozen containment test marker",
        test_marker="tests/test_frozen_containment.py",
    ),
    PromotionPolicy(
        lesson_key="native-frontend-environment-blocker",
        rule_id="record-native-frontend-environment-blocker",
        kind="behavior",
        scope="frontend environment diagnosis",
        enforcement_point="integration owner review",
        false_positive_risk="environment evidence can be host-specific",
        verification_method="integration owner reviews the attached evidence",
        behavior_proposal="Record the reviewed environment boundary in the managed AGENTS block.",
    ),
    PromotionPolicy(
        lesson_key="containment-c1-c2-boundary",
        rule_id="enforce-c1-c2-containment-boundary",
        kind="mechanical",
        scope="frozen containment boundaries",
        enforcement_point="focused containment test gate",
        false_positive_risk="only applies to C1/C2 containment surfaces",
        verification_method="run the frozen containment test marker",
        test_marker="tests/test_frozen_containment.py",
    ),
    # --- v1.8.1 Notebook wave lessons (registered so recurrence can promote) ---
    # A lesson only enters the promotion pipeline once a policy declares its
    # enforcement boundary. Registering here is the deliberate human gate the
    # system uses instead of auto-promoting arbitrary lesson text.
    PromotionPolicy(
        lesson_key="packet-parsers-reject-unknown-fields",
        rule_id="require-exact-keys-in-packet-parsers",
        kind="mechanical",
        scope="contract packet from_dict parsers",
        enforcement_point="contract lock compatibility suite",
        false_positive_risk="only applies to versioned packet parsers",
        verification_method="run the contract lock suite that asserts unknown fields are refused",
        test_marker="tests/contracts/test_v181_contract_lock.py",
    ),
    PromotionPolicy(
        lesson_key="check-accepted-adrs-before-starting",
        rule_id="start-devline-from-context-pack",
        kind="behavior",
        scope="starting any new version or lane",
        enforcement_point="integration owner review before feature work",
        false_positive_risk="a genuinely trivial one-file fix may not warrant a full pack",
        verification_method="integration owner confirms a frozen Context Pack exists for the line",
        behavior_proposal=(
            "Refuse feature work on a devline without a frozen Context Pack, and grep "
            "docs/superpowers/specs for accepted ADRs before starting; record the rule in "
            "the managed AGENTS block."
        ),
    ),
    PromotionPolicy(
        lesson_key="mirror-existing-index-vocabulary",
        rule_id="mirror-shared-data-vocabulary-across-packs",
        kind="behavior",
        scope="adding a model that shares data with an existing pack",
        enforcement_point="contract sprint review",
        false_positive_risk="only applies when two packs are meant to be compared on one series",
        verification_method="integration owner confirms index and sample vocabulary match the peer pack",
        behavior_proposal=(
            "When a new model shares a dataset with an existing pack, mirror that pack's "
            "index and sample vocabulary in the Contract Sprint before locking."
        ),
    ),
    PromotionPolicy(
        lesson_key="fixture-numbers-must-be-arithmetically-coherent",
        rule_id="assert-fixture-arithmetic-identity",
        kind="behavior",
        scope="hand-authored numeric canonical fixtures",
        enforcement_point="contract sprint review",
        false_positive_risk="only applies to fixtures carrying derived numeric quantities",
        verification_method="integration owner confirms an arithmetic-identity check covers the fixture",
        behavior_proposal=(
            "Add an arithmetic-identity assertion (e.g. AIC/BIC vs log-likelihood and k) for any "
            "hand-authored numeric fixture before it becomes a shared lock."
        ),
    ),
    # --- 2026-07-23 integration review findings (F-6, F-7) ---
    PromotionPolicy(
        lesson_key="derive-model-shape-from-capability-not-literal",
        rule_id="genesis-x-requirement-from-capability",
        kind="mechanical",
        scope="notebook genesis materialization model-shape checks",
        enforcement_point="notebook materialization test gate",
        false_positive_risk="only applies to genesis model-param validation branches",
        verification_method="run the univariate-genesis materialization marker",
        test_marker=(
            "tests/test_notebook_materialization.py::"
            "test_univariate_genesis_option_materializes_without_x_regressors"
        ),
    ),
    PromotionPolicy(
        lesson_key="fixture-restores-all-coupled-registration-state",
        rule_id="fixture-restores-loader-tracking",
        kind="mechanical",
        scope="test fixtures mutating shared model-pack registration",
        enforcement_point="pack runtime test gate",
        false_positive_risk="only applies to fixtures that declare a pack directly",
        verification_method="run the ETS declaration capability marker in isolation",
        test_marker=(
            "tests/models/ets/test_ets_pack_runtime.py::"
            "test_declaration_exposes_one_selectable_capability"
        ),
    ),
)


def promote(
    control_dir: Path,
    events: Iterable[Mapping[str, Any]],
    *,
    policies: Sequence[PromotionPolicy] = DEFAULT_PROMOTION_POLICIES,
) -> dict[str, dict[str, object]]:
    """Promote distinct incidents for configured lesson keys.

    The first occurrence remains line-local.  The second appends exactly one
    candidate.  The third enables a mechanical rule only when a source event
    references its required test marker; behavior rules become review proposals
    only and this function never writes AGENTS.md.
    """

    directory = _ensure_control_dir(control_dir)
    policy_by_lesson = _policy_map(policies)
    events = list(events)
    grouped = _distinct_incidents(events, policy_by_lesson)
    high_severity = _high_severity_lessons(events, policy_by_lesson)
    candidates = read_candidate_rules(directory)
    ledger = read_promotion_ledger(directory)
    global_rules = read_global_rules(directory)
    result: dict[str, dict[str, object]] = {}

    for lesson_key, policy in policy_by_lesson.items():
        sources = grouped.get(lesson_key, [])
        count = len(sources)
        candidate_id = _candidate_id(lesson_key)
        candidate_status = "line_experience" if count < 2 else "candidate"
        global_status: str | None = None

        candidate = None
        if count >= 2:
            candidate = _candidate_record(policy, sources[:2])
            _append_unique_jsonl(directory / _CANDIDATE_FILE, candidate, "candidate_id", validate_candidate_rule)
            if not _ledger_has(ledger, _ledger_id(lesson_key, "candidate")):
                entry = _ledger_record(
                    policy,
                    decision="candidate_created",
                    occurrence_count=2,
                    sources=sources[:2],
                    candidate_id=candidate_id,
                )
                _append_unique_jsonl(directory / _LEDGER_FILE, entry, "ledger_id", validate_promotion_ledger_entry)
                ledger.append(entry)
            candidates = _replace_or_append(candidates, candidate, "candidate_id")

        if count >= 3:
            if policy.kind == "behavior":
                global_status = "proposal_pending_review"
                ledger_id = _ledger_id(lesson_key, "behavior_proposal")
                if not _ledger_has(ledger, ledger_id):
                    entry = _ledger_record(
                        policy,
                        decision="behavior_rule_proposed",
                        occurrence_count=count,
                        sources=sources[:3],
                        candidate_id=candidate_id,
                        proposal_target="AGENTS.md managed block",
                    )
                    _append_unique_jsonl(directory / _LEDGER_FILE, entry, "ledger_id", validate_promotion_ledger_entry)
                    ledger.append(entry)
            elif _has_test_marker(sources, policy.test_marker):
                global_status = "enabled"
                rule = _global_rule_record(policy, sources[:3], candidate)
                if not _global_has(global_rules, policy.rule_id):
                    global_rules["rules"].append(rule)
                    _write_global_rules(directory / _GLOBAL_FILE, global_rules)
                ledger_id = _ledger_id(lesson_key, "mechanical_enabled")
                if not _ledger_has(ledger, ledger_id):
                    entry = _ledger_record(
                        policy,
                        decision="mechanical_rule_enabled",
                        occurrence_count=count,
                        sources=sources[:3],
                        candidate_id=candidate_id,
                        rule_id=policy.rule_id,
                    )
                    _append_unique_jsonl(directory / _LEDGER_FILE, entry, "ledger_id", validate_promotion_ledger_entry)
                    ledger.append(entry)
            else:
                global_status = "blocked_missing_test_marker"
                ledger_id = _ledger_id(lesson_key, "mechanical_blocked")
                if not _ledger_has(ledger, ledger_id):
                    entry = _ledger_record(
                        policy,
                        decision="mechanical_rule_blocked_missing_test_marker",
                        occurrence_count=count,
                        sources=sources[:3],
                        candidate_id=candidate_id,
                        block_reason="no distinct triggering event references the required test marker",
                    )
                    _append_unique_jsonl(directory / _LEDGER_FILE, entry, "ledger_id", validate_promotion_ledger_entry)
                    ledger.append(entry)

        # E3 -- efficacy feedback. A rule is enabled at 3 distinct incidents; a
        # 4th or later distinct incident means the enabled rule did not prevent
        # recurrence. Record it once per new count so the signal is durable and
        # a human can refine the rule rather than the system silently re-counting.
        rule_effective: bool | None = None
        if _global_has(global_rules, policy.rule_id):
            rule_effective = count <= 3
            if count > 3:
                ledger_id = _ledger_id(f"{lesson_key}--{count}", "ineffective")
                if not _ledger_has(ledger, ledger_id):
                    entry = _ledger_record(
                        policy,
                        decision="rule_ineffective_recurrence",
                        occurrence_count=count,
                        sources=sources[-2:],
                        candidate_id=candidate_id,
                        rule_id=policy.rule_id,
                        block_reason=(
                            f"lesson recurred at occurrence {count} after its rule was enabled; "
                            "the rule did not prevent recurrence and should be refined"
                        ),
                    )
                    entry["ledger_id"] = ledger_id
                    entry["ledger_sha256"] = _record_hash(
                        {k: v for k, v in entry.items() if k != "ledger_sha256"}
                    )
                    _append_unique_jsonl(directory / _LEDGER_FILE, entry, "ledger_id", validate_promotion_ledger_entry)
                    ledger.append(entry)

        result[lesson_key] = {
            "distinct_incidents": count,
            "candidate_status": candidate_status,
            "global_rule_status": global_status,
            # E2 -- a high-severity single occurrence is surfaced for a human,
            # but never auto-promoted: the schema's two-incident evidence rule holds.
            "severity_review": count < 2 and lesson_key in high_severity,
            "rule_effective": rule_effective,
        }
    return result


def _high_severity_lessons(
    events: Iterable[Mapping[str, Any]], policies: Mapping[str, PromotionPolicy]
) -> set[str]:
    """Lesson keys with at least one promotable high-severity incident."""

    flagged: set[str] = set()
    for event in events:
        lesson_key = event.get("lesson_key")
        if lesson_key not in policies or event.get("type") not in PROMOTABLE_EVENT_TYPES:
            continue
        if event.get("severity") == "high":
            flagged.add(str(lesson_key))
    return flagged


def read_candidate_rules(control_dir: Path) -> list[dict[str, Any]]:
    records = _read_jsonl(_ensure_control_dir(control_dir) / _CANDIDATE_FILE, validate_candidate_rule)
    _require_unique(records, "candidate_id")
    return records


def read_promotion_ledger(control_dir: Path) -> list[dict[str, Any]]:
    records = _read_jsonl(_ensure_control_dir(control_dir) / _LEDGER_FILE, validate_promotion_ledger_entry)
    _require_unique(records, "ledger_id")
    return records


def read_global_rules(control_dir: Path) -> dict[str, Any]:
    path = _ensure_control_dir(control_dir) / _GLOBAL_FILE
    if not path.exists():
        return {"schema_version": 1, "rules": []}
    _reject_symlink(path, "global-rules.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, PromotionError) as error:
        raise PromotionError("global-rules.json is not valid canonical JSON") from error
    validate_global_rules(value)
    return value


def validate_candidate_rule(value: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "candidate_id", "lesson_key", "status", "occurrence_count",
        "trigger_event_ids", "sources", "scope", "enforcement_point", "test_marker",
        "false_positive_risk", "verification_method", "candidate_sha256",
    }
    _require_exact_keys(value, required, "candidate rule")
    if value["schema_version"] != 1 or value["status"] != "candidate" or value["occurrence_count"] != 2:
        raise PromotionError("candidate rule has an invalid promotion state")
    for field in ("candidate_id", "lesson_key", "scope", "enforcement_point", "false_positive_risk", "verification_method"):
        _require_text(value[field], field)
    if value["test_marker"] is not None:
        _require_text(value["test_marker"], "test_marker")
    _validate_sources(value["sources"], value["trigger_event_ids"], minimum=2)
    _validate_hash(value, "candidate_sha256")


def validate_promotion_ledger_entry(value: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "ledger_id", "lesson_key", "decision", "occurrence_count",
        "trigger_event_ids", "sources", "candidate_id", "rule_id", "proposal_target",
        "block_reason", "ledger_sha256",
    }
    _require_exact_keys(value, required, "promotion ledger entry")
    if value["schema_version"] != 1 or value["decision"] not in {
        "candidate_created", "mechanical_rule_enabled", "mechanical_rule_blocked_missing_test_marker",
        "behavior_rule_proposed", "rule_ineffective_recurrence",
    }:
        raise PromotionError("promotion ledger entry has an invalid decision")
    for field in ("ledger_id", "lesson_key", "candidate_id"):
        _require_text(value[field], field)
    if not isinstance(value["occurrence_count"], int) or isinstance(value["occurrence_count"], bool) or value["occurrence_count"] < 2:
        raise PromotionError("occurrence_count must be an integer of at least two")
    _validate_sources(value["sources"], value["trigger_event_ids"], minimum=2)
    for optional in ("rule_id", "proposal_target", "block_reason"):
        if value[optional] is not None:
            _require_text(value[optional], optional)
    _validate_hash(value, "ledger_sha256")


def validate_global_rules(value: Mapping[str, Any]) -> None:
    _require_exact_keys(value, {"schema_version", "rules"}, "global rules")
    if value["schema_version"] != 1 or not isinstance(value["rules"], list):
        raise PromotionError("global rules must contain schema_version 1 and a rules array")
    rule_ids: set[str] = set()
    for rule in value["rules"]:
        if not isinstance(rule, Mapping):
            raise PromotionError("global rule must be an object")
        required = {
            "schema_version", "rule_id", "lesson_key", "status", "occurrence_count",
            "trigger_event_ids", "sources", "scope", "enforcement_point", "test_marker",
            "false_positive_risk", "verification_method", "source_candidate_sha256", "rule_sha256",
        }
        _require_exact_keys(rule, required, "global rule")
        if rule["schema_version"] != 1 or rule["status"] != "enabled" or rule["occurrence_count"] < 3:
            raise PromotionError("global rule has an invalid enabled state")
        for field in ("rule_id", "lesson_key", "scope", "enforcement_point", "test_marker", "false_positive_risk", "verification_method", "source_candidate_sha256"):
            _require_text(rule[field], field)
        if rule["rule_id"] in rule_ids:
            raise PromotionError("global rules contain duplicate rule_id")
        rule_ids.add(rule["rule_id"])
        _validate_sources(rule["sources"], rule["trigger_event_ids"], minimum=3)
        _validate_sha256_text(rule["source_candidate_sha256"], "source_candidate_sha256")
        _validate_hash(rule, "rule_sha256")


def _policy_map(policies: Sequence[PromotionPolicy]) -> dict[str, PromotionPolicy]:
    result: dict[str, PromotionPolicy] = {}
    for policy in policies:
        if policy.lesson_key in result:
            raise PromotionError("duplicate promotion policy lesson_key")
        result[policy.lesson_key] = policy
    return result


def _distinct_incidents(
    events: Iterable[Mapping[str, Any]], policies: Mapping[str, PromotionPolicy]
) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    seen: dict[str, set[str]] = {}
    for event in events:
        _validate_source_event(event)
        lesson_key = event["lesson_key"]
        if lesson_key not in policies or event["type"] not in PROMOTABLE_EVENT_TYPES:
            continue
        incident_id = event["incident_id"]
        if incident_id in seen.setdefault(lesson_key, set()):
            continue
        seen[lesson_key].add(incident_id)
        grouped.setdefault(lesson_key, []).append(
            {
                "event_id": event["event_id"],
                "event_sha256": event["event_sha256"],
                "evidence_ref": event["evidence"]["ref"],
            }
        )
    return grouped


def _validate_source_event(event: Mapping[str, Any]) -> None:
    if not isinstance(event, Mapping):
        raise PromotionError("promotion event must be an object")
    previous = event.get("prev_event_sha256")
    try:
        validated = validate_event(event, previous_sha256=previous)
    except (EventValidationError, TypeError) as error:
        raise PromotionError("promotion event does not satisfy the event contract") from error
    if validated != dict(event):
        raise PromotionError("promotion event is not canonical validated event data")


def _candidate_record(policy: PromotionPolicy, sources: Sequence[dict[str, str]]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 1,
        "candidate_id": _candidate_id(policy.lesson_key),
        "lesson_key": policy.lesson_key,
        "status": "candidate",
        "occurrence_count": 2,
        "trigger_event_ids": [source["event_id"] for source in sources],
        "sources": _public_sources(sources),
        "scope": policy.scope,
        "enforcement_point": policy.enforcement_point,
        "test_marker": policy.test_marker,
        "false_positive_risk": policy.false_positive_risk,
        "verification_method": policy.verification_method,
    }
    record["candidate_sha256"] = _record_hash(record)
    return record


def _ledger_record(
    policy: PromotionPolicy,
    *,
    decision: str,
    occurrence_count: int,
    sources: Sequence[dict[str, str]],
    candidate_id: str,
    rule_id: str | None = None,
    proposal_target: str | None = None,
    block_reason: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema_version": 1,
        "ledger_id": _ledger_id(policy.lesson_key, _decision_suffix(decision)),
        "lesson_key": policy.lesson_key,
        "decision": decision,
        "occurrence_count": occurrence_count,
        "trigger_event_ids": [source["event_id"] for source in sources],
        "sources": _public_sources(sources),
        "candidate_id": candidate_id,
        "rule_id": rule_id,
        "proposal_target": proposal_target,
        "block_reason": block_reason,
    }
    record["ledger_sha256"] = _record_hash(record)
    return record


def _global_rule_record(
    policy: PromotionPolicy,
    sources: Sequence[dict[str, str]],
    candidate: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if candidate is None:
        raise PromotionError("an enabled rule requires its second-occurrence candidate")
    record: dict[str, Any] = {
        "schema_version": 1,
        "rule_id": policy.rule_id,
        "lesson_key": policy.lesson_key,
        "status": "enabled",
        "occurrence_count": 3,
        "trigger_event_ids": [source["event_id"] for source in sources],
        "sources": _public_sources(sources),
        "scope": policy.scope,
        "enforcement_point": policy.enforcement_point,
        "test_marker": policy.test_marker,
        "false_positive_risk": policy.false_positive_risk,
        "verification_method": policy.verification_method,
        "source_candidate_sha256": candidate["candidate_sha256"],
    }
    record["rule_sha256"] = _record_hash(record)
    return record


def _append_unique_jsonl(
    path: Path,
    record: Mapping[str, Any],
    key: str,
    validator: Any,
) -> bool:
    directory = path.parent
    _reject_symlink(directory, "development-control directory")
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as error:
        raise PromotionError(f"could not append {path.name}") from error
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        existing = _read_jsonl(path, validator)
        if any(item[key] == record[key] for item in existing):
            return False
        validator(record)
        _write_all(fd, _canonical_bytes(record) + b"\n")
        os.fsync(fd)
        return True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _write_global_rules(path: Path, value: Mapping[str, Any]) -> None:
    validate_global_rules(value)
    if path.exists():
        _reject_symlink(path, "global-rules.json")
    encoded = _canonical_bytes(value) + b"\n"
    try:
        fd, temporary = tempfile.mkstemp(prefix=".global-rules-", dir=path.parent)
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        raise PromotionError("could not atomically write global-rules.json") from error


def _read_jsonl(path: Path, validator: Any) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    _reject_symlink(path, path.name)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise PromotionError(f"could not read {path.name}") from error
    if not raw:
        return []
    if not raw.endswith(b"\n"):
        raise PromotionError(f"{path.name} must end in a newline")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines(), start=1):
        if not line:
            raise PromotionError(f"{path.name} line {index} is empty")
        try:
            record = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, PromotionError) as error:
            raise PromotionError(f"{path.name} line {index} is invalid JSON") from error
        if not isinstance(record, dict) or _canonical_bytes(record) != line:
            raise PromotionError(f"{path.name} line {index} is not canonical JSON")
        validator(record)
        records.append(record)
    return records


def _ensure_control_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _reject_symlink(path, "development-control directory")
    if not path.is_dir():
        raise PromotionError("development-control path must be a directory")
    return path


def _reject_symlink(path: Path, label: str) -> None:
    try:
        mode = os.lstat(path).st_mode
    except OSError as error:
        raise PromotionError(f"{label} is unavailable") from error
    if stat.S_ISLNK(mode):
        raise PromotionError(f"{label} must not be a symlink")


def _validate_sources(value: Any, event_ids: Any, *, minimum: int) -> None:
    if not isinstance(value, list) or not isinstance(event_ids, list) or len(value) < minimum:
        raise PromotionError("promotion records require enough source events")
    if len(value) != len(event_ids) or len(set(event_ids)) != len(event_ids):
        raise PromotionError("source events and trigger_event_ids must be distinct and aligned")
    for source, event_id in zip(value, event_ids, strict=True):
        if not isinstance(source, Mapping) or set(source) != {"event_id", "event_sha256"}:
            raise PromotionError("source must contain exactly event_id and event_sha256")
        if source["event_id"] != event_id:
            raise PromotionError("source event_id does not match trigger_event_ids")
        _require_text(source["event_id"], "source.event_id")
        _validate_sha256_text(source["event_sha256"], "source.event_sha256")


def _validate_hash(value: Mapping[str, Any], field: str) -> None:
    _validate_sha256_text(value.get(field), field)
    without_hash = dict(value)
    supplied = without_hash.pop(field)
    if supplied != _record_hash(without_hash):
        raise PromotionError(f"{field} does not match canonical record")


def _validate_sha256_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or len(value) != _SHA256_LENGTH or any(character not in "0123456789abcdef" for character in value):
        raise PromotionError(f"{field} must be a sha256 digest")


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise PromotionError(f"{label} has unexpected or missing fields")


def _require_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PromotionError(f"{field} must be non-empty text")


def _record_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PromotionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _write_all(fd: int, content: bytes) -> None:
    cursor = 0
    while cursor < len(content):
        written = os.write(fd, content[cursor:])
        if written <= 0:
            raise PromotionError("short write while appending promotion record")
        cursor += written


def _candidate_id(lesson_key: str) -> str:
    return f"candidate--{lesson_key}"


def _ledger_id(lesson_key: str, suffix: str) -> str:
    return f"promotion--{lesson_key}--{suffix}"


def _decision_suffix(decision: str) -> str:
    return {
        "candidate_created": "candidate",
        "mechanical_rule_enabled": "mechanical_enabled",
        "mechanical_rule_blocked_missing_test_marker": "mechanical_blocked",
        "behavior_rule_proposed": "behavior_proposal",
        # E3: keyed by occurrence count so each new recurrence is a distinct,
        # idempotent ledger entry rather than overwriting the last one.
        "rule_ineffective_recurrence": "ineffective",
    }[decision]


def _public_sources(sources: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return [{"event_id": source["event_id"], "event_sha256": source["event_sha256"]} for source in sources]


def _has_test_marker(sources: Sequence[dict[str, str]], marker: str | None) -> bool:
    return marker is not None and any(marker in source["evidence_ref"] for source in sources)


def _ledger_has(ledger: Sequence[Mapping[str, Any]], ledger_id: str) -> bool:
    return any(entry["ledger_id"] == ledger_id for entry in ledger)


def _global_has(value: Mapping[str, Any], rule_id: str) -> bool:
    return any(rule["rule_id"] == rule_id for rule in value["rules"])


def _replace_or_append(records: list[dict[str, Any]], record: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    return [dict(record) if item[key] == record[key] else item for item in records] or [dict(record)]


def _require_unique(records: Sequence[Mapping[str, Any]], key: str) -> None:
    values = [record[key] for record in records]
    if len(values) != len(set(values)):
        raise PromotionError(f"duplicate {key} in promotion records")
