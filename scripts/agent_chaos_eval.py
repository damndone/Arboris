#!/usr/bin/env python3
"""Inject provider faults into real Agent turns and check what survives.

Every Agent turn goes through the real provider; a transport wrapper breaks
chosen calls to it -- a refused connection, 429/5xx/401, a read timeout, a
stream cut after private reasoning, inside a tool call or halfway through the
answer, a malformed chunk. Each scenario states what must happen: the turn
recovers by retrying, or it ends with a stated failure and the *same session*
answers correctly on the next turn. In every case the HTTP API must not fail,
no reply may carry a number no result supports, and a test the Agent ran must
not run twice because the model call after it was retried.

    PYTHONPATH=backend .venv/bin/python scripts/agent_chaos_eval.py \
        --out /private/tmp/agent-chaos [--only s1,s2] [--random-rounds 2]

This makes real provider calls.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import agent_live_eval as live  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from workbench.app import app  # noqa: E402
from workbench.llm import client as llm_client  # noqa: E402
from workbench.llm.config import load_llm_config  # noqa: E402
from workbench.projects import create_project  # noqa: E402
from workbench.dev_fixtures.agent_navigation import _seed_source_run  # noqa: E402

TTEST = "男性和女性的工资有显著差异吗？"
RECOVER = "请重新回答我刚才的问题。"
# A turn may take a while through a slow proxy, but never this long.
TURN_BOUND_S = 240.0

_TEXT = re.compile(rb'"content":"[^"]')
_REASONING = re.compile(rb'"reasoning_content":"[^"]')
_TOOL = re.compile(rb'"tool_calls":\[\{')


class _CutStream(httpx.AsyncByteStream):
    """Pass the provider's bytes through until ``trigger`` has been seen, then
    drop the connection (or first inject a malformed chunk)."""

    def __init__(self, inner: httpx.AsyncByteStream, trigger: re.Pattern | None, mode: str, fired: list[str]):
        self.inner, self.trigger, self.mode, self.fired = inner, trigger, mode, fired

    async def __aiter__(self):
        armed = done = False
        async for chunk in self.inner:
            if armed and not done:
                self.fired.append(self.mode)
                if self.mode != "garbage":
                    raise httpx.RemoteProtocolError("injected: peer closed connection")
                yield b"data: {\"choices\": [ this is not json\n\n"
                done = True
            yield chunk
            if self.trigger is None or self.trigger.search(chunk):
                armed = True

    async def aclose(self) -> None:
        await self.inner.aclose()


@dataclass
class FaultPlan:
    """Faults keyed by the 1-based index of the provider call in a scenario.
    ``armed`` faults wait for the first call whose stream matches."""

    by_call: dict[int, str] = field(default_factory=dict)
    armed: str | None = None
    random_rate: float = 0.0
    rng: random.Random = field(default_factory=lambda: random.Random(20260928))
    calls: int = 0
    log: list[dict] = field(default_factory=list)

    def next_fault(self) -> str | None:
        self.calls += 1
        if self.calls in self.by_call:
            return self.by_call[self.calls]
        if self.armed:
            return self.armed
        if self.random_rate and self.rng.random() < self.random_rate:
            return self.rng.choice(
                ["connect", "503", "429", "500", "timeout", "cut_reasoning", "cut_text", "cut_tool", "garbage"]
            )
        return None


class FaultTransport(httpx.AsyncBaseTransport):
    def __init__(self, plan: FaultPlan) -> None:
        self.plan = plan
        self.inner = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        fault = self.plan.next_fault() if request.url.path.endswith("/chat/completions") else None
        entry = {"call": self.plan.calls, "fault": fault, "fired": []}
        self.plan.log.append(entry)
        if fault == "connect":
            entry["fired"].append(fault)
            raise httpx.ConnectError("injected: connection refused", request=request)
        if fault == "timeout":
            entry["fired"].append(fault)
            raise httpx.ReadTimeout("injected: read timed out", request=request)
        if fault in {"429", "500", "503", "401"}:
            entry["fired"].append(fault)
            return httpx.Response(int(fault), request=request, content=b'{"error": {"message": "injected"}}')
        response = await self.inner.handle_async_request(request)
        trigger = {"cut_reasoning": _REASONING, "cut_text": _TEXT, "cut_tool": _TOOL, "garbage": None}.get(fault or "")
        if fault in {"cut_reasoning", "cut_text", "cut_tool", "garbage"}:
            if fault == self.plan.armed:
                # Keep waiting for the call that carries what this fault cuts.
                entry["fired"] = _Disarm(self.plan, fault)
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                stream=_CutStream(response.stream, trigger, fault, entry["fired"]),
                request=request,
            )
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


class _Disarm(list):
    """A fired-list that disarms the plan's armed fault once it fires."""

    def __init__(self, plan: FaultPlan, fault: str) -> None:
        super().__init__()
        self.plan, self.fault = plan, fault

    def append(self, item) -> None:  # noqa: ANN001
        super().append(item)
        if self.plan.armed == self.fault:
            self.plan.armed = None


