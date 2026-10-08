"""Bounded retention for evidence that tests keep in the ignored local/ tree.

A test that keeps evidence asks for ``run_dir(category)`` and writes under
``local/test-evidence/<category>/<run>``, one run directory per pytest session.
At the end of the session (tests/conftest.py) every category the session used
keeps its ``KEEP`` newest runs. A run is never removed when it is marked:

* ``.failed`` -- a test that wrote into it failed (attributed per test);
* ``.keep``   -- the session ran with ``WORKBENCH_KEEP_EVIDENCE=1``.

Only directories whose names are run stamps, directly inside a category of
``local/test-evidence``, are ever removed; symlinks, other names and anything
outside that root are left alone. This is the one bounded exception to the
user's rule that nothing is deleted automatically (2026-10-07, "keep the last
3 of each kind, always keep the failed one"), mirroring pytest's
``tmp_path_retention_count = 3``.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
KEEP = 3
_RUN_NAME = re.compile(r"^\d{8}T\d{6}-\d+$")


def _stamp() -> str:
    return f"{datetime.now():%Y%m%dT%H%M%S}-{os.getpid()}"


def _current_test() -> str | None:
    value = os.environ.get("PYTEST_CURRENT_TEST")
    return value.rsplit(" (", 1)[0] if value else None


class EvidenceStore:
    def __init__(self, root: Path, *, stamp: str | None = None) -> None:
        self.root = Path(root)
        self.stamp = stamp or _stamp()
        self._writers: dict[str, set[str]] = {}

    def run_dir(self, category: str) -> Path:
        """This session's evidence directory for a category, created on first use."""

        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", category):
            raise ValueError(f"invalid evidence category {category!r}")
        path = self.root / category / self.stamp
        if not path.is_dir():
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
            path.chmod(0o700)
            if os.environ.get("WORKBENCH_KEEP_EVIDENCE") == "1":
                (path / ".keep").write_text("WORKBENCH_KEEP_EVIDENCE=1\n")
        test = _current_test()
        writers = self._writers.setdefault(category, set())
        if test:
            writers.add(test)
        return path

    def mark_failed(self, category: str, test: str) -> None:
        path = self.root / category / self.stamp
        if path.is_dir():
            with (path / ".failed").open("a", encoding="utf-8") as handle:
                handle.write(test + "\n")

    def test_failed(self, test: str) -> None:
        """Mark every category this test wrote evidence into."""

        for category, writers in self._writers.items():
            if test in writers:
                self.mark_failed(category, test)

    def prune(self, keep: int = KEEP) -> list[Path]:
        removed: list[Path] = []
        for category in sorted(self._writers):
            directory = self.root / category
            if directory.is_symlink() or not directory.is_dir():
                continue
            runs = sorted(
                path
                for path in directory.iterdir()
                if _RUN_NAME.fullmatch(path.name) and path.is_dir() and not path.is_symlink()
            )
            for path in runs[:-keep] if keep else runs:
                if (path / ".failed").exists() or (path / ".keep").exists():
                    continue
                shutil.rmtree(path)
                removed.append(path)
        return removed


STORE = EvidenceStore(REPO / "local" / "test-evidence")


def run_dir(category: str) -> Path:
    return STORE.run_dir(category)
