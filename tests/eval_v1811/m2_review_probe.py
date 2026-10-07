"""Read-only numerical review of M2 functional tip; run under exclusive runner."""
from pathlib import Path
import ast
import hashlib
import json
import subprocess
import sys
import warnings

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from workbench.econometrics.runner import run_glm, run_negative_binomial
from workbench.econometrics import runner
from tests.stata_oracle import emit, run
from workbench.contracts.model.inference_kernel import kernel_from_fitted
from workbench.econometrics.normalize import _public_term

OUT = Path(__file__).parent
REFERENCE = ROOT / "tests/fixtures/count_models/reference-v3"


def capture(call):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result, fitted = call()
            try:
                json.dumps(result, allow_nan=False)
                strict_json = True
            except ValueError as exc:
                strict_json = str(exc)
            keys = ["model_id","model_type","nobs","llf","aic","bic","coefficients","ancillary_parameters",
                    "information_matrix","convergence","warnings","alpha_estimated","alpha_fixed_value","dispersion","overdispersion_test"]
            return {"returned": True, "result": {key:result[key] for key in keys if key in result}, "strict_json": strict_json,
                    "params": np.asarray(fitted.params).tolist(),
                    "natural_score": np.asarray(fitted.model.score(np.asarray(fitted.params))).tolist(),
                    "covariance_eigenvalues": np.linalg.eigvalsh(np.asarray(fitted.cov_params())).tolist(),
                    "runtime_warnings": [str(w.message) for w in caught]}
        except Exception as exc:
            return {"returned": False, "exception": type(exc).__name__, "message": str(exc),
                    "runtime_warnings": [str(w.message) for w in caught]}


def main():
    r_path = OUT / "m2_review_r.json"
    subprocess.run(["Rscript", str(OUT / "m2_review_oracle.R"), str(ROOT), str(r_path)], check=True)
    rows = {}
    baseline_source = subprocess.run(["git","show","6f0f87c6d8241a93d81e2c34f8ef8e9408a907b3:backend/workbench/econometrics/runner.py"],cwd=ROOT,check=True,capture_output=True,text=True).stdout
    baseline_function = next(n for n in ast.parse(baseline_source).body if isinstance(n,ast.FunctionDef) and n.name=="run_glm")
    baseline_globals = dict(vars(runner))
    exec(compile(ast.Module(body=[baseline_function],type_ignores=[]),"baseline_run_glm","exec"),baseline_globals)
    boundary = pd.read_csv(REFERENCE / "poisson.csv", float_precision="round_trip")
    for dispersion in ["mean", "constant"]:
        rows[f"boundary_{dispersion}"] = capture(lambda: run_negative_binomial(boundary,"y",["x1","x2"],"review",dispersion=dispersion))
    data = pd.read_csv(REFERENCE / "nb2.csv", float_precision="round_trip")
    for value in [-1., .5, float("inf")]:
        modified = data.astype({"y": float})
        modified.loc[0,"y"] = value
        for family in ["poisson", "negative_binomial"]:
            rows[f"invalid_glm_{family}_{value}"] = capture(lambda: run_glm(modified,"y",["x1","x2"],"review",family,alpha=.5 if family=="negative_binomial" else None))
        if value == -1.:
            rows["baseline_negative_glm"] = capture(lambda: baseline_globals["run_glm"](modified,"y",["x1","x2"],"baseline","negative_binomial"))
            rows["baseline_negative_poisson"] = capture(lambda: baseline_globals["run_glm"](modified,"y",["x1","x2"],"baseline","poisson"))
    for regressor in ["x1","alpha"]:
        named = data.rename(columns={"x1":regressor})
        _, fitted = run_negative_binomial(named,"y",[regressor,"x2"],"review")
        rows[f"current_consumer_{regressor}"] = kernel_from_fitted(fitted,model_id="review",model_type="negative_binomial",nobs=len(data),public_name=_public_term)
    precision = pd.read_csv(ROOT / "tests/fixtures/admission/glm_negative_binomial/data.csv", float_precision="round_trip")
    rows["glm_precision"] = capture(lambda: run_glm(precision,"y",["x1","x2"],"review","negative_binomial",alpha=1.))
    for form, command, ancillary in [("mean","nbreg y x1 x2", "lnalpha"),("constant","nbreg y x1 x2, dispersion(constant)","lndelta")]:
        body = "\n".join([f'import delimited "{REFERENCE / "poisson.csv"}", asdouble clear case(preserve)',
            command+ (", " if form=="mean" else " ")+"difficult iterate(1000) tolerance(1e-10) ltolerance(1e-12)",
            emit("converged","e(converged)"),emit("ll","e(ll)"),emit("b_log",f"_b[/{ancillary}]"),emit("se_log",f"_se[/{ancillary}]"),emit("lr","e(chi2_c)")])
        rows[f"stata_boundary_{form}"] = run(OUT / f"m2_review_stata_boundary_{form}",body)
    # Stata nbreg validates the support; GLM is also checked as a separate entry.
    body = "\n".join([f'import delimited "{REFERENCE / "nb2.csv"}", asdouble clear case(preserve)',
        "replace y=0.5 in 1", "capture noisily glm y x1 x2, family(nbinomial 0.5) link(log) ml", emit("glm_fractional_rc","_rc"),
        "capture noisily nbreg y x1 x2", emit("nb_fractional_rc","_rc"),
        "replace y=-1 in 1", "capture noisily glm y x1 x2, family(nbinomial 0.5) link(log) ml", emit("glm_negative_rc","_rc")])
    rows["stata_invalid"] = run(OUT / "m2_review_stata_invalid",body)
    paths = ["backend/workbench/econometrics/count_models.py","backend/workbench/econometrics/runner.py",
             "tests/fixtures/count_models/reference-v3/poisson.csv","tests/fixtures/admission/glm_negative_binomial/data.csv"]
    evidence = {"baseline":"6f0f87c6d8241a93d81e2c34f8ef8e9408a907b3","functional_tip":"cda5c2f14a82928826bae526d780201add0f30f2",
                "hashes":{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},"probes": rows}
    (OUT / "m2_review_evidence.json").write_text(json.dumps(evidence, indent=2, allow_nan=True)+"\n")
    for name, row in rows.items():
        if "result" in row:
            res=row["result"]
            print(name, json.dumps({"ll":res.get("llf"),"ancillary":res.get("ancillary_parameters"),"convergence":res.get("convergence"),"lr":res.get("overdispersion_test"),"strict_json":row["strict_json"],"natural_score":row["natural_score"],"covariance_eigenvalues":row["covariance_eigenvalues"]}))
        else:
            print(name,json.dumps(row))


if __name__ == "__main__":
    main()
