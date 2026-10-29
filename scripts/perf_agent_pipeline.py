"""Offline local Agent pipeline replay from one frozen real provider/session tape.

This profiles context, schema publication, schema argument checks, fingerprints
and persistence. It never invokes a handler, provider, reviewer or statistical
operation. Recorded model latency is reported separately. This is not complete
Agent execution, quality evaluation or end-to-end statistical acceptance.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import resource
import shutil
import socket
import sys
from time import perf_counter


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def verify_source_snapshot(tree: Path, expected_sha256: str | None = None):
    """Verify the entire registered source tree, including lazy dependencies."""
    tree = tree.resolve()
    manifest_path = tree / "source-manifest.json"
    raw = manifest_path.read_bytes()
    checksum = sha(raw)
    if expected_sha256 is not None and checksum != expected_sha256:
        raise ValueError("frozen source manifest digest changed")
    registration = json.loads(raw)
    expected = {item["path"]:item for item in registration["files"]}
    if len(expected) != len(registration["files"]):
        raise ValueError("duplicate frozen source path")
    actual = set()
    for path in (tree / "backend").rglob("*"):
        if "__pycache__" in path.relative_to(tree).parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            raise ValueError("symlink in frozen source tree")
        if path.is_file():
            actual.add(str(path.relative_to(tree)))
    if actual != set(expected):
        raise ValueError("frozen source file set changed")
    for relative,item in expected.items():
        path = tree / relative
        if not path.resolve().is_relative_to(tree / "backend"):
            raise ValueError("frozen source path outside backend")
        raw = path.read_bytes()
        if sha(raw) != item["sha256"] or ("bytes" in item and len(raw) != item["bytes"]):
            raise ValueError("frozen source file digest changed: " + relative)
    return {"manifest_sha256":checksum,"files":len(expected)}


def prepare(args):
    """Copy/hash only: no product invocation or measurement during preparation."""
    if args.fixture.exists():
        raise FileExistsError(args.fixture)
    args.fixture.mkdir(parents=True)
    sessions = args.fixture / "sessions"
    sessions.mkdir()
    files = []
    for source in sorted(args.sessions.iterdir()):
        if source.name.endswith((".jsonl", ".meta.json")):
            raw = source.read_bytes()
            destination = sessions / source.name
            destination.write_bytes(raw)
            files.append({"path": str(destination.relative_to(args.fixture)), "sha256": sha(raw), "bytes": len(raw)})
    raw = args.tape.read_bytes()
    (args.fixture / "provider_tape.jsonl").write_bytes(raw)
    files.append({"path": "provider_tape.jsonl", "sha256": sha(raw), "bytes": len(raw)})
    tape = [json.loads(line) for line in raw.splitlines() if line.strip()]
    entries = [json.loads(line) for line in (sessions / (args.session_id + ".jsonl")).read_bytes().splitlines() if line.strip()]
    groups, checkpoints = -1, []
    for index, entry in enumerate(entries):
        payload = entry.get("payload") or {}
        if entry["entry_type"] == "turn_state" and payload.get("stage") == "initial":
            groups += 1
        if entry["entry_type"] == "turn_state" and payload.get("stage") == "provider":
            checkpoints.append((index, groups))
    if len(checkpoints) != len(tape):
        raise ValueError("recorded provider/session call counts differ; no inferred matching")
    schedule = []
    for ordinal, ((index, group), record) in enumerate(zip(checkpoints, tape)):
        end = checkpoints[ordinal + 1][0] if ordinal + 1 < len(checkpoints) else len(entries)
        assistant = next((entry["payload"] for entry in entries[index + 1:end]
                          if entry["entry_type"] == "turn_state" and entry["payload"].get("stage") == "assistant"), {})
        parent = entries[index].get("parent_ref")
        if not parent or parent["session_id"] != args.session_id:
            raise ValueError("provider context leaf must be explicit on the same session")
        schedule.append({"ordinal": ordinal, "group": group, "leaf": parent["entry_id"],
                         "expected_context_fingerprint": assistant.get("context_fingerprint"),
                         "calls": (assistant.get("assistant") or {}).get("tool_calls", []),
                         "persist": [{"entry_type": entry["entry_type"], "payload": entry["payload"],
                                      "idempotency": entry.get("idempotency")}
                                     for entry in entries[index + 1:end]
                                     if entry["entry_type"] in {"message", "tool_intent", "tool_receipt"}],
                         "recorded_model_seconds": record.get("elapsed_s"), "recorded_status": record.get("status")})
    manifest = {"schema_version": 1, "session_id": args.session_id,
                "source_tape": str(args.tape.resolve()), "source_sessions": str(args.sessions.resolve()),
                "files": files, "schedule": schedule,
                "schedule_sha256": sha(json_bytes(schedule)), "scope": "offline_local_pipeline_replay"}
    (args.fixture / "manifest.json").write_bytes(json_bytes(manifest) + b"\n")
    print(json.dumps({"fixture": str(args.fixture.resolve()), "manifest_sha256": sha(json_bytes(manifest) + b"\n"),
                      "requests": len(schedule), "groups": groups + 1, "files": len(files)}))


def worker(args):
    def forbidden(*unused, **kwargs):
        raise RuntimeError("network access is forbidden in local pipeline replay")
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = forbidden
    started = perf_counter()
    source_tree = args.source_tree.resolve() if args.source_tree else Path(__file__).resolve().parents[1]
    source_snapshot = (verify_source_snapshot(source_tree) if args.source_tree
                       else {"manifest_sha256":None,"reason":"diagnostic_unregistered_default_source"})
    source_validated = perf_counter()
    sys.path.insert(0, str(source_tree / "backend"))
    from workbench.agent.context import ContextBuilder
    from workbench.agent.model import _to_openai_tool_descriptors, _to_openai_wire_messages
    from workbench.agent.session import JsonlSessionRepository
    from workbench.agent.tools import ToolDefinition, ToolRegistry, _wrap_single_strings, validation_details
    from workbench.agent.tool_receipts import tool_call_sha256, _canonical
    from workbench import native_canonical
    imported = perf_counter()
    source_modules = [module for name,module in sys.modules.items()
                      if (name == "workbench" or name.startswith("workbench."))
                      and getattr(module, "__file__", None)
                      and Path(module.__file__).suffix == ".py"]
    if any(not Path(module.__file__).resolve().is_relative_to(source_tree / "backend") for module in source_modules):
        raise ValueError("pipeline imported a module outside the selected source tree")
    source_paths = [Path(__file__).resolve(), *[Path(module.__file__).resolve() for module in source_modules]]
    source_sha256 = {str(path):sha(path.read_bytes()) for path in source_paths}
    raw_manifest = (args.fixture / "manifest.json").read_bytes()
    if sha(raw_manifest) != args.sha256:
        raise ValueError("fixed manifest SHA256 mismatch")
    manifest = json.loads(raw_manifest)
    for item in manifest["files"]:
        if sha((args.fixture / item["path"]).read_bytes()) != item["sha256"]:
            raise ValueError("fixed replay input SHA256 mismatch")
    if sha(json_bytes(manifest["schedule"])) != manifest["schedule_sha256"]:
        raise ValueError("fixed call schedule SHA256 mismatch")
    if args.work_dir.exists():
        raise FileExistsError(args.work_dir)
    args.work_dir.mkdir(parents=True)
    shutil.copytree(args.fixture / "sessions", args.work_dir / "agent-sessions")
    tape = [json.loads(line) for line in (args.fixture / "provider_tape.jsonl").read_bytes().splitlines() if line.strip()]
    repository = JsonlSessionRepository(args.work_dir)
    context = ContextBuilder(repository)
    persistence = JsonlSessionRepository(args.work_dir / "persistence")
    persistence.create_session(manifest["session_id"], chain_id="frozen-replay", role="chain")
    loaded = perf_counter()
    durations = defaultdict(float)
    counts = defaultdict(int)
    results = []
    registry = None
    schemas = None
    previous_group = None
    profile = cProfile.Profile() if args.profile else None
    if profile:
        profile.enable()
    for item, exchange in zip(manifest["schedule"], tape):
        request = exchange["request"]
        step = {"ordinal": item["ordinal"], "group": item["group"], "recorded_status": item["recorded_status"]}
        t = perf_counter()
        snapshot = context.build(manifest["session_id"], leaf_entry_id=item["leaf"])
        durations["context_build"] += perf_counter() - t
        expected = item["expected_context_fingerprint"]
        if expected and snapshot.fingerprint != expected:
            raise ValueError(f"recorded context fingerprint differs at step {item['ordinal']}")
        step["context_fingerprint"] = snapshot.fingerprint
        t = perf_counter()
        tools = request.get("tools", [])
        current_schemas = sha(json_bytes(tools))
        # Product publishes a registry once for each user turn, not once for
        # every internal provider step. A schema change requires publication.
        if registry is None or previous_group != item["group"] or current_schemas != schemas:
            registry = ToolRegistry()
            for descriptor in tools:
                f = descriptor["function"]
                registry.register(ToolDefinition(f["name"], "v1", f["parameters"], "none",
                    forbidden, description=f.get("description", "")))
                counts["schema_admission_attempts"] += 1
            schemas, previous_group = current_schemas, item["group"]
            counts["registry_builds"] += 1
        wire_tools = _to_openai_tool_descriptors(registry.descriptors())
        if sorted(wire_tools, key=lambda d:d["function"]["name"]) != sorted(tools, key=lambda d:d["function"]["name"]):
            raise ValueError("published schema differs from recording")
        durations["schema_publication"] += perf_counter() - t
        t = perf_counter()
        wire_messages = _to_openai_wire_messages(snapshot.messages)
        body = {**request, "messages": wire_messages, "tools": wire_tools}
        request_encoding = json_bytes(body)
        step["local_request_sha256"] = sha(request_encoding)
        # The context hash check above is exact. Wire content can differ because
        # provider-private reasoning is routed separately from public context.
        step["recorded_request_sha256"] = exchange.get("request_sha256")
        durations["wire_serialization"] += perf_counter() - t
        checks = []
        for call in item["calls"]:
            t = perf_counter()
            definition = registry._definitions.get(call["tool_id"])
            if definition is None:
                raise ValueError("recorded tool missing from the recorded registry")
            arguments = _wrap_single_strings(definition, call.get("arguments") or {})
            errors = validation_details(definition.input_schema, arguments)
            durations["schema_argument_validation"] += perf_counter() - t
            counts["tool_calls"] += 1
            checks.append({"tool_id": call["tool_id"], "errors": errors})
            t = perf_counter()
            tool_call_sha256(call)
            durations["tool_call_fingerprint"] += perf_counter() - t
        step["validation_sha256"] = sha(json_bytes(checks))
        t = perf_counter()
        # Replay the real recorded local persistence payloads into this worker's
        # private copy. No permission or tool handler is invoked or substituted.
        for recorded in item["persist"]:
            if recorded["entry_type"] == "tool_receipt":
                _canonical(recorded["payload"])
            identity = recorded.get("idempotency")
            if identity:
                persistence.append_once(manifest["session_id"], recorded["entry_type"], recorded["payload"],
                                        key=identity["key"], stage=identity["stage"])
            else:
                persistence.append(manifest["session_id"], recorded["entry_type"], recorded["payload"])
            counts["persisted_entries"] += 1
        durations["receipt_encoding_and_persistence"] += perf_counter() - t
        results.append(step)
    if profile:
        profile.disable()
    local_finished = perf_counter()
    if source_snapshot["manifest_sha256"]:
        verify_source_snapshot(source_tree, source_snapshot["manifest_sha256"])
    if any(sha(Path(path).read_bytes()) != value for path,value in source_sha256.items()):
        raise ValueError("pipeline source changed during replay")
    finished = perf_counter()
    summary = {"schema_version": 1, "scope": "offline_local_pipeline_replay", "default_product_path": False,
        "instrumented": bool(profile), "source_snapshot":source_snapshot, "source_tree": str(source_tree), "source_sha256": source_sha256, "python_version": sys.version,
        "manifest_sha256": args.sha256, "schedule_sha256": manifest["schedule_sha256"],
        "result_sha256": sha(json_bytes(results)), "requests": len(results), "counts": dict(counts),
        "seconds": finished - started, "source_preflight_seconds":source_validated - started,
        "source_postflight_seconds":finished - local_finished, "import_seconds": imported - source_validated,
        "input_copy_seconds": loaded - imported, "local_pipeline_seconds": local_finished - loaded, "stage_seconds": dict(durations),
        "recorded_model_seconds": sum(item["recorded_model_seconds"] or 0 for item in manifest["schedule"]),
        "recorded_model_wait_is_replayed": False,
        "tool_computation": "excluded; no handler invoked", "provider_requests": 0,
        "persistence_scope": "same recorded payload/order and append-vs-append_once on a fresh local session; new IDs",
        "validation_scope": "recorded JSON schemas via original schema checker; excludes runtime normalizers, admission and authorization",
        "context_contract": "exact source leaf and recorded fingerprint; stdlib JSON fingerprint, not canonical-v1",
        "canonical_engine": (native_canonical.backend_info() if native_canonical._load.cache_info().currsize
                             else {"engine": "not_invoked", "reason": "no_canonical_v1_numeric_call"}),
        "native_kernel_contribution": "not inferred; no canonical-v1 call added to this replay",
        "rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
        "work_dir": str(args.work_dir.resolve())}
    if profile:
        stats = pstats.Stats(profile)
        summary["profile_top_cumulative"] = [
            {"file": key[0], "line": key[1], "function": key[2], "primitive_calls": value[0],
             "calls": value[1], "self_seconds": value[2], "cumulative_seconds": value[3]}
            for key, value in sorted(stats.stats.items(), key=lambda pair:pair[1][3], reverse=True)[:50]]
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("prepare")
    setup.add_argument("--tape", type=Path, required=True)
    setup.add_argument("--sessions", type=Path, required=True)
    setup.add_argument("--session-id", required=True)
    setup.add_argument("--fixture", type=Path, required=True)
    run = sub.add_parser("worker")
    run.add_argument("--fixture", type=Path, required=True)
    run.add_argument("--source-tree", type=Path)
    run.add_argument("--sha256", required=True)
    run.add_argument("--work-dir", type=Path, required=True)
    run.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    prepare(args) if args.command == "prepare" else worker(args)


if __name__ == "__main__":
    main()
