"""Retained native Stata two-endogenous 2SLS HC0/z reference.

ivregress vce(robust) without small uses HC0, no N/(N-K) correction,
normal coefficient inference and chi-square Wald. Adding small would switch
to corrected covariance/t/F, which is outside the frozen current convention.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from tests.stata_oracle import STATA, emit, run

parser = argparse.ArgumentParser()
parser.add_argument("output_directory", type=Path)
args = parser.parse_args()
owned = Path(__file__).resolve().parent
output = args.output_directory.resolve()
if not output.is_relative_to(owned):
    raise ValueError("Output outside owned fixture directory")
print("Writing native Stata evidence to", output, flush=True)
target = output / "stata_reference.json"
if target.exists():
    raise RuntimeError("Retained native reference exists; choose a fresh output directory")
if not STATA.is_file():
    raise RuntimeError(f"Required Stata native oracle unavailable: {STATA}")
data = output / "data.csv"
if not data.is_file():
    raise RuntimeError("Run native R data/reference generation first")
terms = {"Intercept": "_cons", "x1": "x1", "xe1": "xe1", "xe2": "xe2"}
body = [f'import delimited using "{data}", asdouble clear case(preserve)',
        "ivregress 2sls y x1 (xe1 xe2 = z1 z2), vce(robust)",
        emit("nobs", "e(N)"), emit("nominal_residual_df", "e(N)-colsof(e(b))")]
for term, native in terms.items():
    body.extend([emit(f"b_{term}", f"_b[{native}]"),
                 emit(f"se_{term}", f"_se[{native}]"),
                 emit(f"z_{term}", f"_b[{native}]/_se[{native}]"),
                 emit(f"p_{term}", f"2*normal(-abs(_b[{native}]/_se[{native}]))")])
    for other, native_other in terms.items():
        body.append(emit(f"cov_{term}_{other}",
                         f'el(e(V),colnumb(e(V),"{native}"),colnumb(e(V),"{native_other}"))'))
body.extend(["test xe1 xe2", emit("wald_statistic", "r(chi2)"),
             emit("wald_df_num", "r(df)"), emit("wald_p", "r(p)")])
batch = output / f"stata_batch_{uuid4().hex[:10]}"
assert not batch.exists()
values = run(batch, "\n".join(body), name="iv_two_endogenous")
reference = {
    "reference": "Stata 18 ivregress 2sls y x1 (xe1 xe2=z1 z2), vce(robust), no small",
    "binary": str(STATA), "batch_directory": batch.name,
    "data_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
    "terms": list(terms), "nobs": int(values["nobs"]),
    "params": {t: values[f"b_{t}"] for t in terms},
    "std_error": {t: values[f"se_{t}"] for t in terms},
    "z": {t: values[f"z_{t}"] for t in terms}, "p": {t: values[f"p_{t}"] for t in terms},
    "covariance": [[values[f"cov_{a}_{b}"] for b in terms] for a in terms],
    "nominal_residual_df": int(values["nominal_residual_df"]),
    "inference": {"covariance_estimator": "HC0", "unbiased": False, "debiased": False,
                  "reference_distribution": "z", "df_method": "asymptotic", "df_den": None,
                  "small_option": False, "small_sample_factor": 1},
    "wald_joint": {"distribution": "chi2", "statistic": values["wald_statistic"],
                   "df_num": int(values["wald_df_num"]), "df_den": None,
                   "p_value": values["wald_p"], "constraints": ["xe1=0", "xe2=0"]},
}
target.write_text(json.dumps(reference, indent=2) + "\n")
print(json.dumps(reference, indent=2))
