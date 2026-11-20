"""Describe the formal development cohort and check its exact launch receipt."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

PLAN_SHA256 = "27110238a5ef0c02bcbf15ac9f020304e259489584ce405dc7b40e4ce7bd5222"
MAX_REQUESTS = 11_880
START_FREE_BYTES = 25 * 1024**3
MODES = ("ask", "auto")


def plan_sha256(slots):
    return hashlib.sha256((json.dumps(slots, separators=(",", ":")) + "\n").encode()).hexdigest()


def frozen_slots(tasks):
    cases = set(Path(__file__).with_name("pass3-cases.txt").read_text(encoding="utf-8").splitlines())
    ids = sorted(task.id for task in tasks)
    slots = [dict(suite="dev", task_id=task_id, mode=mode, repeat=repeat)
             for mode in MODES for task_id in ids for repeat in range(1, 4 if task_id in cases else 2)]
    if plan_sha256(slots) != PLAN_SHA256:
        raise ValueError("M5 development inventory differs from the preregistered plan")
    return slots, cases


def scope(candidate, out, slots):
    from .budget import NVIDIA_BASE_URL, NVIDIA_MODEL, NVIDIA_PROVIDER_ID

    if not re.fullmatch(r"[a-f0-9]{40}", candidate):
        raise ValueError("M5 requires a full Git candidate SHA")
    return {"schema": "agent-m5-dev-approval/v1", "candidate_sha": candidate, "run_root": str(out),
            "plan_sha256": PLAN_SHA256, "slot_count": len(slots), "grader": "v2",
            "provider_id": NVIDIA_PROVIDER_ID, "base_url": NVIDIA_BASE_URL, "model": NVIDIA_MODEL,
            "reasoning_effort": "high", "max_output_tokens": 32768, "max_requests": MAX_REQUESTS,
            "min_start_interval_s": 2, "max_http_inflight": 1, "paid_budget": 0,
            "authorized_data": "development fixtures and their generated artifacts",
            "denied_operation_classes": ["external", "high"], "max_nudges": 8, "max_wall_s": 1800,
            "unknown_usage_policy": "stop", "recovery": "no additional harness retries"}


def verify_receipt(path, expected, *, clean, out, free_bytes):
    try:
        with path.open("rb") as stream:
            receipt = json.loads(stream.read(8193))
        if not isinstance(receipt, dict):
            raise ValueError
        approval = receipt.pop("approval_ref", None)
        approved = {**expected, "launch": True}
        if (not isinstance(approval, str) or not approval.strip()
                or json.dumps(receipt, sort_keys=True) != json.dumps(approved, sort_keys=True)):
            raise ValueError
    except (OSError, ValueError) as exc:
        raise ValueError("M5 development approval receipt must match the exact frozen scope and authorize launch") from exc
    if not clean or os.path.lexists(out) or not out.parent.is_dir():
        raise ValueError("M5 development requires a clean candidate and a fresh output root with an existing parent")
    if free_bytes < START_FREE_BYTES:
        raise ValueError("M5 development needs at least 25 GiB available at launch")
    return approval
