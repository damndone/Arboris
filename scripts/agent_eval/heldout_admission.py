"""Verify and claim a one-use v1.9.1 held-out seal before loading cases."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


RELEASE = "v1.9.1"
SOURCE = Path("scripts/agent_eval/heldout.py")
SOURCE_SHA256 = "d75733bc8a46854512f9a2523468caa0491047157e98daa3d1e5de5ab90a0425"
SCENARIOS, VARIANTS = 7, 3
TASK_COUNT = SCENARIOS * VARIANTS
APPROVAL_SCHEMA = "agent-heldout-approval/v1"
LIVE_APPROVAL_SCHEMA = "agent-heldout-live-approval/v2"
NVIDIA_LIVE_APPROVAL_SCHEMA = "agent-heldout-nvidia-live-approval/v3"
DIRECT_BASES = ("https://api.deepseek.com", "https://api.deepseek.com/v1")
DIRECT_MODEL = "deepseek-flash"
MAX_NUDGES, MAX_WALL_S = 8, 1800
CONTEXT_LIMIT, OUTPUT_LIMIT = 1_048_576, 393_216
_RELEASE_WORKTREE = Path(".worktrees/workbench-v1.9.1")
_MARKER = _RELEASE_WORKTREE / "local/agent-eval/heldout-v1.9.1-consumed.json"
_SCOPE_FIELDS = ("release", "candidate_sha", "run_root", "heldout_source_sha256", "allocation_sha256", "task_count")
_APPROVAL_FIELDS = {*_SCOPE_FIELDS, "schema", "historical_exposure_review", "approval_ref"}
_LIVE_FIELDS = {"provider_id", "base_url", "model", "reasoning_effort", "quote", "cap_cny", "max_requests"}
_MAX_RECEIPT_BYTES = 8192


class HeldoutAdmissionError(ValueError):
    """This invocation cannot consume the held-out cohort."""


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "--no-optional-locks", "-C", str(root), *args],
                            check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _json_bytes(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def frozen_allocation() -> tuple[list[dict], str]:
    allocation = [{"ordinal": ordinal, "mode": "auto" if ordinal % 2 else "ask"}
                  for ordinal in range(1, TASK_COUNT + 1)]
    return allocation, hashlib.sha256(_json_bytes(allocation)).hexdigest()


def _require_release_worktree(common: Path) -> None:
    worktree = common.parent / _RELEASE_WORKTREE
    try:
        if worktree.resolve(strict=True) != worktree or not worktree.is_dir():
            raise HeldoutAdmissionError("The canonical v1.9.1 worktree is unavailable at its registered path.")
        top = Path(_git(worktree, "rev-parse", "--show-toplevel")).resolve(strict=True)
        owner = Path(_git(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve(strict=True)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HeldoutAdmissionError("The canonical v1.9.1 worktree is unavailable at its registered path.") from exc
    if top != worktree or owner != common:
        raise HeldoutAdmissionError("The canonical v1.9.1 worktree does not belong to this Git common directory.")


def describe(repository_root: Path, run_root: Path) -> dict:
    """Bind a plan by bytes and ordinal alone. Never import the task source."""
    root = repository_root.resolve()
    try:
        checkout = Path(_git(root, "rev-parse", "--show-toplevel")).resolve(strict=True)
        candidate = _git(root, "rev-parse", "HEAD")
        common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve(strict=True)
        dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=all"))
        with (root / SOURCE).open("rb") as stream:
            source_sha = hashlib.file_digest(stream, "sha256").hexdigest()
        if _git(root, "rev-parse", "HEAD") != candidate:
            raise HeldoutAdmissionError("The candidate changed during held-out verification.")
        out = run_root.resolve()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HeldoutAdmissionError("The candidate, held-out source, or run-root identity could not be checked.") from exc
    if checkout != root or common.name != ".git" or not common.is_dir() or not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise HeldoutAdmissionError("Use the canonical Git checkout and a full source candidate SHA.")
    if source_sha != SOURCE_SHA256:
        raise HeldoutAdmissionError("The held-out source SHA-256 differs from the frozen bytes.")

    _require_release_worktree(common)
    marker = common.parent / _MARKER
    allocation, allocation_sha = frozen_allocation()
    return {"release": RELEASE, "candidate_sha": candidate, "candidate_clean": not dirty,
            "run_root": str(out), "run_root_unused": not os.path.lexists(out),
            "heldout_source_sha256": source_sha, "scenario_count": SCENARIOS, "variants_per_scenario": VARIANTS,
            "task_count": TASK_COUNT, "repeat": 1, "transport": "headless",
            "allocation_policy": "source-order-alternating-auto-first/v1", "allocation": allocation,
            "allocation_sha256": allocation_sha,
            "mode_counts": {"ask": TASK_COUNT // 2, "auto": (TASK_COUNT + 1) // 2},
            "consumption_marker": str(marker), "consumed": os.path.lexists(marker)}


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HeldoutAdmissionError("The held-out approval receipt repeats a JSON field.")
        result[key] = value
    return result


def nvidia_live_scope(max_requests: int) -> dict:
    """Describe the exact free-route policy, without authorizing or claiming it."""
    from .budget import NVIDIA_BASE_URL, NVIDIA_MODEL, NVIDIA_PROVIDER_ID

    if type(max_requests) is not int or not 1 <= max_requests <= 999999:
        raise HeldoutAdmissionError("Invalid NVIDIA held-out request limit.")
    return {
        "provider_id": NVIDIA_PROVIDER_ID, "base_url": NVIDIA_BASE_URL, "model": NVIDIA_MODEL,
        "reasoning_effort": "high", "max_output_tokens": 32768, "max_requests": max_requests,
        "min_start_interval_s": 2, "max_http_inflight": 1, "paid_budget": 0,
        "authorized_data": "heldout fixtures and their generated artifacts",
        "denied_operation_classes": ["external", "high"], "unknown_usage_policy": "stop",
        "recovery": "no additional harness retries",
    }


def _receipt(path: Path) -> tuple[dict, str]:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise HeldoutAdmissionError("The held-out approval receipt must be a regular file.")
            raw = stream.read(_MAX_RECEIPT_BYTES + 1)
        if len(raw) > _MAX_RECEIPT_BYTES:
            raise HeldoutAdmissionError("The held-out approval receipt exceeds its size limit.")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HeldoutAdmissionError("The held-out approval receipt could not be read as JSON.") from exc
    schema = value.get("schema") if type(value) is dict else None
    expected = _APPROVAL_FIELDS
    if schema in (LIVE_APPROVAL_SCHEMA, NVIDIA_LIVE_APPROVAL_SCHEMA):
        expected = expected | {"live_scope"}
    if schema == NVIDIA_LIVE_APPROVAL_SCHEMA:
        expected = expected | {"launch"}
    if (schema not in (APPROVAL_SCHEMA, LIVE_APPROVAL_SCHEMA, NVIDIA_LIVE_APPROVAL_SCHEMA) or set(value) != expected
            or type(value["task_count"]) is not int or not isinstance(value["approval_ref"], str)
            or not 0 < len(value["approval_ref"].strip()) <= 500):
        raise HeldoutAdmissionError("The held-out approval receipt has invalid fields or lacks an approval reference.")
    if value["historical_exposure_review"] != "verified_unexposed":
        raise HeldoutAdmissionError("The held-out approval receipt must record a completed human review of prior exposure.")
    if schema == LIVE_APPROVAL_SCHEMA:
        from .budget import QUOTE, CNY_MISS, CNY_OUTPUT
        from decimal import Decimal

        scope = value["live_scope"]
        if (type(scope) is not dict or set(scope) != _LIVE_FIELDS
                or not isinstance(scope["provider_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", scope["provider_id"])
                or scope["base_url"] not in DIRECT_BASES or scope["model"] != DIRECT_MODEL
                or scope["reasoning_effort"] not in ("high", "none") or scope["quote"] != QUOTE
                or type(scope["max_requests"]) is not int or not 1 <= scope["max_requests"] <= 999999
                or not isinstance(scope["cap_cny"], str) or not re.fullmatch(r"[0-9]{1,6}(\.[0-9]{1,2})?", scope["cap_cny"])
                or Decimal(scope["cap_cny"]) < CONTEXT_LIMIT * CNY_MISS + OUTPUT_LIMIT * CNY_OUTPUT):
            raise HeldoutAdmissionError("Invalid held-out live provider scope, tariff, request limit or CNY cap.")
    if schema == NVIDIA_LIVE_APPROVAL_SCHEMA:
        scope = value["live_scope"]
        if value["launch"] is not True or type(scope) is not dict:
            raise HeldoutAdmissionError("The NVIDIA held-out receipt must explicitly authorize the exact launch.")
        try:
            matches_scope = _json_bytes(scope) == _json_bytes(nvidia_live_scope(scope.get("max_requests")))
        except (ValueError, RecursionError) as exc:
            raise HeldoutAdmissionError("Invalid NVIDIA held-out provider or request policy.") from exc
        if not matches_scope:
            raise HeldoutAdmissionError("Invalid NVIDIA held-out provider or request policy.")
    return value, hashlib.sha256(raw).hexdigest()


def verify(receipt: Path, *, repository_root: Path, run_root: Path) -> dict:
    """Verify receipt scope. The operator supplies the actual human approval record."""
    approval, receipt_sha = _receipt(receipt)
    plan = describe(repository_root, run_root)
    if plan["consumed"]:
        raise HeldoutAdmissionError("The held-out cohort is already consumed in this host clone.")
    if not plan["candidate_clean"] or not plan["run_root_unused"]:
        raise HeldoutAdmissionError("The held-out cohort requires a clean frozen candidate and an unused run root.")
    mismatches = [field for field in _SCOPE_FIELDS if approval[field] != plan[field]]
    if mismatches:
        raise HeldoutAdmissionError("The held-out receipt differs from the frozen scope for " + ", ".join(mismatches) + ".")
    result = {**plan, "approval_ref": approval["approval_ref"], "approval_receipt_sha256": receipt_sha}
    if approval["schema"] in (LIVE_APPROVAL_SCHEMA, NVIDIA_LIVE_APPROVAL_SCHEMA):
        result["live_scope"] = approval["live_scope"]
    if approval["schema"] == NVIDIA_LIVE_APPROVAL_SCHEMA:
        result["live_approval_schema"] = NVIDIA_LIVE_APPROVAL_SCHEMA
    return result


def consume(receipt: Path, *, repository_root: Path, run_root: Path, expected_receipt_sha: str | None = None) -> Path:
    """Claim before opening cases, after an independent live provider and cost gate.

    A crash, partial marker, or later failure leaves the cohort consumed. The
    canonical release worktree owns the marker shared by its Git clone.
    """
    plan = verify(receipt, repository_root=repository_root, run_root=run_root)
    if expected_receipt_sha is not None and plan["approval_receipt_sha256"] != expected_receipt_sha:
        raise HeldoutAdmissionError("The held-out approval receipt changed after preflight.")
    marker = Path(plan["consumption_marker"])
    canonical_root = marker.parents[len(_MARKER.parts) - 1]
    record = {"schema": "agent-heldout-consumed/v1", "consumed_at": datetime.now(UTC).isoformat(),
              **{key: plan[key] for key in (*_SCOPE_FIELDS, "approval_ref", "approval_receipt_sha256")}}
    if "live_scope" in plan:
        record["live_scope"] = plan["live_scope"]
    if "live_approval_schema" in plan:
        record["live_approval_schema"] = plan["live_approval_schema"]
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        with ExitStack() as opened:
            directory = os.open(canonical_root, directory_flags)
            opened.callback(os.close, directory)
            for depth, name in enumerate(_MARKER.parts[:-1]):
                parent = directory
                local_storage = depth >= len(_RELEASE_WORKTREE.parts)
                if local_storage:
                    try:
                        os.mkdir(name, mode=0o700, dir_fd=parent)
                    except FileExistsError:
                        pass
                directory = os.open(name, directory_flags, dir_fd=parent)
                opened.callback(os.close, directory)
                if local_storage:
                    os.fsync(parent)
            fd = os.open(marker.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                stream.write(_json_bytes(record) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(directory)
    except FileExistsError as exc:
        raise HeldoutAdmissionError("The held-out cohort is already consumed in this host clone.") from exc
    except OSError as exc:
        raise HeldoutAdmissionError("The held-out marker could not be committed. Preserve any marker and stop.") from exc
    return marker
