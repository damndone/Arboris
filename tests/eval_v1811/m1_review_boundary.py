"""Distinguish a Stata unconstrained optimum from the C1 nonnegative model."""
from pathlib import Path
import json
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stata_oracle import emit,run

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/"m1_review_evidence_ca428fcd"/"arma22_garch22"
OUT=ROOT/("m1_review_boundary_evidence_"+uuid.uuid4().hex[:8])
print(f"evidence_directory={OUT}",flush=True)
body=f'import delimited "{SOURCE/"data.csv"}", clear asdouble case(preserve)\ntsset t\nconstraint define 1 [ARCH]L.garch=0\n'
body+='quietly arch y, ar(1/2) ma(1/2) arch(1/2) garch(1/2) constraints(1) arch0(xb) arma0(zero) vce(opg) tolerance(1e-12) ltolerance(1e-12) nrtolerance(1e-8) iterate(500)\n'
body+=emit("ll","e(ll)")+"\n"+emit("converged","e(converged)")+"\nmatrix b=e(b)\n"
names=["mu","ar1","ar2","ma1","ma2","arch1","arch2","garch1","garch2","omega"]
for i,name in enumerate(names,1):body+=emit(name,f"b[1,{i}]")+"\n"
oracle=run(OUT,body,name="m1_review_boundary_oracle")
comparison=json.loads((SOURCE/"opg"/"comparison.json").read_text())
w=comparison["workbench"]
record={"stata_constrained":oracle,"workbench_ll":w["log_likelihood"],"ll_absolute_difference":abs(oracle["ll"]-w["log_likelihood"]),"parameter_max_absolute_difference":max(abs(oracle[name]-w["parameters"][name]) for name in names),"source":str(SOURCE)}
(OUT/"comparison.json").write_text(json.dumps(record,indent=2))
print(json.dumps(record),flush=True)
assert oracle["converged"]==1
assert record["ll_absolute_difference"]<1e-6
assert record["parameter_max_absolute_difference"]<1e-4
