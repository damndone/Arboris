"""Run native R and independent Stata fixed-alpha GLM evidence once per output."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from tests.stata_oracle import STATA,emit,run

HERE=Path(__file__).resolve().parent
INPUT=HERE.parent/"data.csv"
source_hash=hashlib.sha256(INPUT.read_bytes()).hexdigest()
stata_output=HERE/(sys.argv[1] if len(sys.argv)>1 else "native-stata")
if stata_output.exists():
    raise ValueError("Preserve previous native output directories")
if not STATA.is_file():
    raise RuntimeError("Required available Stata binary is missing; no silent skip")
if (HERE/"native-r").exists():
    existing=json.loads((HERE/"native-r/oracle.json").read_text())
    if existing["meta"]["source_sha256"]!=source_hash:
        raise AssertionError("Retained R oracle is bound to a different input")
else:
    subprocess.run(["Rscript",str(HERE/"generate_oracle.R"),str(INPUT),source_hash,str(HERE/"native-r")],check=True)

lines=[f'import delimited "{INPUT}", asdouble clear case(preserve)',
       "glm ynb x1 x2 x3, family(nbinomial 1) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)"]
def emit17(name,expression):
    return emit(name,expression).replace("%21.15g","%24.17g")
for term in ["_cons","x1","x2","x3"]:
    lines += [emit17(f"b_{term}",f"_b[{term}]"),emit17(f"se_{term}",f"_se[{term}]")]
lines += [emit17("ll_full","e(ll)"),emit17("nobs","e(N)"),emit17("df_resid","e(df)"),
          emit17("converged","e(converged)"),"estimates store full",
          "test x1 x2",emit17("wj_stat","r(chi2)"),emit17("wj_df","r(df)"),emit17("wj_p","r(p)"),
          "test x1-x2=1",emit17("ws_stat","r(chi2)"),emit17("ws_df","r(df)"),emit17("ws_p","r(p)"),
          "lincom x1+2*x2-.5",emit17("lc_est","r(estimate)"),emit17("lc_se","r(se)"),
          "nlcom _b[x1]/_b[x2]","matrix nb_nl_b=r(b)","matrix nb_nl_v=r(V)",
          emit17("nl_est","nb_nl_b[1,1]"),emit17("nl_se","sqrt(nb_nl_v[1,1])"),
          "margins, dydx(x1 x2)","matrix nb_ma_b=r(b)","matrix nb_ma_v=r(V)"]
for index,term in enumerate(["x1","x2"],1):
    lines += [emit17(f"ma_{term}_est",f"nb_ma_b[1,{index}]"),emit17(f"ma_{term}_se",f"sqrt(nb_ma_v[{index},{index}])")]
lines += ["margins, dydx(x1 x2) atmeans","matrix nb_mm_b=r(b)","matrix nb_mm_v=r(V)"]
for index,term in enumerate(["x1","x2"],1):
    lines += [emit17(f"mm_{term}_est",f"nb_mm_b[1,{index}]"),emit17(f"mm_{term}_se",f"sqrt(nb_mm_v[{index},{index}])")]
lines += ["glm ynb x1, family(nbinomial 1) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)",
          emit17("ll_restricted","e(ll)"),"estimates store restricted","lrtest full restricted",
          emit17("lr_stat","r(chi2)"),emit17("lr_df","r(df)"),emit17("lr_p","r(p)")]
reference=run(stata_output,"\n".join(lines))
(stata_output/"reference.json").write_text(json.dumps(reference,indent=2,allow_nan=False)+"\n")
print(json.dumps(reference,indent=2))
if hashlib.sha256(INPUT.read_bytes()).hexdigest()!=source_hash:
    raise AssertionError("Original input changed during native generation")
