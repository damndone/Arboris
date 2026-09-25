#!/usr/bin/env python3
"""Run natural-language requests through the real Agent HTTP path.

Seeds a scratch project with a synthetic wage dataset and one OLS run, then
sends each case to a fresh chain-Agent session on that run using the
configured LLM provider. Records the assistant answer, tool calls, proposals
and latency per case, for human scoring. This makes real provider calls.

    PYTHONPATH=backend .venv/bin/python scripts/agent_live_eval.py \
        --out /private/tmp/agent-eval --cases scripts/agent_live_eval_cases.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from workbench.app import app  # noqa: E402
from workbench.dev_fixtures.agent_navigation import _seed_source_run  # noqa: E402
from workbench.llm.config import load_llm_config  # noqa: E402
from workbench.projects import create_project  # noqa: E402


def _dataset(path: Path, seed: int = 20260925) -> Path:
    rng = np.random.default_rng(seed)
    n = 400
    education = rng.integers(9, 21, n)
    experience = rng.integers(0, 35, n)
    age = np.clip(education + experience + 6 + rng.integers(-2, 3, n), 18, 70)
    female = rng.binomial(1, 0.48, n)
    region = rng.choice(["north", "south", "east", "west"], n)
    region_effect = pd.Series(region).map({"north": 0.10, "south": -0.08, "east": 0.04, "west": 0.0})
    log_wage = (
        1.2 + 0.08 * education + 0.035 * experience - 0.0006 * experience**2
        - 0.12 * female + region_effect.to_numpy() + rng.normal(0, 0.35, n)
    )
    union_p = 1 / (1 + np.exp(-(-1.0 + 0.04 * experience - 0.05 * (education - 14) + 0.3 * (region == "north"))))
    frame = pd.DataFrame(
        {
            "wage": np.round(np.exp(log_wage), 2),
            "education": education,
            "experience": experience,
            "age": age,
            "female": female,
            "region": region,
            "union": rng.binomial(1, union_p),
            "hours": np.round(rng.normal(40, 6, n), 1),
        }
    )
    frame.loc[rng.choice(n, 12, replace=False), "hours"] = np.nan
    frame.to_csv(path, index=False)
    return path


def _session_messages(root: Path, session_id: str) -> list[dict]:
    path = root / "workbench" / "agent-sessions" / f"{session_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _tool_calls(entries: list[dict]) -> list[dict]:
    calls = []
    for entry in entries:
        payload = entry.get("payload") or {}
        for call in payload.get("tool_calls") or []:
            calls.append({"name": call.get("name") or call.get("tool_id"), "arguments": call.get("arguments")})
    return calls


def _confirm_and_wait(client, root: Path, session_id: str, run_id: str, proposal: dict) -> dict:
    started = time.monotonic()
    confirmed = client.post(
        f"/agent/sessions/{session_id}/proposals/{proposal['proposal_id']}/confirm",
        params={"project_root": str(root)},
        json={
            "revision": proposal["revision"],
            "fingerprint": proposal["fingerprint"],
            "active_head_run_id": run_id,
        },
    )
    body = confirmed.json()
    if confirmed.status_code != 200:
        return {"proposal_id": proposal["proposal_id"], "status": f"http_{confirmed.status_code}", "error": body}
    operation = body.get("operation") or {}
    record_id = operation.get("record_id")
    deadline = time.monotonic() + 300
    while operation.get("status") not in {"completed", "failed", "stale", "cancelled"} and time.monotonic() < deadline:
        time.sleep(1)
        polled = client.get(
            f"/agent/sessions/{session_id}/operations/{record_id}", params={"project_root": str(root)}
        )
        if polled.status_code == 200:
            operation = polled.json().get("operation") or operation
    return {
        "proposal_id": proposal["proposal_id"],
        "operation_id": proposal.get("operation_id"),
        "status": operation.get("status"),
        "error": operation.get("error") or operation.get("failure"),
        "result_run_ids": operation.get("result_run_ids") or operation.get("run_ids"),
        "elapsed_s": round(time.monotonic() - started, 1),
        "operation": operation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--only", default=None, help="comma-separated case ids")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="confirm every pending proposal as the user would, and record execution; "
        "each case then gets its own project so one execution cannot stale another",
    )
    args = parser.parse_args()

    out = args.out.expanduser().resolve()
    scratch = {Path(tempfile.gettempdir()).resolve(), Path("/private/tmp").resolve()}
    if not any(out == item or item in out.parents for item in scratch):
        raise SystemExit(f"refusing non-scratch output root: {out}")
    config = load_llm_config()
    if not config.is_configured():
        raise SystemExit("LLM provider is not configured")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        cases = [case for case in cases if case["id"] in wanted]

    out.mkdir(parents=True, exist_ok=True)
    os.environ["WORKBENCH_INCREMENTAL_CACHE"] = "1"
    dataset = _dataset(out / "wages.csv")

    def seeded(name: str) -> tuple[Path, str]:
        project = out / name
        if not project.exists():
            create_project(out, name)
        return project, _seed_source_run(project, dataset, timeout_s=180.0)

    root, run_id = seeded("project")
    client = TestClient(app)
    results = []
    for case in cases:
        if args.confirm:
            root, run_id = seeded(f"project-{case['id']}")
        created = client.post(
            "/agent/sessions",
            params={"project_root": str(root)},
            json={"role": "chain", "chain_id": f"run:{run_id}", "run_id": run_id, "context_packet": {}},
        )
        created.raise_for_status()
        session_id = created.json()["session_id"]
        started = time.monotonic()
        response = client.post(
            f"/agent/sessions/{session_id}/turns",
            params={"project_root": str(root)},
            json={"question": case["request"]},
        )
        elapsed = round(time.monotonic() - started, 1)
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {"raw": response.text}
        proposals = client.get(
            f"/agent/sessions/{session_id}/proposals", params={"project_root": str(root)}
        )
        executions = []
        if args.confirm and proposals.status_code == 200:
            for proposal in proposals.json().get("proposals", []):
                if proposal.get("status") != "pending":
                    continue
                executions.append(_confirm_and_wait(client, root, session_id, run_id, proposal))
        entries = _session_messages(root, session_id)
        record = {
            "id": case["id"],
            "request": case["request"],
            "expected": case["expected"],
            "http_status": response.status_code,
            "elapsed_s": elapsed,
            "status": body.get("status"),
            "assistant": (body.get("assistant") or {}).get("content") if isinstance(body.get("assistant"), dict) else body.get("assistant"),
            "error": body.get("error") or body.get("detail") or (body.get("raw") if response.status_code >= 400 else None),
            "tool_calls": _tool_calls(entries),
            "proposals": proposals.json() if proposals.status_code == 200 else {"http_status": proposals.status_code},
            "executions": executions,
            "session_id": session_id,
        }
        results.append(record)
        print(
            f"[{case['id']}] http={response.status_code} {elapsed}s "
            f"tools={[c['name'] for c in record['tool_calls']]} "
            f"executions={[item.get('status') for item in executions]}",
            flush=True,
        )

    report = {
        "provider": {"base_url": config.base_url, "model": config.model},
        "source_run_id": run_id,
        "project_root": str(root),
        "results": results,
    }
    (out / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
