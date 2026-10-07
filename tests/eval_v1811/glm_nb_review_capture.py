"""Fresh independent native runs; only writes a new review evidence directory."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.stata_oracle import emit, run
from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.postestimation import wald_test, lincom, nlcom, lr_test
from workbench.postestimation.estimation_data import estimation_design
from workbench.postestimation.margins import marginal_effects

INPUT = ROOT / "tests/fixtures/postestimation/data.csv"
OUTPUT = Path(sys.argv[1]).resolve()
if OUTPUT.exists():
    raise ValueError("Review evidence directory must be fresh")
OUTPUT.mkdir(parents=True)
source_hash = hashlib.sha256(INPUT.read_bytes()).hexdigest()
with (OUTPUT / "r-output.txt").open("w") as stream:
    subprocess.run(["Rscript", str(Path(__file__).with_suffix(".R").with_name("glm_nb_review_native.R")),
                    str(INPUT), str(OUTPUT / "r-reference.json")], check=True, stdout=stream, stderr=subprocess.STDOUT)
def number(key, expression):
    return emit(key, expression).replace("%21.15g", "%24.17g")
body = [f'import delimited "{INPUT}", asdouble clear case(preserve)',
        'glm ynb x1 x2 x3, family(nbinomial 1) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)']
for term in ["_cons", "x1", "x2", "x3"]:
    body += [number(f"b_{term}", f"_b[{term}]"), number(f"se_{term}", f"_se[{term}]")]
body += [number("nobs", "e(N)"), number("df_resid", "e(df)"), number("converged", "e(converged)"),
         number("ll_full", "e(ll)"), "matrix review_cov=e(V)", "estimates store review_full"]
# Stata orders x1,x2,x3,_cons; retain its complete native covariance block.
for i in range(1, 5):
    for j in range(1, 5):
        body += [number(f"cov_{i}_{j}", f"review_cov[{i},{j}]")]
for prefix, command in [("wj", "test x1 x2"), ("ws", "test x1-x2=1")]:
    body += [command, number(prefix+"_stat", "r(chi2)"), number(prefix+"_df", "r(df)"), number(prefix+"_p", "r(p)")]
body += ["lincom x1+2*x2-.5",number("lc_est","r(estimate)"),number("lc_se","r(se)"),
         "nlcom _b[x1]/_b[x2]", "matrix review_b=r(b)", "matrix review_V=r(V)",
         number("nl_est","review_b[1,1]"),number("nl_se","sqrt(review_V[1,1])")]
for prefix, command in [("ma","margins, dydx(x1 x2)"),("mm","margins, dydx(x1 x2) atmeans")]:
    body += [command,"matrix review_b=r(b)","matrix review_V=r(V)"]
    for i, term in enumerate(["x1","x2"],1):
        body += [number(f"{prefix}_{term}_est",f"review_b[1,{i}]"),number(f"{prefix}_{term}_se",f"sqrt(review_V[{i},{i}])")]
body += ['glm ynb x1, family(nbinomial 1) link(log) ml vce(eim) scale(1) iterate(1000) tolerance(1e-12) ltolerance(1e-12)',
         number("ll_restricted","e(ll)"),"estimates store review_restricted","lrtest review_full review_restricted",
         number("lr_stat","r(chi2)"),number("lr_df","r(df)"),number("lr_p","r(p)")]
stata = run(OUTPUT / "stata", "\n".join(body), name="glm_nb_review")
(OUTPUT / "stata-reference.json").write_text(json.dumps(stata,indent=2,allow_nan=False)+"\n")
log_path = OUTPUT / "stata/glm_nb_review.log"
log = log_path.read_text(errors="replace")
own = log[log.index(". do glm_nb_review.do"):]
(OUTPUT / "stata-own-output.txt").write_text(own)
kernels = {}; roots = {}; outcomes = {}
for label, columns in [("full",["x1","x2","x3"]),("restricted",["x1"])]:
    project = create_project(OUTPUT / "projects", label)
    outcome = run_workflow(project.root,[INPUT],mode="auto",model_type="glm:negative_binomial",
                           y="ynb",x=columns,model_options={"alpha":1.0})
    root = project.root / "runs" / outcome["run_id"]
    assert outcome["status"] == "completed", read_json(root / "errors.json")
    kernels[label] = read_json(root / kernel_relative_path("glm_1")); roots[label] = root
    outcomes[label] = outcome["status"]
full = kernels["full"]
design = estimation_design(roots["full"],full)
owner = {"kernels":kernels,"outcomes":outcomes,
         "wj":wald_test(full,[{"terms":{"x1":1},"value":0},{"terms":{"x2":1},"value":0}]),
         "ws":wald_test(full,[{"terms":{"x1":1,"x2":-1},"value":1}]),
         "lc":lincom(full,{"x1":1,"x2":2},constant=-.5),"nl":nlcom(full,"x1/x2"),
         "lr":lr_test(full,kernels["restricted"]),
         "margins":{prefix:marginal_effects(full,design,inverse_link="log",variables=["x1","x2"],at=at)
                    for prefix,at in [("ma","average"),("mm","means")]}}
(OUTPUT / "owner.json").write_text(json.dumps(owner,indent=2,allow_nan=False)+"\n")
assert hashlib.sha256(INPUT.read_bytes()).hexdigest() == source_hash
(OUTPUT / "source.json").write_text(json.dumps({"path":str(INPUT),"sha256_before_and_after":source_hash,
    "stata_raw_log_sha256":hashlib.sha256(log_path.read_bytes()).hexdigest()},indent=2)+"\n")
print(json.dumps({"source_sha256":source_hash,"stata_native_fields":len(stata),"owner":outcomes}))
