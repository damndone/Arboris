"""Capture post-fix results and preserve all previous oracle evidence."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd

from workbench.econometrics.runner import run_glm, run_negative_binomial

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
output = HERE / (sys.argv[1] if len(sys.argv) > 1 else "workbench-remediation.json")
if output.exists():
    raise ValueError("Preserve prior evidence")
if not (HERE / "r-full-precision.json").exists():
    subprocess.run(["Rscript", str(HERE / "capture_precision.R"),
                    str(HERE / "fractional-oracle/data.csv"), str(HERE / "r-full-precision.json")], check=True)
stata = json.loads((HERE.parent / "reference-v3/stata.json").read_text())
rows = {}
for name, dispersion, alpha in [("nb2", "mean", None), ("nb1", "constant", None), ("fixed", "mean", .5)]:
    frame = pd.read_csv(HERE.parent / f"reference-v3/{'nb2' if name=='fixed' else name}.csv", float_precision="round_trip")
    packet, fitted = run_negative_binomial(frame, "y", ["x1", "x2"], name, dispersion=dispersion, alpha=alpha)
    beta, se = np.asarray(fitted.params)[:3], np.asarray(fitted.bse)[:3]
    row = {"beta": beta.tolist(), "se": se.tolist(), "ll": float(fitted.llf),
           "covariance": np.asarray(fitted.cov_params()).tolist(), "convergence": packet["convergence"],
           "max_beta_abs_error_stata": float(np.max(abs(beta-np.array([stata[name][f"b_{term}"] for term in ["_cons", "x1", "x2"]])))),
           "max_se_relative_error_stata": float(np.max(abs(se/np.array([stata[name][f"se_{term}"] for term in ["_cons", "x1", "x2"]])-1)))}
    if alpha is None:
        row.update(natural_score=fitted.model.score(np.asarray(fitted.params)).tolist(),
                   natural_mean_score_max=float(np.max(abs(fitted.model.score(np.asarray(fitted.params))))/len(frame)),
                   information_eigenvalues=np.linalg.eigvalsh(-fitted.model.hessian(np.asarray(fitted.params))).tolist(),
                   ancillary=packet["ancillary_parameters"], overdispersion=packet["overdispersion_test"])
    rows[name] = row
for form in ["mean", "constant"]:
    frame = pd.read_csv(HERE.parent / "reference-v3/poisson.csv", float_precision="round_trip")
    try:
        run_negative_binomial(frame, "y", ["x1", "x2"], "boundary", dispersion=form)
    except ValueError as error:
        rows[f"boundary_{form}"] = {"status": "explicit_failure", "error": str(error)}
    else:
        raise AssertionError("Uncertified point returned inference")
frame = pd.read_csv(HERE / "fractional-oracle/data.csv", float_precision="round_trip")
fractional_stata = json.loads((HERE / "fractional-oracle/stata.json").read_text())
fractional_r = json.loads((HERE / "r-full-precision.json").read_text())
for name, call in [("fractional_fixed", run_negative_binomial), ("fractional_glm", run_glm)]:
    packet, fitted = call(frame, "y", ["x1", "x2"], name,
                         *(["negative_binomial"] if call == run_glm else []), alpha=.5)
    beta, se = np.asarray(fitted.params), np.asarray(fitted.bse)
    reference_beta = np.asarray(fractional_r["coefficients"], dtype=float) if call == run_glm else np.array([fractional_stata[f"b_{t}"] for t in ["_cons", "x1", "x2"]])
    reference_se = np.asarray(fractional_r["std_error"], dtype=float) if call == run_glm else np.array([fractional_stata[f"se_{t}"] for t in ["_cons", "x1", "x2"]])
    rows[name] = {"beta": beta.tolist(), "se": se.tolist(), "ll": float(fitted.llf),
                  "max_beta_abs_error": float(np.max(abs(beta-reference_beta))),
                  "max_se_relative_error": float(np.max(abs(se/reference_se-1))),
                  "information_matrix": packet["information_matrix"], "convergence": packet["convergence"]}
rows["production_sha256"] = hashlib.sha256((ROOT / "backend/workbench/econometrics/count_models.py").read_bytes()).hexdigest()
output.write_text(json.dumps(rows, indent=2, allow_nan=False)+"\n")
print(json.dumps(rows, indent=2, allow_nan=False))
