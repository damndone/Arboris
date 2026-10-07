"""Evidence inventory for the independent M2 review, without numerical work."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
INTEGRATION=ROOT.parent/"workbench-v1.8.11"
BASE="6f0f87c6d8241a93d81e2c34f8ef8e9408a907b3"
TIP="cda5c2f14a82928826bae526d780201add0f30f2"


def git(*args):
    return subprocess.run(["git",*args],cwd=ROOT,check=True,capture_output=True,text=True).stdout.strip()


def main():
    assert git("rev-parse","HEAD")==TIP
    runner="backend/workbench/econometrics/runner.py"
    original=ast.parse(git("show",f"{BASE}:{runner}"))
    current=ast.parse((ROOT/runner).read_text())
    def excluded(tree):
        return [ast.dump(node,include_attributes=False) for node in tree.body
                if not (isinstance(node,ast.FunctionDef) and node.name in {"run_glm","run_negative_binomial"})]
    assert excluded(original)==excluded(current)
    changed=git("diff","--name-only",f"{BASE}..{TIP}").splitlines()
    assert all(p in {runner,"backend/workbench/econometrics/count_models.py","docs/superpowers/handoffs/2026-10-04-codex-v1811-m2-report.md"}
               or p.startswith("tests/fixtures/count_models/") or (p.startswith("tests/test_count_models_") and p.endswith(".py")) for p in changed)
    lock=json.loads((INTEGRATION/"docs/superpowers/release-trains/v1.8.11/contract-lock-manifest.json").read_text())
    locked=[]
    for entry in lock["locked_files"]:
        actual=hashlib.sha256((INTEGRATION/entry["path"]).read_bytes()).hexdigest()
        assert actual==entry["sha256"]
        locked.append({**entry,"verified":True})
    paths=[ROOT/p for p in changed]+list((ROOT/"tests/eval_v1811").glob("m2_review_*"))
    files=[]
    for path in paths:
        if path.is_file() and path.name!="m2_review_manifest.json":
            files.append({"path":str(path.relative_to(ROOT)),"sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    files.append({"path":str(child.relative_to(ROOT)),"sha256":hashlib.sha256(child.read_bytes()).hexdigest()})
    report=ROOT/"docs/superpowers/handoffs/2026-10-04-v1.8.11-m2-independent-review.md"
    if report.exists():
        files.append({"path":str(report.relative_to(ROOT)),"sha256":hashlib.sha256(report.read_bytes()).hexdigest()})
    out={"baseline":BASE,"functional_tip":TIP,"branch":git("branch","--show-current"),
         "worktree":str(ROOT),"runner_outside_owned_functions":"AST identical to baseline",
         "producer_scope":"all changed files inside M2 work order", "changed_paths":changed,
         "contract_lock_verified":locked,"files":files}
    (ROOT/"tests/eval_v1811/m2_review_manifest.json").write_text(json.dumps(out,indent=2)+"\n")
    print("M2 scope and frozen contract verified; manifest written")


if __name__=="__main__":
    main()
