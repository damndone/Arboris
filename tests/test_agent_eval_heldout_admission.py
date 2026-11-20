"""Exercise held-out admission with synthetic bytes and no provider or case imports."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import builtins
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import sys
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
CANDIDATE = "a" * 40


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    sealed_cases = ModuleType("agent_eval.heldout")
    sealed_cases.heldout_tasks = lambda: pytest.fail("held-out task construction was reached")
    monkeypatch.setitem(sys.modules, "agent_eval.heldout", sealed_cases)
    spec = importlib.util.spec_from_file_location("offline_heldout_runner_test", SCRIPTS / "agent_eval_run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "heldout_tasks" not in vars(module), "the evaluation runner still imports held-out cases"
    original_import = builtins.__import__

    def protected_import(name, *args, **kwargs):
        if name == "agent_eval.heldout" and not getattr(sealed_cases, "synthetic_dispatch", False):
            pytest.fail("the held-out task module was imported")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", protected_import)
    monkeypatch.setattr(module, "_hold_machine_awake", lambda: None)
    monkeypatch.setattr(module, "load_llm_config", lambda: pytest.fail("provider configuration was reached"))
    return module


@pytest.fixture
def sealed_source(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    assert importlib.util.find_spec("agent_eval.heldout_admission") is not None, "missing held-out seal helper"
    from agent_eval import heldout_admission as admission

    canonical = tmp_path / "canonical"
    common_dir = canonical / ".git"
    common_dir.mkdir(parents=True)
    (canonical / ".worktrees/workbench-v1.9.1").mkdir(parents=True)
    source = b"synthetic held-out manifest placeholder, not a case\n"
    source_sha = hashlib.sha256(source).hexdigest()
    monkeypatch.setattr(admission, "SOURCE_SHA256", source_sha)
    roots = [tmp_path / "candidate-a", tmp_path / "candidate-b"]
    for root in roots:
        path = root / "scripts/agent_eval/heldout.py"
        path.parent.mkdir(parents=True)
        path.write_bytes(source)

    def git(root, *args):
        return {
            ("rev-parse", "--show-toplevel"): str(root),
            ("rev-parse", "HEAD"): CANDIDATE,
            ("rev-parse", "--path-format=absolute", "--git-common-dir"): str(common_dir),
            ("status", "--porcelain", "--untracked-files=all"): "",
        }[args]

    monkeypatch.setattr(admission, "_git", git)
    return admission, roots


def _invoke(monkeypatch, runner, out, *options):
    monkeypatch.setattr(sys, "argv", ["agent_eval_run.py", "--suite", "heldout", "--out", str(out), *options])
    return runner.main()


def _approval(admission, root, out, path, **changes):
    proposed = admission.describe(root, out)
    receipt = {
        "schema": "agent-heldout-approval/v1",
        "release": proposed["release"],
        "candidate_sha": proposed["candidate_sha"],
        "run_root": proposed["run_root"],
        "heldout_source_sha256": proposed["heldout_source_sha256"],
        "allocation_sha256": proposed["allocation_sha256"],
        "task_count": proposed["task_count"],
        "historical_exposure_review": "verified_unexposed",
        "approval_ref": "synthetic test receipt only",
        **changes,
    }
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def test_ordinary_heldout_invocation_stops_before_config_or_output(runner, tmp_path, monkeypatch, capsys):
    out = tmp_path / "unused"
    with pytest.raises(SystemExit) as refused:
        _invoke(monkeypatch, runner, out)
    assert refused.value.code == 2 and "--heldout-approval-receipt" in capsys.readouterr().err
    assert not out.exists()


def test_dry_check_reports_fixed_ordinal_allocation_without_consuming(runner, sealed_source, tmp_path, monkeypatch, capsys):
    admission, (root, _) = sealed_source
    out = tmp_path / "unused"
    monkeypatch.setattr(runner, "ROOT", root)
    assert _invoke(monkeypatch, runner, out, "--check-heldout-admission") == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["status"] == "approval_required"
    assert plan["task_count"] == 21 and plan["mode_counts"] == {"ask": 10, "auto": 11}
    assert [(slot["ordinal"], slot["mode"]) for slot in plan["allocation"]] == [
        (ordinal, "auto" if ordinal % 2 else "ask") for ordinal in range(1, 22)
    ]
    assert not out.exists() and not Path(plan["consumption_marker"]).exists()


def test_verified_receipt_is_read_only_and_cannot_bypass_live_cost_gate(runner, sealed_source, tmp_path, monkeypatch, capsys):
    admission, (root, _) = sealed_source
    out = tmp_path / "unused"
    receipt = _approval(admission, root, out, tmp_path / "synthetic-approval.json")
    monkeypatch.setattr(runner, "ROOT", root)
    options = ("--heldout-approval-receipt", str(receipt))
    assert _invoke(monkeypatch, runner, out, *options, "--check-heldout-admission") == 0
    assert json.loads(capsys.readouterr().out)["status"] == "seal_verified"
    with pytest.raises(SystemExit) as refused:
        _invoke(monkeypatch, runner, out, *options, "--free-route-ledger", str(tmp_path / "unguarded.json"))
    assert refused.value.code == 2 and "separate M5 live provider and cost authorization" in capsys.readouterr().err
    plan = admission.describe(root, out)
    assert not out.exists() and not Path(plan["consumption_marker"]).exists()
    assert not (tmp_path / "unguarded.json").exists()


LIVE_SCOPE = {"provider_id": "synthetic-direct", "base_url": "https://api.deepseek.com/v1",
              "model": "deepseek-flash", "reasoning_effort": "high", "cap_cny": "20.00",
              "max_requests": 50, "quote": "deepseek-flash-cny-peak-2026-10-21"}
NVIDIA_SCHEMA = "agent-heldout-nvidia-live-approval/v3"
NVIDIA_LIVE_SCOPE = {
    "provider_id": "nvidia-nemotron-free",
    "base_url": "https://integrate.api.nvidia.com/v1",
    "model": "nvidia/nemotron-3-ultra-550b-a55b",
    "reasoning_effort": "high",
    "max_output_tokens": 32768,
    "max_requests": 2,
    "min_start_interval_s": 2,
    "max_http_inflight": 1,
    "paid_budget": 0,
    "authorized_data": "heldout fixtures and their generated artifacts",
    "denied_operation_classes": ["external", "high"],
    "unknown_usage_policy": "stop",
    "recovery": "no additional harness retries",
}


@pytest.fixture(params=["v2", "v3"])
def live_synthetic(request, runner, sealed_source, tmp_path, monkeypatch):
    from workbench.llm.config import LLMConfig

    admission, (root, _) = sealed_source
    out = tmp_path / "sealed-new-run"
    nvidia = request.param == "v3"
    scope = NVIDIA_LIVE_SCOPE if nvidia else LIVE_SCOPE
    approval_fields = {"schema": NVIDIA_SCHEMA, "launch": True} if nvidia else {
        "schema": "agent-heldout-live-approval/v2",
    }
    receipt = _approval(admission, root, out, tmp_path / "synthetic-live.json",
                        live_scope=scope, **approval_fields)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "_git", lambda *args: "" if args[0] == "status" else CANDIDATE)
    monkeypatch.delenv("WORKBENCH_REASONING_EFFORT", raising=False)
    config = LLMConfig(scope["base_url"], "synthetic-not-a-secret", scope["model"],
                       provider_id=scope["provider_id"], reasoning_effort="high",
                       reasoning_efforts=("none", "high") if nvidia else None)
    monkeypatch.setattr(runner, "load_llm_config", lambda: config)
    plan = admission.describe(root, out)
    marker = Path(plan["consumption_marker"])
    calls = []
    source = sys.modules["agent_eval.heldout"]
    source.synthetic_dispatch = True

    def fake_tasks():
        assert marker.is_file(), "attempt to open sealed source before claiming the cohort"
        scenario = SimpleNamespace(id="synthetic", frame=lambda seed: SimpleNamespace(
            to_csv=lambda path, **_: path.write_text("x,y\n1,2\n")))
        return [SimpleNamespace(id=f"case-{i}", language="en", prompt=f"synthetic {i}", scenario=scenario,
                                variant="fixture", seed=i, seed_model={}) for i in range(1, 22)]

    @contextmanager
    def fake_tape(path, *, budget):
        assert budget.path == out / "budget.json"
        if nvidia:
            assert budget.state["round_kind"] == "m5-heldout"
            assert budget.state["request_limit"] == scope["max_requests"]
            assert budget.overload_recovery is None and budget.serial_coordinator.path == out / "serial.json"
        yield SimpleNamespace(context={})

    def fake_conversation(client, root, run, prompt, policy, **kwargs):
        assert (out / "schedule.json").is_file(), "the schedule was not persisted before dispatch"
        calls.append((prompt, policy.mode))
        return {"stop_reason": "completion_marker", "completed_marker": True}

    source.heldout_tasks = fake_tasks
    monkeypatch.setattr(runner, "TestClient", lambda *_, **__: None)
    monkeypatch.setattr(runner, "create_project", lambda directory, name: SimpleNamespace(root=directory / name))
    monkeypatch.setattr(runner, "_seed", lambda *args: "synthetic-run")
    monkeypatch.setattr(runner, "provider_tape", fake_tape)
    monkeypatch.setattr(runner, "run_conversation", fake_conversation)
    return out, receipt, marker, config, calls


def test_live_receipt_dispatches_source_order_and_splits_grade_compatible_groups(
        runner, live_synthetic, monkeypatch):
    out, receipt, marker, config, calls = live_synthetic
    options = ("--heldout-approval-receipt", str(receipt))
    assert _invoke(monkeypatch, runner, out, *options, "--check-heldout-admission") == 0
    assert not marker.exists() and not out.exists() and calls == []
    assert _invoke(monkeypatch, runner, out, *options) == 0
    assert json.loads(marker.read_bytes())["approval_receipt_sha256"] == hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert calls == [(f"synthetic {i}", "auto" if i % 2 else "ask") for i in range(1, 22)]
    for mode, n in (("ask", 10), ("auto", 11)):
        meta = json.loads((out / mode / "run_meta.json").read_text())
        assert meta["policy"]["mode"] == mode and meta["repeat"] == 1 and len(meta["tasks"]) == n
        assert len(list((out / mode / "tasks").glob("*/record.json"))) == n
    with pytest.raises(SystemExit):
        _invoke(monkeypatch, runner, out, *options)
    assert len(calls) == 21


def test_live_receipt_stops_and_keeps_all_21_planned_slots(runner, live_synthetic, monkeypatch):
    out, receipt, marker, config, calls = live_synthetic

    def interrupted(*args, **kwargs):
        calls.append("first request")
        raise runner.BudgetStop("unknown usage")

    monkeypatch.setattr(runner, "run_conversation", interrupted)
    assert _invoke(monkeypatch, runner, out, "--heldout-approval-receipt", str(receipt)) == 86
    record = json.loads((out / "auto/tasks/case-1.r1/record.json").read_text())
    assert marker.exists() and calls == ["first request"] and record["status"] == "round_budget_stopped"
    assert len(json.loads((out / "schedule.json").read_text())["slots"]) == 21
    assert not list((out / "ask/tasks").glob("*/record.json"))


def test_durable_provider_stop_takes_precedence_over_a_normal_task_return(runner, live_synthetic, monkeypatch):
    out, receipt, marker, config, calls = live_synthetic

    @contextmanager
    def cancelled_tape(path, *, budget):
        yield SimpleNamespace(context={})
        budget.stop("transport interrupted; provider usage unknown")

    monkeypatch.setattr(runner, "provider_tape", cancelled_tape)
    assert _invoke(monkeypatch, runner, out, "--heldout-approval-receipt", str(receipt)) == 86
    assert marker.exists() and calls == [("synthetic 1", "auto")]
    record = json.loads((out / "auto/tasks/case-1.r1/record.json").read_text())
    assert record["status"] == "round_budget_stopped" and "usage unknown" in record["error"]
    assert not (out / "ask/tasks/case-2.r1").exists()


@pytest.mark.parametrize("refusal", ["route", "storage", "override", "reasoning_catalog"])
def test_live_receipt_preflight_refusal_keeps_seal_unconsumed(
        runner, live_synthetic, monkeypatch, capsys, refusal):
    from dataclasses import replace

    out, receipt, marker, config, calls = live_synthetic
    options = ["--heldout-approval-receipt", str(receipt)]
    if refusal == "route":
        monkeypatch.setattr(runner, "load_llm_config",
                            lambda: replace(config, base_url="https://proxy.example/v1"))
    elif refusal == "reasoning_catalog":
        monkeypatch.setattr(runner, "load_llm_config", lambda: replace(config, reasoning_efforts=()))
    elif refusal == "storage":
        monkeypatch.setattr(runner.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    else:
        options.extend(["--max-nudges", "9"])
    with pytest.raises(SystemExit) as refused:
        _invoke(monkeypatch, runner, out, *options)
    assert refused.value.code == 2
    assert {"route": "provider", "storage": "storage", "override": "policy",
            "reasoning_catalog": "provider"}[refusal] in capsys.readouterr().err
    assert not marker.exists() and not out.exists() and not calls


@pytest.mark.parametrize("field, wrong_value", [
    ("provider_id", "proxy"), ("base_url", "https://api.deepseek.com/v1"), ("model", "deepseek-flash"),
    ("reasoning_effort", "none"), ("max_output_tokens", 32769), ("max_http_inflight", 2),
    ("min_start_interval_s", 1), ("max_requests", True), ("max_requests", 0),
    ("paid_budget", "0"), ("paid_budget", False), ("paid_budget", 1),
    ("unknown_usage_policy", "continue"), ("recovery", "retry once"), ("extra", False),
])
def test_nvidia_receipt_pins_free_policy(sealed_source, tmp_path, field, wrong_value):
    admission, (root, _) = sealed_source
    out = tmp_path / "unused"
    path = tmp_path / "synthetic-nvidia.json"
    _approval(admission, root, out, path, schema=NVIDIA_SCHEMA, launch=True,
              live_scope={**NVIDIA_LIVE_SCOPE, field: wrong_value})
    with pytest.raises(admission.HeldoutAdmissionError, match="NVIDIA"):
        admission.verify(path, repository_root=root, run_root=out)
    assert not out.exists()


@pytest.mark.parametrize("changes", [{"launch": False}, {"launch": 1}, {"historical_exposure_review": "unknown"}])
def test_nvidia_receipt_requires_intent_and_exposure_review(sealed_source, tmp_path, changes):
    admission, (root, _) = sealed_source
    out = tmp_path / "unused"
    fields = {"schema": NVIDIA_SCHEMA, "launch": True, "live_scope": NVIDIA_LIVE_SCOPE, **changes}
    receipt = _approval(admission, root, out, tmp_path / "synthetic-nvidia.json", **fields)
    with pytest.raises(admission.HeldoutAdmissionError):
        admission.verify(receipt, repository_root=root, run_root=out)


@pytest.mark.parametrize("live_synthetic", ["v3"], indirect=True)
def test_nvidia_preflight_rejects_unknown_usage_override_before_claim(
        runner, live_synthetic, monkeypatch, capsys):
    from agent_eval import budget

    out, receipt, marker, _, calls = live_synthetic
    monkeypatch.setattr(budget, "ACCEPT_UNKNOWN_USAGE", True)
    with pytest.raises(SystemExit, match="2"):
        _invoke(monkeypatch, runner, out, "--heldout-approval-receipt", str(receipt))
    assert "unknown usage" in capsys.readouterr().err
    assert not marker.exists() and not out.exists() and not calls


@pytest.mark.parametrize("live_synthetic", ["v3"], indirect=True)
def test_nvidia_rechecks_receipt_bytes_before_claim(runner, live_synthetic, monkeypatch, capsys):
    out, receipt, marker, config, calls = live_synthetic

    def mutate_receipt():
        approval = json.loads(receipt.read_bytes())
        approval["live_scope"]["max_requests"] += 1
        receipt.write_text(json.dumps(approval))
        return config

    monkeypatch.setattr(runner, "load_llm_config", mutate_receipt)
    with pytest.raises(SystemExit, match="2"):
        _invoke(monkeypatch, runner, out, "--heldout-approval-receipt", str(receipt))
    assert "receipt changed after preflight" in capsys.readouterr().err
    assert not marker.exists() and not out.exists() and not calls


@pytest.mark.parametrize("fault", ["count", "cost", "route", "model", "credential", "usage", "http", "sync",
                                   "reasoning", "auxiliary", "bounded_auxiliary"])
def test_heldout_recorder_fails_closed_at_wire_boundary(tmp_path, monkeypatch, fault):
    import httpx
    monkeypatch.syspath_prepend(str(SCRIPTS))
    from agent_eval.budget import BudgetStop, HeldoutProviderBudget
    from agent_eval.recorder import provider_tape
    from workbench.llm import client as llm
    from workbench.llm.config import LLMConfig

    monkeypatch.delenv("WORKBENCH_REASONING_EFFORT", raising=False)
    scope = {**LIVE_SCOPE, "cap_cny": "5.25" if fault == "cost" else "20.00",
             "max_requests": 1 if fault in ("count", "bounded_auxiliary") else 50,
             "reasoning_effort": "none" if fault == "reasoning" else "high"}
    config = LLMConfig(scope["base_url"], "synthetic-only", scope["model"],
                       provider_id=scope["provider_id"], reasoning_effort=scope["reasoning_effort"])
    budget = HeldoutProviderBudget(tmp_path / "ledger.json", scope=scope, config=config)
    requests = []

    def mocked(request):
        requests.append(str(request.url))
        usage = None if fault == "usage" else {"prompt_tokens": 4000, "completion_tokens": 1000}
        return httpx.Response(503 if fault == "http" else 200, json={"usage": usage})

    def fake_transport(*, trust_env):
        assert trust_env is False
        return httpx.MockTransport(mocked)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", fake_transport)
    tape = tmp_path / "tape.jsonl"
    original_sync = llm._client_factory

    async def scenario():
        payload = {"model": "fallback" if fault == "model" else scope["model"], "reasoning_effort": "high"}
        if fault == "reasoning":
            payload.update(reasoning_effort="none", thinking={"type": "enabled"})
        if fault in ("auxiliary", "bounded_auxiliary"):
            payload.pop("reasoning_effort")
            payload["thinking"] = {"type": "disabled"}
            if fault == "bounded_auxiliary":
                payload["max_tokens"] = 8192
        url = ("https://wrong.invalid/v1" if fault == "route" else scope["base_url"]) + "/chat/completions"
        headers = {"Authorization": "Bearer " + ("changed" if fault == "credential" else config.api_key)}
        with provider_tape(tape, budget=budget):
            if fault == "sync":
                llm._client_factory(config)
            async with llm._async_client_factory(config) as client:
                await client.post(url, json=payload, headers=headers)
                await client.post(url, json=payload, headers=headers)

    with pytest.raises(BudgetStop):
        asyncio.run(scenario())
    assert llm._client_factory is original_sync and budget.stopped
    count = int(fault in ("count", "cost", "usage", "http", "bounded_auxiliary"))
    assert requests == [scope["base_url"] + "/chat/completions"] * count
    assert budget.state.get("requests", 0) == count
    assert bool(budget.state["reservations"]) is (fault in ("usage", "http"))
    assert len(tape.read_text().splitlines() if tape.exists() else []) == count


@pytest.mark.parametrize("fault, sent, unsettled", [
    ("wrong_route", 0, False), ("method", 0, False), ("credential", 0, False), ("sync", 0, False),
    ("model", 0, False), ("too_much_output", 0, False), ("alternate_output", 0, False), ("non_object_body", 0, False),
    ("limit", 1, False), ("bounded_auxiliary", 1, False), ("unknown_usage", 1, True),
    ("credit", 1, True), ("429", 1, True), ("503", 1, True),
])
def test_nvidia_heldout_guard_pins_wire_and_stops_without_retry(tmp_path, monkeypatch, fault, sent, unsettled):
    import httpx
    from agent_eval.budget import BudgetStop, PinnedNvidiaEvaluationGuard
    from agent_eval.recorder import provider_tape
    from workbench.llm import client as llm
    from workbench.llm.config import LLMConfig

    monkeypatch.setenv("WORKBENCH_REASONING_EFFORT", "high")
    scope = NVIDIA_LIVE_SCOPE
    config = LLMConfig(scope["base_url"], "test-only", scope["model"],
                       provider_id=scope["provider_id"], reasoning_efforts=("none", "high"))
    guard = PinnedNvidiaEvaluationGuard(tmp_path / "budget.json", config=config, serial_path=tmp_path / "serial.json",
                                        round_kind="m5-heldout", request_limit=1)
    requests = []

    def mock_wire(request):
        requests.append(request)
        if fault.isdecimal():
            return httpx.Response(int(fault), json={"error": "synthetic provider refusal"})
        if fault == "unknown_usage":
            return httpx.Response(200, json={})
        usage = {"prompt_tokens": 10, "completion_tokens": 1}
        if fault == "credit":
            usage["credit"] = 1
        return httpx.Response(200, json={"usage": usage})

    def mock_transport(*, trust_env):
        assert trust_env is False
        return httpx.MockTransport(mock_wire)

    monkeypatch.setattr(httpx, "AsyncHTTPTransport", mock_transport)
    tape = tmp_path / "tape.jsonl"
    original_sync = llm._client_factory

    async def use_recorder():
        payload = {"model": config.model, "reasoning_effort": "high", "max_tokens": 32768}
        if fault == "model":
            payload["model"] = "fallback"
        if fault == "too_much_output":
            payload["max_tokens"] = 32769
        if fault == "bounded_auxiliary":
            payload.update(reasoning_effort="none", max_tokens=8192)
        if fault == "alternate_output":
            payload.update(reasoning_effort="none", max_tokens=8192, max_completion_tokens=32768)
        if fault == "non_object_body":
            payload = []
        route = "https://proxy.invalid/v1" if fault == "wrong_route" else config.base_url
        headers = {"Authorization": "Bearer " + ("changed" if fault == "credential" else config.api_key)}
        method = "GET" if fault == "method" else "POST"
        with provider_tape(tape, budget=guard):
            if fault == "sync":
                llm._client_factory(config)
            async with llm._async_client_factory(config) as client:
                for _ in range(2):
                    await client.request(method, route + "/chat/completions", json=payload, headers=headers)

    with pytest.raises(BudgetStop):
        asyncio.run(use_recorder())
    assert llm._client_factory is original_sync and guard.stopped
    assert len(requests) == guard.state["requests"] == sent
    assert bool(guard.state["reservations"]) is unsettled
    assert len(tape.read_text().splitlines() if tape.exists() else []) == sent
    if sent and not unsettled:
        assert guard.state["charges"][0]["billing_status"] == "unknown; credit not reported"


def test_pinned_heldout_guard_requires_a_serial_ledger(tmp_path, monkeypatch):
    from agent_eval.budget import PinnedNvidiaEvaluationGuard
    from workbench.llm.config import LLMConfig

    scope = NVIDIA_LIVE_SCOPE
    config = LLMConfig(scope["base_url"], "test-only", scope["model"],
                       provider_id=scope["provider_id"], reasoning_efforts=("none", "high"))
    monkeypatch.setenv("WORKBENCH_REASONING_EFFORT", "high")
    ledger = tmp_path / "budget.json"
    with pytest.raises(ValueError, match="serial request ledger"):
        PinnedNvidiaEvaluationGuard(ledger, config=config, serial_path=None,
                                    round_kind="m5-heldout", request_limit=1)
    assert not ledger.exists()


@pytest.mark.parametrize("changes", [
    {"candidate_sha": "b" * 40}, {"run_root": "/elsewhere"}, {"heldout_source_sha256": "b" * 64},
    {"allocation_sha256": "b" * 64}, {"task_count": 42}, {"approval_ref": ""},
    {"historical_exposure_review": "unknown"}, {"extra": True},
])
def test_receipt_must_match_exact_frozen_scope(sealed_source, tmp_path, changes):
    admission, (root, _) = sealed_source
    out = tmp_path / "unused"
    receipt = _approval(admission, root, out, tmp_path / "synthetic-approval.json", **changes)
    with pytest.raises(admission.HeldoutAdmissionError):
        admission.verify(receipt, repository_root=root, run_root=out)
    assert not out.exists()


def test_source_drift_refuses_even_if_receipt_exists(sealed_source, tmp_path):
    admission, (root, _) = sealed_source
    out = tmp_path / "unused"
    receipt = _approval(admission, root, out, tmp_path / "synthetic-approval.json")
    (root / "scripts/agent_eval/heldout.py").write_bytes(b"changed synthetic source")
    with pytest.raises(admission.HeldoutAdmissionError, match="source SHA-256"):
        admission.verify(receipt, repository_root=root, run_root=out)


@pytest.mark.parametrize("options", [("--repeat", "2"), ("--tasks", "only-one"), ("--mode", "ask"),
    ("--transport", "http"), ("--replay-round", "/tmp/prior"), ("--allow-low-space-this-round",)])
def test_partial_repeat_replay_or_mode_override_is_rejected(runner, tmp_path, monkeypatch, capsys, options):
    with pytest.raises(SystemExit) as refused:
        _invoke(monkeypatch, runner, tmp_path / "unused", "--check-heldout-admission", *options)
    assert refused.value.code == 2 and "fixed 21-task allocation" in capsys.readouterr().err


@pytest.mark.parametrize("second_schema", ["agent-heldout-approval/v1", NVIDIA_SCHEMA])
def test_one_atomic_marker_covers_two_linked_checkout_and_output_roots(sealed_source, tmp_path, second_schema):
    admission, roots = sealed_source
    outs = [tmp_path / "run-a", tmp_path / "run-b"]
    fields = {"schema": second_schema}
    if second_schema == NVIDIA_SCHEMA:
        fields.update(launch=True, live_scope=NVIDIA_LIVE_SCOPE)
    receipts = [_approval(admission, roots[0], outs[0], tmp_path / "synthetic-0.json"),
                _approval(admission, roots[1], outs[1], tmp_path / "synthetic-1.json", **fields)]

    def claim(index):
        try:
            return admission.consume(receipts[index], repository_root=roots[index], run_root=outs[index])
        except admission.HeldoutAdmissionError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, range(2)))
    [marker] = [value for value in results if isinstance(value, Path)]
    [failure] = [value for value in results if isinstance(value, str)]
    assert "already consumed" in failure
    assert marker == (tmp_path / "canonical/.worktrees/workbench-v1.9.1/local/agent-eval/heldout-v1.9.1-consumed.json")
    assert not (tmp_path / "canonical/local").exists()
    assert json.loads(marker.read_text(encoding="utf-8"))["candidate_sha"] == CANDIDATE
    assert all(not out.exists() for out in outs)
    assert "already consumed" in claim(0)  # no automatic resume, even in the winning output root


def test_admission_requires_existing_release_worktree(sealed_source, tmp_path):
    admission, (root, _) = sealed_source
    authoritative = tmp_path / "canonical/.worktrees/workbench-v1.9.1"
    authoritative.rmdir()
    with pytest.raises(admission.HeldoutAdmissionError, match="canonical v1.9.1 worktree is unavailable"):
        admission.describe(root, tmp_path / "unused")
    assert not authoritative.exists()


@pytest.mark.parametrize("foreign_checkout", [True, False])
def test_release_worktree_must_have_exact_top_level_and_shared_git_common_dir(sealed_source, tmp_path, monkeypatch, foreign_checkout):
    admission, (root, _) = sealed_source
    authoritative = tmp_path / "canonical/.worktrees/workbench-v1.9.1"
    foreign = tmp_path / "another-clone/.git"
    foreign.mkdir(parents=True)
    git = admission._git

    def redirect(checkout, *args):
        if checkout == authoritative:
            if foreign_checkout and args == ("rev-parse", "--path-format=absolute", "--git-common-dir"):
                return str(foreign)
            if not foreign_checkout and args == ("rev-parse", "--show-toplevel"):
                return str(tmp_path / "canonical")
        return git(checkout, *args)

    monkeypatch.setattr(admission, "_git", redirect)
    with pytest.raises(admission.HeldoutAdmissionError, match="canonical v1.9.1 worktree does not belong"):
        admission.describe(root, tmp_path / "unused")


def test_existing_empty_marker_blocks_activation_after_partial_failure(sealed_source, tmp_path):
    admission, (root, _) = sealed_source
    out = tmp_path / "unused"
    receipt = _approval(admission, root, out, tmp_path / "synthetic-approval.json")
    marker = Path(admission.describe(root, out)["consumption_marker"])
    marker.parent.mkdir(parents=True)
    marker.touch()
    with pytest.raises(admission.HeldoutAdmissionError, match="already consumed"):
        admission.consume(receipt, repository_root=root, run_root=out)
    assert marker.read_bytes() == b""


def test_failed_marker_flush_keeps_the_cohort_consumed(sealed_source, tmp_path, monkeypatch):
    admission, (root, _) = sealed_source
    out = tmp_path / "unused"
    receipt = _approval(admission, root, out, tmp_path / "synthetic-approval.json")
    sync = admission.os.fsync

    def fail_file_only(fd):
        if stat.S_ISREG(admission.os.fstat(fd).st_mode):
            raise OSError("synthetic marker flush failure")
        sync(fd)

    monkeypatch.setattr(admission.os, "fsync", fail_file_only)
    with pytest.raises(admission.HeldoutAdmissionError, match="Preserve any marker"):
        admission.consume(receipt, repository_root=root, run_root=out)
    with pytest.raises(admission.HeldoutAdmissionError, match="already consumed"):
        admission.consume(receipt, repository_root=root, run_root=out)
    assert not out.exists()


def test_receipt_cannot_consume_into_an_existing_run_root(sealed_source, tmp_path):
    admission, (root, _) = sealed_source
    out = tmp_path / "occupied"
    receipt = _approval(admission, root, out, tmp_path / "synthetic-approval.json")
    out.mkdir()
    with pytest.raises(admission.HeldoutAdmissionError, match="unused run root"):
        admission.consume(receipt, repository_root=root, run_root=out)
    plan = admission.describe(root, out)
    assert not Path(plan["consumption_marker"]).exists()
