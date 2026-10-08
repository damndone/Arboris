"""Subprocesses started by tests import this checkout's backend.

The shared virtualenv carries an editable install of whichever worktree last
ran `pip install -e`. Until v1.8.12 it pointed at the v1.8.6 worktree, so a
test that launched a CLI or script in a subprocess without its own PYTHONPATH
exercised v1.8.6 code; once that worktree was archived, those subprocesses
could not import `workbench` at all. tests/conftest.py now puts this
checkout's backend first on PYTHONPATH for every subprocess.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"


def test_a_subprocess_imports_workbench_from_this_checkout() -> None:
    found = subprocess.run(
        [sys.executable, "-c", "import workbench; print(workbench.__file__)"],
        cwd="/", env=dict(os.environ), capture_output=True, text=True,
    )
    assert found.returncode == 0, found.stderr
    assert Path(found.stdout.strip()).resolve().is_relative_to(BACKEND.resolve()), found.stdout
