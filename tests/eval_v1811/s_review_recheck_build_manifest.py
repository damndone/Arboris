"""Freeze new evidence while verifying old assets and producer scope unchanged."""
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

root = Path(__file__).resolve().parents[2]
start = json.loads((Path(__file__).with_name('s_review_recheck_start.json')).read_text())
old = json.loads((Path(__file__).with_name('s_review_manifest.json')).read_text())
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip() == start['candidate']
for path, expected in old['artifacts'].items():
    assert sha(root/path) == expected, path
for path, expected in start['production_hashes'].items():
    assert sha(root/path) == expected, path
for record in start['locked_files']:
    assert sha(root/record['path']) == record['sha256'], record['path']
directory = Path(__file__).with_name('s_review_recheck_evidence')
commands = [json.loads(p.read_text()) for p in sorted(directory.glob('pytest-*.json'))]
executions = []
for path in sorted(directory.rglob('execution.json')):
    record = json.loads(path.read_text())
    record['directory'] = str(path.parent.relative_to(root))
    executions.append(record)
paths = list(directory.rglob('*')) + list(Path(__file__).parent.glob('s_review_recheck_*.py'))
paths += [Path(__file__).with_name('s_review_recheck_start.json'), Path(__file__).with_name('s_review_recheck_local_only.json'), root/'docs/superpowers/handoffs/2026-10-04-v1.8.11-s-independent-recheck.md']
artifacts = {str(p.relative_to(root)):sha(p) for p in sorted(paths) if p.is_file()}
manifest = {**start, 'generated_at':datetime.now(timezone.utc).isoformat(),
    'decision':'PASS_FOR_CURRENT_CANDIDATE; COMPLETE_C3_NOT_READY',
    'original_cases':{'passed':33,'failed':3,'failures':'Explicit full-FPC NOT_FULLY_NATIVE; no skips/xfail'},
    'new_cases':{'passed':48,'failed':0,'seconds':24.20},
    'first_run':'6 failed, 63 passed; three FPC and three reviewer invalid newline assumptions; preserved',
    'commands':commands,'executions':executions,'artifacts':artifacts,
    'raw_log_policy':'Raw .log and original output.txt retained locally; public_output.txt omits pre-do license identity',
    'local_only_artifacts':json.loads(Path(__file__).with_name('s_review_recheck_local_only.json').read_text()),
    'limits':['FPC pending Integration','GLM-NB admission pending Integration/M2','No full315/browser/provider/gate',
              'Builder provenance/authorization is Root-owned; S consumer reviewed with exact supplied SHA']}
Path(__file__).with_name('s_review_recheck_manifest.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'old_assets_verified':len(old['artifacts']),'new_assets':len(artifacts),'executions':len(executions),'decision':manifest['decision']}))
