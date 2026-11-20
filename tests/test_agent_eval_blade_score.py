"""Exercise BLADE's native alignments without starting its evaluator."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/agent_eval/blade_score.py"
COMMIT = "6118fa8d5007b91aa8c91c518182db82446a4547"
JUDGE = {"model_snapshot": "fixture-judge-1", "temperature": 0, "settings_sha256": "a" * 64}
TRUTH = {"num_cvars1": 1, "num_mspecs1_unique": 1, "num_mspecs1": 1, "num_tspecs1": 1}
NAMES = ("affairs", "amtl", "boxes", "caschools", "crofoot", "fish", "hurricane",
         "mortgage", "panda_nuts", "reading", "soccer", "teachingratings")


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _plan(tmp_path, *, names=("hurricane",), repeats=20):
    source = tmp_path / "source"
    datasets = {}
    for name in names:
        (source / name).mkdir(parents=True)
        files = {}
        for filename in ("data.csv", "info.json", "annotations.csv"):
            raw = filename.encode()
            (source / name / filename).write_bytes(raw)
            files[filename] = hashlib.sha256(raw).hexdigest()
        datasets[name] = {"files": files, "truth": TRUTH}
    plan = {"source_commit": COMMIT, "repeats": repeats, "bootstrap_seed": 11, "judge": JUDGE,
            "input_protocol_sha256": "b" * 64, "datasets": datasets}
    return plan, _write(tmp_path / "plan.json", plan)["sha256"]


def _cohort(tmp_path, plan, digest, name, *, failure_slots=(), missing_slots=(),
            outer_errors=(), partial_transforms=(), defect=None):
    base = tmp_path / name
    base.mkdir()
    datasets = {}
    for dataset, planned in plan["datasets"].items():
        repeats = plan["repeats"]
        generated = {str(i): {"cvars": {}, "m_code": "raise RuntimeError", "transform_code": "raise RuntimeError"}
                     for i in range(repeats) if i not in missing_slots}
        for i in failure_slots:
            generated[str(i)] = [2, "generation failed"]
        analyses = [entry for entry in generated.values() if isinstance(entry, dict)]
        evaluation = []
        for i, analysis in enumerate(analyses):
            result = {"res_type": 6 if i in outer_errors else 5}
            if i in partial_transforms:
                result["res_type_transform"] = 4
            evaluation.append({"dataset_name": dataset, "analysis": analysis, "eval_run_result": result})
        status = [result.get("res_type_transform", result["res_type"])
                  for result in (row["eval_run_result"] for row in evaluation)] + [2] * len(failure_slots)
        nrows = len(analyses) - len(outer_errors)
        metrics = {
            **TRUTH, "status": status, "analyses": analyses, "num_cvars2": [2] * nrows,
            "num_tspecs2": [2] * nrows, "matched_models": [["model"]] * nrows,
            "matched_models_cvar": [["model | vars"]] * nrows,
        }
        for field in ("matched_cvars", "matched_gspecs", "matched_vspecs"):
            metrics[field] = [["expert"]] * nrows
            metrics[field + "2"] = [["analysis"]] * nrows
        retained_status = [s for s in status if s not in {2, 6}]
        for i, s in enumerate(retained_status):
            if s == 4:
                metrics["num_tspecs2"][i] = 0
                for field in ("matched_gspecs", "matched_vspecs", "matched_gspecs2", "matched_vspecs2"):
                    metrics[field][i] = []
        if defect == "unbound alignment":
            evaluation[0]["analysis"] = {**analyses[0], "m_code": "different"}
        if defect == "truncated metrics":
            metrics["matched_models"].pop()
        if defect == "wrong denominator":
            metrics["num_mspecs1"] += 1
        if defect == "wrong dataset":
            evaluation[0]["dataset_name"] = "fish"
        if defect == "noninteger status":
            metrics["status"][0] = 5.0
        datasets[dataset] = {
            "files": planned["files"],
            "submission": _write(base / f"{dataset}-submission.json",
                                 {"dataset_name": dataset, "n": repeats, "analyses": generated}),
            "evaluation": _write(base / f"{dataset}-evaluation.json",
                                 {"dataset_name": dataset, "results": evaluation}),
            "metrics": _write(base / f"{dataset}-metrics.json", metrics),
        }
    if defect == "wrong dataset files":
        datasets["hurricane"]["files"] = {}
    if defect == "different judge":
        judge = {**JUDGE, "model_snapshot": "fixture-judge-2"}
    elif defect == "boolean judge temperature":
        judge = {**JUDGE, "temperature": False}
    else:
        judge = JUDGE
    if defect == "missing evaluation":
        for entry in datasets.values():
            del entry["evaluation"], entry["metrics"]
    receipt = {"judge": JUDGE, "source_commit": COMMIT,
               "datasets": {dataset: {key: files[key]["sha256"] for key in ("evaluation", "metrics")}
                            for dataset, files in datasets.items() if "evaluation" in files}}
    document = {"cohort": name, "plan_sha256": digest, "judge": judge,
                "input_protocol_sha256": plan["input_protocol_sha256"], "datasets": datasets,
                "judge_receipt": _write(base / "judge-receipt.json", receipt)}
    if defect == "wrong judge receipt":
        receipt["datasets"] = {}
        document["judge_receipt"] = _write(base / "judge-receipt.json", receipt)
    if defect == "tampered metrics":
        (base / "hurricane-metrics.json").write_text("{}")
    _write(base / "cohort.json", document)
    return base / "cohort.json"


def _run(tmp_path, digest, *cohorts):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "plan.json"), "--plan-sha256", digest,
         "--dataset-root", str(tmp_path / "source"), "--cohorts", *map(str, cohorts)],
        capture_output=True, text=True, check=False,
    )


def test_full_native_pair_reproduces_weighted_precision_coverage_bootstrap(tmp_path):
    plan, digest = _plan(tmp_path, names=NAMES)
    first = _cohort(tmp_path, plan, digest, "first")
    second = _cohort(tmp_path, plan, digest, "second")
    run = _run(tmp_path, digest, first, second)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["pair_ready"]
    a, b = report["cohorts"]
    assert a["counts"] == {"planned": 240, "aligned": 240, "partial_transform": 0, "generation_failed": 0,
                           "evaluator_failed": 0, "missing_generation": 0, "missing_alignment": 0}
    # Three types have 1/2 precision and unit coverage, while both model types are 1/1.
    assert a["frozen_slots"]["point_weighted_f1"] == pytest.approx(5 / 6)
    assert a["native_order"]["bootstrap_mean_weighted_f1"] == pytest.approx(5 / 6)
    assert a["native_order"]["bootstrap_ci95"] == pytest.approx([5 / 6] * 2)
    assert a["native_order"] == b["native_order"]


def test_missing_and_failed_slots_keep_their_order_and_denominator(tmp_path):
    plan, digest = _plan(tmp_path, repeats=11)
    cohort = _cohort(tmp_path, plan, digest, "gaps", failure_slots=(0,), missing_slots=(10,), outer_errors=(0,))
    run = _run(tmp_path, digest, cohort)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert not report["pair_ready"]
    scored = report["cohorts"][0]
    assert scored["counts"] == {"planned": 11, "aligned": 8, "partial_transform": 0, "generation_failed": 1,
                                 "evaluator_failed": 1, "missing_generation": 1, "missing_alignment": 0}
    assert scored["frozen_slots"]["components"]["cvar"]["precision"] == pytest.approx(4 / 11)
    assert scored["native_order"]["components"]["cvar"]["precision"] == pytest.approx(4 / 9)
    assert scored["native_order"]["bootstrap_mean_weighted_f1"] is None


@pytest.mark.parametrize(("defect", "error"), [
    ("unbound alignment", "analysis identity"),
    ("different judge", "judge mismatch"),
    ("boolean judge temperature", "judge mismatch"),
    ("noninteger status", "status order"),
    ("wrong judge receipt", "judge receipt"),
    ("truncated metrics", "metric rows"),
    ("wrong denominator", "truth counts"),
    ("wrong dataset", "analysis identity"),
    ("wrong dataset files", "input file identities"),
    ("tampered metrics", "SHA-256 mismatch"),
])
def test_incompatible_native_receipts_are_rejected(tmp_path, defect, error):
    plan, digest = _plan(tmp_path)
    cohort = _cohort(tmp_path, plan, digest, "broken", defect=defect)
    run = _run(tmp_path, digest, cohort)
    assert run.returncode != 0
    assert error in run.stderr


def test_unverified_plan_sha_is_rejected_before_scoring(tmp_path):
    plan, digest = _plan(tmp_path)
    cohort = _cohort(tmp_path, plan, digest, "first")
    run = _run(tmp_path, "0" * 64, cohort)
    assert run.returncode != 0
    assert "SHA-256 mismatch" in run.stderr



def test_submissions_without_alignments_remain_unscored(tmp_path):
    plan, digest = _plan(tmp_path)
    cohort = _cohort(tmp_path, plan, digest, "missing", defect="missing evaluation")
    run = _run(tmp_path, digest, cohort)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert not report["pair_ready"]
    assert report["cohorts"][0]["counts"]["missing_alignment"] == 20
    assert report["cohorts"][0]["native_order"]["point_weighted_f1"] is None



def test_pair_with_only_generation_and_transform_failures_keeps_native_denominator(tmp_path):
    plan, digest = _plan(tmp_path, names=NAMES)
    first = _cohort(tmp_path, plan, digest, "first")
    second = _cohort(tmp_path, plan, digest, "second", failure_slots=(0,), partial_transforms=(0,))
    run = _run(tmp_path, digest, first, second)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["pair_ready"]
    cohort = report["cohorts"][1]
    assert set(cohort["native_denominators"].values()) == {20}
    assert cohort["counts"]["generation_failed"] == cohort["counts"]["partial_transform"] == 12
    assert cohort["native_order"]["components"]["model"]["precision"] == pytest.approx(19 / 20)
    assert cohort["native_order"]["components"]["transform_value"]["precision"] == pytest.approx(18 / 40)


def test_incomplete_pair_cannot_pass_admission(tmp_path):
    plan, digest = _plan(tmp_path, names=NAMES)
    first = _cohort(tmp_path, plan, digest, "first")
    second = _cohort(tmp_path, plan, digest, "second", missing_slots=(0,), outer_errors=(0,))
    run = _run(tmp_path, digest, first, second)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert not report["pair_ready"]
    assert "delta" not in report
    assert report["cohorts"][1]["counts"]["missing_generation"] == 12
    assert report["cohorts"][1]["counts"]["evaluator_failed"] == 12
