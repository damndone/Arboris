"""Offline full Agent turn replay of one recorded evaluation task, timing everything but the model.

The recorded task's provider tape is served by the evaluation recorder's replay
transport (``scripts/agent_eval/recorder.py``) while the real headless Agent,
tools, approvals and simulated user run unchanged. Network access is refused.
Only answered (HTTP 200) exchanges are replayed: during recording the harness
retried 429 / interrupted requests below the product, so the product never saw
them.

Timing stays outside product functions: each Agent turn call and each provider
exchange is timed by the harness. Per provider step, the non-model time is the
wall time between the previous model response (or the start of the turn) and
the next request, with the turn's tail after the last response added to its
last step. Recorded model latency is not replayed.

    PYTHONPATH=backend .venv/bin/python scripts/perf_agent_turn_replay.py \
        --task-dir <recorded task folder> --work <new folder> [--profile]
"""
from __future__ import annotations

import argparse
import cProfile
import gzip
import hashlib
import json
import os
from pathlib import Path
import pstats
import re
import resource
import socket
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]


def _select_backend(backend: Path) -> None:
    """Import the product from ``backend`` (an exported source tree for A/B runs)."""
    sys.path[:0] = [str(backend), str(ROOT / "scripts")]

_ID_PATTERNS = re.compile(
    r"[0-9a-f]{64}|[0-9a-f]{32}|[0-9a-f]{24}|nocv1:[0-9a-f]{8}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|\d{8}_\d{6}_\d{6}_[0-9a-f]{8}|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?"
    r"|(?:call|proposal|approval|turn|op|operation|record)[-_][0-9A-Za-z-]{6,}")


def _forbid_network() -> None:
    def forbidden(*unused, **kwargs):
        raise RuntimeError("network access is forbidden in offline turn replay")
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = forbidden


_EPOCH_SECONDS = re.compile(r"\b1[789]\d{8}\.\d+")


def normalized(text: str) -> str:
    """Replace run-specific identifiers and timestamps by first-appearance ordinals (epoch seconds by 0)."""
    seen: dict[str, str] = {}
    text = _EPOCH_SECONDS.sub("0", text)
    return _ID_PATTERNS.sub(lambda match: seen.setdefault(match.group(0), f"<id{len(seen)}>"), text)


def _delta_text(raw: str) -> str:
    """All streamed strings in arrival order, to catch an identifier split across chunks."""
    parts: list[str] = []

    def collect(value):
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    for line in raw.split("\n"):
        if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}:
            collect([choice.get("delta") for choice in json.loads(line[5:]).get("choices", [])])
    return "".join(parts)


def _answered_tape(source: Path, destination: Path, renames: dict[str, str]) -> int:
    """Answered exchanges only, with recorded run ids mapped to this replay's run ids."""
    records = [json.loads(line) for line in gzip.decompress(source.read_bytes()).split(b"\n") if line.strip()]
    answered = []
    for record in records:
        if record["status"] != 200:
            continue
        raw = record["response_raw"]
        for old, new in renames.items():
            if len(old) != len(new):
                raise ValueError("run id rename must keep the length")
            raw = raw.replace(old, new)
            if old in _delta_text(raw):
                raise ValueError("a recorded run id is split across stream chunks; replay would diverge")
        answered.append(json.dumps({**record, "response_raw": raw}, ensure_ascii=False))
    destination.write_text("\n".join(answered) + "\n", encoding="utf-8")
    return len(answered)


def _check_product_origin(backend: Path) -> None:
    outside = sorted(name for name, module in sys.modules.items()
                     if (name == "workbench" or name.startswith("workbench.")) and getattr(module, "__file__", None)
                     and not Path(module.__file__).resolve().is_relative_to(backend))
    if outside:
        raise ValueError(f"product modules imported from outside {backend}: {outside[:3]}")


def _seed(root: Path, dataset: Path, form: dict[str, str]) -> str:
    """The evaluation's import step (``agent_eval_run._seed``), without that module's
    import of this checkout's backend, which would defeat ``--backend``."""
    from time import monotonic, sleep
    from workbench.dev_fixtures.agent_navigation import _wait_for_terminal_run
    from workbench.events import get_event_manager
    from workbench.services.run_service import _submit_run

    events = get_event_manager()
    deadline = monotonic() + 120
    while not events.try_acquire_slot():
        if monotonic() >= deadline:
            raise TimeoutError("timed out waiting for the run slot")
        sleep(0.05)
    try:
        result = _submit_run(root, form=form, upload_bytes=dataset.read_bytes(),
                             upload_filename=dataset.name, started_at="agent-eval-seed")
    except Exception:
        events.release_slot(None)
        raise
    _wait_for_terminal_run(root, result["run_id"], timeout_s=300)
    return result["run_id"]


def _replay_store(path: Path, provider: dict) -> None:
    store = {"version": 1, "active_provider_id": provider["id"], "providers": [provider]}
    path.write_text(json.dumps(store), encoding="utf-8")
    path.chmod(0o600)