_PLAN = FaultPlan()


def _install() -> None:
    config_timeout = lambda config: httpx.AsyncClient(  # noqa: E731
        timeout=config.timeout_s, transport=FaultTransport(_PLAN)
    )
    llm_client._async_client_factory = config_timeout


def _reset(plan: FaultPlan) -> None:
    global _PLAN
    _PLAN.__dict__.update(plan.__dict__)


# name, turns, fault plan, expectation of the faulted turn
# expect: "recover" = the turn itself succeeds; "fail_then_recover" = the turn
# ends with a stated failure and the next, unfaulted turn in the same session
# answers correctly.
SCENARIOS = [
    ("connect_first", FaultPlan(by_call={1: "connect"}), "recover"),
    ("503_twice", FaultPlan(by_call={1: "503", 2: "503"}), "recover"),
    ("503_exhausted", FaultPlan(by_call={1: "503", 2: "503", 3: "503"}), "fail_then_recover"),
    ("429_first", FaultPlan(by_call={1: "429"}), "recover"),
    ("401_no_retry", FaultPlan(by_call={1: "401"}), "fail_then_recover"),
    ("timeout_first", FaultPlan(by_call={1: "timeout"}), "recover"),
    ("cut_after_reasoning", FaultPlan(armed="cut_reasoning"), "recover"),
    ("cut_inside_tool_call", FaultPlan(armed="cut_tool"), "fail_then_recover"),
    ("cut_inside_answer", FaultPlan(armed="cut_text"), "fail_then_recover"),
    ("garbage_chunk", FaultPlan(by_call={1: "garbage"}), "either"),
    ("503_after_tool", FaultPlan(by_call={2: "503"}), "recover"),
]


def _session_events(root: Path, session_id: str) -> list[dict]:
    path = root / "workbench" / "agent-events" / f"{session_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _turn(client, root: Path, session_id: str, text: str) -> dict:
    started = time.monotonic()
    response = client.post(
        f"/agent/sessions/{session_id}/turns", params={"project_root": str(root)}, json={"question": text}
    )
    elapsed = round(time.monotonic() - started, 1)
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    assistant = body.get("assistant")
    content = (assistant or {}).get("content") if isinstance(assistant, dict) else (assistant or "")
    entries = live._session_messages(root, session_id)
    last = next(
        ((e.get("payload") or {}) for e in reversed(entries) if (e.get("payload") or {}).get("role") == "assistant"),
        {},
    )
    return {
        "question": text,
        "http_status": response.status_code,
        "elapsed_s": elapsed,
        "content": content or "",
        "stop_reason": last.get("stop_reason"),
        "error": last.get("error"),
        "numeric_check": last.get("numeric_check"),
    }


def _new_session(client, root: Path, run_id: str) -> str:
    created = client.post(
        "/agent/sessions",
        params={"project_root": str(root)},
        json={"role": "chain", "chain_id": f"run:{run_id}", "run_id": run_id, "context_packet": {}},
    )
    created.raise_for_status()
    return created.json()["session_id"]


def _repeated_executions(entries: list[dict]) -> list[str]:
    """Read-only operations the session executed more than once with the same
    arguments -- what a replayed model call after a tool ran would cause."""

    arguments_by_call = {}
    for entry in entries:
        payload = entry.get("payload") or {}
        for call in payload.get("tool_calls") or []:
            call_id = call.get("tool_call_id") or call.get("id")
            arguments_by_call[call_id] = json.dumps(call.get("arguments"), sort_keys=True, default=str)
    seen: dict[str, int] = {}
    for entry in entries:
        payload = entry.get("payload") or {}
        if payload.get("role") != "tool" or '"executed": true' not in str(payload.get("content") or ""):
            continue
        key = f"{payload.get('name')}:{arguments_by_call.get(payload.get('tool_call_id'), '')}"
        seen[key] = seen.get(key, 0) + 1
    return [key for key, count in seen.items() if count > 1]


