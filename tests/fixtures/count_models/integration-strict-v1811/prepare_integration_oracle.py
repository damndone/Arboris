"""Project native full-precision R evidence to the existing GLM oracle schema."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASELINE = "35e81a0ed2ad7c498001c967c46557dc30b6fa03"
output = HERE / "glm-negative-binomial-v1811-oracle.json"
native = json.loads((HERE / "native-reference/glm-fixed-alpha-reference.json").read_text())["full_precision"]["epsilon1e-16"]
beta = {"Intercept" if name == "(Intercept)" else name:float(value) for name,value in native["params"].items()}
standard_errors = dict(zip(beta,[float(value) for value in native["std_error"]]))
ready = {"meta":{"generator":"tests/fixtures/count_models/integration-strict-v1811/generate_reference.R",
                 "r_version":"R version 4.6.0 (2026-04-24)","seed":20261003,"n":450,"epsilon":1e-16,
                 "verification_level":"Same original CSV, log GLM fixed alpha=1; final expected information, scale=1; no alpha estimation",
                 "source":"native-reference/glm-fixed-alpha-reference.json"},
         "inference":{"covariance_estimator":"nonrobust","df_method":"asymptotic","reference_distribution":"z","df_resid":447},
         "coefficients":beta,"std_error":standard_errors}
ready_text = json.dumps(ready,indent=2,allow_nan=False)+"\n"
if output.exists():
    if output.read_text() != ready_text:
        raise ValueError("Preserve earlier Integration-ready references")
else:
    output.write_text(ready_text)
paths = ["tests/fixtures/postestimation/data.csv","tests/fixtures/postestimation/oracle.json","tests/fixtures/postestimation/generate_oracle.R",
         "tests/fixtures/admission/glm_negative_binomial/data.csv","tests/fixtures/admission/glm_negative_binomial/oracle.json",
         "tests/fixtures/admission/glm_negative_binomial/oracle_high_precision.json","tests/fixtures/admission/glm_negative_binomial/generate_oracle.R",
         "backend/workbench/econometrics/count_models.py","backend/workbench/econometrics/runner.py"]
rows=[]
for path in paths:
    # Other lanes had already changed the Integration runner. Prove this task
    # left its local production file untouched using its own exact start tip.
    identity = "edeba374247bd9e4d608a68e87def84883315cdc" if path.endswith("runner.py") else BASELINE
    committed=subprocess.check_output(["git","show",f"{identity}:{path}"],cwd=ROOT)
    current=(ROOT/path).read_bytes()
    if committed!=current:
        raise AssertionError(f"Read-only input/production changed: {path}")
    rows.append({"path":path,"sha256":hashlib.sha256(current).hexdigest(),"verified_against":identity,"unchanged":True})
manifest={"integration_merge_baseline":BASELINE,"numeric_runtime_head":json.loads((HERE/"comparison.json").read_text())["integration_head"],
          "read_only_files":rows,"reference_only_scope":True,"no_old_oracle_update_required_for_nb2":True}
(HERE/"input-scope-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
print(json.dumps(ready,indent=2))
print("Original seven reference inputs unchanged from Integration merge; production unchanged from declared exact identity")
