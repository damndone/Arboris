#!/usr/bin/env python3
"""Withhold hashes of license-bearing raw logs from tracked files.

A redacted Stata log differs from its raw original only in the license header
values, so publishing the raw log's SHA-256 lets anyone recover the serial by
trying candidate values against it. This replaces every such hash in tracked
text with a keyed placeholder ``withheld-raw-sha256-<hmac>``; the key and the
placeholder -> real hash map stay in ignored local storage, so the evidence
remains verifiable on this machine.

Hashes withheld: every ignored local file whose license header still carries
a value, and every value a tracked JSON declares under a key containing "raw"
and ending in "sha256". Run it again after adding evidence; it is idempotent.

    .venv/bin/python scripts/withhold_raw_log_hashes.py \\
        --key local/license-raw/withheld-hash-key --map local/license-raw/withheld-hash-map.json
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
from pathlib import Path

HEADER = re.compile(rb"(?m)^[ \t]*(?:Serial number|Licensed to)[ \t]*:[ \t]*([^\r\n]*)")
DECLARED = re.compile(r'"([A-Za-z_]*raw[A-Za-z_]*sha256)"\s*:\s*"([0-9a-f]{64})"')
PREFIX = "withheld-raw-sha256-"


def carries_license_value(data: bytes) -> bool:
    return any(match[1].strip() not in (b"", b"[REDACTED]") for match in HEADER.finditer(data))


def placeholder(key: bytes, digest: str) -> str:
    return PREFIX + hmac.new(key, digest.encode(), hashlib.sha256).hexdigest()[:24]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--scan", type=Path, action="append", default=None, help="ignored roots holding raw logs (default: local)")
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    args = parser.parse_args()
    repo = args.repo.resolve()
    tracked = subprocess.check_output(["git", "-C", str(repo), "ls-files", "-z"]).decode().split("\0")
    tracked = [name for name in tracked if name]

    hashes: dict[str, dict] = {}
    for root in args.scan or [Path("local")]:
        for path in (repo / root).rglob("*"):
            if path.is_file() and not path.is_symlink() and path.stat().st_size < 50_000_000:
                data = path.read_bytes()
                if carries_license_value(data):
                    hashes.setdefault(hashlib.sha256(data).hexdigest(), {"local_raw": [], "declared_as": []})[
                        "local_raw"].append(str(path.relative_to(repo)) if path.is_relative_to(repo) else str(path))
    texts: dict[str, str] = {}
    for name in tracked:
        try:
            texts[name] = (repo / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if name.endswith(".json"):
            for match in DECLARED.finditer(texts[name]):
                hashes.setdefault(match[2], {"local_raw": [], "declared_as": []})["declared_as"].append(f"{name}:{match[1]}")

    args.key.parent.mkdir(parents=True, exist_ok=True)
    if not args.key.exists():
        args.key.write_bytes(os.urandom(32))
    os.chmod(args.key, 0o600)
    key = args.key.read_bytes()
    replacements = {digest: placeholder(key, digest) for digest in hashes}

    changed = []
    for name, text in texts.items():
        updated = text
        for digest, value in replacements.items():
            if digest in updated:
                updated = updated.replace(digest, value)
        if updated != text:
            (repo / name).write_text(updated, encoding="utf-8")
            changed.append(name)

    previous = json.loads(args.map.read_text()) if args.map.exists() else {"withheld": {}}
    for digest, info in hashes.items():
        entry = previous["withheld"].setdefault(replacements[digest], {"sha256": digest, "local_raw": [], "declared_as": []})
        entry["local_raw"] = sorted(set(entry["local_raw"]) | set(info["local_raw"]))
        entry["declared_as"] = sorted(set(entry["declared_as"]) | set(info["declared_as"]))
    previous["note"] = "placeholder -> real SHA-256 of a license-bearing raw log; never commit this file"
    args.map.write_text(json.dumps(previous, indent=2, sort_keys=True) + "\n")
    os.chmod(args.map, 0o600)
    print(json.dumps({"hashes": len(hashes), "files_changed": len(changed)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
