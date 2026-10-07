"""Capture exact Workbench/Stata/R comparisons; no oracle regeneration."""
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
from workbench.econometrics.runner import run_glm, run_negative_binomial

ROOT = Path(__file__).resolve().parent
output = ROOT / sys.argv[1]
if output.exists():
    raise ValueError("Evidence output must be a new file")
print(f"Workbench evidence output: {output}", flush=True)
stata = json.loads((ROOT / "reference-v3/stata.json").read_text())
r = json.loads((ROOT / "reference-v3/r.json").read_text())
rows = {}
for name, dispersion, alpha in [("nb2", "mean", None), ("nb1", "constant", None), ("fixed", "mean", .5), ("poisson", "mean", None)]:
    frame = pd.read_csv(ROOT / f"reference-v3/{'nb2' if name=='fixed' else name}.csv", float_precision="round_trip")
    packet, fitted = run_negative_binomial(frame, "y", ["x1", "x2"], name, dispersion=dispersion, alpha=alpha)
    coefficients = [packet["coefficients"][t]["estimate"] for t in ["Intercept", "x1", "x2"]]
    se = [packet["coefficients"][t]["std_error"] for t in ["Intercept", "x1", "x2"]]
    sb = [stata[name][f"b_{t}"] for t in ["_cons", "x1", "x2"]]
    ss = [stata[name][f"se_{t}"] for t in ["_cons", "x1", "x2"]]
    row = {"coefficients": coefficients, "std_error": se,
           "max_coefficient_abs_error_stata": float(np.max(np.abs(np.array(coefficients)-sb))),
           "max_se_relative_error_stata": float(np.max(np.abs(np.array(se)/ss-1))),
           "ll": packet["llf"], "ancillary": packet["ancillary_parameters"],
           "overdispersion_test": packet["overdispersion_test"], "convergence": packet["convergence"],
           "warnings": packet.get("warnings", [])}
    if alpha is None:
        logname = "lndelta" if name=="nb1" else "lnalpha"
        a = packet["ancillary_parameters"][1]["estimate"]
        row.update(alpha_relative_error_stata=float(a/np.exp(stata[name][f"b_{logname}"])-1),
                   ancillary_log_se_relative_error_stata=float(packet["ancillary_parameters"][0]["std_error"]/stata[name][f"se_{logname}"]-1),
                   lr_relative_error_stata=float(packet["overdispersion_test"]["statistic"]/stata[name]["lr"]-1),
                   score_natural=fitted.model.score(np.asarray(fitted.params)).tolist(),
                   hessian_eigenvalues=np.linalg.eigvalsh(fitted.model.hessian(np.asarray(fitted.params))).tolist())
    if name=="nb2":
        row["max_coefficient_abs_error_r"] = float(np.max(np.abs(np.array(coefficients)-r["nb2"]["coefficients"])))
        row["max_se_relative_error_r"] = float(np.max(np.abs(np.array(se)/r["nb2"]["std_error"]-1)))
    rows[name] = row
frame = pd.read_csv(ROOT / "reference-v3/nb2.csv", float_precision="round_trip")
packet, fitted = run_glm(frame, "y", ["x1", "x2"], "fixed_glm", "negative_binomial", alpha=.5)
rows["fixed_glm"] = {"coefficients": np.asarray(fitted.params).tolist(), "std_error": np.asarray(fitted.bse).tolist(),
                     "max_coefficient_abs_error_r": float(np.max(np.abs(np.asarray(fitted.params)-r["fixed_glm"]["coefficients"]))),
                     "max_se_relative_error_r": float(np.max(np.abs(np.asarray(fitted.bse)/r["fixed_glm"]["std_error"]-1))),
                     "convergence": packet["convergence"]}
precision = json.loads((ROOT / "glm_precision.json").read_text())
frame = pd.read_csv(ROOT.parent / "admission/glm_negative_binomial/data.csv", float_precision="round_trip")
packet, fitted = run_glm(frame, "y", ["x1", "x2"], "glm", "negative_binomial", alpha=1.)
rows["glm_precision"] = {"coefficients": np.asarray(fitted.params).tolist(), "std_error": np.asarray(fitted.bse).tolist(),
                         "convergence": packet["convergence"], "score": fitted.model.score(fitted.params).tolist(),
                         "epsilon14_max_abs_error": float(np.max(np.abs(np.asarray(fitted.params)-precision["cases"][0]["coefficients"]))),
                         "epsilon16_max_abs_error": float(np.max(np.abs(np.asarray(fitted.params)-precision["cases"][1]["coefficients"])))}
output.write_text(json.dumps(rows, indent=2, allow_nan=False)+"\n")
print(json.dumps({name:{k:v for k,v in row.items() if 'error' in k or k=='convergence'} for name,row in rows.items()},indent=2))
