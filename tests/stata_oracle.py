"""Run Stata in batch mode as an oracle for Workbench results.

Stata is the reference many users will check Workbench against, so where an
estimate, a test or a data operation has a Stata equivalent, the oracle tests
compute both and compare. Tests using it skip when Stata is not installed
(set WORKBENCH_STATA to a stata-mp/stata-se binary to point elsewhere).

A do-file writes its results with ``emit`` lines to a tab-separated file;
``run`` returns them as a dict of floats (or strings for ``emit_text``).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

STATA = Path(os.environ.get("WORKBENCH_STATA", "/Applications/Stata/StataMP.app/Contents/MacOS/stata-mp"))
requires_stata = pytest.mark.skipif(not STATA.exists(), reason="Stata is not installed")

_RESULTS = "wb_results.tsv"


def emit(name: str, expression: str) -> str:
    """A numeric result: ``emit("b_mpg", "_b[mpg]")``."""

    return f'file write wbout "{name}" _tab %21.15g ({expression}) _n'


def emit_text(name: str, macro: str) -> str:
    """A text result from an extended macro: ``emit_text("lab", ": variable label price")``."""

    return f'file write wbout "{name}" _tab `"`{macro}\'"\' _n'


def run(workdir: Path, body: str, *, name: str = "oracle") -> dict[str, float | str]:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / _RESULTS).unlink(missing_ok=True)
    do_file = workdir / f"{name}.do"
    do_file.write_text(
        "\n".join(
            [
                "version 18",
                "set more off",
                f'file open wbout using "{_RESULTS}", write replace',
                body,
                "file close wbout",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    subprocess.run([str(STATA), "-b", "do", do_file.name], cwd=workdir, check=True, timeout=300)
    log = (workdir / f"{name}.log").read_text(encoding="utf-8", errors="replace")
    # Only the do-file's own output counts: a user's profile.do can hold
    # GUI-only commands that fail in batch mode before it starts.
    marker = f". do {do_file.name}"
    own = log[log.index(marker):] if marker in log else log
    # Batch Stata exits 0 on an error; the log ends with the return code.
    if re.search(r"(?m)^r\(\d+\);", own):
        raise RuntimeError(f"Stata failed:\n{log[-3000:]}")
    results: dict[str, float | str] = {}
    for line in (workdir / _RESULTS).read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("\t")
        value = value.strip()
        try:
            results[key] = float(value)
        except ValueError:
            results[key] = value
    return results
