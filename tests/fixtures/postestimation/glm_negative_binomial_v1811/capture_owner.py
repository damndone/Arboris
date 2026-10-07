"""Capture fresh owner workflows and native comparisons without deleting runs."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from tests.test_glm_nb_v1811_reference import collect_owner_results, load_oracle

HERE=Path(__file__).resolve().parent
target=HERE / "owner-evidence.json"
if target.exists():
    raise RuntimeError("Preserve previous owner evidence")
project_root=Path(tempfile.mkdtemp(prefix="v1811-glm-nb-owner-"))
owner=collect_owner_results(project_root)
r=load_oracle()["full_precision"]
stata=json.loads((HERE / "native-stata-v3/reference.json").read_text())
rows=[]
def add(label,actual,native,tolerance,kind="relative"):
    actual=float(actual); native=float(native)
    error=abs(actual-native)
    relative=error/abs(native) if native else None
    passed=error <= tolerance if kind=="absolute" else relative is not None and relative <= tolerance
    rows.append(dict(quantity=label,owner=actual,native=native,absolute_error=error,
                     relative_error=relative,tolerance=tolerance,tolerance_kind=kind,passed=passed))
for i,name in enumerate(owner["full_kernel"]["param_names"]):
    rname="(Intercept)" if name=="Intercept" else name
    sname="_cons" if name=="Intercept" else name
    beta=owner["full_kernel"]["params"][i]
    se=owner["full_kernel"]["vcov"][i][i]**.5
    add(f"R coefficient {name}",beta,r["params"][rname],1e-8,"absolute")
    add(f"R SE {name}",se,r["std_error"][rname],1e-6,"absolute")
    add(f"Stata coefficient {name}",beta,stata[f"b_{sname}"],1e-8,"absolute")
    add(f"Stata SE {name}",se,stata[f"se_{sname}"],1e-6,"absolute")
for case in ["wald_joint","wald_shifted","lincom","nlcom","lr_drop_x2_x3"]:
    for key in ["statistic","estimate","std_error","loglik_full","loglik_restricted","p_value"]:
        if key in r[case]:
            add(f"R {case}.{key}",owner[case][key],r[case][key],1e-5 if key=="p_value" else 1e-6)
for at in ["average","at_means"]:
    for effect in owner["margins"][at]["effects"]:
        for key,tol in [("estimate",1e-6),("std_error",1e-5)]:
            add(f"R margins.{at}.{effect['variable']}.{key}",effect[key],r["margins"][at][effect["variable"]][key],tol)
for case,prefix in [("wald_joint","wj"),("wald_shifted","ws"),("lr_drop_x2_x3","lr")]:
    for key,suffix,tol in [("statistic","stat",1e-6),("p_value","p",1e-5)]:
        add(f"Stata {case}.{key}",owner[case][key],stata[f"{prefix}_{suffix}"],tol)
for case,prefix in [("lincom","lc"),("nlcom","nl")]:
    for key,suffix in [("estimate","est"),("std_error","se")]:
        add(f"Stata {case}.{key}",owner[case][key],stata[f"{prefix}_{suffix}"],1e-6)
for at,prefix in [("average","ma"),("at_means","mm")]:
    for effect in owner["margins"][at]["effects"]:
        for key,suffix,tol in [("estimate","est",1e-6),("std_error","se",1e-5)]:
            add(f"Stata margins.{at}.{effect['variable']}.{key}",effect[key],stata[f"{prefix}_{effect['variable']}_{suffix}"],tol)
assert all(row["passed"] for row in rows)
paths=["tests/fixtures/postestimation/data.csv","tests/fixtures/postestimation/oracle.json",
       "backend/workbench/econometrics/count_models.py","backend/workbench/econometrics/runner.py",
       "backend/workbench/contracts/model/inference_kernel.py","backend/workbench/postestimation/margins.py",
       "backend/workbench/postestimation/core.py"]
hashes={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in paths if (ROOT/path).exists()}
evidence=dict(baseline="01fb0752bce129c8d8848c021eca776dadccb515",project_root=str(project_root),
              owner=owner,comparisons=rows,readonly_source_sha256=hashes)
target.write_text(json.dumps(evidence,indent=2,allow_nan=False)+"\n")
lines=["# Fresh owner / native numeric comparison","","| Quantity | Owner | Native | Absolute error | Relative error | Tolerance |","|---|---:|---:|---:|---:|---:|"]
for row in rows:
    lines.append(f"| {row['quantity']} | {row['owner']:.17g} | {row['native']:.17g} | {row['absolute_error']:.4g} | {row['relative_error']:.4g} | {row['tolerance_kind']} {row['tolerance']:g} |")
(HERE/"numeric-diff.md").write_text("\n".join(lines)+"\n")
print(f"{len(rows)} full-precision comparisons PASS; retained owner projects: {project_root}")
