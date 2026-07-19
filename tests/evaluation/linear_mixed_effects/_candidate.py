"""Candidate-only import boundary for the independent evaluation harness."""

from __future__ import annotations

import importlib
import os
from types import ModuleType

import pytest


STRICT_CANDIDATE_ENV = "WORKBENCH_EVALUATION_REQUIRE_CANDIDATE"


def require_candidate_module(module_name: str) -> ModuleType:
    """Load a supplied feature module or make an absent candidate explicit.

    A standalone Evaluation Lane intentionally starts before Feature Lane code
    exists. Local authoring runs therefore skip unavailable candidate-only
    checks. The evidence collector sets ``STRICT_CANDIDATE_ENV=1`` after its
    Git preflight, turning the same absence into a failed evaluation.
    """

    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        missing_name = error.name or ""
        if missing_name != module_name and not module_name.startswith(
            missing_name + "."
        ):
            raise
        message = (
            f"supplied candidate does not provide required module: {module_name}; "
            "no candidate can be accepted without it"
        )
        if os.environ.get(STRICT_CANDIDATE_ENV) == "1":
            pytest.fail(message)
        pytest.skip(message)
