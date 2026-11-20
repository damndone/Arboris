#!/usr/bin/env python3
"""Build every declared production variant (output under local/).

A worktree, a merge or a release needs this once. Some operations have a Python reference;
native-only operations require a verified build. `--check` builds nothing and
reports each named variant whose build is missing, stale, incomplete or damaged.

    .venv/bin/python scripts/build_native.py
    .venv/bin/python scripts/build_native.py --check
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from workbench.native_build import NativeBuildError, default_output, variants, verify_build


def modules() -> list[Path]:
    return sorted(path.parent for path in (ROOT / "native").glob("*/build.py"))


def output_directory(module: Path) -> Path | None:
    """Use the same output declaration as the module's builder."""
    return default_output(module)


def status(module: Path, *, variant: str = "row-exact") -> str:
    out = output_directory(module)
    if out is None or not out.is_dir() or not any(out.iterdir()):
        return "missing"
    try:
        verify_build(module, out, check_toolchain=True, variant=variant)
    except (NativeBuildError, OSError) as error:
        return f"invalid: {error}"
    return "current"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    failures = 0
    for module in modules():
        declared = variants(module)
        for variant in declared:
            label = f"{module.name}:{variant}"
            if args.check:
                state = status(module, variant=variant)
                failures += state != "current"
                print(f"{label:36s} {state}")
                continue
            started = time.monotonic()
            command = [sys.executable, str(module / "build.py")]
            if len(declared) > 1:
                command += ["--engine", variant]
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            state = status(module, variant=variant) if result.returncode == 0 else "build command failed"
            outcome = "built and verified" if state == "current" else "FAILED"
            failures += state != "current"
            print(f"{label:36s} {outcome} in {time.monotonic() - started:.1f} s", flush=True)
            if result.returncode:
                print(result.stderr[-1500:], file=sys.stderr)
            elif state != "current":
                print(state, file=sys.stderr)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
