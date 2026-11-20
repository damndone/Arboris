"""Audit existing grades against a frozen list of suite/task_id/mode/repeat slots.

Pass the JSON plan followed by grade JSON files, each beside its run_meta.json.
The report goes to stdout. The audit reads scores without rerunning the grader.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re


_FIELDS = ("suite", "task_id", "mode", "repeat")
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_TASK_RUN = re.compile(r"(.+)\.r([1-9][0-9]*)")
_OUTCOMES = ("correct", "incorrect", "interrupted", "missing", "ran_unscored")


def _slot(suite, task_id, mode, repeat):
    if suite not in ("dev", "heldout", "external") or mode not in ("legacy", "ask", "auto"):
        raise ValueError("a slot needs a valid suite and mode")
    if not isinstance(task_id, str) or not _TASK.fullmatch(task_id):
        raise ValueError("a slot needs a canonical task_id")
    if type(repeat) is not int or repeat < 1:
        raise ValueError("a slot repeat must be a positive integer")
    return suite, task_id, mode, repeat


def _source(suite, task_id):
    return task_id.partition(".")[0] if suite == "external" else None


def _read_grades(plan, groups, candidate):
    declared = set()
    seen = {}
    for meta, grades in groups:
        if candidate is not None and (
            meta.get("git_head") != candidate or meta.get("product_dirty") is not False
            or grades.get("summary", {}).get("grader") != "v2"
        ):
            raise ValueError("formal grades must use the frozen candidate, clean product tree and grader v2")
        suite, mode, repeat = meta["suite"], meta["policy"]["mode"], meta["repeat"]
        tasks = meta["tasks"]
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("run_meta must declare a nonempty task list")
        task_ids = {_slot(suite, task, mode, repeat)[1] for task in tasks}
        if len(task_ids) != len(tasks):
            raise ValueError("duplicate tasks in run_meta")
        expected = {key for key in plan if key[0] == suite and key[1] in task_ids
                    and key[2] == mode and key[3] <= repeat}
        if len(expected) != len(tasks) * repeat:
            raise ValueError("unexpected run_meta slots outside the frozen plan")
        if declared & expected:
            raise ValueError("duplicate run_meta slots across grade files")
        declared.update(expected)
        if not isinstance(grades["tasks"], list):
            raise ValueError("grades must contain a task list")
        for row in grades["tasks"]:
            match = _TASK_RUN.fullmatch(row["task"])
            if not match:
                raise ValueError("a grade task must have a .r<repeat> suffix")
            task_id, rep = match.groups()
            key = _slot(suite, task_id, mode, int(rep))
            if key not in expected or row.get("suite", suite) != suite or row.get("mode", mode) != mode:
                raise ValueError(f"unexpected grade for {key}")
            if key in seen:
                raise ValueError(f"duplicate grade for {key}")
            source = _source(suite, task_id)
            if row.get("source", source) != source:
                raise ValueError(f"unexpected grade source for {key}")
            status, correct = row["status"], row.get("correct")
            if not isinstance(status, str) or not status or (correct is not None and type(correct) is not bool):
                raise ValueError(f"invalid grade status or correctness for {key}")
            if status != "ran":
                outcome = "interrupted"
            elif correct is None:
                outcome = "ran_unscored"
            else:
                outcome = "correct" if correct else "incorrect"
            seen[key] = row, outcome
    return seen


def _pass3_trial(grade):
    if grade is None:
        return "missing"
    row, outcome = grade
    if outcome == "interrupted":
        return outcome
    if row.get("grader") != "v2":
        raise ValueError("pass3 development rows must use grader v2")
    if row.get("completed_marker") is not True:
        return "not_completed"
    if row.get("appropriate_family_used") is not True:
        return "method_mismatch"
    estimate = row.get("estimate") or {}
    if estimate.get("applicable") is not True or estimate.get("recovered") is not True:
        return "estimate_not_recovered"
    return "passed"


def _pass3_summary(plan, grades, cases):
    modes = ("ask", "auto")
    required = {("dev", case, mode, rep) for case in cases for mode in modes for rep in (1, 2, 3)}
    if len(required) != 108 or not required <= plan:
        raise ValueError("the plan must include all 108 approved pass3 slots")
    summaries = {}
    for mode in modes:
        trials = {case: [_pass3_trial(grades.get(("dev", case, mode, rep))) for rep in (1, 2, 3)]
                  for case in cases}
        passed = sum(all(trial == "passed" for trial in results) for results in trials.values())
        summaries[mode] = {"planned_cases": len(cases), "passed_cases": passed,
                           "required_cases": 14, "passed": passed >= 14, "cases": trials}
    return {"passed": all(item["passed"] for item in summaries.values()), "modes": summaries}


def _development_completion_counts(slots, grades, eligible_scenarios):
    eligible = [key for key in slots if key[1].rsplit(".", 1)[0] in eligible_scenarios]
    scored = correct = 0
    for key in eligible:
        row, _ = grades.get(key, ({}, "missing"))
        family = row.get("appropriate_family_used")
        estimate = row.get("estimate")
        if (row.get("status") == "ran" and row.get("grader") == "v2" and type(family) is bool
                and isinstance(estimate, dict) and estimate.get("applicable") is True
                and type(estimate.get("recovered")) is bool):
            scored += 1
            correct += family and estimate["recovered"]
    return {
        "planned_r1": len(slots),
        "estimate_eligible_r1": len(eligible),
        "scored_eligible_r1": scored,
        "confirmed_correct_r1": correct,
        "confirmed_correct_all_rate": correct / len(slots),
        "confirmed_correct_estimate_eligible_rate": correct / len(eligible),
    }


def _development_applicability(slots, grades, stability_cases):
    if __package__:
        from .m5_dev_admission import PLAN_SHA256, plan_sha256
    else:
        from m5_dev_admission import PLAN_SHA256, plan_sha256

    modes = {mode: {"planned_r1": 0, "reported_inapplicable_r1": 0} for mode in ("ask", "auto")}
    for key in slots:
        suite, _, mode, repeat = key
        if suite != "dev" or mode not in modes or repeat != 1:
            continue
        modes[mode]["planned_r1"] += 1
        row, _ = grades.get(key, ({}, "missing"))
        estimate = row.get("estimate")
        if (row.get("status") == "ran" and row.get("grader") == "v2"
                and isinstance(estimate, dict) and estimate.get("applicable") is False):
            modes[mode]["reported_inapplicable_r1"] += 1
    result = {
        "status": "unresolved_applicability",
        "reason": ("The M0 baseline uses 54 deterministically scored r1 tasks. The later execution draft uses "
                   "all 63 r1 tasks. The frozen threshold needs an explicit treatment of inapplicable estimates."),
        "modes": modes,
    }
    plan = [dict(zip(_FIELDS, key)) for key in sorted(slots, key=lambda key: (key[2], key[1], key[3]))]
    # The 18 frozen open cases cover precisely the estimate-eligible dev scenarios.
    # Use their roster so missing grades cannot shrink either R1 denominator.
    if plan_sha256(plan) == PLAN_SHA256:
        eligible_scenarios = {case.rsplit(".", 1)[0] for case in stability_cases}
        views = {}
        for mode in modes:
            r1 = [key for key in slots if key[2] == mode and key[3] == 1]
            non_iv = [key for key in r1 if not key[1].startswith("iv_")]
            views[mode] = {
                "including_iv": _development_completion_counts(r1, grades, eligible_scenarios),
                "excluding_iv": _development_completion_counts(non_iv, grades, eligible_scenarios),
            }
        result["denominator_views"] = views
    return result


def _finite_grade_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _heldout_adjudication(row):
    family = row.get("appropriate_family_used")
    if type(family) is not bool:
        return "unresolved_method"
    estimate = row.get("estimate")
    if not isinstance(estimate, dict) or type(estimate.get("applicable")) is not bool:
        return "unverified_estimate"
    if not estimate["applicable"]:
        return "estimate_inapplicable"
    recovered = estimate.get("recovered")
    if (type(recovered) is not bool or not _finite_grade_number(estimate.get("truth"))
            or estimate.get("truth_source") not in ("population", "sample_oracle") or "best" not in estimate):
        return "unverified_estimate"
    best = estimate["best"]
    if best is None:
        if recovered:
            return "unverified_estimate"
    elif (not isinstance(best, dict) or not _finite_grade_number(best.get("estimate"))
            or any(type(best.get(field)) is not bool for field in ("covers_truth", "within_tolerance"))
            or recovered != (best["covers_truth"] or best["within_tolerance"])):
        return "unverified_estimate"
    if not family:
        return "method_mismatch"
    return "correct" if recovered else "estimate_not_recovered"


def _heldout_summary(slots, grades):
    modes = {mode: {"planned": 0, "marker_completed": 0, "correctly_completed": 0} for mode in ("ask", "auto")}
    outcomes = {}
    for key in slots:
        totals = modes[key[2]]
        totals["planned"] += 1
        row, outcome = grades.get(key, ({}, "missing"))
        if row.get("status") == "ran":
            if row.get("grader") != "v2" or type(row.get("completed_marker")) is not bool:
                raise ValueError("ran heldout tasks require a v2 completion record")
            totals["marker_completed"] += row["completed_marker"]
            outcome = _heldout_adjudication(row)
            totals["correctly_completed"] += outcome == "correct"
        outcomes[key] = outcome
    planned = len(slots)
    markers = sum(totals["marker_completed"] for totals in modes.values())
    correct = sum(totals["correctly_completed"] for totals in modes.values())
    evidence_complete = all(outcome in ("correct", "method_mismatch", "estimate_not_recovered")
                            for outcome in outcomes.values())
    return {
        "planned": planned,
        "marker_coverage": {"completed": markers, "completion_rate": markers / planned},
        "correctly_completed": correct,
        "correct_completion_rate": correct / planned,
        "evidence_complete": evidence_complete,
        "passed": evidence_complete and correct * 5 >= planned * 4,
        "modes": modes,
    }, outcomes


def audit_coverage(plan, groups, *, pass3_candidate=None):
    """Join the planned slots to (run_meta, grade document) pairs."""
    heldout_candidate = None
    if isinstance(plan, dict) and plan.get("schema") == "agent-heldout-schedule/v1":
        if __package__:
            from .heldout_admission import frozen_allocation
        else:
            from heldout_admission import frozen_allocation

        allocation, allocation_sha = frozen_allocation()
        heldout_candidate = plan["candidate_sha"]
        receipt = plan["approval_receipt_sha256"]
        if (pass3_candidate is not None or not re.fullmatch(r"[0-9a-f]{40}", heldout_candidate)
                or not re.fullmatch(r"[0-9a-f]{64}", receipt) or plan["allocation_sha256"] != allocation_sha):
            raise ValueError("invalid sealed heldout schedule identity")
        plan = plan["slots"]
        if (len(plan) != len(allocation) or len({row["task_id"] for row in plan}) != len(allocation)
                or any(row["suite"] != "heldout" or row["repeat"] != 1 or row["mode"] != slot["mode"]
                       for row, slot in zip(plan, allocation, strict=True))):
            raise ValueError("heldout schedule must keep the exact single-exposure allocation")
        groups = list(groups)
        for meta, _ in groups:
            if (meta.get("approval_receipt_sha256") != receipt
                    or meta["tasks"] != [row["task_id"] for row in plan if row["mode"] == meta["policy"]["mode"]]):
                raise ValueError("heldout grades do not match the sealed receipt and assigned group")
    if not isinstance(plan, list) or not plan:
        raise ValueError("plan must be a nonempty list of explicit slots")
    slots = [_slot(**row) for row in plan]
    expected = set(slots)
    if len(expected) != len(slots):
        raise ValueError("duplicate planned slot")
    if pass3_candidate is not None and not re.fullmatch(r"[0-9a-f]{40}", pass3_candidate):
        raise ValueError("pass3 requires the full frozen candidate commit SHA")
    grades = _read_grades(expected, groups, heldout_candidate or pass3_candidate)
    rows = []
    counts = defaultdict(Counter)
    for key in slots:
        suite, task_id, mode, repeat = key
        row, outcome = grades.get(key, ({}, "missing"))
        rows.append({**dict(zip(_FIELDS, key)), "grade_status": row.get("status"), "outcome": outcome})
        counts[(suite, mode, repeat, _source(suite, task_id))][outcome] += 1
    summaries = []
    for (suite, mode, repeat, source), outcomes in sorted(counts.items()):
        total = sum(outcomes.values())
        correct = outcomes["correct"]
        scored = correct + outcomes["incorrect"]
        summaries.append({
            "suite": suite, "mode": mode, "repeat": repeat, "source": source,
            "planned": total, "scored": scored, **{name: outcomes[name] for name in _OUTCOMES},
            "conditional_accuracy": correct / scored if scored else None,
            "planned_accuracy": correct / total if scored or source in ("qrdata", "replication") else None,
        })
    result = {"groups": summaries, "slots": rows}
    if pass3_candidate is not None:
        cases = Path(__file__).with_name("pass3-cases.txt").read_text(encoding="utf-8").splitlines()
        result["pass3"] = _pass3_summary(expected, grades, cases)
        result["development_correct_completion"] = _development_applicability(slots, grades, cases)
    if heldout_candidate is not None:
        result["heldout"], heldout_outcomes = _heldout_summary(slots, grades)
        for key, row in zip(slots, rows, strict=True):
            row["heldout_outcome"] = heldout_outcomes[key]
    return result


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plan", type=Path)
    parser.add_argument("grades", type=Path, nargs="*")
    parser.add_argument("--pass3-candidate", help="score the approved Ask/Auto stability gate for this frozen commit")
    args = parser.parse_args()
    try:
        result = audit_coverage(_read(args.plan), [
            (_read(path.with_name("run_meta.json")), _read(path)) for path in args.grades
        ], pass3_candidate=args.pass3_candidate)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2))
    return int(any(key in result and not result[key]["passed"] for key in ("pass3", "heldout")))


if __name__ == "__main__":
    raise SystemExit(main())
