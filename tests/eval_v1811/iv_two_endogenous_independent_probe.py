"""Fresh independent R/Stata/owner evidence; never edit producer assets."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tests.stata_oracle import STATA,emit,emit_text,run
from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.postestimation.registry import run_operation
from workbench.projects import create_project

HERE=Path(__file__).with_name("iv_two_endogenous_independent_evidence")
AUTHOR=ROOT / "tests/fixtures/postestimation/iv_two_endogenous_v1811"
DATA=AUTHOR / "data.csv"
if (HERE/"owner.json").exists():
    raise RuntimeError("Fresh independent evidence must not overwrite retained runs")
protected=json.loads((AUTHOR/"protected_assets_before.json").read_text())
author_paths=subprocess.run(["git","diff","--name-only","01fb0752","0a612419536a02fbba287e79114b6fab36dc025d"],check=True,capture_output=True,text=True).stdout.splitlines()
before={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in author_paths}
with (HERE/"r_output.txt").open("x") as out:
    subprocess.run(["Rscript",str(Path(__file__).with_name("iv_two_endogenous_independent_moments.R")),str(DATA),str(HERE)],check=True,stdout=out,stderr=subprocess.STDOUT)
assert STATA.is_file(),"Native Stata is required, no skip"
body=[f'import delimited using "{DATA}", asdouble clear case(preserve)',
      "ivregress 2sls y x1 (xe1 xe2 = z1 z2), vce(robust)"]
e17=lambda name,expression:emit(name,expression).replace("%21.15g","%24.17g")
terms={"Intercept":"_cons","x1":"x1","xe1":"xe1","xe2":"xe2"}
body += [emit_text("endogenous","e(endog)"),emit_text("exogenous_and_instruments","e(exog)"),
         emit_text("exogenous_regressors","e(exogr)"),emit_text("small_option","e(small)"),
         emit_text("vce","e(vce)"),e17("nobs","e(N)"),e17("nominal_residual_df","e(N)-colsof(e(b))")]
for term,native in terms.items():
    body += [e17(f"b_{term}",f"_b[{native}]"),e17(f"se_{term}",f"_se[{native}]"),
             e17(f"p_{term}",f"2*normal(-abs(_b[{native}]/_se[{native}]))")]
    for other,native_other in terms.items():
        body += [e17(f"cov_{term}_{other}",f'el(e(V),colnumb(e(V),"{native}"),colnumb(e(V),"{native_other}"))')]
body += ["test xe1 xe2",e17("wald_statistic","r(chi2)"),e17("wald_df","r(df)"),e17("wald_p","r(p)"),
         "ivregress 2sls y x1 (xe1 xe2 = z1 z2), vce(robust) small",
         emit_text("control_small_option","e(small)"),e17("control_df_resid","e(df_r)")]
for term,native in terms.items():
    body += [e17(f"control_se_{term}",f"_se[{native}]")]
body += ["test xe1 xe2",e17("control_wald_F","r(F)"),e17("control_wald_p","r(p)"),e17("control_wald_df_den","r(df_r)")]
private=HERE/"private_raw_stata"
assert not private.exists()
values=run(private,"\n".join(body),name="independent_iv")
header=re.compile(rb"(?m)^([ \t]*)(Serial number:|Licensed to:)([^\r\n]*)(\r?\n|$)")
raw=(private/"independent_iv.log").read_bytes()
assert len(header.findall(raw))==2
redacted=header.sub(lambda m:m.group(1)+m.group(2)+b" [REDACTED]"+m.group(4),raw)
(HERE/"stata.log").write_bytes(redacted)
for source,target in [("independent_iv.do","stata.do"),("wb_results.tsv","stata.tsv")]:
    (HERE/target).write_bytes((private/source).read_bytes())
subprocess.run(["git","check-ignore","--quiet",str((private/"independent_iv.log").relative_to(ROOT))],check=True,cwd=ROOT)
redaction=dict(raw_ignored_path=str((private/"independent_iv.log").relative_to(ROOT)),raw_sha256=hashlib.sha256(raw).hexdigest(),
 redacted_sha256=hashlib.sha256(redacted).hexdigest(),non_header_bytes_equal=header.sub(b"",raw)==header.sub(b"",redacted),changed_header_count=2)
(HERE/"stata_reference.json").write_text(json.dumps(dict(terms=list(terms),values=values,redaction=redaction),indent=2,allow_nan=False)+"\n")
project=create_project(HERE/"private_projects","independent_iv")
outcome=run_workflow(project.root,[DATA],mode="auto",model_type="iv_2sls",y="y",x=["x1"],iv_endog=["xe1","xe2"],iv_instruments=["z1","z2"])
root=project.root/"runs"/outcome["run_id"]
assert outcome["status"]=="completed",read_json(root/"errors.json")
kernel=read_json(root/kernel_relative_path("iv_2sls_1"))
spec={"constraints":[{"terms":{"xe1":1},"value":0},{"terms":{"xe2":1},"value":0}]}
owner=dict(run_root=str(root),kernel=kernel,primary=read_json(root/"model_results/iv_2sls_1.json"),
           run_inputs=read_json(root/"run_inputs.json"),wald=run_operation("wald",[kernel],spec))
(HERE/"owner.json").write_text(json.dumps(owner,indent=2,allow_nan=False)+"\n")
for name,digest in protected.items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
    original=subprocess.run(["git","show",f"01fb0752:{name}"],check=True,capture_output=True).stdout
    assert (ROOT/name).read_bytes()==original,name
assert before=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in author_paths}
(HERE/"scope.json").write_text(json.dumps(dict(candidate="0a612419536a02fbba287e79114b6fab36dc025d",baseline="01fb0752bce129c8d8848c021eca776dadccb515",author_assets_sha256=before,protected_sha256=protected,author_assets_unchanged=True,protected_byte_identical_to_baseline=True),indent=2)+"\n")
print("Fresh R moments, native Stata default/small controls and public owner captured; all producer and 9 protected assets unchanged")
