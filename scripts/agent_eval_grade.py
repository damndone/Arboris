#!/usr/bin/env python3
"""Grade an evaluation round produced by ``agent_eval_run.py``.

Deterministic part (no model): reads each task's project from disk --

* models the Agent estimated (``runs/*/model_results``) and their specs;
* operations it executed (the analysis ledger, agent actor only);
* whether a qualifying model recovers the scenario's truth;
* coverage of the checks the design needs; completion; user actions;
* numbers shown to the person that no result supports (the product's own numeric check);
* provider usage from the tape: calls, prompt/completion tokens, cache hits.

Live outbound review (``--judge``) is disabled pending a separate scoped
approval. The minimized packet does not support the historical rubric.

    PYTHONPATH=backend .venv/bin/python scripts/agent_eval_grade.py local/agent-eval/baseline-v190
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from workbench.jsonl_store import jsonl_lines

from agent_eval import judge  # noqa: E402
from agent_eval.dgps import SCENARIOS, Scenario  # noqa: E402
from agent_eval.external import SOCCER_REFERENCE, final_answer_lines, qrdata_correct, replication_correct  # noqa: E402


def scenario_for_record(record: dict[str, Any]) -> Scenario:
    if record.get("suite") == "heldout":
        from agent_eval.heldout import HELDOUT_SCENARIOS

        return HELDOUT_SCENARIOS[record["scenario"]]
    return SCENARIOS[record["scenario"]]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _family_matches(model_type: str, families: tuple[str, ...]) -> bool:
    model_type = (model_type or "").lower()
    for family in families:
        family = family.lower()
        if model_type == family or model_type.startswith(family + "_") or model_type.startswith(family + ":"):
            return True
        if family in {"time_series", "matching", "meta", "synthetic_control", "power_analysis", "anova"} and family in model_type:
            return True
    return False


def models_in(project: Path, seed_run_id: str) -> list[dict[str, Any]]:
    out = []
    for path in sorted((project / "runs").glob("*/model_results/*.json")):
        if path.name.startswith(("checks_", "diagnostics_")):
            continue
        result = _read_json(path)
        if not isinstance(result, dict) or "coefficients" not in result:
            continue
        run_id = path.parent.parent.name
        form = ((_read_json(path.parent.parent / "run_inputs.json") or {}).get("form") or {})
        coefficients = result.get("coefficients")
        rows = coefficients.items() if isinstance(coefficients, dict) else (
            (row.get("term"), row) for row in coefficients or [] if isinstance(row, dict))
        out.append({
            "run_id": run_id,
            "seed": run_id == seed_run_id,
            "model_id": result.get("model_id"),
            "model_type": result.get("model_type") or "",
            # Some families (IV, panel) leave y/x out of the result; the run's form has them.
            "y": result.get("y_column") or form.get("y"),
            "x": result.get("x_columns") or [v for v in str(form.get("x") or "").split(",") if v],
            "covariance": result.get("covariance_estimator") or result.get("covariance"),
            "nobs": result.get("nobs"),
            "coefficients": {
                str(term): {k: row.get(k) for k in ("estimate", "std_error", "ci_lower", "ci_upper", "p_value")}
                for term, row in rows if isinstance(row, dict)
            },
        })
    return out


#: Checks the engine computes for every fitted linear model (diagnostics_*.json),
#: named by the operation they stand in for.
_AUTOMATIC = {"breusch_pagan": "diagnostics.breusch_pagan", "cooks_distance": "diagnostics.influence",
              "durbin_watson": "diagnostics.breusch_godfrey"}


def automatic_diagnostics(project: Path) -> set[str]:
    found = set()
    for path in (project / "runs").glob("*/model_results/diagnostics_*.json"):
        payload = _read_json(path) or {}
        found.update(op for key, op in _AUTOMATIC.items() if payload.get(key) is not None)
    return found


def agent_operations(project: Path) -> list[dict[str, Any]]:
    path = project / "workbench" / "analysis_ledger.jsonl"
    if not path.exists():
        return []
    out = []
    for line in jsonl_lines(path.read_text(encoding="utf-8")):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("actor") != "agent":
            continue
        out.append({"source": entry.get("source"), "status": entry.get("status"),
                    "operations": [step.get("operation_id") for step in entry.get("steps") or []]})
    return out


def _qualifies(model: dict[str, Any], scenario) -> bool:
    if model["seed"] or not _family_matches(model["model_type"], scenario.appropriate_families):
        return False
    want_log = scenario.extra.get("log_outcome")
    y = str(model.get("y") or "").lower()
    outcome = (scenario.outcome or "").lower()
    if want_log and not (y != outcome and (outcome in y or re.search(r"(^|_)(ln|log)", y))):
        return False
    if not want_log and outcome and y != outcome and scenario.id not in {"dirty_data"}:
        return False
    terms = [str(t).lower() for t in model["coefficients"]]
    main = (scenario.main_term or "").lower()
    # A polynomial in the main term changes what its coefficient means.
    return not any(main and t != main and main in t and ("pow" in t or "**" in t or "^" in t) for t in terms)


def artifact_operations(project: Path) -> list[str]:
    """Operations that left a workflow artifact but no model result file."""
    ops = []
    for path in sorted((project / "runs").glob("*/artifacts/*/*.json")):
        name = path.stem
        for prefix, kind in (("workflow_p7_", "p7"), ("workflow_capability_", "capability")):
            if name.startswith(prefix):
                body = re.sub(r"_[0-9a-f]{16}_[0-9a-f]{24}$", "", name[len(prefix):])
                ops.append(body)
    return ops


def _artifact_families(project: Path) -> set[str]:
    families = set()
    for op in artifact_operations(project):
        if "arma_garch" in op:
            families.update({"arma_garch", "time_series"})
        for family in ("time_series", "matching", "meta", "synthetic_control", "power_analysis", "survival"):
            if op.startswith(family):
                families.add(family if family != "survival" else "survival_test")
    return families


def _garch_persistence(project: Path) -> float | None:
    for path in sorted((project / "runs").glob("*/artifacts/*/*arma_garch*.json")):
        found: dict[str, float] = {}

        def walk(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "variance" and isinstance(value, dict) and "alpha[1]" in value and "beta[1]" in value:
                        found["p"] = float(value["alpha[1]"]) + float(value["beta[1]"])
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)
        walk(_read_json(path))
        if "p" in found:
            return found["p"]
    return None


def _vecm_long_run(project: Path, outcome: str) -> list[float]:
    values = []
    for path in sorted((project / "runs").glob("*/artifacts/p7_analysis/*time_series_vecm*.json")):
        payload = _read_json(path) or {}
        result = ((payload.get("result") or {}).get("result") or {})
        beta = result.get("beta")
        request = payload.get("request") or {}
        columns = list(((request.get("column_bindings") or {}).get("columns") or []))
        if isinstance(beta, list) and len(beta) == 2 and beta[0] and abs(float(beta[0][0])) > 0:
            # With the outcome first, the long-run slope is -beta[1]/beta[0];
            # with it second, the reciprocal.
            slope = -float(beta[1][0]) / float(beta[0][0])
            if columns and columns[0] != outcome and slope:
                slope = 1 / slope
            values.append(slope)
    return values


def _candidate_rows(model: dict[str, Any], scenario) -> list[tuple[float, Any, Any]]:
    coefficients = model["coefficients"]
    extra = scenario.extra
    if "terms_by_family" in extra:
        term = next((t for f, t in extra["terms_by_family"].items() if _family_matches(model["model_type"], (f,))), None)
        row = coefficients.get(term) if term else None
        return [(float(row["estimate"]), row.get("ci_lower"), row.get("ci_upper"))] if row and row.get("estimate") is not None else []
    if "term_contains" in extra:
        groups = extra["term_contains"]
        groups = groups if isinstance(groups[0], tuple) else (groups,)
        rows = [row for term, row in coefficients.items()
                if any(all(part in term.lower() for part in group) for group in groups) and row.get("estimate") is not None]
        return [(float(r["estimate"]), r.get("ci_lower"), r.get("ci_upper")) for r in rows]
    if "linear_combination" in extra:
        names = {t for weights in extra["linear_combination"] for t in weights}
        present = {t for t in names if coefficients.get(t, {}).get("estimate") is not None}
        for weights in extra["linear_combination"]:
            # A combination applies only to a model that holds exactly its terms.
            if set(weights) == present:
                return [(sum(w * float(coefficients[t]["estimate"]) for t, w in weights.items()), None, None)]
        return []
    row = coefficients.get(scenario.main_term)
    return [(float(row["estimate"]), row.get("ci_lower"), row.get("ci_upper"))] if row and row.get("estimate") is not None else []


#: v1 = the grader frozen at eval-v1.9.1-frozen (17c382e4); v2 adds sample truths for
#: scenarios whose fixed draw departs from the population value (GAP 2026-10-22).
GRADER_VERSIONS = ("v1", "v2")
GRADER_VERSION = "v2"


def scenario_truth(scenario, directory: Path | None, grader: str = GRADER_VERSION) -> tuple[float | None, str]:
    """The value an estimate is scored against, and where it comes from."""
    sample = scenario.extra.get("sample_truth")
    if grader == "v1" or sample is None or directory is None:
        return scenario.truth, "population"
    frames = sorted(p for p in directory.glob("*.csv"))
    if not frames:
        return scenario.truth, "population"
    import pandas as pd
    return float(sample(pd.read_csv(frames[0]))), "sample_oracle"


def estimate_check(models: list[dict[str, Any]], scenario, project: Path | None = None, *,
                   truth: float | None = None) -> dict[str, Any]:
    extra = scenario.extra
    if truth is not None:
        from dataclasses import replace
        scenario = replace(scenario, truth=truth)
    scored_by_rule = any(k in extra for k in ("terms_by_family", "term_contains", "linear_combination", "garch_persistence"))
    if scenario.truth is None or extra.get("score_estimate") is False or not (scenario.main_term or scored_by_rule):
        return {"applicable": False}
    if extra.get("garch_persistence"):
        value = _garch_persistence(project) if project else None
        recovered = value is not None and abs(value - scenario.truth) <= scenario.tolerance
        return {"applicable": True, "truth": scenario.truth, "recovered": recovered,
                "best": None if value is None else {"estimate": value, "model_type": "arma_garch", "ci": [None, None],
                                                    "covers_truth": False, "within_tolerance": recovered}}
    best = None
    if extra.get("vecm_long_run") and project is not None:
        for value in _vecm_long_run(project, scenario.outcome):
            close = abs(value - scenario.truth) <= scenario.tolerance
            if best is None or close and not best["within_tolerance"]:
                best = {"model_type": "vecm", "estimate": value, "ci": [None, None], "covers_truth": False,
                        "within_tolerance": close}
    if "log_log_elasticity" in extra:
        target, tolerance = extra["log_log_elasticity"]
        for model in models:
            y = str(model.get("y") or "").lower()
            if model["seed"] or not re.search(r"(^|_)(ln|log)", y):
                continue
            for term, row in model["coefficients"].items():
                if re.search(r"(^|_)(ln|log)", term.lower()) and "price" in term.lower() and row.get("estimate") is not None:
                    est = float(row["estimate"])
                    close = abs(est - target) <= tolerance
                    if best is None or close and not best["within_tolerance"]:
                        best = {"model_type": model["model_type"] + " (log-log elasticity)", "estimate": est,
                                "ci": [row.get("ci_lower"), row.get("ci_upper")], "covers_truth": False,
                                "within_tolerance": close}
    for model in models:
        if not _qualifies(model, scenario):
            continue
        for est, lo, hi in _candidate_rows(model, scenario):
            covered = lo is not None and hi is not None and float(lo) <= scenario.truth <= float(hi)
            close = abs(est - scenario.truth) <= scenario.tolerance
            candidate = {"run_id": model["run_id"], "model_type": model["model_type"], "estimate": est,
                         "ci": [lo, hi], "covers_truth": covered, "within_tolerance": close}
            if best is None or (covered or close) and not (best["covers_truth"] or best["within_tolerance"]):
                best = candidate
    return {"applicable": True, "truth": scenario.truth, "best": best,
            "recovered": bool(best and (best["covers_truth"] or best["within_tolerance"]))}


def _model_messages(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages = []
    for entry in entries:
        payload = entry.get("payload") or {}
        if entry.get("entry_type") == "message" and isinstance(payload.get("content"), str):
            messages.append({"role": payload.get("role"), "content": payload["content"]})
        elif entry.get("entry_type") == "custom_message" and isinstance(payload.get("content"), str):
            messages.append({"role": "system", "content": payload["content"]})
    return messages


def unsupported_numbers(replies: list[str], entries: list[dict[str, Any]], prompt: str) -> list[str]:
    """Numbers shown to the person that no given number supports.

    Uses the product's own rule (``numeric_grounding.check``): every decimal
    in a reply must equal, at the digits written, a number the model was
    given or a ``calculate`` result. Counted on what the person saw.
    """
    from workbench.agent import numeric_grounding

    messages = _model_messages(entries) + [{"role": "user", "content": prompt}]
    found = []
    for reply in replies:
        for finding in numeric_grounding.check(reply, messages):
            found.append(str(getattr(finding, "text", None) or getattr(finding, "value", finding)))
    return sorted(set(found))


def usage_from_tape(path: Path) -> dict[str, Any]:
    calls = prompt = completion = hit = miss = 0
    elapsed = []
    request_bytes = []
    compacted = path.with_name(path.name + ".gz")  # scripts/agent_eval/compact_rounds.py
    text = (path.read_text(encoding="utf-8") if path.exists()
            else gzip.decompress(compacted.read_bytes()).decode("utf-8") if compacted.exists() else None)
    if text is not None:
        for line in jsonl_lines(text):
            record = json.loads(line)
            calls += 1
            elapsed.append(record.get("elapsed_s") or 0)
            request_bytes.append(record.get("request_bytes") or 0)
            usage = record.get("usage") or {}
            prompt += usage.get("prompt_tokens") or 0
            completion += usage.get("completion_tokens") or 0
            hit += usage.get("prompt_cache_hit_tokens") or 0
            miss += usage.get("prompt_cache_miss_tokens") or 0
    return {"provider_calls": calls, "prompt_tokens": prompt, "completion_tokens": completion,
            "cache_hit_tokens": hit, "cache_miss_tokens": miss,
            "cache_hit_rate": round(hit / prompt, 4) if prompt else None,
            "provider_seconds": round(sum(elapsed), 1),
            "median_request_bytes": statistics.median(request_bytes) if request_bytes else None}


def grade_task(directory: Path, *, grader: str = GRADER_VERSION) -> dict[str, Any] | None:
    if grader not in GRADER_VERSIONS:
        raise ValueError(f"grader must be one of {GRADER_VERSIONS}")
    record = _read_json(directory / "record.json")
    if not record:
        return None
    if record.get("suite") == "external":
        return grade_external(directory, record)
    scenario = scenario_for_record(record)
    out: dict[str, Any] = {"task": directory.name, "scenario": scenario.id, "variant": record.get("variant"),
                           "status": record.get("status")}
    if record.get("status") != "ran":
        out["error"] = record.get("error")
        return out
    project = Path(record["project_root"])
    conversation = record["conversation"]
    models = models_in(project, record["seed_run_id"])
    operations = agent_operations(project)
    executed = [op for entry in operations if entry["status"] == "completed" for op in entry["operations"]]
    expected = scenario.expected_checks
    automatic = automatic_diagnostics(project)
    covered = [check for check in expected
               if any(op == alt or op.startswith(alt + ".") for alt in check.split("|") for op in executed)
               or any(alt in automatic for alt in check.split("|"))]
    replies = [turn["reply"] for turn in conversation["turns"]]
    entries = conversation["entries"]
    tool_calls = [call for e in entries if e.get("entry_type") == "message"
                  for call in (e.get("payload") or {}).get("tool_calls") or []]
    rejected = 0
    for e in entries:
        payload = e.get("payload") or {}
        if e.get("entry_type") == "message" and payload.get("role") == "tool":
            try:
                rejected += json.loads(payload.get("content") or "{}").get("ok") is False
            except ValueError:
                pass
    agent_models = [m for m in models if not m["seed"]]
    truth, truth_source = scenario_truth(scenario, directory, grader)
    out.update({
        "completed_marker": conversation["completed_marker"],
        "stop_reason": conversation["stop_reason"],
        "user_actions": conversation["user_actions"],
        "confirmations": len(conversation["confirmations"]),
        "failed_operations": sum(1 for c in conversation["confirmations"] if c.get("status") not in {"completed"}),
        "nudges": conversation["nudges"],
        "wall_s": conversation["wall_s"],
        "agent_turns": len(conversation["turns"]),
        "tool_calls": len(tool_calls),
        "tool_rejections": rejected,
        "models_estimated": len(agent_models),
        "families_used": sorted({m["model_type"] for m in agent_models} | _artifact_families(project)),
        "appropriate_family_used": (any(_family_matches(m["model_type"], scenario.appropriate_families) for m in agent_models)
                                    or bool(_artifact_families(project) & set(scenario.appropriate_families)))
                                   if scenario.appropriate_families else None,
        "artifact_operations": artifact_operations(project),
        "estimate": {**estimate_check(models, scenario, project, truth=truth), "truth_source": truth_source},
        "grader": grader,
        "checks_expected": list(expected),
        "checks_covered": covered,
        "check_coverage": round(len(covered) / len(expected), 3) if expected else None,
        "operations_executed": executed,
        "unsupported_numbers": unsupported_numbers(replies, entries, record["prompt"]),
        "final_answer_chars": len(replies[-1]) if replies else 0,
        "usage": usage_from_tape(directory / "provider_tape.jsonl"),
    })
    return out


def _final_answer_line(reply: str) -> str | None:
    lines = final_answer_lines(reply)
    return re.split(r"[:：]", lines[-1], maxsplit=1)[-1].strip() if lines else None


def grade_external(directory: Path, record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"task": directory.name, "suite": "external", "source": record.get("source"),
                           "status": record.get("status")}
    if record.get("status") != "ran":
        out["error"] = record.get("error")
        return out
    conversation = record["conversation"]
    replies = [turn["reply"] for turn in conversation["turns"]]
    final = next((r for r in reversed(replies) if final_answer_lines(r)), replies[-1] if replies else "")
    out.update({
        "user_actions": conversation["user_actions"], "nudges": conversation["nudges"], "wall_s": conversation["wall_s"],
        "completed_marker": conversation["completed_marker"], "final_answer": _final_answer_line(final),
        "unsupported_numbers": unsupported_numbers(replies, conversation["entries"], record["prompt"]),
        "usage": usage_from_tape(directory / "provider_tape.jsonl"),
    })
    if record.get("source") == "qrdata":
        out["category"] = (record.get("reference") or {}).get("category")
        out["correct"] = bool(qrdata_correct(record["answer"], final, record["question_type"]))
    if record.get("source") == "replication":
        out["correct"] = bool(replication_correct(record["reference"], final))
    if record.get("task_id") == "blade.soccer":
        ors = [float(m) for m in re.findall(r"(?:odds ratio|OR)[^0-9]{0,20}(\d+\.\d+)", final, re.I)]
        out["reported_odds_ratios"] = ors
        out["within_many_analysts_range"] = bool(ors) and SOCCER_REFERENCE["odds_ratio_min"] <= ors[0] <= SOCCER_REFERENCE["odds_ratio_max"]
    return out


def judge_task(directory: Path, _graded: dict[str, Any]) -> dict[str, Any]:
    """Prepare the direct API boundary using only the outbound projection."""
    packet = judge.outbound_packet(_read_json(directory / "record.json"))
    messages = [{"role": "system", "content": judge.OUTBOUND_SYSTEM},
                {"role": "user", "content": judge.outbound_prompt(packet)}]
    judge.require_outbound_approval()

    from workbench.llm.client import chat_completion
    from workbench.llm.config import load_llm_config

    response = chat_completion(messages, load_llm_config())
    return judge.outbound_result(response.get("content") or response.get("text") or "")


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    external = [r for r in rows if r.get("suite") == "external" and r.get("status") == "ran"]
    rows = [r for r in rows if r.get("suite") != "external"]
    ran = [r for r in rows if r.get("status") == "ran"]
    def rate(key, predicate=bool):
        values = [r[key] for r in ran if r.get(key) is not None]
        return round(sum(1 for v in values if predicate(v)) / len(values), 3) if values else None
    recovered = [r["estimate"]["recovered"] for r in ran if r["estimate"].get("applicable")]
    total_tool_calls = sum(r["tool_calls"] for r in ran)
    usage = [r["usage"] for r in ran]
    prompt = sum(u["prompt_tokens"] for u in usage)
    out = {
        "tasks": len(rows), "ran": len(ran), "harness_errors": len(rows) - len(ran),
        "completed_marker_rate": rate("completed_marker"),
        "appropriate_family_rate": rate("appropriate_family_used"),
        "estimate_recovered_rate": round(sum(recovered) / len(recovered), 3) if recovered else None,
        "mean_check_coverage": round(statistics.mean([r["check_coverage"] for r in ran if r["check_coverage"] is not None]), 3)
                               if any(r["check_coverage"] is not None for r in ran) else None,
        "median_user_actions": statistics.median([r["user_actions"] for r in ran]) if ran else None,
        "median_nudges": statistics.median([r["nudges"] for r in ran]) if ran else None,
        "median_wall_s": statistics.median([r["wall_s"] for r in ran]) if ran else None,
        "tool_rejection_rate": round(sum(r["tool_rejections"] for r in ran) / total_tool_calls, 4) if total_tool_calls else None,
        "tasks_with_unsupported_numbers": sum(1 for r in ran if r["unsupported_numbers"]),
        "provider_calls": sum(u["provider_calls"] for u in usage),
        "prompt_tokens": prompt,
        "completion_tokens": sum(u["completion_tokens"] for u in usage),
        "cache_hit_rate": round(sum(u["cache_hit_tokens"] for u in usage) / prompt, 4) if prompt else None,
    }
    if external:
        qr = [r for r in external if r.get("source") == "qrdata"]
        out["external"] = {
            "qrdata_tasks": len(qr),
            "qrdata_accuracy": round(sum(r["correct"] for r in qr) / len(qr), 3) if qr else None,
            "qrdata_accuracy_by_category": {c: round(sum(r["correct"] for r in qr if r["category"] == c) / n, 3)
                                            for c in {r["category"] for r in qr}
                                            for n in [sum(1 for r in qr if r["category"] == c)]},
            "blade_tasks": sum(1 for r in external if r.get("source") == "blade"),
            "replications_reproduced": sum(1 for r in external if r.get("source") == "replication" and r.get("correct")),
            "replications": sum(1 for r in external if r.get("source") == "replication"),
            "soccer": next(({"odds_ratios": r.get("reported_odds_ratios"), "within_range": r.get("within_many_analysts_range")}
                            for r in external if r["task"].startswith("blade.soccer")), None),
            "blade_rubric_overall": (round(statistics.mean(statistics.mean(r["judge"][k]["score"] for k in judge.RUBRIC)
                                                           for r in external if r.get("source") == "blade" and isinstance(r.get("judge"), dict)), 2)
                                     if any(r.get("source") == "blade" and isinstance(r.get("judge"), dict) for r in external) else None),
            "median_user_actions": statistics.median([r["user_actions"] for r in external]),
        }
    judged = [r["judge"] for r in ran if isinstance(r.get("judge"), dict)]
    if judged:
        out["rubric_mean"] = {key: round(statistics.mean(j[key]["score"] for j in judged), 2) for key in judge.RUBRIC}
        out["rubric_overall"] = round(statistics.mean(statistics.mean(j[k]["score"] for k in judge.RUBRIC) for j in judged), 2)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("round_dir", type=Path)
    parser.add_argument("--judge", action="store_true", help="live review (requires separate scoped approval)")
    parser.add_argument("--grader", choices=GRADER_VERSIONS, default=GRADER_VERSION,
                        help="v1 = frozen at eval-v1.9.1-frozen (writes grades.json); v2 writes grades-v2.json")
    args = parser.parse_args()
    if args.judge:
        try:
            judge.require_outbound_approval()
        except judge.OutboundJudgeBlocked as exc:
            parser.error(str(exc))
    rows = []
    for directory in sorted((args.round_dir / "tasks").iterdir()):
        graded = grade_task(directory, grader=args.grader)
        if graded is None:
            continue
        if args.judge and graded.get("status") == "ran":
            try:
                graded["outbound_review"] = judge_task(directory, graded)
            except judge.OutboundJudgeBlocked as exc:
                parser.error(str(exc))
            except Exception as exc:  # record without importing the historical score cache
                graded["outbound_review"] = {"protocol": judge.OUTBOUND_PROTOCOL, "status": "unscored",
                                             "reason": type(exc).__name__}
        rows.append(graded)
    summary = summarize(rows)
    name = "grades.json" if args.grader == "v1" else f"grades-{args.grader}.json"
    (args.round_dir / name).write_text(json.dumps({"summary": {**summary, "grader": args.grader}, "tasks": rows},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
