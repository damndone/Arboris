"""Prove the supplement preserves old assets and production at exact commits."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "edeba374247bd9e4d608a68e87def84883315cdc"
TIP = "768948b1c83fca666df665ece0104127eaa48ab2"
sha = lambda raw: hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


original = json.loads((ROOT / "tests/eval_v1811/m2_review_manifest.json").read_text())
exceptions = {"backend/workbench/econometrics/count_models.py",
              "docs/superpowers/handoffs/2026-10-04-codex-v1811-m2-report.md"}
preserved = []
assert len(original["files"]) == 82
for row in original["files"]:
    if row["path"] not in exceptions:
        digest = sha((ROOT / row["path"]).read_bytes())
        assert digest == row["sha256"], row["path"]
        preserved.append({"path": row["path"], "sha256": digest})
assert len(preserved) == 80
changes = git("diff", "--name-status", BASE, TIP).decode().splitlines()
rows = []
for row in changes:
    status, path = row.split("\t")
    assert ((status == "M" and path in exceptions and path.startswith("docs/"))
            or (status == "A" and path.startswith("tests/"))), row
    committed = git("show", f"{TIP}:{path}")
    assert (ROOT / path).read_bytes() == committed, path
    rows.append({"status": status, "path": path, "sha256": sha(committed)})
assert len(rows) == 21
assert git("diff", "--name-only", BASE, TIP, "backend", "tests/eval_v1811") == b""
production = []
for path in ["backend/workbench/econometrics/count_models.py", "backend/workbench/econometrics/runner.py"]:
    raw = git("show", f"{BASE}:{path}")
    assert raw == git("show", f"{TIP}:{path}") == (ROOT / path).read_bytes()
    production.append({"path": path, "sha256": sha(raw)})
source_manifest = json.loads((ROOT / "tests/fixtures/count_models/integration-strict-v1811/input-scope-manifest.json").read_text())
for row in source_manifest["read_only_files"]:
    raw = (ROOT / row["path"]).read_bytes()
    assert sha(raw) == row["sha256"]
    assert raw == git("show", f'{row["verified_against"]}:{row["path"]}')
result = {"baseline": BASE, "reviewed_functional_tip": TIP,
          "original_manifest_count": 82, "original_80_preserved": preserved,
          "unchanged_production": production, "producer_changed_paths": rows,
          "input_scope_manifest_all_9_verified": True,
          "independent_evidence": [{"path": p.name, "sha256": sha(p.read_bytes())}
              for p in [Path(__file__), ROOT / "tests/eval_v1811/m2_review_reference_supplement.R",
                        ROOT / "tests/eval_v1811/m2_review_reference_supplement_r.txt"]]}
output = ROOT / "tests/eval_v1811/m2_review_reference_supplement_manifest.json"
if output.exists():
    raise ValueError("Preserve the independent scope evidence")
output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
print(json.dumps({"baseline": BASE, "tip": TIP, "original_assets_preserved": len(preserved),
                  "producer_changed_paths": len(rows), "production_unchanged": True,
                  "all_scope_manifest_hashes_verified": True}, indent=2))
