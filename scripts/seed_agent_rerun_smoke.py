#!/usr/bin/env python3
"""Create a local-only pending Agent-confirmed model.rerun fixture."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from workbench.dev_fixtures.agent_navigation import seed_agent_rerun_smoke_fixture


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--input-file", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    root = args.project_root.expanduser().resolve()
    scratch_roots = {
        Path(tempfile.gettempdir()).resolve(),
        Path("/private/tmp").resolve(),
    }
    if not any(root == candidate or candidate in root.parents for candidate in scratch_roots):
        allowed = ", ".join(str(candidate) for candidate in sorted(scratch_roots))
        raise SystemExit(f"refusing non-scratch project root outside {allowed}: {root}")
    fixture = seed_agent_rerun_smoke_fixture(
        root,
        input_file=args.input_file,
        timeout_s=args.timeout,
    )
    print(json.dumps(fixture.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
