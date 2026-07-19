"""Canonical LMM fixtures with strict candidate-checkout provenance."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


STRICT_CANDIDATE_ENV = "WORKBENCH_EVALUATION_REQUIRE_CANDIDATE"
CANDIDATE_ROOT_ENV = "WORKBENCH_EVALUATION_CANDIDATE_ROOT"
_FIXTURE_RELATIVE_ROOT = Path("tests/fixtures/models/linear_mixed_effects")
_EVALUATOR_ROOT = Path(__file__).parents[3]


def lmm_fixture_root() -> Path:
    """Return evaluator fixtures locally and candidate fixtures in strict mode."""

    candidate_root = os.environ.get(CANDIDATE_ROOT_ENV)
    if candidate_root:
        return Path(candidate_root).resolve() / _FIXTURE_RELATIVE_ROOT
    if os.environ.get(STRICT_CANDIDATE_ENV) == "1":
        pytest.fail("strict candidate root is not set for canonical LMM fixtures")
    return _EVALUATOR_ROOT / _FIXTURE_RELATIVE_ROOT
