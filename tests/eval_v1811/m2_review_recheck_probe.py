"""Fresh read-only M2 recheck, independent native R/Stata evidence."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
from tests.stata_oracle import emit, run
from workbench.econometrics.runner import run_negative_binomial, run_glm


def capture(call):
    try:
        packet,fitted=call()
    except ValueError as error:
        return {"returned":False,"message":str(error)}
    json.dumps(packet,allow_nan=False)
    p=np.asarray(fitted.params)
    V=np.asarray(fitted.cov_params())
    observed=packet["information_matrix"]=="observed"
    H=-fitted.model.hessian(p) if packet["alpha_estimated"] else -fitted.model.hessian(p,observed=observed)
    return {"returned":True,"params":p.tolist(),"se":np.asarray(fitted.bse).tolist(),"ll":float(fitted.llf),
            "score":np.asarray(fitted.model.score(p)).tolist(),"n":int(fitted.nobs),
            "information":H.tolist(),"covariance":V.tolist(),"information_eigenvalues":np.linalg.eigvalsh(H).tolist(),
            "covariance_eigenvalues":np.linalg.eigvalsh(V).tolist(),"inverse_residual":float(np.max(np.abs(H@V-np.eye(len(p))))),
            "convergence":packet["convergence"],"information_matrix":packet["information_matrix"],
            "alpha_estimated":packet["alpha_estimated"],"ancillary":packet["ancillary_parameters"],"strict_json":True}


def main():
    points={}
    ref=ROOT/"tests/fixtures/count_models/reference-v3"
    for name,form in [("nb2","mean"),("nb1","constant")]:
        d=pd.read_csv(ref/f"{name}.csv",float_precision="round_trip")
        points[name]=capture(lambda:run_negative_binomial(d,"y",["x1","x2"],"recheck",dispersion=form))
        boundary=pd.read_csv(ref/"poisson.csv",float_precision="round_trip")
        points[f"boundary_{form}"]=capture(lambda:run_negative_binomial(boundary,"y",["x1","x2"],"recheck",dispersion=form))
    fractional=ROOT/"tests/fixtures/count_models/p1-remediation-20261004/fractional-oracle/data.csv"
    d=pd.read_csv(fractional,float_precision="round_trip")
    points["fractional_fixed"]=capture(lambda:run_negative_binomial(d,"y",["x1","x2"],"recheck",alpha=.5))
    points["fractional_glm"]=capture(lambda:run_glm(d,"y",["x1","x2"],"recheck","negative_binomial",alpha=.5))
    points["fractional_joint"]=capture(lambda:run_negative_binomial(d,"y",["x1","x2"],"recheck"))
    for value in [-1.,float("inf"),-float("inf")]:
        bad=d.copy();bad.loc[0,"y"]=value
        for family in ["poisson","negative_binomial"]:
            points[f"invalid_{family}_{value}"]=capture(lambda:run_glm(bad,"y",["x1","x2"],"recheck",family,alpha=.5 if family=="negative_binomial" else None))
        points[f"invalid_fixed_{value}"]=capture(lambda:run_negative_binomial(bad,"y",["x1","x2"],"recheck",alpha=.5))
    points_path=OUT/"m2_review_recheck_points.json"
    points_path.write_text(json.dumps(points,indent=2,allow_nan=False)+"\n")
    rpath=OUT/"m2_review_recheck_r.json"
    subprocess.run(["Rscript",str(OUT/"m2_review_recheck_oracle.R"),str(ROOT),str(points_path),str(rpath)],check=True)
    body="\n".join([f'import delimited "{fractional}", asdouble clear case(preserve)',
        "glm y x1 x2, family(nbinomial 0.5) link(log) ml iterate(1000) tolerance(1e-12) ltolerance(1e-12)",
        *[emit(f"b_{t}",f"_b[{t}]").replace("%21.15g","%24.17g") for t in ["_cons","x1","x2"]],
        *[emit(f"se_{t}",f"_se[{t}]").replace("%21.15g","%24.17g") for t in ["_cons","x1","x2"]],
        emit("ll","e(ll)").replace("%21.15g","%24.17g"),
        "replace y=-1 in 1","capture noisily glm y x1 x2, family(nbinomial 0.5) link(log) ml",emit("negative_rc","_rc")])
    stata=run(OUT/"m2_review_recheck_stata",body)
    (OUT/"m2_review_recheck_stata.json").write_text(json.dumps(stata,indent=2)+"\n")
    evidence={"functional_tip":"3d4c73c0ef3763057fd1ca250c9165638b9e577e","code_commit":"96f356fc8606dfc32323dfb9d45b6fbbaa6c3051",
              "production_sha256":hashlib.sha256((ROOT/"backend/workbench/econometrics/count_models.py").read_bytes()).hexdigest(),
              "points":points,"r":json.loads(rpath.read_text()),"stata":stata}
    (OUT/"m2_review_recheck_evidence.json").write_text(json.dumps(evidence,indent=2,allow_nan=False)+"\n")
    print(json.dumps(evidence,indent=2,allow_nan=False))


if __name__=="__main__":main()
