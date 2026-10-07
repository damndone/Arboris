"""Record independent focused runs under the integration resource lock."""
from pathlib import Path
import subprocess
import sys
import uuid

root = Path(__file__).resolve().parents[2]
output = Path(__file__).with_name('s_review_evidence') / ('pytest-' + uuid.uuid4().hex[:8] + '.txt')
command = [sys.executable,
    '/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py',
    sys.executable, '-m', 'pytest', *sys.argv[1:]]
output.parent.mkdir(parents=True, exist_ok=True)
print(f'Independent pytest log: {output}', flush=True)
completed = subprocess.run(command, cwd=root, capture_output=True, text=True)
output.write_text(completed.stdout + completed.stderr)
public = '\n'.join(line for line in (completed.stdout + completed.stderr).splitlines()
                   if 'Serial number:' not in line and 'Licensed to:' not in line)
output.with_suffix('.public.txt').write_text(public + '\n')
print(completed.stdout[-7000:] + completed.stderr)
raise SystemExit(completed.returncode)
