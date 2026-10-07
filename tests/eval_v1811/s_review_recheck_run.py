"""Retain new review command output and serialize heavy execution."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

root = Path(__file__).resolve().parents[2]
target = Path(__file__).with_name('s_review_recheck_evidence')
target.mkdir(exist_ok=True)
command = [sys.executable, str(root.parent/'workbench-v1.8.11/local/v1811-coordination/run_exclusive.py'),
           sys.executable, '-m', 'pytest', '-q', '-s', *sys.argv[1:], '--tb=short']
run = subprocess.run(command, cwd=root, capture_output=True, text=True)
name = 'pytest-' + uuid.uuid4().hex[:8]
path = target/(name+'.txt')
path.write_text(run.stdout+run.stderr)
(target/(name+'.json')).write_text(json.dumps({'command':command,'exit':run.returncode,'output':str(path.relative_to(root))},indent=2))
print(str(path.relative_to(root)))
print('\n'.join((run.stdout+run.stderr).splitlines()[-35:]))
sys.exit(run.returncode)
