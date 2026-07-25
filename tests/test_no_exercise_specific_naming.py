"""Product code must not name one exercise, dataset, or course assignment.

The multi-step workflow was first built to answer a single course exercise, and
that exercise leaked into the server: a "Class 3" preset whose bindings were its
variables, a diagnostics gate keyed to its column names, a fixed set of its
survey years, and — worst — a report line telling every future user that "the
Class 3 workflow did not complete".

Each of those passed its tests. They were wrong in a way tests of the exercise
itself could never catch, because the exercise was the thing being encoded. This
guard is the check that does catch it: generic code may not mention a specific
assignment's identifiers at all.

If this test fails, the fix is to derive the value from the request, the data, or
a declared contract — not to add the new name to the allowlist below.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

# Directories holding generic product code. Tests and fixtures may legitimately
# use a real dataset; the server may not.
SCANNED_ROOTS = (
    ("backend/workbench", (".py",)),
    ("frontend/src", (".ts", ".tsx")),
)

# A line ending in this marker is an intentional, documented read of a value
# that older persisted records still carry. It is not permission to write one.
LEGACY_COMPAT_MARKER = "# legacy-compat"

# Column names from the reference exercise's dataset. Their presence in generic
# code means the code only works for that dataset.
_REFERENCE_COLUMNS = (
    "pblack",
    "pfl",
    "totreg",
    "adj_dppupil_comp",
    "adj_ldppupil_comp",
    "bdsnew",
    "psereg",
    "pup_tch",
    "plep",
    "phisp",
    "pasian",
    "pwhite",
    "pfemale",
    "pimmig",
    "zmath",
    "title1_schlwide",
    "newschool9816",
)

FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"class[\s_-]?3\b", "names a specific course exercise"),
    *(
        # Not \b: underscore is a word character, so \bpblack\b would miss
        # `residuals_vs_pblack` — which is exactly the shape the real defect
        # took. Treat any non-alphanumeric as a boundary.
        (
            rf"(?<![A-Za-z0-9]){re.escape(column)}(?![A-Za-z0-9])",
            "names a column from one specific dataset",
        )
        for column in _REFERENCE_COLUMNS
    ),
    # The reference panel's waves, as a literal sequence.
    (r"1998\s*,\s*2002\s*,\s*2006", "hard-codes one panel's survey years"),
)


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for relative, suffixes in SCANNED_ROOTS:
        root = REPO_ROOT / relative
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            # A co-located test file is a test, not product code.
            if ".test." in path.name or path.name.startswith("test_"):
                continue
            files.append(path)
    return files


def test_the_guard_actually_scans_the_product_source() -> None:
    """A guard that silently scans nothing would pass forever."""
    files = _scanned_files()

    assert len(files) > 200, f"expected to scan the product tree, found {len(files)} files"
    assert any(path.name == "workflow_contracts.py" for path in files)
    assert any(path.suffix == ".tsx" for path in files)


@pytest.mark.parametrize("pattern, reason", FORBIDDEN_PATTERNS)
def test_product_code_is_free_of_exercise_specific_naming(pattern: str, reason: str) -> None:
    compiled = re.compile(pattern, re.IGNORECASE)
    offenders: list[str] = []

    for path in _scanned_files():
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if not compiled.search(line):
                continue
            if LEGACY_COMPAT_MARKER in line:
                continue
            offenders.append(
                f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()[:110]}"
            )

    assert not offenders, (
        f"generic code {reason}:\n"
        + "\n".join(offenders)
        + "\n\nDerive the value from the request, the data, or a declared "
        "contract instead of naming it here."
    )


def test_the_guard_detects_a_reintroduced_name(tmp_path) -> None:
    """The guard must fail on a real regression, not just pass vacuously."""
    sample = 'raise ValueError("the Class 3 workflow did not complete")'
    assert any(
        re.search(pattern, sample, re.IGNORECASE) for pattern, _ in FORBIDDEN_PATTERNS
    )

    sample_column = 'required = {"residuals_vs_pblack", "fitted_vs_pfl"}'
    assert any(
        re.search(pattern, sample_column, re.IGNORECASE)
        for pattern, _ in FORBIDDEN_PATTERNS
    )


def test_the_legacy_compat_marker_is_not_a_general_escape_hatch() -> None:
    """The marker exists for reads of already-persisted keys, and stays rare."""
    marked: list[str] = []
    for path in _scanned_files():
        for number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if LEGACY_COMPAT_MARKER in line:
                marked.append(f"{path.relative_to(REPO_ROOT)}:{number}")

    assert len(marked) <= 4, (
        "too many legacy-compat exemptions; these should shrink over time, "
        "not accumulate:\n" + "\n".join(marked)
    )
