"""Freeze independent evidence; never modify any author asset."""
import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
AREA = Path(__file__).with_name('s_review_evidence')
CANDIDATE = '2df49e516077b77eed37a9d7c3cb12212f157ab2'
BASE = '6f0f87c6d8241a93d81e2c34f8ef8e9408a907b3'
INTEGRATION = ROOT.parent / 'workbench-v1.8.11'


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def save_once(path, value):
    blob = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode() + b'\n'
    if path.exists():
        assert path.read_bytes() == blob, f'Immutable evidence differs: {path}'
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    for log in AREA.glob('pytest-*.txt'):
        if log.name.endswith('.public.txt'):
            continue
        public = '\n'.join(line for line in log.read_text().splitlines()
                           if 'Serial number:' not in line and 'Licensed to:' not in line) + '\n'
        target = log.with_suffix('.public.txt')
        if not target.exists():
            target.write_text(public)
    for output in AREA.glob('*/output.txt'):
        target = output.with_name('public_output.txt')
        if target.exists():
            continue
        value = output.read_text()
        if '. do analysis.do' in value:
            value = value[value.index('. do analysis.do'):]
        target.write_text(value)

    latest = {}
    for plan_file in AREA.glob('*/plan.json'):
        folder = plan_file.parent
        plan = json.loads(plan_file.read_text())
        language = next((lang for lang in ('stata', 'r', 'python') if f'-{lang}-' in folder.name), None)
        if language:
            key = (plan['run_id'], language)
            if key not in latest or plan_file.stat().st_mtime > (latest[key]/'plan.json').stat().st_mtime:
                latest[key] = folder
    numeric_records = []
    executions = []
    for (case, language), folder in sorted(latest.items()):
        record = {'case': case, 'language': language, 'directory': str(folder.relative_to(ROOT))}
        execution = folder/'execution.json'
        if execution.exists():
            record.update(json.loads(execution.read_text()))
        else:
            record['refusal'] = json.loads((folder/'refusal.json').read_text())
        executions.append(record)
        values_file = folder/'numeric_actual.tsv'
        if not values_file.exists():
            continue
        values = [None if value.strip()=='.' else float(value) for value in values_file.read_text().splitlines()]
        script_file = folder/({'stata':'analysis.do','r':'analysis.R','python':'analysis.py'}[language])
        text = script_file.read_text()
        if language == 'stata':
            expected = re.findall(r'(?m)^assert !missing\(wb_number_\d+\) & abs\(wb_number_\d+-\(([-+0-9.eE]+)\)\) <= ([-+0-9.eE]+)\+([-+0-9.eE]+)\*', text)
        else:
            expected = re.findall(r'(?m)^wb_check\(checks\[\[?\d+\]?\], ([-+0-9.eE]+), ([-+0-9.eE]+), ([-+0-9.eE]+),', text)
        assert len(values)==len(expected), (folder, len(values), len(expected))
        pairs=[]
        for actual, (wanted, absolute, relative) in zip(values,expected):
            wanted, absolute, relative=map(float,(wanted,absolute,relative))
            nonfinite = actual is not None and not math.isfinite(actual)
            pairs.append({'expected': wanted, 'actual': None if nonfinite else actual, 'non_finite': nonfinite,
                          'abs_tolerance': absolute, 'rel_tolerance': relative,
                          'delta': abs(actual-wanted) if actual is not None and not nonfinite else None,
                          'allowed': absolute+relative*abs(wanted)})
        numeric_records.append({**record, 'pairs':pairs})
    save_once(AREA/'numeric_pairs.json',numeric_records)
    save_once(AREA/'latest_executions.json',executions)

    lock_path=INTEGRATION/'docs/superpowers/release-trains/v1.8.11/contract-lock-manifest.json'
    lock=json.loads(lock_path.read_text())
    frozen=[]
    for entry in lock['locked_files']:
        current=(ROOT/entry['path']).read_bytes()
        baseline=git('show', BASE+':'+entry['path'])
        assert digest(current)==digest(baseline)==entry['sha256'], entry
        frozen.append(entry)
    changes=git('diff','--name-status',BASE,CANDIDATE).decode().splitlines()
    author_files={line.split('\t')[-1]:digest((ROOT/line.split('\t')[-1]).read_bytes()) for line in changes}
    allowed=lambda path: (path.startswith('backend/workbench/script_export/') and path not in {'backend/workbench/script_export/plan.py','backend/workbench/script_export/__init__.py'}) or path.startswith('tests/fixtures/script_export/') or (path.startswith('tests/test_script_export_') and path!='tests/test_script_export_plan_contract.py') or path=='docs/superpowers/handoffs/2026-10-04-codex-v1811-s-report.md'
    assert all(allowed(path) for path in author_files)
    for path,value in author_files.items():
        assert digest(git('show',CANDIDATE+':'+path))==value, path
    runner='backend/workbench/econometrics/runner.py'
    runner_ast={commit:digest(ast.dump(ast.parse(git('show',commit+':'+runner).decode()),include_attributes=False).encode()) for commit in (BASE,CANDIDATE)}
    assert len(set(runner_ast.values()))==1
    if '--evidence-only' in sys.argv:return
    artifacts={}
    for path in Path(__file__).parent.glob('s_review_*'):
        paths=path.rglob('*') if path.is_dir() else (path,)
        for item in paths:
            if not item.is_file() or item.name=='s_review_manifest.json' or item.suffix=='.log' or item.name=='output.txt' or (item.name.startswith('pytest-') and not item.name.endswith('.public.txt')):
                continue
            artifacts[str(item.relative_to(ROOT))]=digest(item.read_bytes())
    report=ROOT/'docs/superpowers/handoffs/2026-10-04-v1.8.11-s-independent-review.md'
    if report.exists():artifacts[str(report.relative_to(ROOT))]=digest(report.read_bytes())
    manifest={'evaluation_id':'v1811-s-independent-001', 'evaluated_commit':CANDIDATE,
              'production_code_commit':'8f925ed6451ec7888d1c866dfdc42b77afb0729d',
              'contract_lock_commit':BASE, 'evaluation_harness_commit':git('rev-parse','HEAD').decode().strip(),
              'generated_at':datetime.now(timezone.utc).isoformat(), 'decision':'REQUEST_CHANGES',
              'environment':{'python':platform.python_version(),'platform':platform.system(),
                'packages':{name:importlib.metadata.version(name) for name in ('numpy','pandas','scipy','statsmodels','linearmodels')}},
              'commands':[
                {'files':'s_review_test_adversarial.py s_review_test_required_coverage.py','failed':16,'passed':20,'seconds':14.91,'exit':1,'output':'tests/eval_v1811/s_review_evidence/pytest-ea2ac672.public.txt'},
                {'files':'tests/test_script_export_plan_contract.py + all seven S oracle/render/integrity files','failed':21,'passed':292,'seconds':140.79,'exit':1,'output':'tests/eval_v1811/s_review_evidence/pytest-22c1b633.public.txt'}],
              'locked_files':frozen,'integration_lock_manifest_sha256':digest(lock_path.read_bytes()),
              'producer_owned_files_at_review':author_files,'runner_ast_hashes':runner_ast,
              'independent_executions':executions,'artifacts':artifacts,
              'limits':['No integration overlay executed by this reviewer','No browser/full gate/provider/Downloads test','Original raw logs retained locally; public copies omit license identity only', 'Generated scripts and captured logs preserve original trailing whitespace; full evidence diff-check reports it. Review source/report diff-check is separately clean.']}
    destination=Path(__file__).with_name('s_review_manifest.json')
    if destination.exists():raise RuntimeError('Manifest is immutable; use a new evaluation ID')
    destination.write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(destination)


if __name__=='__main__':main()
