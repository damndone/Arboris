"""Independent real-Stata adversarial checks against the frozen M1 tip."""
from pathlib import Path
import json
import sys
import uuid

import numpy as np
import pandas as pd
from scipy.stats import norm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stata_oracle import STATA, emit, run
from workbench.engine.packs.arma_garch.joint_mle import fit_joint_arma_garch
from workbench.engine.packs.arma_garch.volatility import VarianceCandidateSpec

ROOT = Path(__file__).resolve().parent
OUT = ROOT / ("m1_review_evidence_" + uuid.uuid4().hex[:8])
OUT.mkdir()
assert STATA.exists(), "Real Stata is required; no skip allowed"
print(f"evidence_directory={OUT}", flush=True)

def simulate(n, ar, ma, alpha, beta, mu, seed):
    rng = np.random.default_rng(seed)
    e, u, h = np.zeros(n+500), np.zeros(n+500), np.ones(n+500)
    for t in range(4, n+500):
        h[t] = .2 + sum(a*e[t-i-1]**2 for i,a in enumerate(alpha)) + sum(b*h[t-i-1] for i,b in enumerate(beta))
        e[t] = rng.normal()*np.sqrt(h[t])
        u[t] = sum(a*u[t-i-1] for i,a in enumerate(ar)) + sum(b*e[t-i-1] for i,b in enumerate(ma)) + e[t]
    return mu+u[500:]

records = []
failures = []
cases = [
    ("ma2_arch2", [], [.4,-.2], [.2,.18], [], 1.5, 1600),
    ("arma22_garch22", [.45,-.18], [.4,-.2], [.15,.12], [.25,.28], 1.5, 2500),
    ("arma12_garch11_zero", [.5], [.4,-.2], [.2], [.65], 0., 1800),
]
for ci,(case,ar,ma,alpha,beta,mu,n) in enumerate(cases):
    y = simulate(n, ar, ma, alpha, beta, mu, 20261004+ci)
    directory = OUT/case
    directory.mkdir()
    pd.DataFrame({"t":np.arange(1,n+1),"y":y}).to_csv(directory/"data.csv",index=False,float_format="%.17g")
    p,q,r,s = len(ar),len(ma),len(alpha),len(beta)
    spec = VarianceCandidateSpec.create(model="garch" if s else "arch",p=r,q=s,distribution="normal")
    names = (["mu"] if mu else [])+[f"ar{i}" for i in range(1,p+1)]+[f"ma{i}" for i in range(1,q+1)]
    stata_names = names+[f"arch{i}" for i in range(1,r+1)]+[f"garch{i}" for i in range(1,s+1)]+["omega"]
    options = (f"ar(1/{p}) " if p else "")+f"ma(1/{q}) arch(1/{r}) "+(f"garch(1/{s}) " if s else "")+("noconstant " if not mu else "")
    for vce in ("opg","oim","robust"):
        target = directory/vce
        body = f'import delimited "{directory / "data.csv"}", clear asdouble case(preserve)\ntsset t\n'
        body += f'quietly arch y, {options}vce({vce}) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)\n'
        body += emit("ll","e(ll)")+"\n"+emit("nobs","e(N)")+"\n"+emit("converged","e(converged)")+"\n"
        body += "matrix b=e(b)\nmatrix V=e(V)\nquietly estat ic\nmatrix IC=r(S)\n"+emit("aic","IC[1,5]")+"\n"+emit("bic","IC[1,6]")+"\n"
        for i,name in enumerate(stata_names,1):
            body += emit("b_"+name,f"b[1,{i}]")+"\n"+emit("se_"+name,f"sqrt(V[{i},{i}])")+"\n"
            body += emit("lo_"+name,f"b[1,{i}]-invnormal(.975)*sqrt(V[{i},{i}])")+"\n"+emit("hi_"+name,f"b[1,{i}]+invnormal(.975)*sqrt(V[{i},{i}])")+"\n"
        body += 'predict double innovation, residuals\npredict double variance, variance\nformat innovation variance %24.17g\nexport delimited innovation variance using "series.csv", replace\n'
        body += f'quietly arch y, {options}arch0(xb) arma0(zero) vce({vce}) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)\n'+emit("explicit_ll","e(ll)")+"\n"
        oracle=run(target,body,name="m1_review_oracle")
        result=fit_joint_arma_garch(y,mean_p=p,mean_q=q,include_constant=bool(mu),variance_spec=spec,time_index_semantics="observation_order",vce=vce)
        series=pd.read_csv(target/"series.csv")
        checks={"ll_relative":abs(result.log_likelihood-oracle["ll"])/abs(oracle["ll"]),"aic_relative":abs(result.aic-oracle["aic"])/abs(oracle["aic"]),"bic_relative":abs(result.bic-oracle["bic"])/abs(oracle["bic"]),"parameter_absolute":max(abs(result.parameters[name]-oracle["b_"+name]) for name in result.parameter_names),"se_relative":max(abs(result.standard_errors[name]/oracle["se_"+name]-1) for name in result.parameter_names),"ci_absolute":max(abs(result.parameters[name]+sign*norm.ppf(.975)*result.standard_errors[name]-oracle[("hi_" if sign==1 else "lo_")+name]) for name in result.parameter_names for sign in (-1,1)),"presample_default_explicit_ll":abs(oracle["explicit_ll"]-oracle["ll"])}
        for field in ("residual","variance"):
            actual=np.asarray(result.conditional_series[field]); expected=series["innovation" if field=="residual" else "variance"].to_numpy()
            checks[field+"_max_absolute"]=float(np.max(np.abs(actual-expected)))
            try:
                np.testing.assert_allclose(actual,expected,rtol=1e-3,atol=1e-4)
            except AssertionError as exc:
                failures.append({"case":case,"vce":vce,"field":field,"error":str(exc)})
        record={"case":case,"vce":vce,"checks":checks,"oracle":oracle,"workbench":result.to_dict()}
        (target/"comparison.json").write_text(json.dumps(record,indent=2,allow_nan=False))
        records.append({"case":case,"vce":vce,"checks":checks})
        print(json.dumps(records[-1]),flush=True)
        assert oracle["converged"]==1 and oracle["nobs"]==result.nobs==n
        if checks["ll_relative"]>1e-6 or checks["aic_relative"]>1e-6 or checks["bic_relative"]>1e-6:
            failures.append({"case":case,"vce":vce,"field":"reported_ll_ic","checks":checks})
        if checks["parameter_absolute"]>1e-4 or checks["se_relative"]>1e-3 or checks["ci_absolute"]>2e-4:
            failures.append({"case":case,"vce":vce,"field":"reported_parameters_se_ci","checks":checks})
        assert checks["presample_default_explicit_ll"]<=1e-8
        h0=result.presample["variance"]
        assert abs(result.conditional_series["variance"][0]-(result.parameters["omega"]+sum(result.parameters[k] for k in result.parameters if k.startswith(("arch","garch")))*h0))<1e-10
        assert abs(h0-np.mean(np.asarray(result.conditional_series["residual"])**2))<1e-10
(OUT/"summary.json").write_text(json.dumps(records,indent=2))
(OUT/"failures.json").write_text(json.dumps(failures,indent=2))
assert not failures, json.dumps(failures,indent=2)
print("9 independent real-Stata scenarios passed",flush=True)
