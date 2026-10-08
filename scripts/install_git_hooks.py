#!/usr/bin/env python3
"""Install the versioned Workbench git hooks into this checkout.

Writes only <common git dir>/hooks/pre-push (shared by every worktree), as a
byte-for-byte copy of scripts/git_hooks/pre-push. An existing hook with other
content is left alone unless --force is given, so a hand-made hook is never
replaced silently. Run it on every new machine or clone:

    python3 scripts/install_git_hooks.py
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "git_hooks" / "pre-push"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="replace an existing pre-push hook that differs")
    args = parser.parse_args(argv)
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True, check=True
    ).stdout.strip()
    hooks = Path(common).resolve() / "hooks"
    target = hooks / "pre-push"
    source = SOURCE.read_bytes()
    if target.exists() and target.read_bytes() == source:
        print(f"pre-push guard already installed at {target}")
        return 0
    if target.exists() and not args.force:
        print(f"{target} exists with other content; not replaced (use --force)", file=sys.stderr)
        return 1
    hooks.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(".pre-push.installing")
    temporary.write_bytes(source)
    os.chmod(temporary, 0o755)
    os.replace(temporary, target)
    print(f"pre-push guard installed at {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
