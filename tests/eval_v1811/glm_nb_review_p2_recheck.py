"""Read-only targeted proof. Never serialize private license field values."""
from pathlib import Path
import ast
import hashlib
import json
import re
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "tests/fixtures/postestimation/glm_negative_binomial_v1811"
BEFORE = "87f964311115117f08b790a6247645ad23e1ff80"
TIP = "06e3c798b4758a2c32fae2c30708641d54b15642"
BASELINE = "01fb0752bce129c8d8848c021eca776dadccb515"

def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT)

def sha(value):
    return hashlib.sha256(value).hexdigest()

def collect():
    manifest=json.loads((ASSET / "manifest.json").read_text())
    old_manifest=json.loads(git("show",BEFORE+":"+str((ASSET/"manifest.json").relative_to(ROOT))))
    records=[]; private_values=set(); changed_total=0
    pattern=re.compile(rb"^([ \t]*(?:Serial number|Licensed to):)([^\r\n]*)(\r?\n|$)")
    for name,item in manifest["log_redaction"]["files"].items():
        path=ASSET/name; raw_path=ROOT/item["raw_copy"]
        raw=raw_path.read_bytes(); original=git("show",BEFORE+":"+str(path.relative_to(ROOT)))
        current=path.read_bytes(); old_lines=raw.splitlines(keepends=True); new_lines=current.splitlines(keepends=True)
        assert len(old_lines)==len(new_lines), "Line count changed"
        changed=[]; old_payload=[]; new_payload=[]; exact=True
        for number,(old,new) in enumerate(zip(old_lines,new_lines),1):
            match=pattern.match(old)
            if match:
                private_values.add(match.group(2).strip())
                exact=exact and new==match.group(1)+b" [REDACTED]"+match.group(3)
            else:
                old_payload.append(old); new_payload.append(new); exact=exact and old==new
            if old!=new: changed.append(number)
        ignored=subprocess.run(["git","check-ignore","--quiet",item["raw_copy"]],cwd=ROOT).returncode==0
        untracked=subprocess.run(["git","ls-files","--error-unmatch",item["raw_copy"]],cwd=ROOT,
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
        changed_total+=len(changed)
        records.append({"path":str(path.relative_to(ROOT)),"raw_copy":item["raw_copy"],
            "raw_sha256":sha(raw),"redacted_sha256":sha(current),"payload_sha256":sha(b"".join(old_payload)),
            "raw_equals_before_git":raw==original,"raw_ignored_and_untracked":ignored and untracked,
            "raw_mode_0600":stat.S_IMODE(raw_path.stat().st_mode)==0o600,
            "exact_header_only_redaction":exact,"changed_lines":changed,
            "payload_byte_identical":old_payload==new_payload,
            "manifest_hashes_match":sha(raw)==item["raw_sha256"] and sha(current)==item["redacted_sha256"]
                and sha(b"".join(old_payload))==item["non_header_payload_sha256"],
            "manifest_line_numbers_match":changed==item["changed_line_numbers"]})
    added=git("diff","--name-only","--diff-filter=A",BASELINE,TIP).decode().splitlines()
    hits=[]; unsafe_headers=[]; scanned=0
    public_header=re.compile(rb"(?m)^[ \t]*(?:Serial number|Licensed to):([^\r\n]*)")
    for relative in added:
        value=(ROOT/relative).read_bytes()
        if b"\x00" in value: continue
        scanned+=1
        if any(secret and secret in value for secret in private_values): hits.append(relative)
        if any(m.group(1).strip()!=b"[REDACTED]" for m in public_header.finditer(value)):
            unsafe_headers.append(relative)
    old_unchanged=[]
    redacted_paths={record["path"] for record in records}
    for relative,old_hash in old_manifest["asset_sha256"].items():
        if relative in redacted_paths or relative=="tests/test_glm_nb_v1811_reference.py": continue
        old_unchanged.append({"path":relative,"unchanged":sha((ROOT/relative).read_bytes())==old_hash})
    test_path="tests/test_glm_nb_v1811_reference.py"
    old_ast=ast.parse(git("show",BEFORE+":"+test_path).decode()); new_ast=ast.parse((ROOT/test_path).read_text())
    new_functions={node.name:ast.dump(node,include_attributes=False) for node in new_ast.body
                   if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
    functions_unchanged=all(new_functions.get(node.name)==ast.dump(node,include_attributes=False)
        for node in old_ast.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)))
    protected=[]
    for relative,item in manifest["readonly_protected"].items():
        current=(ROOT/relative).read_bytes()
        protected.append({"path":relative,"baseline_identical":current==git("show",BASELINE+":"+relative),
                          "sha256":sha(current),"manifest_matches":sha(current)==item["sha256"]})
    original_review=json.loads((ROOT/"tests/eval_v1811/glm_nb_review_manifest.json").read_text())
    review_unchanged=all(sha((ROOT/relative).read_bytes())==digest
                         for relative,digest in original_review["owned_file_sha256"].items())
    asset_matches=all(sha((ROOT/relative).read_bytes())==digest for relative,digest in manifest["asset_sha256"].items())
    return {"reviewed_tip":TIP,"pre_remediation_tip":BEFORE,"baseline":BASELINE,"records":records,
        "changed_header_lines_total":changed_total,"added_tracked_texts_scanned":scanned,
        "private_field_value_hits":hits,"unredacted_header_hits":unsafe_headers,
        "unchanged_statistical_assets":old_unchanged,"existing_author_functions_ast_unchanged":functions_unchanged,
        "protected":protected,"original_independent_evidence_hashes_unchanged":review_unchanged,
        "current_manifest_asset_hashes_match":asset_matches,"current_manifest_asset_count":len(manifest["asset_sha256"])}

if __name__=="__main__":
    proof=collect()
    output=Path(__file__).with_name("glm_nb_review_p2_proof.json")
    if output.exists(): raise ValueError("Preserve previous proof")
    output.write_text(json.dumps(proof,indent=2)+"\n")
    print(json.dumps({"raw_logs":len(proof["records"]),"changed_lines":proof["changed_header_lines_total"],
        "public_texts_scanned":proof["added_tracked_texts_scanned"],"private_value_hits":len(proof["private_field_value_hits"]),
        "unredacted_header_hits":len(proof["unredacted_header_hits"]),"protected":len(proof["protected"])}))
