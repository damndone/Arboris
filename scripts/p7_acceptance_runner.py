#!/usr/bin/env python3
"""Manage registry-derived P7 browser acceptance without calling a provider."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Mapping


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))

from workbench.agent.p7_pack_registry import p7_pack_registry  # noqa: E402
from workbench.qa.notebook_acceptance_evidence import (  # noqa: E402
    BrowserConfirmationObservation,
    collect_notebook_completion_evidence,
)
from workbench.qa.p7_acceptance import (  # noqa: E402
    AcceptanceBatch,
    AttemptLedger,
    P7AcceptanceError,
    RatePolicy,
    build_acceptance_batches,
    build_acceptance_manifest,
    load_acceptance_manifest,
    resolve_fixture_catalog,
    workspace_dirty_digest,
    write_once_manifest,
)


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON contains duplicate key: {key}")
        result[key] = value
    return result


def _read_json_object(path: Path, label: str) -> Mapping[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{label} is not readable strict JSON: {error}") from error
    if not isinstance(parsed, Mapping):
        raise ValueError(f"{label} must contain one JSON object")
    return parsed


def _git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _dirty_digest() -> str:
    return workspace_dirty_digest(_ROOT)


def _verified_git_context(args: argparse.Namespace) -> tuple[str, str]:
    actual_head = _git_head()
    actual_dirty = _dirty_digest()
    supplied_head = getattr(args, "git_head", None)
    supplied_dirty = getattr(args, "dirty_digest", None)
    if supplied_head is not None and supplied_head != actual_head:
        raise ValueError("supplied git HEAD does not match the current checkout")
    if supplied_dirty is not None and supplied_dirty != actual_dirty:
        raise ValueError("supplied dirty digest does not match the current checkout")
    return actual_head, actual_dirty


def _created_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _counts(states: Mapping[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for state in states.values():
        status = state.status
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _load_ledger(args: argparse.Namespace) -> AttemptLedger:
    git_head, dirty_digest = _verified_git_context(args)
    manifest = load_acceptance_manifest(
        args.manifest,
        registry=p7_pack_registry,
        expected_git_head=git_head,
        expected_dirty_digest=dirty_digest,
    )
    return AttemptLedger(args.attempts, manifest, registry=p7_pack_registry)


def _work_packet(
    row: object | None, *, admission_is_durable: bool = False
) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        **asdict(row),
        "next_action": (
            "Admission is durable. Open the Workbench Agent in a visible browser, "
            "submit this ordinary user request, inspect the typed proposal, and "
            "wait for a visible user confirmation before execution."
            if admission_is_durable
            else "Run start-attempt before submitting this request in the browser; "
            "the start command returns the admitted work packet."
        ),
    }


def _batch_work_packet(
    batch: object | None, *, admission_is_durable: bool = False
) -> dict[str, object] | None:
    if batch is None:
        return None
    return {
        **asdict(batch),
        "next_action": (
            "Admission is durable. Open the Workbench Agent in a visible browser, "
            "submit this ordinary family request once, verify every typed child is "
            "present, and wait for one visible user confirmation before execution."
            if admission_is_durable
            else "Run start-batch before submitting this family request in the "
            "browser; the start command returns the admitted work packet."
        ),
    }


def _manifest_batch(ledger: AttemptLedger, pack_family: str) -> AcceptanceBatch:
    try:
        return next(
            batch
            for batch in build_acceptance_batches(ledger.manifest.rows)
            if batch.pack_family == pack_family
        )
    except StopIteration as error:
        raise ValueError(
            f"pack family is not in the frozen manifest: {pack_family!r}"
        ) from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a write-once live-registry manifest")
    init.add_argument("--manifest", type=Path, required=True)
    init.add_argument("--fixture-catalog", type=Path)
    init.add_argument("--git-head")
    init.add_argument("--dirty-digest")
    init.add_argument("--provider", required=True)
    init.add_argument("--model", required=True)
    init.add_argument("--capacity", type=int, default=1)
    init.add_argument("--refill-per-second", type=float, required=True)
    init.add_argument("--cost-per-attempt", type=float, default=1.0)
    init.add_argument("--created-at")

    def add_ledger_paths(command: argparse.ArgumentParser) -> None:
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--attempts", type=Path, required=True)
        command.add_argument("--git-head")
        command.add_argument("--dirty-digest")

    status = commands.add_parser("status", help="verify and summarize every row")
    add_ledger_paths(status)

    next_command = commands.add_parser(
        "next", help="show the next browser work packet without submitting it"
    )
    add_ledger_paths(next_command)

    next_batch = commands.add_parser(
        "next-batch", help="show the next family browser packet without submitting it"
    )
    add_ledger_paths(next_batch)

    start = commands.add_parser(
        "start-attempt", help="append an awaiting-confirmation attempt record"
    )
    add_ledger_paths(start)
    start.add_argument("--operation-id", required=True)

    start_batch = commands.add_parser(
        "start-batch", help="atomically start one family browser submission"
    )
    add_ledger_paths(start_batch)
    start_batch.add_argument("--pack-family", required=True)

    record = commands.add_parser(
        "record", help="append a visible lifecycle result to the current attempt"
    )
    add_ledger_paths(record)
    record.add_argument("--operation-id", required=True)
    record.add_argument("--attempt-no", type=int, required=True)
    record.add_argument(
        "--status",
        required=True,
        choices=("running", "completed", "failed", "blocked", "rejected", "cancelled"),
    )
    record.add_argument("--reason-code")
    record.add_argument("--reason-detail")
    record.add_argument("--project-root", type=Path)
    record.add_argument("--notebook-id")
    record.add_argument("--option-id")
    record.add_argument("--option-revision", type=int)
    record.add_argument("--browser-observation", type=Path)
    record.add_argument("--browser-snapshot", type=Path)

    record_batch = commands.add_parser(
        "record-batch", help="atomically record one visible family lifecycle result"
    )
    add_ledger_paths(record_batch)
    record_batch.add_argument("--pack-family", required=True)
    record_batch.add_argument(
        "--status",
        required=True,
        choices=("running", "completed", "failed", "blocked", "rejected", "cancelled"),
    )
    record_batch.add_argument("--reason-code")
    record_batch.add_argument("--reason-detail")
    record_batch.add_argument("--project-root", type=Path)
    record_batch.add_argument("--notebook-id")
    record_batch.add_argument("--option-id")
    record_batch.add_argument("--option-revision", type=int)
    record_batch.add_argument("--browser-observation", type=Path)
    record_batch.add_argument("--browser-snapshot", type=Path)

    retry = commands.add_parser(
        "retry", help="append a new numbered attempt after a terminal failure"
    )
    add_ledger_paths(retry)
    retry.add_argument("--operation-id", required=True)

    retry_batch = commands.add_parser(
        "retry-batch", help="append one new family submission after terminal failure"
    )
    add_ledger_paths(retry_batch)
    retry_batch.add_argument("--pack-family", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            git_head, dirty_digest = _verified_git_context(args)
            fixture_catalog = (
                _read_json_object(args.fixture_catalog, "fixture catalog")
                if args.fixture_catalog
                else None
            )
            fixture_profiles = resolve_fixture_catalog(
                registry=p7_pack_registry,
                catalog=fixture_catalog,
            )
            manifest = build_acceptance_manifest(
                registry=p7_pack_registry,
                git_head=git_head,
                dirty_digest=dirty_digest,
                provider=args.provider,
                model=args.model,
                rate_policy=RatePolicy(
                    capacity=args.capacity,
                    refill_per_second=args.refill_per_second,
                    cost_per_attempt=args.cost_per_attempt,
                ),
                created_at=args.created_at or _created_at(),
                fixture_profiles=fixture_profiles,
            )
            write_once_manifest(args.manifest, manifest)
            ready = sum(
                row.fixture_profile.status == "ready" for row in manifest.rows
            )
            _emit(
                {
                    "command": "init",
                    "manifest": str(args.manifest),
                    "manifest_digest": manifest.manifest_digest,
                    "registry_digest": manifest.registry_digest,
                    "total_rows": len(manifest.rows),
                    "ready": ready,
                    "blocked": len(manifest.rows) - ready,
                    "family_batches": len(build_acceptance_batches(manifest.rows)),
                    "provider_called": False,
                    "confirmation_performed": False,
                }
            )
        elif args.command == "status":
            ledger = _load_ledger(args)
            states = ledger.states()
            _emit(
                {
                    "command": "status",
                    "manifest_digest": ledger.manifest.manifest_digest,
                    "event_count": len(ledger.events()),
                    "counts": _counts(states),
                    "states": {
                        operation_id: asdict(state)
                        for operation_id, state in states.items()
                    },
                }
            )
        elif args.command == "next":
            ledger = _load_ledger(args)
            decision = ledger.next_admission(now=time.time())
            _emit(
                {
                    "command": "next",
                    "row": _work_packet(decision.row),
                    "rate": asdict(decision.rate),
                    "action": decision.action,
                    "attempt_no": decision.attempt_no,
                    "requires_provider_admission": (
                        decision.requires_provider_admission
                    ),
                    "provider_called": False,
                    "confirmation_performed": False,
                }
            )
        elif args.command == "next-batch":
            ledger = _load_ledger(args)
            decision = ledger.next_batch_admission(now=time.time())
            _emit(
                {
                    "command": "next-batch",
                    "batch": _batch_work_packet(decision.batch),
                    "rate": asdict(decision.rate),
                    "action": decision.action,
                    "attempt_no": decision.attempt_no,
                    "submission_id": decision.submission_id,
                    "requires_provider_admission": (
                        decision.requires_provider_admission
                    ),
                    "provider_called": False,
                    "confirmation_performed": False,
                }
            )
        elif args.command == "start-attempt":
            ledger = _load_ledger(args)
            event = ledger.start_attempt(
                args.operation_id,
                occurred_at=time.time(),
            )
            row = next(
                row
                for row in ledger.manifest.rows
                if row.operation_id == args.operation_id
            )
            _emit(
                {
                    "command": "start-attempt",
                    "attempt": event.to_dict(),
                    "row": _work_packet(row, admission_is_durable=True),
                    "provider_called": False,
                    "confirmation_performed": False,
                }
            )
        elif args.command == "start-batch":
            ledger = _load_ledger(args)
            events = ledger.start_batch(
                args.pack_family,
                occurred_at=time.time(),
            )
            _emit(
                {
                    "command": "start-batch",
                    "attempts": [event.to_dict() for event in events],
                    "batch": _batch_work_packet(
                        _manifest_batch(ledger, args.pack_family),
                        admission_is_durable=True,
                    ),
                    "provider_called": False,
                    "confirmation_performed": False,
                }
            )
        elif args.command == "record":
            ledger = _load_ledger(args)
            evidence = None
            evidence_arguments = (
                args.project_root,
                args.notebook_id,
                args.option_id,
                args.option_revision,
                args.browser_observation,
                args.browser_snapshot,
            )
            if args.status == "completed":
                if any(value is None for value in evidence_arguments):
                    raise ValueError(
                        "completed status requires project_root, notebook_id, "
                        "option_id, option_revision, and browser_observation"
                    )
                observation = BrowserConfirmationObservation.from_mapping(
                    _read_json_object(
                        args.browser_observation,
                        "browser confirmation observation",
                    )
                )
                authority = ledger.completion_authority(args.operation_id)
                evidence = collect_notebook_completion_evidence(
                    project_root=args.project_root,
                    operation_id=args.operation_id,
                    notebook_id=args.notebook_id,
                    option_id=args.option_id,
                    option_revision=args.option_revision,
                    observation=observation,
                    browser_snapshot=args.browser_snapshot,
                    authority=authority,
                )
            elif any(value is not None for value in evidence_arguments):
                raise ValueError(
                    "Notebook completion evidence is only valid for completed status"
                )
            event = ledger.record_status(
                args.operation_id,
                args.attempt_no,
                args.status,
                occurred_at=time.time(),
                evidence=evidence,
                reason_code=args.reason_code,
                reason_detail=args.reason_detail,
            )
            _emit(
                {
                    "command": "record",
                    "attempt": event.to_dict(),
                    "evidence_collected": evidence is not None,
                }
            )
        elif args.command == "record-batch":
            ledger = _load_ledger(args)
            batch = _manifest_batch(ledger, args.pack_family)
            evidence_by_operation = None
            evidence_arguments = (
                args.project_root,
                args.notebook_id,
                args.option_id,
                args.option_revision,
                args.browser_observation,
                args.browser_snapshot,
            )
            if args.status == "completed":
                if any(value is None for value in evidence_arguments):
                    raise ValueError(
                        "completed batch status requires project_root, notebook_id, "
                        "option_id, option_revision, and browser_observation"
                    )
                observation = BrowserConfirmationObservation.from_mapping(
                    _read_json_object(
                        args.browser_observation,
                        "browser confirmation observation",
                    )
                )
                authority = ledger.completion_authority(batch.operation_ids[0])
                evidence_by_operation = {
                    operation_id: collect_notebook_completion_evidence(
                        project_root=args.project_root,
                        operation_id=operation_id,
                        notebook_id=args.notebook_id,
                        option_id=args.option_id,
                        option_revision=args.option_revision,
                        observation=observation,
                        browser_snapshot=args.browser_snapshot,
                        authority=authority,
                    )
                    for operation_id in batch.operation_ids
                }
            elif any(value is not None for value in evidence_arguments):
                raise ValueError(
                    "Notebook completion evidence is only valid for completed status"
                )
            events = ledger.record_batch_status(
                args.pack_family,
                args.status,
                occurred_at=time.time(),
                evidence_by_operation=evidence_by_operation,
                reason_code=args.reason_code,
                reason_detail=args.reason_detail,
            )
            _emit(
                {
                    "command": "record-batch",
                    "attempts": [event.to_dict() for event in events],
                    "evidence_collected": (
                        len(evidence_by_operation)
                        if evidence_by_operation is not None
                        else 0
                    ),
                }
            )
        elif args.command == "retry":
            ledger = _load_ledger(args)
            event = ledger.retry(
                args.operation_id,
                occurred_at=time.time(),
            )
            _emit(
                {
                    "command": "retry",
                    "attempt": event.to_dict(),
                    "provider_called": False,
                    "confirmation_performed": False,
                }
            )
        elif args.command == "retry-batch":
            ledger = _load_ledger(args)
            events = ledger.retry_batch(
                args.pack_family,
                occurred_at=time.time(),
            )
            _emit(
                {
                    "command": "retry-batch",
                    "attempts": [event.to_dict() for event in events],
                    "provider_called": False,
                    "confirmation_performed": False,
                }
            )
        else:  # pragma: no cover - argparse makes this unreachable.
            raise ValueError("unsupported command")
    except (P7AcceptanceError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {"error": type(error).__name__, "message": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
