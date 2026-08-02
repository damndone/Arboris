"""Read-only, nonblocking health projection for approved domain memory.

Runtime retrieval is the correctness boundary: it omits expired records and
downgrades stale ``suggest_default`` records.  This module deliberately does
less.  It makes the same kinds of risk visible to a developer or CI gate
without modifying the store and without declaring a gate failure merely
because a hint requires review.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Iterable

from .scope import MemoryScope
from .store import DomainMemoryStore, DomainMemoryStoreError


class DomainMemoryPreflightError(ValueError):
    """The read-only preflight could not inspect the configured store."""


@dataclass(frozen=True, slots=True)
class DomainMemoryPreflightFinding:
    memory_id: str
    revision: int
    code: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "memory_id": self.memory_id,
            "revision": self.revision,
            "code": self.code,
        }


@dataclass(frozen=True, slots=True)
class DomainMemoryPreflight:
    approved_count: int
    findings: tuple[DomainMemoryPreflightFinding, ...]

    def lines(self) -> tuple[str, ...]:
        status = "clean" if not self.findings else "attention_required"
        result = [
            "DOMAIN_MEMORY_PREFLIGHT "
            f"status={status} approved={self.approved_count} findings={len(self.findings)}"
        ]
        result.extend(
            "DOMAIN_MEMORY_PREFLIGHT "
            f"memory_id={item.memory_id} revision={item.revision} code={item.code}"
            for item in self.findings
        )
        return tuple(result)


def _timestamp(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DomainMemoryPreflightError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DomainMemoryPreflightError(f"{field} is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise DomainMemoryPreflightError(f"{field} must have a timezone")
    return parsed.astimezone(timezone.utc)


def _finding(
    content: object,
    code: str,
) -> DomainMemoryPreflightFinding:
    return DomainMemoryPreflightFinding(
        memory_id=content.memory_id,
        revision=content.revision,
        code=code,
    )


def _current_approved_contents(store: DomainMemoryStore) -> tuple[object, ...]:
    content_ids = sorted({item.memory_id for item in store.list_content()})
    approved: list[object] = []
    for memory_id in content_ids:
        approval = store.current_approval(memory_id)
        if approval is None:
            continue
        try:
            content = store.get_content(memory_id, approval.content_revision)
        except KeyError as error:
            raise DomainMemoryPreflightError(
                "current approval references an unavailable content revision"
            ) from error
        if content.content_hash != approval.content_hash:
            raise DomainMemoryPreflightError(
                "current approval content hash does not match the content revision"
            )
        approved.append(content)
    return tuple(approved)


def collect_domain_memory_preflight(
    store: DomainMemoryStore,
    *,
    now: str,
    warning_window_seconds: int = 7 * 24 * 60 * 60,
) -> DomainMemoryPreflight:
    """Summarize approved-memory health without changing state or failing a gate."""

    if not isinstance(store, DomainMemoryStore):
        raise DomainMemoryPreflightError("store is required")
    if (
        not isinstance(warning_window_seconds, int)
        or isinstance(warning_window_seconds, bool)
        or not 0 <= warning_window_seconds <= 366 * 24 * 60 * 60
    ):
        raise DomainMemoryPreflightError("warning_window_seconds is invalid")
    now_value = _timestamp(now, field="now")
    warning_at = now_value + timedelta(seconds=warning_window_seconds)
    findings: list[DomainMemoryPreflightFinding] = []
    approved = _current_approved_contents(store)

    for content in approved:
        if store.current_validity(content.memory_id) is None:
            findings.append(_finding(content, "APPROVAL_NOT_ACTIVE"))
            continue
        try:
            review_after = _timestamp(content.review_after, field="review_after")
        except DomainMemoryPreflightError:
            findings.append(_finding(content, "REVIEW_TIMESTAMP_INVALID"))
        else:
            if review_after <= now_value:
                findings.append(_finding(content, "REVIEW_DUE"))
            elif review_after <= warning_at:
                findings.append(_finding(content, "REVIEW_DUE_SOON"))

        if content.expires_at is not None:
            try:
                expires_at = _timestamp(content.expires_at, field="expires_at")
            except DomainMemoryPreflightError:
                findings.append(_finding(content, "EXPIRY_TIMESTAMP_INVALID"))
            else:
                if expires_at <= now_value:
                    findings.append(_finding(content, "EXPIRED"))
                elif expires_at <= warning_at:
                    findings.append(_finding(content, "EXPIRES_SOON"))

        # Inform-only hints are never executable defaults, so absence of a
        # verifier is not a health fault. It is mandatory only when a record
        # requests the stronger suggest_default effect.
        if content.apply_mode != "suggest_default":
            continue
        if content.verifier is None or content.last_validated_at is None:
            findings.append(_finding(content, "VERIFIER_MISSING"))
            continue
        try:
            last_validated_at = _timestamp(
                content.last_validated_at,
                field="last_validated_at",
            )
        except DomainMemoryPreflightError:
            findings.append(_finding(content, "VERIFIER_TIMESTAMP_INVALID"))
            continue
        if last_validated_at > now_value:
            findings.append(_finding(content, "VERIFIER_TIMESTAMP_FUTURE"))
        elif now_value - last_validated_at > timedelta(
            seconds=content.verifier.valid_for_seconds
        ):
            findings.append(_finding(content, "VERIFIER_STALE"))

    findings.sort(key=lambda item: (item.memory_id, item.revision, item.code))
    return DomainMemoryPreflight(
        approved_count=len(approved),
        findings=tuple(findings),
    )


def _scope_json(value: str) -> MemoryScope:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise DomainMemoryPreflightError("scope_json is not valid JSON") from error
    try:
        return MemoryScope.from_dict(payload)
    except Exception as error:
        raise DomainMemoryPreflightError("scope_json is not a valid memory scope") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Print nonblocking approved-memory health findings.")
    parser.add_argument("--root", required=True, help="absolute DomainMemoryStore root")
    parser.add_argument("--scope-json", required=True, help="exact MemoryScope JSON object")
    parser.add_argument("--now", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--warning-window-seconds", type=int, default=7 * 24 * 60 * 60)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        store = DomainMemoryStore(
            Path(args.root),
            _scope_json(args.scope_json),
            create=False,
        )
        preflight = collect_domain_memory_preflight(
            store,
            now=args.now,
            warning_window_seconds=args.warning_window_seconds,
        )
    except (DomainMemoryPreflightError, DomainMemoryStoreError) as error:
        print(f"DOMAIN_MEMORY_PREFLIGHT status=unavailable reason={error}")
        return 2
    for line in preflight.lines():
        print(line)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())


__all__ = [
    "DomainMemoryPreflight",
    "DomainMemoryPreflightError",
    "DomainMemoryPreflightFinding",
    "collect_domain_memory_preflight",
    "main",
]
