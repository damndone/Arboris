"""Bounded numeric summary and immutable-reference/license protection audit."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[4]
OWNED = Path(__file__).resolve().parent
BASELINE = '04d84b6d8f027ff8a45921bd9a5f4aeec28398c5'
sha = lambda data: hashlib.sha256(data).hexdigest()
protected = subprocess.check_output(['git','ls-files','tests/fixtures/postestimation','tests/fixtures/survey_fpc_v1811','tests/fixtures/survey','tests/test_script_export_survey_oracles.py','tests/test_script_export_model_oracles.py','tests/test_script_export_render.py','tests/test_script_export_plan_contract.py'],cwd=REPO,text=True).splitlines()
records = []
for relative in protected:
    original = subprocess.check_output(['git','show',BASELINE+':'+relative],cwd=REPO)
    current = (REPO / relative).read_bytes()
    assert current == original, relative
    records.append(dict(path=relative,baseline_sha256=sha(original),current_sha256=sha(current),unchanged=True))
(OWNED/'protected_assets.json').write_text(json.dumps(records,indent=2)+'\n')
header = re.compile(rb'(?m)^([ \t]*(?:Serial number|Licensed to)[ \t]*:[ \t]*)([^\r\n]*)(\r?\n|$)')
payload = lambda data: header.sub(lambda m: m[1]+m[3],data)
protected_logs=[]
for manifest in OWNED.rglob('log_protection.json'):
    parsed=json.loads(manifest.read_text());items=parsed if isinstance(parsed,list) else [parsed]
    for item in items:
        raw=REPO / item['ignored_raw'];log=manifest.parent / item.get('log','analysis.log')
        assert raw.stat().st_mode & 0o777 == 0o600
        assert subprocess.run(['git','check-ignore','--quiet',str(raw)],cwd=REPO).returncode==0
        raw_data=raw.read_bytes();data=log.read_bytes()
        assert sha(raw_data)==item['raw_sha256'] and sha(data)==item['redacted_sha256']
        assert payload(raw_data)==payload(data)
        assert all(match[2]==b'[REDACTED]' for match in header.finditer(data))
        protected_logs.append(dict(tracked_log=str(log.relative_to(REPO)),**item,payload_sha256=sha(payload(data))))
files=list(OWNED.rglob('*'))+[REPO/'tests/test_script_export_v1811_statistical_adapters.py',*[REPO/'backend/workbench/script_export/exporters'/name for name in ('models.py','survey.py','__init__.py')]]
report=REPO/'docs/superpowers/handoffs/2026-10-04-v1811-script-statistical-adapters-report.md'
if report.exists():files.append(report)
findings=[];scanned=0
for path in files:
    if not path.is_file():continue
    try:text=path.read_bytes().decode('utf-8')
    except UnicodeDecodeError:continue
    scanned+=1
    for match in header.finditer(text.encode()):
        if match[2]!=b'[REDACTED]':findings.append(str(path.relative_to(REPO)))
assert not findings, findings
(OWNED/'asset_protection_manifest.json').write_text(json.dumps(dict(baseline=BASELINE,protected_reference_count=len(records),scanned_new_text_count=scanned,unredacted_header_findings=findings,protected_logs=protected_logs),indent=2)+'\n')
# Select only successful latest focused run directories, retaining all earlier evidence.
transcript=(OWNED/'final_focused_01.txt').read_text()
selected=re.findall(r'Native evidence: (tests/fixtures/script_export/v1811_statistical_adapters/\S+) (stata|r|python)',transcript)
selected = [(p,l) for p,l in selected if "/glm_nb_primitives_" not in p]
selected += re.findall(r'Native evidence: (tests/fixtures/script_export/v1811_statistical_adapters/\S+) (stata|r|python)',(OWNED/'final_primitives_02.txt').read_text())
summary=[]
for relative,language in selected:
    path=REPO/relative;execution=json.loads((path/'execution.json').read_text())
    pairs=json.loads((path/'numeric_pairs.json').read_text())
    if execution['normalized_exit']!=0:continue
    assert all('actual' in item for item in pairs)
    timing=json.loads((path/'timing.json').read_text())
    row=dict(path=relative,language=language,number_count=len(pairs),max_absolute_difference=max((p['difference'] for p in pairs),default=0),max_relative_difference=max((p['difference']/abs(p['expected']) for p in pairs if p['expected']),default=0),all_within_tolerance=all(p['difference']<=p['allowed'] for p in pairs),elapsed_seconds=timing['elapsed_seconds'])
    assert row['all_within_tolerance']
    summary.append(row)
(OWNED/'numeric_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(dict(protected_references=len(records),protected_logs=len(protected_logs),scanned_new_texts=scanned,unredacted_header_findings=len(findings),successful_final_native_runs=len(summary)),indent=2))