def run(args) -> dict:
    _forbid_network()
    backend = args.backend.resolve()
    _select_backend(backend)
    if args.work.exists():
        raise FileExistsError(args.work)
    args.work.mkdir(parents=True)
    record = json.loads((args.task_dir / "record.json").read_text(encoding="utf-8"))
    provider = json.loads(args.provider.read_text(encoding="utf-8"))
    _replay_store(args.work / "llm-providers.json", provider)
    os.environ["WORKBENCH_LLM_CONFIG_PATH"] = str(args.work / "llm-providers.json")
    started = perf_counter()

    from fastapi.testclient import TestClient
    from agent_eval import recorder, runner
    from workbench.app import app
    from workbench.projects import create_project
    imported = perf_counter()
    _check_product_origin(backend)

    [source_dataset] = args.task_dir.glob("*.csv")
    dataset = args.work / source_dataset.name
    dataset.write_bytes(source_dataset.read_bytes())
    project = create_project(args.work, "project")
    run_id = _seed(project.root, dataset, record["seed_model"])
    answered = _answered_tape(args.task_dir / "provider_tape.jsonl.gz", args.work / "provider_tape.jsonl",
                              {record["seed_run_id"]: run_id})
    seeded = perf_counter()

    exchanges: list[dict] = []
    original_handle = recorder._RecordingTransport.handle_async_request

    async def timed_handle(transport, request):
        t0 = perf_counter()
        response = await original_handle(transport, request)
        exchanges.append({"sent": t0, "answered": perf_counter(), "body": request.content})
        return response

    recorder._RecordingTransport.handle_async_request = timed_handle
    turns: list[dict] = []
    original_turn = runner._turn
    profile = cProfile.Profile() if args.profile else None

    def timed_turn(*turn_args, **turn_kwargs):
        first = len(exchanges)
        if profile:
            profile.enable()
        t0 = perf_counter()
        result = original_turn(*turn_args, **turn_kwargs)
        t1 = perf_counter()
        if profile:
            profile.disable()
        mine = exchanges[first:]
        marks = [t0, *[point for item in mine for point in (item["sent"], item["answered"])], t1]
        gaps = [marks[2 * i + 1] - marks[2 * i] for i in range(len(mine) + 1)]
        steps = gaps[:-1]
        if steps:
            steps[-1] += gaps[-1]
        turns.append({"wall_s": t1 - t0, "transport_s": sum(i["answered"] - i["sent"] for i in mine),
                      "provider_steps": len(mine), "step_nonmodel_s": steps,
                      "status": result.get("status"), "user": result.get("user", "")[:60]})
        return result

    runner._turn = timed_turn
    client = TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    policy = runner.Policy(max_nudges=8, max_wall_s=1800, language=record["language"], mode="ask",
                           transport="headless")
    with recorder.provider_tape(args.work / "provider_tape.jsonl", mode="replay") as tape:
        conversation = runner.run_conversation(client, project.root, run_id, record["prompt"], policy,
                                               focus_node="stage:cleaned")
        mismatches, left = tape.mismatches, len(tape.queue)
    finished = perf_counter()
    runner._turn = original_turn
    recorder._RecordingTransport.handle_async_request = original_handle

    _check_product_origin(backend)
    session_file = project.root / "workbench" / "agent-sessions" / f"{conversation['session_id']}.jsonl"
    entries = [json.loads(line) for line in session_file.read_text(encoding="utf-8").split("\n") if line.strip()]
    semantic = [{"entry_type": e["entry_type"], "payload": e.get("payload")} for e in entries]
    normalized_journal = normalized(json.dumps(semantic, ensure_ascii=False, sort_keys=True))
    steps = [value for turn in turns for value in turn["step_nonmodel_s"]]
    request_digests = [hashlib.sha256(normalized(item.pop("body").decode("utf-8")).encode()).hexdigest()
                       for item in exchanges]
    summary = {
        "schema_version": 1, "scope": "offline_full_turn_replay", "task": record["task_id"], "backend": str(backend),
        "source_task_dir": str(args.task_dir), "answered_exchanges": answered, "replay_mismatches": mismatches,
        "replay_left": left, "replayed_exchanges": len(exchanges), "turns": turns,
        "turn_count": len(turns), "step_count": len(steps),
        "step_nonmodel_ms_median": statistics.median(steps) * 1000 if steps else None,
        "step_nonmodel_ms_max": max(steps) * 1000 if steps else None,
        "turn_nonmodel_s_total": sum(t["wall_s"] - t["transport_s"] for t in turns),
        "conversation_wall_s": finished - seeded, "import_s": imported - started, "seed_s": seeded - imported,
        "stop_reason": conversation.get("stop_reason"), "confirmations": [
            {k: c.get(k) for k in ("status", "elapsed_s")} for c in conversation.get("confirmations", [])],
        "final_reply_sha256": hashlib.sha256(
            (conversation["turns"][-1]["reply"] if conversation["turns"] else "").encode()).hexdigest(),
        "normalized_journal_sha256": hashlib.sha256(normalized_journal.encode()).hexdigest(),
        "journal_entries": len(entries), "normalized_request_sha256": request_digests,
        "rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
    }
    (args.work / "normalized-journal.json").write_text(normalized_journal, encoding="utf-8")
    if profile:
        profile.dump_stats(str(args.work / "turns.prof"))
        stats = pstats.Stats(profile)
        summary["profile_top_cumulative"] = [
            {"file": key[0], "line": key[1], "function": key[2], "calls": value[1],
             "self_seconds": value[2], "cumulative_seconds": value[3]}
            for key, value in sorted(stats.stats.items(), key=lambda pair: pair[1][3], reverse=True)[:80]]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--task-dir", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--provider", type=Path, required=True,
                        help="provider entry JSON (no real key needed; the network is refused)")
    parser.add_argument("--backend", type=Path, default=ROOT / "backend",
                        help="product source tree to import (default: this checkout's backend)")
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    summary = run(args)
    text = json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"turns", "profile_top_cumulative"}},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
