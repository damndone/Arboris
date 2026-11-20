"""Final coverage accounts for every frozen task without rerunning its grader."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/agent_eval/final_coverage.py"


def _slot(task_id, *, suite="external", mode="ask", repeat=1):
    return {"suite": suite, "task_id": task_id, "mode": mode, "repeat": repeat}


def _group(tmp_path, tasks, grades, *, suite="external", mode="ask", repeat=1, candidate=None):
    tmp_path.mkdir()
    (tmp_path / "run_meta.json").write_text(json.dumps(
        {"suite": suite, "policy": {"mode": mode}, "tasks": tasks, "repeat": repeat,
         "git_head": candidate, "product_dirty": False}
    ))
    path = tmp_path / "grades-v2.json"
    path.write_text(json.dumps({"summary": {"grader": "v2"}, "tasks": grades}))
    return path


def _audit(tmp_path, slots, *groups, pass3_candidate=None):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(slots))
    options = ["--pass3-candidate", pass3_candidate] if pass3_candidate else []
    return subprocess.run([sys.executable, str(SCRIPT), str(plan), *map(str, groups), *options],
                          capture_output=True, text=True, check=False)


def test_qr_coverage_uses_all_40_frozen_slots_and_preserves_the_grades(tmp_path):
    ids = [f"qrdata.{i:03d}" for i in range(40)]
    grades = [{"task": f"{task}.r1", "suite": "external", "source": "qrdata",
               "status": "ran", "correct": i < 30} for i, task in enumerate(ids[:37])]
    grades.append({"task": f"{ids[37]}.r1", "status": "task_stopped", "source": "qrdata"})
    group = _group(tmp_path / "qr", ids, grades)
    original = group.read_bytes()

    result = _audit(tmp_path, [_slot(task) for task in ids], group)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    totals = report["groups"][0]
    assert totals["planned"] == 40 and totals["scored"] == 37
    assert {name: totals[name] for name in ("correct", "incorrect", "interrupted", "missing")} == {
        "correct": 30, "incorrect": 7, "interrupted": 1, "missing": 2,
    }
    assert totals["conditional_accuracy"] == 30 / 37 and totals["planned_accuracy"] == 30 / 40
    assert report["slots"][37]["grade_status"] == "task_stopped"
    assert group.read_bytes() == original


def test_modes_and_repeats_are_distinct_and_unscored_grades_stay_unscored(tmp_path):
    task = "dev.open"
    planned = [_slot(task, suite="dev", mode=mode, repeat=repeat)
               for mode in ("ask", "auto") for repeat in (1, 2)]
    ask = _group(tmp_path / "ask", [task], [{"task": f"{task}.r1", "status": "ran", "completed_marker": True}],
                 suite="dev", repeat=2)
    auto = _group(tmp_path / "auto", [task], [{"task": f"{task}.r2", "status": "harness_error"}],
                  suite="dev", mode="auto", repeat=2)

    result = _audit(tmp_path, planned, ask, auto)

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert [row["outcome"] for row in report["slots"]] == ["ran_unscored", "missing", "missing", "interrupted"]
    assert all(group["planned_accuracy"] is None for group in report["groups"])


def test_unstarted_qr_group_keeps_its_planned_denominator(tmp_path):
    result = _audit(tmp_path, [_slot("qrdata.001")])
    assert result.returncode == 0, result.stderr
    totals = json.loads(result.stdout)["groups"][0]
    assert totals["planned"] == totals["missing"] == 1
    assert totals["conditional_accuracy"] is None and totals["planned_accuracy"] == 0


@pytest.mark.parametrize(("defect", "message"), [
    ("duplicate plan", "duplicate planned slot"),
    ("duplicate grade", "duplicate grade"),
    ("unexpected grade", "unexpected grade"),
    ("wrong mode", "unexpected run_meta slots"),
    ("unplanned declaration", "unexpected run_meta slots"),
    ("overlapping groups", "duplicate run_meta slots"),
])
def test_ambiguous_or_out_of_scope_records_are_rejected(tmp_path, defect, message):
    task = "qrdata.001"
    plan = [_slot(task)]
    rows = [{"task": f"{task}.r1", "status": "ran", "correct": True}]
    tasks = [task]
    mode = "ask"
    if defect == "duplicate plan":
        plan += plan
    elif defect == "duplicate grade":
        rows += rows
    elif defect == "unexpected grade":
        rows[0]["task"] = f"{task}.r2"
    elif defect == "wrong mode":
        mode = "auto"
    elif defect == "unplanned declaration":
        tasks.append("qrdata.002")
    groups = [_group(tmp_path / "qr", tasks, rows, mode=mode)]
    if defect == "overlapping groups":
        groups.append(_group(tmp_path / "rerun", tasks, [], mode=mode))

    result = _audit(tmp_path, plan, *groups)

    assert result.returncode != 0 and message in result.stderr


PASS3_CASES = SCRIPT.with_name("pass3-cases.txt").read_text(encoding="utf-8").splitlines()
CANDIDATE = "1" * 40


def _pass3_plan():
    return [_slot(case, suite="dev", mode=mode, repeat=rep)
            for mode in ("ask", "auto") for case in PASS3_CASES for rep in (1, 2, 3)]


def test_pass3_has_two_fixed_denominators_and_no_credit_for_missing_or_wrong_trials(tmp_path):
    ask_rows, auto_rows = [], []
    for i, case in enumerate(PASS3_CASES):
        for rep in (1, 2, 3):
            row = {"task": f"{case}.r{rep}", "status": "ran", "grader": "v2", "completed_marker": True,
                   "appropriate_family_used": True, "estimate": {"applicable": True, "recovered": True}}
            if i != 14 or rep != 2:
                ask_rows.append(row if i != 15 or rep != 3 else {**row, "appropriate_family_used": False})
            if i == 16 and rep == 2:
                ask_rows[-1] = {**row, "estimate": {"applicable": True, "recovered": False}}
            if i == 17 and rep == 1:
                ask_rows[-1] = {**row, "completed_marker": False}
            auto_rows.append(row if i < 13 or rep != 3 else {"task": row["task"], "status": "task_stopped"})
    ask = _group(tmp_path / "ask", PASS3_CASES, ask_rows, suite="dev", repeat=3, candidate=CANDIDATE)
    auto = _group(tmp_path / "auto", PASS3_CASES, auto_rows, suite="dev", mode="auto", repeat=3, candidate=CANDIDATE)

    result = _audit(tmp_path, _pass3_plan(), ask, auto, pass3_candidate=CANDIDATE)

    assert result.returncode == 1, result.stderr
    gate = json.loads(result.stdout)["pass3"]
    assert gate["passed"] is False
    assert [(gate["modes"][mode]["passed_cases"], gate["modes"][mode]["planned_cases"],
             gate["modes"][mode]["passed"]) for mode in ("ask", "auto")] == [(14, 18, True), (13, 18, False)]
    ask_trials = gate["modes"]["ask"]["cases"]
    assert ask_trials[PASS3_CASES[14]][1] == "missing"
    assert ask_trials[PASS3_CASES[15]][2] == "method_mismatch"
    assert ask_trials[PASS3_CASES[16]][1] == "estimate_not_recovered"
    assert ask_trials[PASS3_CASES[17]][0] == "not_completed"


def test_pass3_will_not_pool_other_candidates_or_shrink_the_frozen_plan(tmp_path):
    group = _group(tmp_path / "ask", PASS3_CASES, [], suite="dev", repeat=3, candidate="2" * 40)
    rejected = _audit(tmp_path, _pass3_plan(), group, pass3_candidate=CANDIDATE)
    assert rejected.returncode != 0 and "frozen candidate" in rejected.stderr

    missing = _audit(tmp_path, _pass3_plan()[:-1], pass3_candidate=CANDIDATE)
    assert missing.returncode != 0 and "108 approved" in missing.stderr


def _heldout_schedule():
    from hashlib import sha256

    slots = [_slot(f"synthetic-{i}", suite="heldout", mode="auto" if i % 2 else "ask") for i in range(1, 22)]
    allocation = [{"ordinal": i, "mode": slot["mode"]} for i, slot in enumerate(slots, 1)]
    return {"schema": "agent-heldout-schedule/v1", "slots": slots, "candidate_sha": CANDIDATE,
            "approval_receipt_sha256": "a" * 64, "allocation_sha256": sha256(
                json.dumps(allocation, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}


def _heldout_row(slot, *, family=True, recovered=True, marker=True):
    return {"task": f"{slot['task_id']}.r1", "status": "ran", "grader": "v2", "completed_marker": marker,
            "appropriate_family_used": family, "estimate": {"applicable": True, "recovered": recovered,
                "truth": 2, "truth_source": "population", "best": {"estimate": 2 if recovered else 0,
                    "covers_truth": False, "within_tolerance": recovered}}}


def _heldout_groups(tmp_path, schedule, all_rows):
    groups = []
    for mode in ("ask", "auto"):
        assigned = [slot["task_id"] for slot in schedule["slots"] if slot["mode"] == mode]
        rows = [row for row in all_rows if row["task"].removesuffix(".r1") in assigned]
        group = _group(tmp_path / mode, assigned, rows, suite="heldout", mode=mode, candidate=CANDIDATE)
        meta_path = group.with_name("run_meta.json")
        meta_path.write_text(json.dumps({**json.loads(meta_path.read_text()), "approval_receipt_sha256": "a" * 64}))
        groups.append(group)
    return groups


@pytest.mark.parametrize(("correct", "marked", "expected_exit"), [(16, 21, 1), (17, 0, 0)])
def test_sealed_heldout_completion_uses_all_planned_slots(tmp_path, correct, marked, expected_exit):
    schedule = _heldout_schedule()
    rows = [_heldout_row(slot, family=i < correct or i % 2 == 0,
                         recovered=i < correct or i % 2 == 1, marker=i < marked)
            for i, slot in enumerate(schedule["slots"])]
    groups = _heldout_groups(tmp_path, schedule, rows)
    result = _audit(tmp_path, schedule, *groups)
    assert result.returncode == expected_exit, result.stderr
    score = json.loads(result.stdout)["heldout"]
    assert score["marker_coverage"]["completed"] == marked and score["planned"] == 21
    assert score["correctly_completed"] == correct and score["correct_completion_rate"] == correct / 21
    assert score["evidence_complete"] is True
    assert score["modes"]["ask"]["planned"] == 10 and score["modes"]["auto"]["planned"] == 11

    meta_path = groups[0].with_name("run_meta.json")
    meta_path.write_text(json.dumps({**json.loads(meta_path.read_text()), "git_head": "2" * 40}))
    rejected = _audit(tmp_path, schedule, *groups)
    assert rejected.returncode == 2 and "frozen candidate" in rejected.stderr


@pytest.mark.parametrize(("fault", "outcome"), [
    ("missing_row", "missing"), ("interrupted", "interrupted"), ("missing_method", "unresolved_method"),
    ("malformed_method", "unresolved_method"), ("not_applicable", "estimate_inapplicable"),
    ("missing_truth", "unverified_estimate"), ("bad_truth", "unverified_estimate"),
    ("missing_truth_source", "unverified_estimate"), ("bad_recovered", "unverified_estimate"),
    ("unsupported_recovery", "unverified_estimate"),
])
def test_heldout_incomplete_adjudication_cannot_pass_with_otherwise_sufficient_correct_rows(tmp_path, fault, outcome):
    schedule = _heldout_schedule()
    rows = [_heldout_row(slot) for slot in schedule["slots"]]
    row = rows[-1]
    if fault == "missing_row":
        rows.pop()
    elif fault == "interrupted":
        row["status"] = "round_budget_stopped"
    elif fault == "missing_method":
        row.pop("appropriate_family_used")
    elif fault == "malformed_method":
        row["appropriate_family_used"] = 1
    else:
        estimate = row["estimate"]
        if fault == "not_applicable":
            row["estimate"] = {"applicable": False, "truth_source": "population"}
        elif fault == "missing_truth":
            estimate.pop("truth")
        elif fault == "bad_truth":
            estimate["truth"] = float("nan")
        elif fault == "missing_truth_source":
            estimate.pop("truth_source")
        elif fault == "bad_recovered":
            estimate["recovered"] = "true"
        elif fault == "unsupported_recovery":
            estimate["best"]["within_tolerance"] = False
    groups = _heldout_groups(tmp_path, schedule, rows)

    result = _audit(tmp_path, schedule, *groups)

    assert result.returncode == 1, result.stderr
    report = json.loads(result.stdout)
    score = report["heldout"]
    assert score["correctly_completed"] == 20 and score["planned"] == 21
    assert score["evidence_complete"] is False and score["passed"] is False
    assert report["slots"][-1]["heldout_outcome"] == outcome


def test_development_inapplicability_remains_unresolved_without_changing_the_plan(tmp_path):
    slot = _slot("synthetic-inapplicable.open", suite="dev")
    planned = [*_pass3_plan(), slot]
    row = {"task": f"{slot['task_id']}.r1", "status": "ran", "grader": "v2", "completed_marker": True,
           "appropriate_family_used": True, "estimate": {"applicable": False}}
    group = _group(tmp_path / "ask", [slot["task_id"]], [row], suite="dev", candidate=CANDIDATE)

    result = _audit(tmp_path, planned, group, pass3_candidate=CANDIDATE)

    assert result.returncode == 1, result.stderr
    score = json.loads(result.stdout)["development_correct_completion"]
    assert score["status"] == "unresolved_applicability"
    assert score["modes"]["ask"] == {"planned_r1": 19, "reported_inapplicable_r1": 1}
    assert score["modes"]["auto"] == {"planned_r1": 18, "reported_inapplicable_r1": 0}
    assert "54" in score["reason"] and "63" in score["reason"]
    assert "denominator_views" not in score


def test_development_reports_both_fixed_denominators_with_the_same_confirmed_numerator(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parents[1]))
    from agent_eval.m5_dev_admission import frozen_slots
    from agent_eval.tasks import dev_tasks

    plan, _ = frozen_slots(dev_tasks())
    adjudicated = {"status": "ran", "grader": "v2", "completed_marker": False,
                   "appropriate_family_used": True, "estimate": {"applicable": True, "recovered": True}}
    rows = {
        "iv_valid.goal": adjudicated,
        "cs_hetero.goal": {**adjudicated, "appropriate_family_used": False, "completed_marker": True},
        "iv_weak.goal": adjudicated,
        "survival.goal": {**adjudicated, "status": "round_budget_stopped"},
        "panel_fe.goal": {**adjudicated, "grader": "v1"},
    }
    group = _group(tmp_path / "ask", list(rows),
                   [{**row, "task": f"{task}.r1"} for task, row in rows.items()],
                   suite="dev", candidate=CANDIDATE)

    result = _audit(tmp_path, plan, group, pass3_candidate=CANDIDATE)

    assert result.returncode == 1, result.stderr
    completion = json.loads(result.stdout)["development_correct_completion"]
    assert completion["status"] == "unresolved_applicability"
    ask = completion["denominator_views"]["ask"]
    assert ask["including_iv"] == {
        "planned_r1": 63, "estimate_eligible_r1": 54, "scored_eligible_r1": 2, "confirmed_correct_r1": 1,
        "confirmed_correct_all_rate": 1 / 63, "confirmed_correct_estimate_eligible_rate": 1 / 54,
    }
    assert ask["excluding_iv"] == {
        "planned_r1": 57, "estimate_eligible_r1": 51, "scored_eligible_r1": 1, "confirmed_correct_r1": 0,
        "confirmed_correct_all_rate": 0, "confirmed_correct_estimate_eligible_rate": 0,
    }
    auto = completion["denominator_views"]["auto"]["including_iv"]
    assert (auto["planned_r1"], auto["estimate_eligible_r1"], auto["scored_eligible_r1"]) == (63, 54, 0)


def test_dev_grading_and_calibration_do_not_load_heldout_material():
    check = """
from importlib.abc import MetaPathFinder
import sys

class DenyHeldout(MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == "agent_eval.heldout":
            raise AssertionError("dev grader loaded heldout material")

sys.meta_path.insert(0, DenyHeldout())
sys.path.insert(0, sys.argv[1])
import agent_eval_grade
import agent_eval_judge
assert agent_eval_grade.scenario_for_record({"scenario": "iv_valid"}).id == "iv_valid"
"""
    result = subprocess.run([sys.executable, "-c", check, str(SCRIPT.parents[1])],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
