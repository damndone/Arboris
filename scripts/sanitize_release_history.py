#!/usr/bin/env python3
"""Copy a release's unpushed history under new refs with license values redacted.

Stata batch logs open with a license header ("Serial number:", "Licensed
to:"). When such a log was committed before it was redacted, the value stays
in history even after the tracked file is fixed; so does any SHA-256 of the
raw log (it lets the value be recovered by trial), which ``--withheld``
replaces with the placeholders scripts/withhold_raw_log_hashes.py used. This copies the named refs
through ``git fast-export`` / ``git fast-import``, replacing those header
values (and any listed literal) with ``[REDACTED]`` in every blob and commit
message, under ``refs/heads/<prefix>/<original name>``. The original refs are
not touched. Commits whose content does not change keep their ids, so pushed
ancestors are shared. A JSON map of original -> rewritten commit ids is
written for tracing ids recorded in documents and devline events.

    PYTHONPATH=backend .venv/bin/python scripts/sanitize_release_history.py \\
        --repo /path/to/repo --exclude refs/remotes/origin/main \\
        --prefix v1811-sanitized --literal <value> --map out.json REF...

Uses only git; no git-filter-repo.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HEADER = re.compile(rb"(?m)^([ \t]*(?:Serial number|Licensed to)[ \t]*:[ \t]*)([^\r\n]*)")
REDACTED = b"[REDACTED]"


def redact(data: bytes, literals: list[bytes], replacements: dict[bytes, bytes] | None = None) -> bytes:
    data = HEADER.sub(lambda m: m[1] + (m[2] if m[2].strip() in (b"", REDACTED) else REDACTED), data)
    for literal in literals:
        data = data.replace(literal, REDACTED)
    for old, new in (replacements or {}).items():
        data = data.replace(old, new)
    return data


def rewrite(stream, out, prefix: bytes, literals: list[bytes], replacements: dict[bytes, bytes] | None = None) -> int:
    """Rewrite a fast-export stream; returns how many data blocks changed."""
    changed = 0
    ref = re.compile(rb"^(commit|reset) refs/heads/(.+)$")
    while True:
        line = stream.readline()
        if not line:
            return changed
        match = ref.match(line.rstrip(b"\n"))
        if match:
            out.write(match[1] + b" refs/heads/" + prefix + b"/" + match[2] + b"\n")
            continue
        if line.startswith(b"data "):
            size = int(line[5:].strip())
            payload = stream.read(size)
            cleaned = redact(payload, literals, replacements)
            changed += cleaned != payload
            out.write(b"data %d\n" % len(cleaned))
            out.write(cleaned)
            continue
        out.write(line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--exclude", action="append", default=[], help="already pushed ref; its history is kept as is")
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--literal", action="append", default=[], help="extra literal value to redact anywhere")
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--withheld", type=Path, default=None,
                        help="withhold_raw_log_hashes.py map: raw-log hashes become the same placeholders as at the tip")
    parser.add_argument("refs", nargs="+")
    args = parser.parse_args()
    git = ["git", "-C", str(args.repo)]
    literals = [value.encode() for value in args.literal]
    replacements = {}
    if args.withheld:
        withheld = json.loads(args.withheld.read_text())["withheld"]
        replacements = {entry["sha256"].encode(): placeholder.encode() for placeholder, entry in withheld.items()}
    with tempfile.TemporaryDirectory() as scratch:
        before, after = Path(scratch) / "export.marks", Path(scratch) / "import.marks"
        export = subprocess.Popen(
            [*git, "fast-export", "--signed-tags=strip", "--tag-of-filtered-object=drop", "--reencode=yes",
             "--reference-excluded-parents", f"--export-marks={before}", *args.refs,
             *(f"^{ref}" for ref in args.exclude)],
            stdout=subprocess.PIPE)
        load = subprocess.Popen([*git, "fast-import", "--quiet", f"--export-marks={after}"], stdin=subprocess.PIPE)
        changed = rewrite(export.stdout, load.stdin, args.prefix.encode(), literals, replacements)
        load.stdin.close()
        if export.wait() or load.wait():
            print("fast-export/fast-import failed", file=sys.stderr)
            return 1
        old = dict(line.split() for line in before.read_text().splitlines())
        new = dict(line.split() for line in after.read_text().splitlines())
    kinds = subprocess.run([*git, "cat-file", "--batch-check=%(objectname) %(objecttype)"],
                           input="\n".join(old.values()), capture_output=True, text=True, check=True).stdout
    commits = {line.split()[0] for line in kinds.splitlines() if line.endswith(" commit")}
    mapping = {old[mark]: new[mark] for mark in old if old[mark] in commits and mark in new}
    args.map.write_text(json.dumps({
        "prefix": args.prefix, "refs": args.refs, "excluded": args.exclude,
        "data_blocks_changed": changed, "commits": len(mapping),
        "unchanged_ids": sum(1 for a, b in mapping.items() if a == b),
        "original_to_sanitized": mapping}, indent=2) + "\n")
    print(json.dumps({"commits": len(mapping), "data_blocks_changed": changed,
                      "unchanged_ids": sum(1 for a, b in mapping.items() if a == b)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
