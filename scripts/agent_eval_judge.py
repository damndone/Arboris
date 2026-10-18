#!/usr/bin/env python3
"""Judge an evaluation round with the CLI judges, showing every step.

Three steps, each separately runnable:

  --export        write each task's judge packet (no model call) for review
  --backend X     run judge X (codex | grok) on the exported packets; prints the
                  task, prompt size, exact command line, time and scores as it goes
  --agreement     compare the judges with each other and with the blind
                  calibration scores (quadratic-weighted kappa, exact / within-1)

    PYTHONPATH=backend .venv/bin/python scripts/agent_eval_judge.py local/agent-eval/baseline-v190 --export
    PYTHONPATH=backend .venv/bin/python scripts/agent_eval_judge.py local/agent-eval/baseline-v190 --backend codex --limit 1
"""

from __future__ import annotations

import argparse
import json
import shlex
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from agent_eval import cli_judges, judge  # noqa: E402
from agent_eval_grade import ALL_SCENARIOS, agent_operations, models_in  # noqa: E402


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


def artifact_results(project: Path, limit_chars: int = 1500) -> list[dict]:
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
    record = json.loads((directory / "record.json").read_text(encoding="utf-8"))
    project = Path(record["project_root"])
    facts = {
        "models": [m for m in models_in(project, record["seed_run_id"]) if not m["seed"]],
        "operations_executed": [op for e in agent_operations(project) if e["status"] == "completed" for op in e["operations"]],
        "failed_operations": sum(1 for c in record["conversation"]["confirmations"] if c.get("status") != "completed"),
        "model_diagnostics": model_diagnostics(project, record["seed_run_id"]),
        "analysis_artifacts": artifact_results(project),
    }
    if record.get("suite") == "external":
        truth = {"source": record.get("source"), "reference": record.get("reference")}
    else:
        s = ALL_SCENARIOS[record["scenario"]]
        truth = {"title": s.title, "estimand_truth": s.truth, "main_term": s.main_term,
                 "appropriate_families": s.appropriate_families, "expected_checks": s.expected_checks,
                 "traps": s.traps, "notes": s.notes}
    final = "\n\n---\n\n".join(t["reply"] for t in record["conversation"]["turns"][-3:])
    return judge.build_prompt(record, truth, facts, final)


def export(round_dir: Path, tasks: list[Path]) -> None:
    total = 0
    for directory in tasks:
        target = round_dir / "judging" / directory.name
        target.mkdir(parents=True, exist_ok=True)
        text = packet(directory)
        (target / "packet.txt").write_text(text, encoding="utf-8")
        total += len(text)
        print(f"exported {directory.name}: {len(text):,} chars")
    print(f"{len(tasks)} packets, {total:,} chars in {round_dir / 'judging'}")


def run_backend(round_dir: Path, tasks: list[Path], backend: str, limit: int | None) -> None:
    done = 0
    for directory in tasks:
        target = (round_dir / "judging" / directory.name).resolve()
        result_file = target / f"{backend}.result.json"
        if result_file.exists() and "scores" in json.loads(result_file.read_text(encoding="utf-8")):
            print(f"[{backend}] {directory.name}: already judged, skipped")
            continue
        if limit is not None and done >= limit:
            break
        text = (target / "packet.txt").read_text(encoding="utf-8")
        argv = cli_judges.command(backend, Path("<empty scratch dir>"), target / f"{backend}.prompt.txt",
                                  target / "schema.json", target / f"{backend}.last_message.json")
        print(f"\n[{backend}] {directory.name}: sending {len(text):,} chars")
        print("  $ " + shlex.join(argv)[:600] + (" ..." if len(shlex.join(argv)) > 600 else ""), flush=True)
        try:
            result = cli_judges.run(backend, text, target)
        except Exception as exc:  # recorded, the loop continues
            result = {"error": f"{type(exc).__name__}: {exc}"}
        result_file.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        if "scores" in result:
            line = "  ".join(f"{k}={v['score']}" for k, v in result["scores"].items())
            print(f"  -> {result['elapsed_s']} s  {line}", flush=True)
        else:
            print(f"  -> ERROR {result.get('error')}  (see {target})", flush=True)
        done += 1


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
    parser.add_argument("--backend", choices=("codex", "grok"))
    parser.add_argument("--agreement", action="store_true")
    parser.add_argument("--tasks", default="")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    tasks = _tasks(args.round_dir, {t for t in args.tasks.split(",") if t})
    if args.export:
        export(args.round_dir, tasks)
    if args.backend:
        run_backend(args.round_dir, tasks, args.backend, args.limit)
    if args.agreement:
        agreement(args.round_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
