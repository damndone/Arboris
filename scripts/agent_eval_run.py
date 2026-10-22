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
import shutil
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
from agent_eval.external import ExternalTask, blade_tasks, qrdata_subset, replication_tasks, seed_model_for  # noqa: E402
from agent_eval.heldout import heldout_tasks  # noqa: E402
from agent_eval.tasks import dev_tasks  # noqa: E402
from agent_eval.budget import BudgetStop, FreeRouteGuard, RoundBudget  # noqa: E402
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
    parser.add_argument("--mode", choices=("legacy", "ask", "auto"), default="legacy",
                        help="legacy = v1.9.0 flow; ask / auto = v1.9.1 execution modes")
    parser.add_argument("--transport", choices=("headless", "http"), default="headless",
                        help="headless = candidate CLI entry; http = explicit legacy HTTP reproduction")
    parser.add_argument("--suite", choices=("dev", "heldout", "external"), default="dev",
                        help="heldout is run once, at the final evaluation only")
    parser.add_argument("--round-budget-cny", type=str, help="shared CNY stop; maximum authorized for this batch is 5")
    parser.add_argument("--budget-ledger", type=Path, help="same ledger for both modes, never reset between tasks")
    parser.add_argument("--free-route-ledger", type=Path,
                        help="run on the free Magpie/WorkBuddy provider; every response must report usage.credit == 0")
    parser.add_argument("--allow-low-space-this-round", action="store_true",
                        help="explicit user-authorized storage exception; never releases financial stops")
    args = parser.parse_args()
    if args.round_budget_cny is not None and args.free_route_ledger is not None:
        parser.error("choose either a CNY round budget or the free route, not both")
    if args.round_budget_cny is not None:
        from decimal import Decimal
        if not args.budget_ledger or not Decimal(0) < Decimal(args.round_budget_cny) <= Decimal(5):
            parser.error("a shared ledger and a positive cap no greater than CNY 5 are required")

    config = load_llm_config()
    if not config.is_configured():
        print("no model provider configured", file=sys.stderr)
        return 2
    budget = None
    if args.round_budget_cny is not None:
        if config.model != "deepseek-flash" or args.suite != "dev":
            parser.error("the authorized small budget is pinned to deepseek-flash development tasks")
        # The approved handoff pins this provider's 1M context. The guard
        # observes documented server output defaults; no model config is changed.
        budget = RoundBudget(args.budget_ledger, cap_cny=args.round_budget_cny, context_tokens=1_048_576)
        if args.allow_low_space_this_round:
            budget.resume_storage_stop()
        if budget.stopped:
            print("shared round budget already stopped; no provider call", flush=True)
            return 86
    if args.free_route_ledger is not None:
        try:
            budget = FreeRouteGuard(args.free_route_ledger, provider_id=config.provider_id, base_url=config.base_url)
        except ValueError as exc:
            parser.error(str(exc))
        if args.allow_low_space_this_round:
            budget.resume_storage_stop()
        if budget.stopped:
            print(f"free-route guard already stopped ({budget.state['reason']}); no provider call", flush=True)
            return 86
    selected = {item for item in args.tasks.split(",") if item}
    suite = {"dev": dev_tasks, "heldout": heldout_tasks,
             "external": lambda: [*qrdata_subset(), *blade_tasks(), *replication_tasks()]}[args.suite]()
    tasks = [task for task in suite if not selected or task.id in selected]
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
        "transport": args.transport,
        "policy": {"max_nudges": args.max_nudges, "max_wall_s": args.max_wall_s, "mode": args.mode,
                   "execution_policy": "proposal_only", "transport": args.transport,
                   "execution_mode_request": args.mode if args.mode in {"ask", "auto"} else "server_default"},
        "suite": args.suite,
        "tasks": [task.id for task in tasks],
        "round_budget": str(args.budget_ledger) if args.round_budget_cny is not None else None,
        "free_route_ledger": str(args.free_route_ledger) if args.free_route_ledger is not None else None,
        "provider": {key: getattr(config, key, None) for key in ("provider_id", "base_url", "model", "data_location")},
        "low_space_exception": args.allow_low_space_this_round,
    }
    (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # The local-request guard admits loopback host names only.
    # A server error is a result to record, not a harness crash.
    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    provider_down = False
    for task in tasks:
        if provider_down:
            break
        for rep in range(1, args.repeat + 1):
            # Each new task is a new measurement, not just each mode/process.
            free = shutil.disk_usage(ROOT).free
            if free < 10_000_000_000 and not args.allow_low_space_this_round:
                if budget is not None:
                    budget.stop("storage threshold: less than 10 GB free before next task")
                print(f"storage stop: {free / 1e9:.3f} GB free; no new task started", flush=True)
                return 86
            name = f"{task.id}.r{rep}"
            directory = out / "tasks" / name
            if (directory / "record.json").exists():
                print(f"skip {name} (done)", flush=True)
                continue
            directory.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            external = isinstance(task, ExternalTask)
            record = {"task_id": task.id, "repeat": rep, "language": task.language, "prompt": task.prompt,
                      "transport": args.transport}
            if external:
                record.update({"suite": "external", "source": task.source, "answer": task.answer,
                               "question_type": task.question_type, "reference": task.reference})
            else:
                record.update({"suite": args.suite, "scenario": task.scenario.id, "variant": task.variant, "seed": task.seed})
            try:
                project = create_project(directory, "project")
                if external:
                    dataset = directory / task.data_path.name
                    dataset.write_bytes(task.data_path.read_bytes())
                    seed_form = seed_model_for(dataset)
                else:
                    dataset = directory / f"{task.scenario.id}.csv"
                    task.scenario.frame(task.seed).to_csv(dataset, index=False)
                    seed_form = task.seed_model
                record["seed_model"] = seed_form
                record["seed_run_id"] = run_id = _seed(project.root, dataset, seed_form)
                record["project_root"] = str(project.root)
                policy = Policy(max_nudges=args.max_nudges, max_wall_s=args.max_wall_s, language=task.language,
                                mode=args.mode, transport=args.transport)
                with provider_tape(directory / "provider_tape.jsonl", budget=budget) as tape:
                    tape.context = {"task": name}
                    record["conversation"] = run_conversation(client, project.root, run_id, task.prompt, policy,
                        progress_path=directory / "conversation-progress.json")
                record["status"] = "ran"
            except BudgetStop as exc:
                record["status"] = "round_budget_stopped"
                record["error"] = str(exc)
                progress = directory / "conversation-progress.json"
                if progress.exists():
                    record["conversation"] = json.loads(progress.read_text())
                    record["conversation"]["stop_reason"] = "round_budget_stopped"
            except RuntimeError as exc:
                # The person's first step (import plus a first model) failed, so in
                # v1.9.0 there is no run for the Agent to talk to: the task is
                # unreachable, which counts against the version, not the harness.
                if "fixture run" in str(exc) and "ended" in str(exc):
                    record["status"] = "unreachable"
                    record["error"] = f"{type(exc).__name__}: {exc}"
                else:
                    record["status"] = "harness_error"
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    record["traceback"] = traceback.format_exc()
            except Exception as exc:  # recorded, the round continues
                record["status"] = "harness_error"
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["traceback"] = traceback.format_exc()
            record["elapsed_s"] = round(time.monotonic() - started, 1)
            (directory / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
            if record["status"] == "round_budget_stopped":
                print(f"{name}: round stopped; no further tasks or provider requests", flush=True)
                return 86
            conversation = record.get("conversation") or {}
            # Stop the round when the provider stops serving (402 balance, 5xx):
            # every further task would only record the same failure.
            tape = directory / "provider_tape.jsonl"
            if tape.exists() and any(json.loads(line).get("status") in {402, 500, 502, 503}
                                     for line in tape.read_text(encoding="utf-8").splitlines()[-3:]):
                print(f"{name}: provider unavailable; stopping the round", flush=True)
                provider_down = True
                break
            print(f"{name}: {record['status']} {record['elapsed_s']}s actions={conversation.get('user_actions')} "
                  f"stop={conversation.get('stop_reason')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
