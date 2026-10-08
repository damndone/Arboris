#!/usr/bin/env python3
"""Install Workbench into the shared virtualenv, pointing at the main checkout.

Every checkout (the main one and each `.worktrees/*` development worktree)
shares one virtualenv. Its editable install names the main checkout, which is
never archived, so `workbench` and `uvicorn workbench.api:app` run the
released code from anywhere; the checkout hook
(scripts/dev_env/workbench_checkout_hook.py) makes a process started inside a
worktree, or by one, import that worktree instead. Run from the main
checkout after a release is merged:

    .venv/bin/python scripts/install_dev_env.py

It replaces only Workbench's own editable install (no dependencies are
changed), copies the hook into site-packages, then runs scripts/check_dev_env.py.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_dev_env import (  # noqa: E402
    CHECKOUT,
    HOOK_MODULE,
    HOOK_PTH,
    HOOK_PTH_TEXT,
    HOOK_SOURCE,
    main_checkout,
    site_packages,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    main = main_checkout()
    if CHECKOUT != main:
        print(f"run this from the main checkout {main}, not {CHECKOUT}: the install must name the main checkout",
              file=sys.stderr)
        return 2
    if not (main / "backend" / "workbench" / "__init__.py").is_file():
        print(f"{main} has no backend/workbench package", file=sys.stderr)
        return 2
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--editable", str(main)],
        check=True,
    )
    site = site_packages()
    shutil.copyfile(HOOK_SOURCE, site / HOOK_MODULE)
    (site / HOOK_PTH).write_text(HOOK_PTH_TEXT, encoding="utf-8")
    print(f"checkout hook installed in {site}")
    return subprocess.run([sys.executable, str(CHECKOUT / "scripts" / "check_dev_env.py")]).returncode


if __name__ == "__main__":
    sys.exit(main())
