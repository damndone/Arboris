"""Persist Integration numeric provenance and old/new/native differences."""
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT))
from tests.test_count_models_v1811_numeric_reference import collect_numeric_results, NB, GLM
from workbench.econometrics import count_models
from workbench.contracts.model.inference_kernel import kernel_from_fitted

HERE = Path(__file__).resolve().parent
output = HERE / "comparison.json"
if output.exists():
    raise ValueError("Preserve prior comparisons")
measured = collect_numeric_results()
old = json.loads((ROOT / "tests/fixtures/postestimation/oracle.json").read_text())["families"]["negative_binomial"]
differences = {}
for operation in ["wald_joint","wald_shifted","lincom","nlcom"]:
    differences[operation] = {}
    for key,value in NB[operation].items():
        if isinstance(value,(float,int)):
            differences[operation][key] = {"native_final":value,"old_oracle":old[operation][key],
                "workbench":measured[operation][key],
                "native_minus_old":value-old[operation][key],
                "workbench_minus_native":measured[operation][key]-value,
                "workbench_relative_error":measured[operation][key]/value-1 if value else None}
for at in ["average","at_means"]:
    differences[f"margins_{at}"] = {}
    for effect in measured["margins"][at]["effects"]:
        differences[f"margins_{at}"][effect["variable"]] = {
            key:{"native":NB["margins"][at][effect["variable"]][key],"workbench":effect[key],
                 "relative_error":effect[key]/NB["margins"][at][effect["variable"]][key]-1}
            for key in ["estimate","std_error"]}
model_module=Path(inspect.getfile(count_models)); integration=model_module.parents[3]
hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [
    ROOT / "tests/fixtures/postestimation/data.csv", ROOT / "tests/fixtures/postestimation/oracle.json",
    ROOT / "tests/fixtures/postestimation/generate_oracle.R",ROOT / "tests/fixtures/admission/glm_negative_binomial/data.csv",
    ROOT / "tests/fixtures/admission/glm_negative_binomial/oracle.json",ROOT / "tests/fixtures/admission/glm_negative_binomial/oracle_high_precision.json",
    model_module,Path(inspect.getfile(kernel_from_fitted))]}
result={"integration_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=integration,text=True).strip(),
        "reference_branch_head":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "production_module":str(model_module),"hashes":hashes,"measured":measured,"differences":differences,
        "glm_native_epsilon1e16":GLM["epsilon1e-16"],
        "nb_original_precision_sufficient":True,"note":"Direct primitives with explicit beta positions; registry/admission/callers not changed."}
output.write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
print(json.dumps({"integration_head":result["integration_head"],"differences":differences,
                  "alpha":measured["alpha"],"nb_natural_mean_score_max":measured["natural_mean_score_max"]},indent=2))