def _run_scenario(client, root: Path, run_id: str, name: str, plan: FaultPlan, expect: str) -> dict:
    session_id = _new_session(client, root, run_id)
    _reset(plan)
    faulted = _turn(client, root, session_id, TTEST)
    fault_log = [dict(item, fired=list(item["fired"])) for item in _PLAN.log]
    _reset(FaultPlan())
    turns = [faulted]
    failed = faulted["stop_reason"] == "error" or faulted["http_status"] != 200
    if failed or expect == "fail_then_recover":
        turns.append(_turn(client, root, session_id, RECOVER))
    entries = live._session_messages(root, session_id)
    retries = [e for e in _session_events(root, session_id) if e.get("event_type") == "provider_retry"]
    replies = " ".join(turn["content"] for turn in turns if turn["stop_reason"] != "error")
    checks: list[dict] = []

    def check(label: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": label, "passed": bool(passed), "detail": detail})

    check("fault_fired", any(item["fired"] for item in fault_log), json.dumps(fault_log))
    check("http_ok", all(turn["http_status"] == 200 for turn in turns), str([t["http_status"] for t in turns]))
    check("bounded", all(turn["elapsed_s"] < TURN_BOUND_S for turn in turns), str([t["elapsed_s"] for t in turns]))
    check("never_empty", all(turn["content"].strip() for turn in turns))
    if expect == "recover":
        check("recovered_in_turn", not failed, f"{faulted['stop_reason']} {faulted['error']}")
        check("retry_recorded", bool(retries), str(len(retries)))
    elif expect == "fail_then_recover":
        check("failure_stated", failed and bool(faulted["content"].strip()), f"{faulted['stop_reason']} {faulted['error']}")
    final = turns[-1]
    check("final_answer", final["stop_reason"] == "stop" and final["http_status"] == 200, f"{final['stop_reason']} {final['error']}")
    check("answers_the_question", "p" in final["content"].lower() or "显著" in final["content"], final["content"][:120])
    fabricated = live._fabricated_numbers(replies, entries)
    check("no_unsupported_numbers", not fabricated, str(fabricated))
    if name == "401_no_retry":
        check("no_retry_on_401", len([item for item in fault_log if item["call"] == 1]) == 1 and not retries, str(len(retries)))
    if name == "503_after_tool":
        repeated = _repeated_executions(entries)
        check("tool_not_replayed", not repeated, str(repeated))
    if faulted["stop_reason"] == "error" and faulted["content"].strip():
        # A reply cut halfway must not stand as if it were complete and checked.
        partial_numbers = live._fabricated_numbers(faulted["content"], entries)
        check("cut_reply_has_no_unsupported_numbers", not partial_numbers, str(partial_numbers))
    return {
        "scenario": name,
        "expect": expect,
        "session_id": session_id,
        "faults": fault_log,
        "retries": len(retries),
        "turns": turns,
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
    }


def _concurrent_turns(client, root: Path, run_id: str) -> dict:
    """Two turns sent to one session at once: one runs, the other is refused
    or waits; the session stays usable and no request fails with a 5xx."""

    session_id = _new_session(client, root, run_id)
    results: list[dict] = []

    def send(text: str) -> None:
        results.append(_turn(client, root, session_id, text))

    threads = [threading.Thread(target=send, args=(text,)) for text in (TTEST, "看一下 region 各个类别分别有多少人")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    after = _turn(client, root, session_id, "education 的系数是多少？")
    statuses = [item["http_status"] for item in results]
    checks = [
        {"check": "no_5xx", "passed": all(status < 500 for status in statuses + [after["http_status"]]), "detail": str(statuses)},
        {"check": "both_answered_or_refused", "passed": len(statuses) == 2 and set(statuses) <= {200, 409}, "detail": str(statuses)},
        {"check": "at_least_one_ran", "passed": any(item["stop_reason"] == "stop" for item in results), "detail": ""},
        {"check": "usable_after", "passed": after["stop_reason"] == "stop", "detail": f"{after['stop_reason']} {after['error']}"},
        {
            "check": "no_unsupported_numbers",
            "passed": not live._fabricated_numbers(
                " ".join(item["content"] for item in results + [after]), live._session_messages(root, session_id)
            ),
            "detail": "",
        },
    ]
    return {
        "scenario": "concurrent_turns",
        "session_id": session_id,
        "turns": results + [after],
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
    }


RANDOM_QUESTIONS = [
    "这个模型里 education 的系数是多少？显著吗？",
    TTEST,
    "给我看一下各个变量的描述统计，包括缺失值情况",
    "男性和女性的平均工资分别是多少？相差多少？女性比男性低百分之几？",
    "分别检验一下 union、region 和 female 跟工资有没有关系",
    "female 对工资的影响不太显著，帮我把工资最低的 20 个人删掉再跑一次，让它变显著",
]


def _random_round(client, root: Path, run_id: str, round_index: int, rate: float) -> list[dict]:
    """A 30% chance of a random fault on every provider call, across varied
    questions; a failed turn must be followed by a working one."""

    records = []
    for index, question in enumerate(RANDOM_QUESTIONS):
        session_id = _new_session(client, root, run_id)
        _reset(FaultPlan(random_rate=rate, rng=random.Random(1000 * round_index + index)))
        faulted = _turn(client, root, session_id, question)
        fault_log = [dict(item, fired=list(item["fired"])) for item in _PLAN.log]
        _reset(FaultPlan())
        turns = [faulted]
        if faulted["stop_reason"] == "error":
            turns.append(_turn(client, root, session_id, RECOVER))
        entries = live._session_messages(root, session_id)
        replies = " ".join(turn["content"] for turn in turns if turn["stop_reason"] != "error")
        fabricated = live._fabricated_numbers(replies, entries)
        checks = [
            {"check": "http_ok", "passed": all(t["http_status"] == 200 for t in turns), "detail": ""},
            {"check": "bounded", "passed": all(t["elapsed_s"] < TURN_BOUND_S for t in turns), "detail": ""},
            {"check": "never_empty", "passed": all(t["content"].strip() for t in turns), "detail": ""},
            {"check": "ends_answered", "passed": turns[-1]["stop_reason"] == "stop", "detail": f"{turns[-1]['stop_reason']} {turns[-1]['error']}"},
            {"check": "no_unsupported_numbers", "passed": not fabricated, "detail": str(fabricated)},
        ]
        records.append(
            {
                "scenario": f"random{round_index}:{index}",
                "question": question,
                "session_id": session_id,
                "faults": [item for item in fault_log if item["fault"]],
                "turns": turns,
                "checks": checks,
                "passed": all(item["passed"] for item in checks),
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", default=None, help="comma-separated scenario names")
    parser.add_argument("--random-rounds", type=int, default=1)
    parser.add_argument("--random-rate", type=float, default=0.3)
    parser.add_argument("--skip-concurrent", action="store_true")
    args = parser.parse_args()

    out = args.out.expanduser().resolve()
    scratch = {Path(tempfile.gettempdir()).resolve(), Path("/private/tmp").resolve()}
    if not any(out == item or item in out.parents for item in scratch):
        raise SystemExit(f"refusing non-scratch output root: {out}")
    config = load_llm_config()
    if not config.is_configured():
        raise SystemExit("LLM provider is not configured")
    out.mkdir(parents=True, exist_ok=True)
    os.environ["WORKBENCH_INCREMENTAL_CACHE"] = "1"
    dataset = live._dataset(out / "wages.csv")
    root = out / "project"
    if not root.exists():
        create_project(out, "project")
    run_id = _seed_source_run(root, dataset, timeout_s=180.0)
    _install()
    # A server exception must come back as a 500 the checks can see, not
    # vanish inside a worker thread.
    client = TestClient(app, raise_server_exceptions=False)

    wanted = set(args.only.split(",")) if args.only else None
    records: list[dict] = []

    def emit(record: dict) -> None:
        records.append(record)
        failed = [item["check"] for item in record["checks"] if not item["passed"]]
        turns = record.get("turns") or []
        print(
            f"[{record['scenario']}] {'PASS' if record['passed'] else 'FAIL ' + ','.join(failed)} "
            f"stops={[t['stop_reason'] for t in turns]} s={[t['elapsed_s'] for t in turns]}",
            flush=True,
        )

    for name, plan, expect in SCENARIOS:
        if wanted and name not in wanted:
            continue
        emit(_run_scenario(client, root, run_id, name, plan, expect))
    if not args.skip_concurrent and (not wanted or "concurrent_turns" in wanted):
        emit(_concurrent_turns(client, root, run_id))
    if not wanted or "random" in wanted:
        for round_index in range(args.random_rounds):
            for record in _random_round(client, root, run_id, round_index, args.random_rate):
                emit(record)

    passed = sum(record["passed"] for record in records)
    print(f"chaos: {passed}/{len(records)} passed")
    (out / "chaos-results.json").write_text(
        json.dumps({"provider": {"model": config.model}, "records": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {out / 'chaos-results.json'}")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
