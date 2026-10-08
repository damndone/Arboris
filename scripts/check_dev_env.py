#!/usr/bin/env python3
"""Check the shared virtualenv's Workbench install (a gate stage).

The virtualenv every checkout shares carries one editable install of
Workbench. It must name the main checkout (archived worktrees disappear; a
worktree must not be imported by other checkouts), the checkout hook must be
the one in this repository, and the ``workbench`` command must start. Each
check is printed; any failure exits 1 with the fix.

    .venv/bin/python scripts/check_dev_env.py

Fix: from the main checkout, ``.venv/bin/python scripts/install_dev_env.py``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

CHECKOUT = Path(__file__).resolve().parents[1]
HOOK_SOURCE = CHECKOUT / "scripts" / "dev_env" / "workbench_checkout_hook.py"
HOOK_MODULE = "_workbench_checkout.py"
HOOK_PTH = "zz_workbench_checkout.pth"
HOOK_PTH_TEXT = "import _workbench_checkout\n"
DISTRIBUTION = "local_econometrics_workbench"
ENV = "WORKBENCH_CHECKOUT_BACKEND"
#: The command must be usable; generous beside the 0.5 s import budget, as it
#: includes interpreter start-up and Typer's help rendering.
COMMAND_START_BUDGET_S = 3.0
FIX = "fix: from the main checkout run `.venv/bin/python scripts/install_dev_env.py`"


def main_checkout(start: Path = CHECKOUT) -> Path:
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=start, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(common).resolve().parent


def site_packages() -> Path:
    return Path(sysconfig.get_paths()["purelib"])


def editable_target(site: Path) -> Path | None:
    for info in sorted(site.glob(f"{DISTRIBUTION}-*.dist-info")):
        record = info / "direct_url.json"
        if record.is_file():
            data = json.loads(record.read_text(encoding="utf-8"))
            if data.get("dir_info", {}).get("editable"):
                return Path(unquote(urlparse(data["url"]).path))
    return None


def editable_paths(site: Path) -> list[Path]:
    paths: list[Path] = []
    for pth in sorted(site.glob(f"__editable__.{DISTRIBUTION}-*.pth")):
        for line in pth.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("import "):
                paths.append(Path(line.strip()))
    return paths


def _clean_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", ENV}}


def imported_backend(cwd: Path, extra: dict[str, str] | None = None) -> Path | None:
    env = _clean_env()
    env.update(extra or {})
    result = subprocess.run(
        [sys.executable, "-c", "import workbench, pathlib; print(pathlib.Path(workbench.__file__).resolve().parents[1])"],
        cwd=cwd, env=env, capture_output=True, text=True,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def run_checks() -> list[tuple[bool, str]]:
    results: list[tuple[bool, str]] = []

    def check(ok: bool, message: str) -> bool:
        results.append((bool(ok), message))
        return bool(ok)

    main = main_checkout()
    main_backend = (main / "backend").resolve()
    here_backend = (CHECKOUT / "backend").resolve()
    site = site_packages()

    target = editable_target(site)
    check(target is not None and target.resolve() == main,
          f"editable install names the main checkout {main} (found {target})")
    paths = editable_paths(site)
    check(bool(paths) and all(path.resolve() == main_backend and path.is_dir() for path in paths),
          f"editable import path is {main_backend} and exists (found {[str(p) for p in paths]})")

    installed = site / HOOK_MODULE
    check(installed.is_file() and installed.read_bytes() == HOOK_SOURCE.read_bytes(),
          f"checkout hook {installed} matches {HOOK_SOURCE.relative_to(CHECKOUT)}")
    pth = site / HOOK_PTH
    check(pth.is_file() and pth.read_text(encoding="utf-8") == HOOK_PTH_TEXT, f"{pth} loads the hook")

    with tempfile.TemporaryDirectory() as scratch:
        outside = Path(scratch).resolve()
        found = imported_backend(outside)
        check(found == main_backend, f"outside any checkout, `import workbench` loads {main_backend} (got {found})")
        found = imported_backend(CHECKOUT)
        check(found == here_backend, f"inside this checkout, `import workbench` loads {here_backend} (got {found})")
        found = imported_backend(outside, {ENV: str(here_backend)})
        check(found == here_backend,
              f"a child process started outside keeps its parent's checkout {here_backend} (got {found})")

        command = Path(sys.executable).parent / "workbench"
        if check(command.is_file(), f"`workbench` command exists at {command}"):
            started = time.perf_counter()
            result = subprocess.run([str(command), "--help"], cwd=outside, env=_clean_env(), capture_output=True, text=True)
            elapsed = time.perf_counter() - started
            started_ok = check(
                result.returncode == 0 and "Usage" in result.stdout,
                f"`workbench --help` starts outside any checkout (exit {result.returncode}"
                + (f": {result.stderr.strip().splitlines()[-1]}" if result.returncode and result.stderr.strip() else "")
                + ")",
            )
            if started_ok:
                check(elapsed < COMMAND_START_BUDGET_S,
                      f"`workbench --help` took {elapsed:.2f} s (budget {COMMAND_START_BUDGET_S} s)")
    return results


def main() -> int:
    results = run_checks()
    for ok, message in results:
        print(("ok    " if ok else "FAIL  ") + message)
    if all(ok for ok, _ in results):
        print("shared virtualenv install is correct")
        return 0
    print(FIX, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
