"""Native Stata evidence for incompatible-response GLM LR; no file deletion."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.stata_oracle import STATA, emit

directory = ROOT / "tests/eval_v1811/count_public_review_stata"
if directory.exists():
    raise ValueError("Preserve earlier native evidence")
directory.mkdir()
body = ["version 18", "set more off",
    f'import delimited "{ROOT / "tests/fixtures/postestimation/data.csv"}", clear varnames(1)',
    "glm yb x1 x2 x3, family(poisson) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)",
    "estimates store full_different_response", "scalar ll_other = e(ll)",
    "glm yc x1, family(poisson) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)",
    "estimates store restricted", "scalar ll_restricted = e(ll)",
    "capture noisily lrtest full_different_response restricted", "scalar incompatible_rc = _rc",
    "glm yc x1 x2 x3, family(poisson) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)",
    "estimates store full_same_response", "lrtest full_same_response restricted",
    "scalar valid_lr = r(chi2)", "scalar valid_p = r(p)",
    'file open wbout using "wb_results.tsv", write',
    emit("incompatible_response_lr_rc", "incompatible_rc"),
    emit("invalid_numeric_lr_if_not_rejected", "2*(ll_other-ll_restricted)"),
    emit("same_response_lr", "valid_lr"), emit("same_response_p", "valid_p"),
    "file close wbout"]
(directory / "oracle.do").write_text("\n".join(body) + "\n")
subprocess.run([str(STATA), "-b", "do", "oracle.do"], cwd=directory, check=True, timeout=60)
result = {key: float(value) for key, value in
          (line.split("\t", 1) for line in (directory / "wb_results.tsv").read_text().splitlines())}
(ROOT / "tests/eval_v1811/count_public_review_stata.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
assert result["incompatible_response_lr_rc"] != 0, "Native LR should require the same response"
