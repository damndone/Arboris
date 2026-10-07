"""Verify frozen assets and retained native log protection without rewriting them."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

REPO = Path(__file__).resolve().parents[4]
OWNED = Path(__file__).resolve().parent
FROZEN = "678d9cc46d155a50aed47b210e2e6a6e82a12882"
sha = lambda data: hashlib.sha256(data).hexdigest()
paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", FROZEN,
    "tests/fixtures/script_export/v1811_statistical_adapters", "tests/fixtures/postestimation",
    "tests/fixtures/survey_fpc_v1811", "tests/fixtures/survey"], cwd=REPO, text=True).splitlines()
records = []
for relative in paths:
    original = subprocess.check_output(["git", "show", FROZEN+":"+relative], cwd=REPO)
    current = (REPO / relative).read_bytes()
    assert current == original, relative
    records.append({"path": relative, "sha256": sha(current), "unchanged": True})
header = re.compile(rb"(?m)^([ \t]*(?:Serial number|Licensed to)[ \t]*:[ \t]*)([^\r\n]*)(\r?\n|$)")
payload = lambda raw: header.sub(lambda match: match[1]+match[3], raw)
logs = []
for manifest in OWNED.rglob("*protection.json"):
    parsed = json.loads(manifest.read_text())
    for item in parsed if isinstance(parsed, list) else [parsed]:
        if "ignored_raw" not in item:
            continue
        raw = REPO / item["ignored_raw"]
        public = manifest.parent / item.get("log", "analysis.log")
        assert raw.stat().st_mode & 0o777 == 0o600
        assert subprocess.run(["git", "check-ignore", "--quiet", str(raw)], cwd=REPO).returncode == 0
        original, redacted = raw.read_bytes(), public.read_bytes()
        assert sha(original) == item["raw_sha256"] and sha(redacted) == item["redacted_sha256"]
        assert payload(original) == payload(redacted)
        assert all(match[2] == b"[REDACTED]" for match in header.finditer(redacted))
        logs.append({"public": str(public.relative_to(REPO)), **item})
scanned = 0
for path in [*OWNED.rglob("*"), REPO / "tests/test_script_export_v1811_statistical_adapters.py",
             REPO / "backend/workbench/script_export/exporters/models.py",
             REPO / "docs/superpowers/handoffs/2026-10-04-v1811-script-statistical-adapters-report.md"]:
    if not path.is_file():
        continue
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        continue
    scanned += 1
    assert all(match[2] == b"[REDACTED]" for match in header.finditer(raw)), str(path.relative_to(REPO))
summary = {"frozen_commit": FROZEN, "frozen_assets_unchanged": len(records),
           "protected_native_logs": len(logs), "scanned_texts": scanned,
           "unredacted_header_findings": 0, "assets": records, "logs": logs}
target = OWNED / "convergence_asset_protection_manifest.json"
assert not target.exists()
target.write_text(json.dumps(summary, indent=2)+"\n")
print(json.dumps({key: value for key, value in summary.items() if key not in {"assets", "logs"}}, indent=2))
