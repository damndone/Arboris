"""Verify preservation of the old 82-file review manifest and current scope."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[2]
TIP="3d4c73c0ef3763057fd1ca250c9165638b9e577e"
OLD="87e5c5decfaea3512300a35d06258d443b7d7670"
OLD_MANIFEST=ROOT/"tests/eval_v1811/m2_review_manifest.json"
ALLOWED_CHANGED={"backend/workbench/econometrics/count_models.py",
                 "docs/superpowers/handoffs/2026-10-04-codex-v1811-m2-report.md"}


def git(*args):
    return subprocess.run(["git",*args],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()


def main():
    old=json.loads(OLD_MANIFEST.read_text())
    changes=[]; unchanged=[]
    for row in old["files"]:
        actual=hashlib.sha256((ROOT/row["path"]).read_bytes()).hexdigest()
        if actual==row["sha256"]:unchanged.append(row["path"])
        else:changes.append({**row,"actual_sha256":actual})
    assert len(old["files"])==82 and len(unchanged)==80
    assert {row["path"] for row in changes}==ALLOWED_CHANGED
    assert git("show",f"{OLD}:tests/eval_v1811/m2_review_manifest.json")==OLD_MANIFEST.read_text().strip()
    changed=git("diff","--name-only",f"{OLD}..{TIP}").splitlines()
    assert all(path in ALLOWED_CHANGED or path.startswith("tests/fixtures/count_models/p1-remediation-20261004/")
               or path=="tests/test_count_models_remediation.py" for path in changed)
    production="backend/workbench/econometrics/count_models.py"
    assert (ROOT/production).read_text().strip()==git("show",f"{TIP}:{production}")
    lock=json.loads((ROOT.parent/"workbench-v1.8.11/docs/superpowers/release-trains/v1.8.11/contract-lock-manifest.json").read_text())
    for row in lock["locked_files"]:
        assert hashlib.sha256((ROOT.parent/"workbench-v1.8.11"/row["path"]).read_bytes()).hexdigest()==row["sha256"]
    files=[]
    for path in sorted((ROOT/"tests/eval_v1811").glob("m2_review_recheck_*")):
        candidates=path.rglob("*") if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_file() and candidate.name!="m2_review_recheck_manifest.json":
                files.append({"path":str(candidate.relative_to(ROOT)),"sha256":hashlib.sha256(candidate.read_bytes()).hexdigest()})
    report=ROOT/"docs/superpowers/handoffs/2026-10-04-v1.8.11-m2-independent-recheck.md"
    if report.exists():files.append({"path":str(report.relative_to(ROOT)),"sha256":hashlib.sha256(report.read_bytes()).hexdigest()})
    out={"baseline":old["baseline"],"review_baseline":OLD,"functional_tip":TIP,
         "code_commit":"96f356fc8606dfc32323dfb9d45b6fbbaa6c3051","old_manifest_total":82,
         "old_manifest_unchanged_count":80,"old_manifest_changed":changes,"author_changed_paths":changed,
         "old_manifest_sha256":hashlib.sha256(OLD_MANIFEST.read_bytes()).hexdigest(),"contract_lock_verified":True,
         "author_files":[{"path":path,"sha256":hashlib.sha256((ROOT/path).read_bytes()).hexdigest()} for path in changed],"files":files}
    prefix="LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py "
    out["command_cwd"]=str(ROOT)
    out["commands"]=[
        prefix+".venv/bin/python tests/eval_v1811/m2_review_recheck_probe.py > tests/eval_v1811/m2_review_recheck_probe_output.txt 2>&1",
        prefix+".venv/bin/python -m pytest -q 'tests/eval_v1811/m2_review_assertions.py::test_count_glm_rejects_negative_support_before_returning_inference' 'tests/eval_v1811/m2_review_assertions.py::test_uncertified_interior_ancillary_point_does_not_publish_regular_oim_inference' > tests/eval_v1811/m2_review_recheck_original_red.txt 2>&1",
        prefix+".venv/bin/python -m pytest -q -s tests/eval_v1811/m2_review_recheck_assertions.py 'tests/eval_v1811/m2_review_assertions.py::test_count_glm_rejects_negative_support_before_returning_inference' 'tests/eval_v1811/m2_review_assertions.py::test_uncertified_interior_ancillary_point_does_not_publish_regular_oim_inference' tests/test_count_models_contract.py tests/test_count_models_remediation.py tests/test_count_models_performance.py > tests/eval_v1811/m2_review_recheck_focused.txt 2>&1",
        prefix+".venv/bin/python -m pytest -q 'tests/test_count_models_boundary.py::test_underdispersed_sample_reports_poisson_boundary_and_valid_test' 'tests/test_count_models_boundary.py::test_boundary_packet_can_be_serialized_without_nonfinite_numbers' 'tests/test_count_models_boundary.py::test_invalid_response_is_rejected_for_joint_and_fixed[0.5-0.5]' 'tests/test_count_models_glm_precision.py::test_explicit_alpha_one_matches_high_precision_admission_oracle' tests/test_admission_oracle_glm_negative_binomial.py > tests/eval_v1811/m2_review_recheck_integration_gaps.txt 2>&1",
        ".venv/bin/python tests/eval_v1811/m2_review_recheck_scope.py"]
    (ROOT/"tests/eval_v1811/m2_review_recheck_manifest.json").write_text(json.dumps(out,indent=2)+"\n")
    print("82 old entries verified: 80 unchanged, only count_models and author report changed; new manifest written")


if __name__=="__main__":main()
