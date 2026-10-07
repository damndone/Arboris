"""Preserve private raw logs, then redact only two Stata license fields."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[4]
HERE=Path(__file__).resolve().parent
PRIVATE=ROOT / "local/v1811-glm-nb-raw-logs/20261004-p2"
NAMES=["native-stata/oracle.log","native-stata-v2/oracle.log",
       "native-stata-v3/oracle.log","native-output.txt"]
FIELD=re.compile(rb"(?m)^([ \t]*)(Serial number:|Licensed to:)([^\r\n]*)(\r?\n|$)")
WHOLE_LINE=re.compile(rb"(?m)^[ \t]*(?:Serial number:|Licensed to:)[^\r\n]*(?:\r?\n|$)")
manifest_path=HERE / "manifest.json"
manifest=json.loads(manifest_path.read_text())
if "log_redaction" in manifest:
    raise RuntimeError("Existing preservation record must not be overwritten")
records={}
# Preserve every complete raw input before editing any tracked log.
for name in NAMES:
    source=HERE / name
    raw=source.read_bytes()
    matches=list(FIELD.finditer(raw))
    assert len(matches)==2 and all(b"[REDACTED]" not in m.group(3) for m in matches)
    private=PRIVATE / name
    subprocess.run(["git","check-ignore","--quiet",str(private.relative_to(ROOT))],check=True,cwd=ROOT)
    private.parent.mkdir(parents=True,exist_ok=True)
    descriptor=os.open(private,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,"wb") as out:
        out.write(raw)
    assert private.read_bytes()==raw
    raw_hash=hashlib.sha256(raw).hexdigest()
    assert manifest["asset_sha256"][str(source.relative_to(ROOT))]==raw_hash
    records[name]=dict(raw_copy=str(private.relative_to(ROOT)),raw_sha256=raw_hash,
                       raw_copy_ignored=True,raw_copy_byte_identical=True)
for name,record in records.items():
    source=HERE / name
    raw=(ROOT / record["raw_copy"]).read_bytes()
    redacted=FIELD.sub(lambda m:m.group(1)+m.group(2)+b" [REDACTED]"+m.group(4),raw)
    old_lines=raw.splitlines(keepends=True); new_lines=redacted.splitlines(keepends=True)
    assert len(old_lines)==len(new_lines)
    changed=[i+1 for i,(old,new) in enumerate(zip(old_lines,new_lines)) if old!=new]
    assert len(changed)==2
    payload=WHOLE_LINE.sub(b"",raw)
    assert payload==WHOLE_LINE.sub(b"",redacted)
    source.write_bytes(redacted)
    record.update(redacted_sha256=hashlib.sha256(redacted).hexdigest(),
                  non_header_payload_sha256=hashlib.sha256(payload).hexdigest(),
                  changed_line_numbers=changed)
    manifest["asset_sha256"][str(source.relative_to(ROOT))]=record["redacted_sha256"]
manifest["log_redaction"]=dict(method="Replace only Serial number/Licensed to field values with [REDACTED]; retain indentation, labels, line endings, every other byte.",
                               originals="Complete raw logs preserved in git-ignored local/ with mode 0600; no deletion or history rewrite.",files=records)
for path in [Path(__file__),ROOT/"tests/test_glm_nb_v1811_reference.py",HERE/"log-redaction-red.txt"]:
    manifest["asset_sha256"][str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
manifest_path.write_text(json.dumps(manifest,indent=2)+"\n")
print("PASS: 4 private raw copies preserved; only 8 license header lines redacted; all non-header bytes identical")
