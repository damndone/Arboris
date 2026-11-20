#!/usr/bin/env python3
"""Export structural judge evidence or inspect historical local judgments.

  --export        write the minimized, unscored packet under judging-outbound
  --export-owner  write restricted local evidence under judging-owner-local
  --agreement     compare historical rubric scores under judging
  --backend X     live CLI review (disabled pending separate scoped approval)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_eval import cli_judges, judge  # noqa: E402
from agent_eval_grade import agent_operations, models_in, scenario_for_record  # noqa: E402


def _tasks(round_dir: Path, only: set[str]) -> list[Path]:
    out = []
    for directory in sorted((round_dir / "tasks").iterdir()):
        record = directory / "record.json"
        if not record.exists():
            continue
        data = json.loads(record.read_text(encoding="utf-8"))
        if data.get("status") != "ran" or (only and directory.name not in only):
            continue
        # Judge first runs only; repeats are scored deterministically.
        if not directory.name.endswith(".r1") or data.get("source") == "qrdata" or data.get("source") == "replication":
            continue
        out.append(directory)
    return out


_DROP_KEYS = {"scope", "assumptions", "input_semantics", "evidence_digest", "schema_version", "contract",
              "contract_version", "request_fingerprint", "result_sha256", "source", "fitted_values", "residuals",
              "fitted_values_preview", "residuals_preview", "forecast", "scores", "rows"}


def _compact(node, depth: int = 0):
    """A reader-sized view of a result: numbers to 6 significant digits, long lists cut."""
    if isinstance(node, float):
        return float(f"{node:.6g}")
    if isinstance(node, dict):
        return {k: _compact(v, depth + 1) for k, v in node.items() if k not in _DROP_KEYS and depth < 8}
    if isinstance(node, list):
        items = [_compact(v, depth + 1) for v in node[:12]]
        return items + ([f"... {len(node) - 12} more"] if len(node) > 12 else [])
    return node


def _with_fit(project: Path, model: dict) -> dict:
    """Add the fit statistics a write-up quotes (R squared, nobs, AIC, ...) to a model entry."""
    path = project / "runs" / model["run_id"] / "model_results" / f"{model['model_id']}.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    fit = {k: payload.get(k) for k in ("nobs", "r_squared", "r_squared_adj", "pseudo_r2", "llf", "aic", "bic")
           if payload.get(k) is not None}
    for key in ("r_squared_within", "within_r_squared", "rsquared_within"):
        if payload.get(key) is not None:
            fit["r_squared_within"] = payload[key]
    return {**model, "fit": _compact(fit)}


def _tool_evidence(entries: list, each: int = 2500, total: int = 30000) -> list[dict]:
    """The tool results the assistant received, compacted, newest last, within a budget."""
    names = {}
    for entry in entries:
        for call in (entry.get("payload") or {}).get("tool_calls") or []:
            names[call.get("tool_call_id") or call.get("id")] = call.get("tool_id")
    out, used = [], 0
    for entry in entries:
        payload = entry.get("payload") or {}
        if entry.get("entry_type") != "message" or payload.get("role") != "tool":
            continue
        content = payload.get("content") or ""
        try:
            content = json.dumps(_compact(json.loads(content)), ensure_ascii=False, separators=(",", ":"))
        except ValueError:
            pass
        name = names.get(payload.get("tool_call_id")) or "tool"
        if name == "inspect_operation_contract":
            continue  # the operation catalog, not evidence
        piece = content[:each]
        out.append({"tool": name, "result": piece})
        used += len(piece)
    while used > total and out:
        used -= len(out.pop(0)["result"])
    return out


def artifact_results(project: Path, limit_chars: int = 4000) -> list[dict]:
    """Every analysis artifact the Agent produced, compacted (diagnostics, tests, explorations)."""
    out = []
    for path in sorted((project / "runs").glob("*/artifacts/*/*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        body = payload.get("result", payload) if isinstance(payload, dict) else payload
        text = json.dumps(_compact(body), ensure_ascii=False, separators=(",", ":"))
        out.append({"artifact": path.parent.name + "/" + path.stem[:60],
                    "result": text[:limit_chars] + (" ...[cut]" if len(text) > limit_chars else "")})
    return out


def model_diagnostics(project: Path, seed_run_id: str) -> list[dict]:
    """The engine's automatic diagnostics for every model the Agent fitted."""
    out = []
    for path in sorted((project / "runs").glob("*/model_results/diagnostics_*.json")):
        if path.parent.parent.name == seed_run_id:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        out.append({"run_id": path.parent.parent.name, **_compact({k: v for k, v in payload.items() if k != "vif_basis"})})
    return out


def packet(directory: Path) -> str:
    """Historical owner packet format, containing private evidence."""
    record = json.loads((directory / "record.json").read_text(encoding="utf-8"))
    if record.get("suite") == "heldout":
        raise ValueError("held-out owner packet requires separate authorization")
    project = Path(record["project_root"])
    facts = {
        # The import model is part of the record the answer may cite; it is marked as such.
        "models": [_with_fit(project, m) for m in models_in(project, record["seed_run_id"])],
        # What the assistant was shown: a number is traceable if it came from here.
        "tool_results_seen_by_assistant": _tool_evidence(record["conversation"]["entries"]),
        "operations_executed": [op for e in agent_operations(project) if e["status"] == "completed" for op in e["operations"]],
        "failed_operations": sum(1 for c in record["conversation"]["confirmations"] if c.get("status") != "completed"),
        "model_diagnostics": model_diagnostics(project, record["seed_run_id"]),
        "analysis_artifacts": artifact_results(project),
    }
    if record.get("suite") == "external":
        truth = {"source": record.get("source"), "reference": record.get("reference")}
    else:
        s = scenario_for_record(record)
        truth = {"title": s.title, "estimand_truth": s.truth, "main_term": s.main_term,
                 "appropriate_families": s.appropriate_families, "expected_checks": s.expected_checks,
                 "traps": s.traps, "notes": s.notes}
    final = "\n\n---\n\n".join(t["reply"] for t in record["conversation"]["turns"][-3:])
    return judge.build_prompt(record, truth, facts, final)


