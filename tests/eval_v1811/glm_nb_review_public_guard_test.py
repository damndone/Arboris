"""Public native reference assets must not contain local license identities."""
from pathlib import Path
import re
import json

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "tests/fixtures/postestimation/glm_negative_binomial_v1811"

def test_public_oracle_assets_exclude_license_serial_and_owner():
    violations = []
    manifest = json.loads((ASSET / "manifest.json").read_text())
    for relative in sorted(manifest["asset_sha256"]):
        path = ROOT / relative
        for line_number,line in enumerate(path.read_text(errors="replace").splitlines(),1):
            # A header kept with the repository's [REDACTED] value carries no identity.
            match=re.match(r"\s*(?:Serial number|Licensed to)\s*:\s*(.*)$",line,re.I)
            if match and match[1].strip()!="[REDACTED]":
                violations.append({"path":str(path.relative_to(ROOT)),"line":line_number,
                                   "field":"license_header","value":"withheld"})
    # Only safe locations are emitted on failure; never include header values.
    assert not violations, violations
