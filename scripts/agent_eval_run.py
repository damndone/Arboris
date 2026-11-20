#!/usr/bin/env python3
"""Run the v1.9.1 end-to-end Agent evaluation (real provider calls).

Each task gets a fresh project; development scenarios retain their naive first
model, while external questions import data without unrelated estimation. A deterministic simulated user then
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
import ast
import json
import os
import re
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
from agent_eval.external import ExternalTask, blade_tasks, qrdata_fresh, qrdata_subset, replication_tasks  # noqa: E402
from agent_eval.tasks import dev_tasks  # noqa: E402
from agent_eval.budget import BudgetStop, FreeRouteGuard, HeldoutProviderBudget, NvidiaFreeEndpointGuard, RoundBudget, TaskStop  # noqa: E402
from agent_eval.budget import PinnedNvidiaEvaluationGuard  # noqa: E402
from perf_evidence import MIN_FREE_BYTES  # noqa: E402
from workbench.app import app  # noqa: E402
from workbench.artifacts import write_text_durable  # noqa: E402
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


def _hold_machine_awake() -> None:
    """An idle sleep suspends a round mid-request and leaves its usage unknown (2026-10-31).

    Holds only idle sleep, until this process exits; a closed lid still sleeps, and the
    run then records it as ``machine_asleep_s``.
    """
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _taped_replies(round_folder: Path, task_name: str) -> Path:
    """The tape of `task_name` in an earlier round, skipping attempts set aside as stopped."""
    found = sorted(path for path in round_folder.rglob(f"tasks/{task_name}/provider_tape.jsonl*")
                   if "attempt0" not in str(path))
    if len(found) != 1:
        raise RuntimeError(f"replay: expected one tape for {task_name} under {round_folder}, found {len(found)}")
    return found[0].with_suffix("") if found[0].suffix == ".gz" else found[0]


def _round_wrote_project_deny_policy(round_folder: Path) -> bool:
    launcher = round_folder / "run.py"
    try:
        tree = ast.parse(launcher.read_text(encoding="utf-8"), filename=str(launcher))
    except FileNotFoundError:
        return False

    nodes = list(ast.walk(tree))
    assignments = [(target.id, node.value) for node in nodes if isinstance(node, ast.Assign)
                   for target in node.targets if isinstance(target, ast.Name)]

    def mentions_permissions_file(node: ast.AST) -> bool:
        return any(isinstance(part, ast.Constant) and isinstance(part.value, str)
                   and part.value.rsplit("/", 1)[-1] == "agent-permissions.json" for part in ast.walk(node))

    paths = {name for name, value in assignments if mentions_permissions_file(value)}

    def is_permission_path(node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in paths) or mentions_permissions_file(node)

    def has_deny_rules(node: ast.AST) -> bool:
        return isinstance(node, ast.Dict) and any(
            isinstance(key, ast.Constant) and key.value == "deny"
            and isinstance(value, (ast.List, ast.Tuple)) and value.elts
            for key, value in zip(node.keys, node.values, strict=True)
        )

    policies = {name for name, value in assignments if has_deny_rules(value)}

    def serializes_deny(node: ast.AST, method: str) -> bool:
        if not (isinstance(node, ast.Call) and node.args and isinstance(node.func, ast.Attribute)
                and node.func.attr == method and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "json"):
            return False
        payload = node.args[0]
        return has_deny_rules(payload) or (isinstance(payload, ast.Name) and payload.id in policies)

    for node in nodes:
        if (isinstance(node, ast.Call) and node.args and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text" and is_permission_path(node.func.value)
                and serializes_deny(node.args[0], "dumps")):
            return True
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            opened = item.context_expr
            handle = item.optional_vars
            if not (isinstance(handle, ast.Name) and isinstance(opened, ast.Call) and opened.args
                    and isinstance(opened.func, ast.Attribute) and opened.func.attr == "open"
                    and is_permission_path(opened.func.value) and isinstance(opened.args[0], ast.Constant)
                    and opened.args[0].value in {"w", "x", "a"}):
                continue
            for statement in node.body:
                for call in ast.walk(statement):
                    if (serializes_deny(call, "dump") and len(call.args) >= 2
                            and isinstance(call.args[1], ast.Name) and call.args[1].id == handle.id):
                        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tasks", default="", help="comma-separated task ids; empty = all dev tasks")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-nudges", type=int, default=8)
    parser.add_argument("--max-wall-s", type=float, default=1800)
    parser.add_argument("--label", default="", help="round label, e.g. baseline-v190")
    parser.add_argument("--mode", choices=("legacy", "ask", "auto"),
                        help="legacy = v1.9.0 flow; ask / auto = v1.9.1 execution modes")
    parser.add_argument("--execution-policy", choices=("auto_read_only", "proposal_only"),
                        help="override the review policy for a development diagnostic, e.g. browser Auto")
    parser.add_argument("--transport", choices=("headless", "http"), default="headless",
                        help="headless = candidate CLI entry; http = explicit legacy HTTP reproduction")
    parser.add_argument("--suite", choices=("dev", "heldout", "external"), default="dev",
                        help="heldout requires a one-use seal and a separately authorized M5 live gate")
    parser.add_argument("--heldout-approval-receipt", type=Path,
                        help="the explicit human approval receipt for the exact frozen held-out scope")
    parser.add_argument("--check-heldout-admission", action="store_true",
                        help="describe or verify the held-out seal without opening cases or consuming it")
    parser.add_argument("--check-m5-dev-admission", action="store_true",
                        help="describe the exact formal development cohort without loading a provider")
    parser.add_argument("--m5-dev-approval-receipt", type=Path,
                        help="explicit approval of the exact frozen formal development scope")
    parser.add_argument("--round-budget-cny", type=str, help="shared CNY stop; maximum authorized for this batch is 5")
    parser.add_argument("--budget-ledger", type=Path, help="same ledger for both modes, never reset between tasks")
    parser.add_argument("--free-route-ledger", type=Path,
                        help="run on the free Magpie/WorkBuddy provider; every response must report usage.credit == 0")
    parser.add_argument("--nvidia-free-ledger", type=Path,
                        help="explicit NVIDIA Ultra free-listed endpoint opt-in; persist across modes; billing remains unknown")
    parser.add_argument("--nvidia-free-round", choices=("dev8", "qrdata40"),
                        help="NVIDIA default round request limit: dev8=240, qrdata40=1200; use separate ledgers")
    parser.add_argument("--nvidia-free-request-limit", type=int,
                        help="explicit positive NVIDIA round request cap; must match the persistent ledger")
    parser.add_argument("--nvidia-overload-recovery-ledger", type=Path,
                        help="explicit 503-only recovery opt-in; same durable ledger for dev8 and QRData40 (default 10 retries)")
    parser.add_argument("--nvidia-shared-retry-limit", type=int,
                        help="explicit positive NVIDIA shared recovery cap; must match the persistent recovery ledger")
    parser.add_argument("--nvidia-recover-unanswered-read-error", action="store_true",
                        help="explicit v2 recovery policy: additionally permit ReadError before any response headers/body")
    parser.add_argument("--nvidia-recover-unanswered-protocol-error", action="store_true",
                        help="explicit v3 policy: additionally permit RemoteProtocolError before any response headers/body")
    parser.add_argument("--nvidia-recover-complete-http-500", action="store_true",
                        help="explicit v4 policy: additionally permit the observed complete error-only HTTP500 JSON")
    parser.add_argument("--nvidia-recover-complete-http-429", action="store_true",
                        help="explicit v5 policy: additionally permit the observed complete error-only HTTP429 JSON")
    parser.add_argument("--nvidia-shared-serial-ledger", type=Path,
                        help="explicit shared serial HTTP lease/stop/start ledger for overlapping task processes")
    parser.add_argument("--nvidia-skip-incomplete-stream-task", action="store_true",
                        help="explicit task-only failure for partial-output SSE EOF without finish/DONE/usage; never retry")
    parser.add_argument("--allow-low-space-this-round", action="store_true",
                        help="explicit user-authorized storage exception; never releases financial stops")
    parser.add_argument("--project-deny-policy", action="store_true",
                        help="write the M5 project rule (deny external and high) into each project, as the M5 dev "
                             "rounds' own run.py did; needed to replay those rounds faithfully")
    parser.add_argument("--replay-round", type=Path,
                        help="replay the answered model replies taped in this earlier round folder, task by task: "
                             "the current code judges the same calls, with no provider request")
    args = parser.parse_args()
    if args.execution_policy is not None and (args.suite != "dev" or args.check_m5_dev_admission
            or args.m5_dev_approval_receipt is not None or args.replay_round is not None):
        parser.error("execution policy override is only for development diagnostics")
    execution_policy = args.execution_policy or Policy.execution_policy
    if args.replay_round is not None and not args.project_deny_policy:
        try:
            needs_deny_policy = _round_wrote_project_deny_policy(args.replay_round)
        except (OSError, SyntaxError, UnicodeError) as exc:
            parser.error(f"cannot inspect the replay round's run.py: {exc}")
        if needs_deny_policy:
            parser.error("the replay round used a project deny policy; add --project-deny-policy")
    formal = None
    if args.check_m5_dev_admission or args.m5_dev_approval_receipt is not None:
        from agent_eval import m5_dev_admission as admission

        if (args.suite != "dev" or args.tasks or args.mode or args.repeat != 1
                or args.transport != "headless" or args.max_nudges != 8 or args.max_wall_s != 1800
                or args.allow_low_space_this_round or args.replay_round is not None
                or args.heldout_approval_receipt is not None or args.check_heldout_admission
                or any(value for key, value in vars(args).items()
                       if key.startswith("nvidia_") or key in ("round_budget_cny", "budget_ledger", "free_route_ledger"))):
            parser.error("M5 development scope does not accept task, mode, transport, provider, or budget overrides")
        out = args.out.resolve()
        clean = not _git("status", "--porcelain", "--untracked-files=all")
        try:
            tasks = sorted(dev_tasks(), key=lambda task: task.id)
            slots, stability_cases = admission.frozen_slots(tasks)
            formal = admission.scope(_git("rev-parse", "HEAD"), out, slots)
            free = shutil.disk_usage(ROOT).free
            if args.check_m5_dev_admission:
                print(json.dumps({**formal, "launch": False, "candidate_clean": clean, "free_bytes": free,
                                  "run_root_unused": not os.path.lexists(out), "slots": slots}, indent=2))
                return 0
            approval = admission.verify_receipt(args.m5_dev_approval_receipt, formal, clean=clean, out=out,
                                               free_bytes=min(free, shutil.disk_usage(out.parent).free))
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
    heldout = None
    nvidia_heldout = False
    if args.suite == "heldout":
        from agent_eval import heldout_admission

        if (args.tasks or args.repeat != 1 or args.mode is not None or args.transport != "headless"
                or args.replay_round is not None or args.allow_low_space_this_round):
            parser.error("heldout requires the fixed 21-task allocation, one headless exposure per task, and a fresh run root")
        if args.heldout_approval_receipt is None and not args.check_heldout_admission:
            parser.error("heldout requires --heldout-approval-receipt and separate M5 live provider and cost authorization")
        try:
            if args.heldout_approval_receipt is None:
                plan = heldout_admission.describe(ROOT, args.out)
                status = "approval_required"
            else:
                plan = heldout_admission.verify(args.heldout_approval_receipt, repository_root=ROOT, run_root=args.out)
                status = "seal_verified"
        except heldout_admission.HeldoutAdmissionError as exc:
            parser.error(str(exc))
        if args.check_heldout_admission:
            print(json.dumps({**plan, "status": status, "live_gate": "receipt_scoped" if "live_scope" in plan
                              else "separate_m5_authorization_required"}, ensure_ascii=False, indent=2))
            return 0
        if "live_scope" not in plan:
            parser.error("heldout seal verified; separate M5 live provider and cost authorization is still required before launch")
        if (args.max_nudges != heldout_admission.MAX_NUDGES or args.max_wall_s != heldout_admission.MAX_WALL_S
                or any(value for key, value in vars(args).items()
                       if key.startswith("nvidia_") or key in ("round_budget_cny", "budget_ledger", "free_route_ledger"))):
            parser.error("heldout requires the receipt's provider and budget policy without overrides")
        heldout = plan
        nvidia_heldout = plan.get("live_approval_schema") == heldout_admission.NVIDIA_LIVE_APPROVAL_SCHEMA
    elif args.heldout_approval_receipt is not None or args.check_heldout_admission:
        parser.error("heldout admission options require --suite heldout")
    args.mode = args.mode or "legacy"
    if heldout is None and formal is None:
        _hold_machine_awake()
    if sum(item is not None for item in (args.round_budget_cny, args.free_route_ledger, args.nvidia_free_ledger)) > 1:
        parser.error("choose one CNY budget, Magpie free route, or NVIDIA free endpoint guard")
    if (args.nvidia_free_ledger is None) != (args.nvidia_free_round is None):
        parser.error("NVIDIA opt-in requires both --nvidia-free-ledger and --nvidia-free-round")
    if args.nvidia_free_request_limit is not None:
        if args.nvidia_free_ledger is None:
            parser.error("NVIDIA request limit requires the explicit NVIDIA endpoint guard")
        if args.nvidia_free_request_limit <= 0:
            parser.error("NVIDIA request limit must be a positive integer")
    if args.nvidia_overload_recovery_ledger is not None and args.nvidia_free_ledger is None:
        parser.error("NVIDIA overload recovery requires the explicit NVIDIA endpoint guard")
    if args.nvidia_shared_retry_limit is not None:
        if args.nvidia_free_ledger is None or args.nvidia_overload_recovery_ledger is None:
            parser.error("NVIDIA shared retry limit requires the explicit NVIDIA endpoint guard and recovery ledger")
        if args.nvidia_shared_retry_limit <= 0:
            parser.error("NVIDIA shared retry limit must be a positive integer")
    if args.nvidia_recover_unanswered_read_error and args.nvidia_overload_recovery_ledger is None:
        parser.error("unanswered ReadError recovery requires --nvidia-overload-recovery-ledger with a new v2 ledger")
    if args.nvidia_recover_unanswered_protocol_error and not args.nvidia_recover_unanswered_read_error:
        parser.error("protocol recovery requires --nvidia-recover-unanswered-read-error with a new v3 ledger")
    if args.nvidia_recover_complete_http_500 and not args.nvidia_recover_unanswered_protocol_error:
        parser.error("complete HTTP500 recovery requires the explicit v3 policies with a new v4 ledger")
    if args.nvidia_recover_complete_http_429 and not args.nvidia_recover_complete_http_500:
        parser.error("complete HTTP429 recovery requires the explicit HTTP500 v4 policy with a new v5 ledger")
    if args.nvidia_shared_serial_ledger is not None and args.nvidia_free_ledger is None:
        parser.error("shared serial scheduling requires the explicit NVIDIA endpoint guard")
    if args.nvidia_skip_incomplete_stream_task and args.nvidia_free_ledger is None:
        parser.error("incomplete-stream task skip requires the explicit NVIDIA endpoint guard")
    if args.nvidia_free_round is not None:
        if args.transport != "headless" or args.mode not in {"ask", "auto"} or args.repeat != 1:
            parser.error("NVIDIA round requires headless Ask/Auto and repeat=1")
        if not 0 < args.max_wall_s <= 1800:
            parser.error("NVIDIA round requires a positive per-task wall limit no greater than 1800 seconds")
        if args.suite != ("dev" if args.nvidia_free_round == "dev8" else "external"):
            parser.error("NVIDIA dev8 requires dev; qrdata40 requires external; heldout is unauthorized")
    if args.round_budget_cny is not None:
        from decimal import Decimal
        if not args.budget_ledger or not Decimal(0) < Decimal(args.round_budget_cny) <= Decimal(5):
            parser.error("a shared ledger and a positive cap no greater than CNY 5 are required")

    config = load_llm_config()
    out = args.out.resolve()
    if heldout is not None:
        if nvidia_heldout:
            try:
                PinnedNvidiaEvaluationGuard.verify_config(config)
            except ValueError as exc:
                parser.error(str(exc))
        elif not HeldoutProviderBudget.config_matches(config, heldout["live_scope"]):
            parser.error("active provider does not match the held-out live receipt")
        if str(out) != heldout["run_root"]:
            parser.error("held-out output path changed after verification")
        parent = out.parent
        if not parent.is_dir() or min(shutil.disk_usage(path).free for path in (parent, ROOT)) < MIN_FREE_BYTES:
            parser.error("heldout storage preflight failed; a precreated parent and sufficient disk space are required")
    if not config.is_configured():
        print("no model provider configured", file=sys.stderr)
        return 2
    budget = None
    if heldout is not None:
        try:
            heldout_admission.consume(args.heldout_approval_receipt, repository_root=ROOT, run_root=out,
                                      expected_receipt_sha=heldout["approval_receipt_sha256"])
        except heldout_admission.HeldoutAdmissionError as exc:
            parser.error(str(exc))
        _hold_machine_awake()
        out.mkdir(mode=0o700, exist_ok=False)
        fd = os.open(out.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        if nvidia_heldout:
            budget = PinnedNvidiaEvaluationGuard(out / "budget.json", config=config, serial_path=out / "serial.json",
                round_kind="m5-heldout", request_limit=heldout["live_scope"]["max_requests"])
        else:
            budget = HeldoutProviderBudget(out / "budget.json", scope=heldout["live_scope"], config=config)
    elif formal is not None:
        from agent_eval.budget import M5DevNvidiaGuard

        if _git("rev-parse", "HEAD") != formal["candidate_sha"] or _git("status", "--porcelain", "--untracked-files=all"):
            parser.error("M5 candidate changed after receipt verification")
        out.mkdir(mode=0o700, exist_ok=False)
        args.nvidia_free_ledger = out / "budget.json"
        args.nvidia_free_round = "m5-dev"
        args.nvidia_shared_serial_ledger = out / "serial.json"
        try:
            budget = M5DevNvidiaGuard(args.nvidia_free_ledger, config=config, serial_path=args.nvidia_shared_serial_ledger)
        except ValueError as exc:
            parser.error(str(exc))
        write_text_durable(out / "schedule.json", json.dumps({**formal, "slots": slots, "approval_ref": approval}) + "\n")
        _hold_machine_awake()
    elif args.nvidia_free_ledger is not None:
        try:
            budget = NvidiaFreeEndpointGuard(args.nvidia_free_ledger, provider_id=config.provider_id,
                base_url=config.base_url, model=config.model, round_kind=args.nvidia_free_round,
                request_limit=args.nvidia_free_request_limit,
                overload_recovery_ledger=args.nvidia_overload_recovery_ledger,
                shared_retry_limit=args.nvidia_shared_retry_limit,
                recover_unanswered_read_errors=args.nvidia_recover_unanswered_read_error,
                recover_unanswered_protocol_errors=args.nvidia_recover_unanswered_protocol_error,
                recover_complete_http_500_errors=args.nvidia_recover_complete_http_500,
                recover_complete_http_429_errors=args.nvidia_recover_complete_http_429,
                shared_serial_ledger=args.nvidia_shared_serial_ledger,
                skip_incomplete_stream_task=args.nvidia_skip_incomplete_stream_task,
                allow_low_space_this_round=args.allow_low_space_this_round)
        except ValueError as exc:
            parser.error(str(exc))
        if budget.stopped:
            print(f"NVIDIA endpoint guard already stopped ({budget.state['reason']}); no provider call", flush=True)
            return 86
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
    if heldout is not None:
        from agent_eval.heldout import heldout_tasks

        tasks = heldout_tasks()
        ids = {task.id for task in tasks}
        if len(tasks) != heldout["task_count"] or len(ids) != len(tasks) or any(
                not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", task_id) for task_id in ids):
            raise RuntimeError("Invalid sealed held-out task inventory after claim; no task dispatched")
    elif formal is None:
        suite = {"dev": dev_tasks,
                 "external": lambda: [*qrdata_subset(), *blade_tasks(), *replication_tasks(),
                                      *(qrdata_fresh() if selected else [])]}[args.suite]()
        tasks = [task for task in suite if not selected or task.id in selected]
    if selected - {task.id for task in tasks}:
        print(f"unknown task ids: {sorted(selected - {t.id for t in tasks})}", file=sys.stderr)
        return 2
    if args.nvidia_free_round == "dev8" and (not selected or not selected <= {
            "iv_weak.goal", "panel_fe.specific", "leverage.goal", "survival.open"}):
        parser.error("NVIDIA dev8 accepts only explicit subsets of iv_weak.goal,panel_fe.specific,leverage.goal,survival.open")
    if args.nvidia_free_round == "qrdata40" and (not selected or not selected <= {task.id for task in [*qrdata_subset(), *qrdata_fresh()]}):
        parser.error("NVIDIA qrdata40 accepts only explicit subsets of the frozen QRData40 tasks or the fresh QRData tasks")

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
                   "execution_policy": execution_policy, "transport": args.transport,
                   "execution_mode_request": args.mode if args.mode in {"ask", "auto"} else "server_default"},
        "suite": args.suite,
        "initialization": "import-only/v1" if args.suite == 'external' else "scenario-seed-model",
        "tasks": [task.id for task in tasks],
        "round_budget": str(args.budget_ledger) if args.round_budget_cny is not None else None,
        "free_route_ledger": str(args.free_route_ledger) if args.free_route_ledger is not None else None,
        "nvidia_free_endpoint": ({"ledger": str(args.nvidia_free_ledger), "round": args.nvidia_free_round,
            "request_limit": budget.request_limit, "minimum_start_interval_s": 2, "serial": True,
            "billing_status": budget.state["billing_status"],
            "default_output_limit": "forbidden" if formal is not None else "provider_default_unverified",
            "explicit_output_token_limit": 32768, "per_task_wall_s": args.max_wall_s,
            "overload_recovery_ledger": str(args.nvidia_overload_recovery_ledger) if args.nvidia_overload_recovery_ledger is not None else None,
            "recover_unanswered_read_errors": args.nvidia_recover_unanswered_read_error,
            "recover_unanswered_protocol_errors": args.nvidia_recover_unanswered_protocol_error,
            "recover_complete_http_500_errors": args.nvidia_recover_complete_http_500,
            "recover_complete_http_429_errors": args.nvidia_recover_complete_http_429,
            "shared_serial_ledger": str(args.nvidia_shared_serial_ledger) if args.nvidia_shared_serial_ledger is not None else None,
            "max_http_inflight": 1,
            "queue_wait_counts_toward_task_wall": True,
            "skip_incomplete_stream_task": args.nvidia_skip_incomplete_stream_task,
            "overload_recovery_schema": budget.overload_recovery.schema if budget.overload_recovery is not None else None,
            "overload_recovery": ({"shared_retry_limit": budget.overload_recovery.retry_limit, "per_request_retry_limit": 2,
                "delays_s": [60, 120], "eligibility": "complete observed error-only SSE 503 plus DONE; no generated output"
                    + ("; or ReadError before any response headers or body" if args.nvidia_recover_unanswered_read_error else "")
                    + ("; or RemoteProtocolError before any response headers or body" if args.nvidia_recover_unanswered_protocol_error else "")
                    + ("; or the observed complete error-only HTTP500 JSON" if args.nvidia_recover_complete_http_500 else "")
                    + ("; or the observed complete error-only HTTP429 JSON" if args.nvidia_recover_complete_http_429 else "")}
                if args.nvidia_overload_recovery_ledger is not None else None),
            "fallback": "forbidden; actual request URL and model checked"} if args.nvidia_free_ledger is not None else None),
        "provider": {key: getattr(config, key, None) for key in ("provider_id", "base_url", "model", "data_location")},
        "reasoning_effort": formal["reasoning_effort"] if formal is not None else
            os.environ.get("WORKBENCH_REASONING_EFFORT") or "default(high)",
        "low_space_exception": args.allow_low_space_this_round,
    }
    if heldout is not None:
        if meta["git_head"] != heldout["candidate_sha"] or meta["product_dirty"]:
            raise RuntimeError("Candidate changed after claiming heldout; no task dispatched")
        slots = [{"suite": "heldout", "task_id": task.id, "repeat": 1, "mode": slot["mode"]}
                 for task, slot in zip(tasks, heldout["allocation"], strict=True)]
        write_text_durable(out / "schedule.json", json.dumps({"schema": "agent-heldout-schedule/v1", "slots": slots,
            "candidate_sha": heldout["candidate_sha"], "allocation_sha256": heldout["allocation_sha256"],
            "approval_receipt_sha256": heldout["approval_receipt_sha256"]}, indent=2) + "\n")
        for mode in ("ask", "auto"):
            group = out / mode
            (group / "tasks").mkdir(parents=True, exist_ok=False)
            group_meta = {**meta, "tasks": [slot["task_id"] for slot in slots if slot["mode"] == mode],
                          "policy": {**meta["policy"], "mode": mode, "execution_mode_request": mode,
                                     "denied_operation_classes": ["external", "high"]},
                          "round_budget": str(budget.path), "reasoning_effort": heldout["live_scope"]["reasoning_effort"],
                          "approval_receipt_sha256": heldout["approval_receipt_sha256"]}
            if nvidia_heldout:
                group_meta.update(heldout_live_scope=heldout["live_scope"], billing_status=budget.state["billing_status"])
            write_text_durable(group / "run_meta.json", json.dumps(group_meta, indent=2) + "\n")
    elif formal is None:
        (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    dispatch = [(task, args.mode, args.repeat, out) for task in tasks]
    if heldout is not None:
        dispatch = [(task, slot["mode"], 1, out / slot["mode"])
                    for task, slot in zip(tasks, slots, strict=True)]
    if formal is not None:
        dispatch = []
        for mode in ("ask", "auto"):
            for repeat in (1, 3):
                group = out / f"{mode}-r{repeat}"
                group_tasks = [task for task in tasks if (task.id in stability_cases) == (repeat == 3)]
                (group / "tasks").mkdir(parents=True, exist_ok=False)
                group_meta = {**meta, "repeat": repeat, "tasks": [task.id for task in group_tasks],
                              "policy": {**meta["policy"], "mode": mode, "execution_mode_request": mode,
                                         "denied_operation_classes": formal["denied_operation_classes"]},
                              "plan_sha256": formal["plan_sha256"], "approval_ref": approval}
                write_text_durable(group / "run_meta.json", json.dumps(group_meta, indent=2) + "\n")
            dispatch.extend((task, mode, 3 if task.id in stability_cases else 1,
                             out / (f"{mode}-r3" if task.id in stability_cases else f"{mode}-r1")) for task in tasks)

    # The local-request guard admits loopback host names only.
    # A server error is a result to record, not a harness crash.
    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    provider_down = False
    for ordinal, (task, mode, repeats, group) in enumerate(dispatch, start=1):
        if provider_down:
            break
        if (heldout is not None or formal is not None) and budget.stopped:
            print("durable budget stop; no new task started", flush=True)
            return 86
        for rep in range(1, repeats + 1):
            # Each new task is a new measurement, not just each mode/process.
            free = shutil.disk_usage(ROOT).free
            if heldout is not None or formal is not None:
                free = min(free, shutil.disk_usage(out).free)
            if free < MIN_FREE_BYTES and not args.allow_low_space_this_round:
                if budget is not None:
                    budget.stop(f"storage threshold: less than {MIN_FREE_BYTES/1e9:g} GB free before next task")
                print(f"storage stop: {free / 1e9:.3f} GB free; no new task started", flush=True)
                return 86
            name = f"{task.id}.r{rep}"
            directory = group / "tasks" / name
            if heldout is None and formal is None and (directory / "record.json").exists():
                print(f"skip {name} (done)", flush=True)
                continue
            directory.mkdir(parents=True, exist_ok=heldout is None and formal is None)
            started = time.monotonic()
            queue_wait_before = getattr(budget, "serial_queue_wait_s", 0.0)
            external = isinstance(task, ExternalTask)
            record = {"task_id": task.id, "repeat": rep, "language": task.language, "prompt": task.prompt,
                      "transport": args.transport}
            if heldout is not None or formal is not None:
                record.update(mode=mode)
                if heldout is not None:
                    record["ordinal"] = ordinal
            if external:
                record.update({"suite": "external", "source": task.source, "answer": task.answer,
                               "question_type": task.question_type, "reference": task.reference})
            else:
                record.update({"suite": args.suite, "scenario": task.scenario.id, "variant": task.variant, "seed": task.seed})
            try:
                project = create_project(directory, "project")
                if heldout is not None or formal is not None or args.project_deny_policy:
                    permission_file = project.root / "workbench/agent-permissions.json"
                    permission_file.parent.mkdir(parents=True, exist_ok=True)
                    with permission_file.open("x", encoding="utf-8") as stream:
                        json.dump({"deny": [{"class": "external"}, {"class": "high"}]}, stream)
                if external:
                    dataset = directory / task.data_path.name
                    dataset.write_bytes(task.data_path.read_bytes())
                    # External questions must be reachable before any model is
                    # chosen. Keep the frozen suite selection unchanged; record
                    # this setup change for comparison with the historical run.
                    seed_form = {"mode": "import", "model_type": "auto", "y": "", "x": ""}
                    record['setup'] = 'import-only/v1'
                else:
                    dataset = directory / f"{task.scenario.id}.csv"
                    task.scenario.frame(task.seed).to_csv(dataset, index=False)
                    seed_form = task.seed_model
                record["seed_model"] = seed_form
                record["seed_run_id"] = run_id = _seed(project.root, dataset, seed_form)
                record["project_root"] = str(project.root)
                policy = Policy(max_nudges=args.max_nudges, max_wall_s=args.max_wall_s, language=task.language,
                                execution_policy=execution_policy, mode=mode, transport=args.transport)
                if args.replay_round is not None:
                    taped = _taped_replies(args.replay_round, name)
                    record["replay_of"] = str(taped)
                    tape_scope = provider_tape(taped, mode="replay", answered_only=True,
                                               request_log=directory / "replayed_requests.jsonl")
                else:
                    tape_scope = provider_tape(directory / "provider_tape.jsonl", budget=budget)
                with tape_scope as tape:
                    tape.context = {"task": name}
                    try:
                        record["conversation"] = run_conversation(client, project.root, run_id, task.prompt, policy,
                            focus_node='stage:cleaned' if external else 'model:ols_1',
                            progress_path=directory / "conversation-progress.json")
                    finally:
                        if args.replay_round is not None:
                            record["replay"] = {"request_mismatches": tape.mismatches,
                                                "replies_left_unused": len(tape.queue)}
                record["status"] = "ran"
            except TaskStop as exc:
                # An explicitly permitted interruption/incomplete reply ends only this task.
                record["status"] = "task_stopped"
                record["error"] = str(exc)
                progress = directory / "conversation-progress.json"
                if progress.exists():
                    record["conversation"] = json.loads(progress.read_text())
                    record["conversation"]["stop_reason"] = "provider_interruptions"
                    record["conversation"]["completed_marker"] = False
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
                elif str(exc).startswith("replay: no recorded response left"):
                    record["status"] = "replay_exhausted"
                    progress = directory / "conversation-progress.json"
                    if progress.exists():
                        record["conversation"] = json.loads(progress.read_text())
                else:
                    record["status"] = "harness_error"
                    record["error"] = f"{type(exc).__name__}: {exc}"
                    record["traceback"] = traceback.format_exc()
            except Exception as exc:  # recorded, the round continues
                record["status"] = "harness_error"
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["traceback"] = traceback.format_exc()
            if heldout is not None or formal is not None:
                billing = budget.state
                if billing["reservations"] and not billing["stopped"]:
                    reason = "formal task ended with unsettled provider usage"
                    budget.stop(reason)
                    billing.update(stopped=True, reason=reason)
                if billing["stopped"] and record["status"] != "round_budget_stopped":
                    record.update(status="round_budget_stopped", error=billing["reason"])
            record["elapsed_s"] = round(time.monotonic() - started, 1)
            if args.nvidia_shared_serial_ledger is not None:
                record["queue_wait_s"] = round(budget.serial_queue_wait_s - queue_wait_before, 3)
                record["queue_wait_counts_toward_task_wall"] = True
            encoded = json.dumps(record, ensure_ascii=False, indent=1)
            if heldout is not None or formal is not None:
                write_text_durable(directory / "record.json", encoded)
            else:
                (directory / "record.json").write_text(encoded, encoding="utf-8")
            if record["status"] == "round_budget_stopped":
                print(f"{name}: round stopped; no further tasks or provider requests", flush=True)
                return 86
            if (heldout is not None or formal is not None) and record["status"] in ("harness_error", "task_stopped"):
                print(f"{name}: {record['status']}; inspect the first failed receipt; no further tasks", flush=True)
                return 86
            conversation = record.get("conversation") or {}
            # Stop the round when the provider stops serving (402 balance, 5xx):
            # every further task would only record the same failure.
            tape = directory / "provider_tape.jsonl"
            recovered = {entry["key"] for entry in budget.state.get("accepted_unknown_requests", [])} if args.nvidia_free_ledger is not None else set()
            if tape.exists() and any(json.loads(line).get("status") in {402, 500, 502, 503}
                                     and json.loads(line).get("budget_reservation") not in recovered
                                     for line in tape.read_text(encoding="utf-8").splitlines()[-3:]):
                print(f"{name}: provider unavailable; stopping the round", flush=True)
                provider_down = True
                break
            print(f"{name}: {record['status']} {record['elapsed_s']}s actions={conversation.get('user_actions')} "
                  f"stop={conversation.get('stop_reason')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