def _outbound_packet(directory: Path) -> judge.OutboundPacket:
    return judge.outbound_packet(json.loads((directory / "record.json").read_text(encoding="utf-8")))


def _slots(round_dir: Path) -> dict[str, str]:
    directories = sorted(path for path in (round_dir / "tasks").iterdir() if path.is_dir())
    return {path.name: f"case-{i:03d}" for i, path in enumerate(directories, 1)}


def _target(round_dir: Path, area: str, label: str) -> Path:
    target = round_dir.resolve() / area / label
    if target.resolve() != target:
        raise ValueError("judge output directory must not use symlinks")
    return target


def export(round_dir: Path, tasks: list[Path], *, owner: bool = False) -> bool:
    exported, refused = 0, 0
    area = "judging-owner-local" if owner else "judging-outbound"
    slots = {} if owner else _slots(round_dir)
    for directory in tasks:
        label = directory.name if owner else slots[directory.name]
        try:
            target = _target(round_dir, area, label)
            path = target / ("owner-packet.txt" if owner else "packet.txt")
            text = packet(directory) if owner else judge.outbound_prompt(_outbound_packet(directory))
            target.mkdir(parents=True, mode=0o700, exist_ok=True)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                if path.is_symlink() or (not owner and path.read_text(encoding="utf-8") != text):
                    raise ValueError("existing packet differs or is a symlink")
                print(f"preserved existing {'owner' if owner else 'outbound'} packet for {label}")
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(text)
        except (ValueError, OSError):
            refused += 1
            print(f"refused {label}: unsupported {'owner' if owner else 'outbound'} evidence or output path")
            continue
        exported += 1
    print(f"{exported} packets, {refused} refused in {area}" if tasks else "No eligible packets")
    return refused == 0


def run_backend(round_dir: Path, tasks: list[Path], backend: str, limit: int | None) -> None:
    if backend not in {"codex", "grok"}:
        raise ValueError("unknown judge backend")
    slots = _slots(round_dir)
    for directory in tasks[:limit]:
        label = slots[directory.name]
        target = _target(round_dir, "judging-review-local", label)
        try:
            result = cli_judges.run(backend, _outbound_packet(directory), target)
        except judge.OutboundJudgeBlocked:
            raise
        except Exception as exc:  # recorded, the loop continues
            result = {"protocol": judge.OUTBOUND_PROTOCOL, "status": "unscored", "reason": type(exc).__name__}
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{backend}.result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(f"[{backend}] {label}: unscored ({result['reason']})", flush=True)


def _qwk(a: list[int], b: list[int]) -> float | None:
    """Quadratic-weighted Cohen's kappa on a 1-5 scale."""
    if len(a) < 2:
        return None
    k = 5
    observed = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        observed[x - 1][y - 1] += 1
    n = len(a)
    row = [sum(r) for r in observed]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = (i - j) ** 2 / (k - 1) ** 2
            num += w * observed[i][j]
            den += w * row[i] * col[j] / n
    return round(1 - num / den, 3) if den else None


def agreement(round_dir: Path) -> None:
    raters: dict[str, dict[str, dict[str, int]]] = {}
    for path in (round_dir / "judging").glob("*/*.result.json"):
        result = json.loads(path.read_text(encoding="utf-8"))
        if "scores" in result:
            raters.setdefault(path.name.split(".")[0], {})[path.parent.name] = {k: v["score"] for k, v in result["scores"].items()}
    blind = round_dir.parent / "calibration_claude_blind.json"
    if blind.exists():
        raters["claude_blind"] = json.loads(blind.read_text(encoding="utf-8"))["scores"]
    names = sorted(raters)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            shared = sorted(set(raters[first]) & set(raters[second]))
            a = [raters[first][t][k] for t in shared for k in judge.RUBRIC]
            b = [raters[second][t][k] for t in shared for k in judge.RUBRIC]
            if not shared:
                continue
            exact = sum(x == y for x, y in zip(a, b)) / len(a)
            within = sum(abs(x - y) <= 1 for x, y in zip(a, b)) / len(a)
            print(f"{first} vs {second}: tasks={len(shared)} qwk={_qwk(a, b)} exact={exact:.2f} within1={within:.2f} "
                  f"mean {statistics.mean(a):.2f} vs {statistics.mean(b):.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("round_dir", type=Path)
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--export-owner", action="store_true", help="write restricted local-only owner packets")
    parser.add_argument("--backend", choices=("codex", "grok"))
    parser.add_argument("--agreement", action="store_true")
    parser.add_argument("--tasks", default="")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.backend:
        try:
            judge.require_outbound_approval()
        except judge.OutboundJudgeBlocked as exc:
            parser.error(str(exc))
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be nonnegative")
    tasks = _tasks(args.round_dir, {t for t in args.tasks.split(",") if t}) if (
        args.export or args.export_owner or args.backend) else []
    ok = True
    if args.export:
        ok = export(args.round_dir, tasks)
    if args.export_owner:
        ok = export(args.round_dir, tasks, owner=True) and ok
    if args.backend:
        run_backend(args.round_dir, tasks, args.backend, args.limit)
    if args.agreement:
        agreement(args.round_dir)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
