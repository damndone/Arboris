"""Persist independent full-precision comparisons and public artifact hashes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

import numpy as np

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).with_name("iv_two_endogenous_independent_evidence")
AUTHOR=ROOT/"tests/fixtures/postestimation/iv_two_endogenous_v1811"
load=lambda path:json.loads(path.read_text())
r=load(HERE/"r_moment_reference.json"); s=load(HERE/"stata_reference.json")["values"]; owner=load(HERE/"owner.json")
terms=r["terms"]
fresh_stata=dict(params={t:s[f"b_{t}"] for t in terms},std_error={t:s[f"se_{t}"] for t in terms},
 covariance=[[s[f"cov_{a}_{b}"] for b in terms] for a in terms],p={t:s[f"p_{t}"] for t in terms},
 wald_joint=dict(statistic=s["wald_statistic"],p_value=s["wald_p"]))
kernel=owner["kernel"]
fresh_owner=dict(params=dict(zip(terms,kernel["params"])),std_error=dict(zip(terms,np.sqrt(np.diag(kernel["vcov"])).tolist())),
 covariance=kernel["vcov"],wald_joint=owner["wald"])
comparisons={}
for label,fresh,reference in [("fresh_R_to_author_R",r,load(AUTHOR/"r_reference.json")),
 ("fresh_R_to_author_Stata",r,load(AUTHOR/"stata_reference.json")),
 ("fresh_Stata_to_fresh_R",fresh_stata,r),("fresh_owner_to_fresh_R",fresh_owner,r)]:
 rows={}
 for key in ["params","std_error","covariance"]:
  a=np.asarray(fresh[key] if key=="covariance" else [fresh[key][t] for t in terms]); b=np.asarray(reference[key] if key=="covariance" else [reference[key][t] for t in terms])
  rows[key]=dict(max_absolute_error=float(np.max(abs(a-b))),max_relative_error=float(np.max(abs((a-b)/b))))
 for key in ["statistic","p_value"]:
  a=fresh["wald_joint"][key]; b=reference["wald_joint"][key]
  rows["wald_"+key]=dict(actual=a,reference=b,absolute_error=abs(a-b),relative_error=abs((a-b)/b))
 comparisons[label]=rows
target=HERE/"comparison.json"
if target.exists(): raise RuntimeError("Preserve earlier review comparisons")
target.write_text(json.dumps(comparisons,indent=2,allow_nan=False)+"\n")
raw_record=load(AUTHOR/"license_header_protection.json")
raw=(ROOT/raw_record["raw_ignored_log"]).read_bytes()
header=re.compile(rb"(?m)^[ \t]*(?:Serial number:|Licensed to:)[ \t]*([^\r\n]*)")
values=header.findall(raw)
producer=load(HERE/"scope.json")["author_assets_sha256"]
for name,digest in producer.items():
 assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
paths=list(HERE.rglob('*'))+list(HERE.parent.glob("iv_two_endogenous_independent_*.py"))+list(HERE.parent.glob("iv_two_endogenous_independent_*.R"))
public=[p for p in paths if p.is_file() and not any(part.startswith('private_') or part=='__pycache__' for part in p.parts)]
for path in public:
 data=path.read_bytes()
 assert not any(value and value in data for value in values),str(path.relative_to(ROOT))
 assert all(value==b'[REDACTED]' for value in header.findall(data)),str(path.relative_to(ROOT))
manifest=dict(candidate="0a612419536a02fbba287e79114b6fab36dc025d",baseline="01fb0752bce129c8d8848c021eca776dadccb515",
 author_assets_unchanged=True,public_review_asset_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in public},
 public_sensitive_values_found=0,private_original_log=load(HERE/"stata_reference.json")["redaction"])
(HERE/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
print(json.dumps(comparisons,indent=2))
print("Independent public assets scanned without sensitive values; all candidate asset hashes unchanged")
