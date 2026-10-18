#!/usr/bin/env python3
"""Run the v1.9.1 end-to-end Agent evaluation (real provider calls).

Each task gets a fresh project with its scenario's data and the naive first
model a person would have run on import; a deterministic simulated user then
drives the conversation (see ``agent_eval/runner.py``). Every provider exchange
is recorded with its usage (``agent_eval/recorder.py``), and the project state
is kept for grading (``agent_eval_grade.py``).

    PYTHONPATH=backend .venv/bin/python scripts/agent_eval_run.py \
        --out local/agent-eval/baseline-v190 --tasks cs_hetero.open,iv_valid.specific

Heavy and paid: run it alone on the machine, and only for the rounds the
objective names (baseline, two mid-term rounds, final).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from agent_eval.recorder import provider_tape  # noqa: E402
from agent_eval.runner import Policy, run_conversation  # noqa: E402
from agent_eval.tasks import dev_tasks  # noqa: E402
from workbench.app import app  # noqa: E402
from workbench.dev_fixtures.agent_navigation import _wait_for_terminal_run  # noqa: E402
from workbench.events import get_event_manager  # noqa: E402
from workbench.llm.config import load_llm_config  # noqa: E402
from workbench.projects import create_project  # noqa: E402
from workbench.services.run_service import _submit_run  # noqa: E402


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()


def _seed(root: Path, dataset: Path, form: dict[str, str]) -> str:
    events = get_event_manager()
    deadline = time.monotonic() + 120
    while not events.try_acquire_slot():
        if time.monotonic() >= deadline:
            raise TimeoutError("timed out waiting for the run slot")
        time.sleep(0.05)
    try:
        result = _submit_run(root, form=form, upload_bytes=dataset.read_bytes(),
                             upload_filename=dataset.name, started_at="agent-eval-seed")
    except Exception:
        events.release_slot(None)
        raise
    _wait_for_terminal_run(root, result["run_id"], timeout_s=300)
    return result["run_id"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tasks", default="", help="comma-separated task ids; empty = all dev tasks")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-nudges", type=int, default=8)
    parser.add_argument("--max-wall-s", type=float, default=1800)
    parser.add_argument("--label", default="", help="round label, e.g. baseline-v190")
    args = parser.parse_args()

    config = load_llm_config()
    if not config.is_configured():
        print("no model provider configured", file=sys.stderr)
        return 2
    selected = {item for item in args.tasks.split(",") if item}
    tasks = [task for task in dev_tasks() if not selected or task.id in selected]
    if selected - {task.id for task in tasks}:
        print(f"unknown task ids: {sorted(selected - {t.id for t in tasks})}", file=sys.stderr)
        return 2

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    meta = {
        "label": args.label,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git_head": _git("rev-parse", "HEAD"),
        # The product tree the run exercised: backend and frontend only, so
        # harness edits do not change it.
        "product_tree": {path: _git("rev-parse", f"HEAD:{path}") for path in ("backend", "frontend")},
        "product_dirty": bool(_git("status", "--porcelain", "--", "backend", "frontend")),
        "model": config.model,
        "base_url_host": config.base_url.split("/")[2] if "//" in config.base_url else config.base_url,
        "repeat": args.repeat,
        "policy": {"max_nudges": args.max_nudges, "max_wall_s": args.max_wall_s},
        "tasks": [task.id for task in tasks],
    }
    (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # The local-request guard admits loopback host names only.
    client = TestClient(app, base_url="http://127.0.0.1")
    for task in tasks:
        for rep in range(1, args.repeat + 1):
            name = f"{task.id}.r{rep}"
            directory = out / "tasks" / name
            if (directory / "record.json").exists():
                print(f"skip {name} (done)", flush=True)
                continue
            directory.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            record = {"task_id": task.id, "repeat": rep, "scenario": task.scenario.id, "variant": task.variant,
                      "language": task.language, "prompt": task.prompt, "seed": task.seed}
            try:
                project = create_project(directory, "project")
                dataset = directory / f"{task.scenario.id}.csv"
                task.scenario.frame(task.seed).to_csv(dataset, index=False)
                record["seed_run_id"] = run_id = _seed(project.root, dataset, task.seed_model)
                record["project_root"] = str(project.root)
                policy = Policy(max_nudges=args.max_nudges, max_wall_s=args.max_wall_s, language=task.language)
                with provider_tape(directory / "provider_tape.jsonl") as tape:
                    tape.context = {"task": name}
                    record["conversation"] = run_conversation(client, project.root, run_id, task.prompt, policy)
                record["status"] = "ran"
            except Exception as exc:  # recorded, the round continues
                record["status"] = "harness_error"
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["traceback"] = traceback.format_exc()
            record["elapsed_s"] = round(time.monotonic() - started, 1)
            (directory / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            conversation = record.get("conversation") or {}
            print(f"{name}: {record['status']} {record['elapsed_s']}s actions={conversation.get('user_actions')} "
                  f"stop={conversation.get('stop_reason')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
