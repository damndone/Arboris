"""Run unchanged related tests with retained output redirected to owned assets."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / 'tests'))
sys.path.insert(0, str(REPO / 'backend'))
import pytest
import test_script_export_data_oracles as native

output = Path(__file__).resolve().parent / ('related_' + uuid4().hex[:10])
output.mkdir()
native.ROOT = output
print('Related retained evidence:', output.relative_to(REPO))
try:
    code = pytest.main(sys.argv[1:])
finally:
    records = []
    header = re.compile(rb'(?m)^([ \t]*(?:Serial number|Licensed to)[ \t]*:[ \t]*)([^\r\n]*)(\r?\n|$)')
    for log in output.rglob('*.log'):
        raw = log.read_bytes()
        local = REPO / 'local/v1811-script-statistical-adapters' / output.name / log.relative_to(output)
        local.parent.mkdir(parents=True, exist_ok=True)
        assert not local.exists()
        local.write_bytes(raw); local.chmod(0o600)
        assert subprocess.run(['git', 'check-ignore', '--quiet', str(local)], cwd=REPO).returncode == 0
        sanitized = header.sub(lambda m: m[1]+b'[REDACTED]'+m[3], raw)
        payload = lambda text: header.sub(lambda m: m[1]+m[3], text)
        assert payload(raw) == payload(sanitized)
        log.write_bytes(sanitized)
        records.append(dict(log=str(log.relative_to(output)), ignored_raw=str(local.relative_to(REPO)),
                            raw_sha256=hashlib.sha256(raw).hexdigest(), redacted_sha256=hashlib.sha256(sanitized).hexdigest(),
                            outside_header_values_byte_identical=True, raw_mode='0600'))
    (output / 'log_protection.json').write_text(json.dumps(records, indent=2)+'\n')
sys.exit(code)
