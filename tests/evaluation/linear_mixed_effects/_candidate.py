"""Candidate-only import boundary for the independent evaluation harness."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest


STRICT_CANDIDATE_ENV = "WORKBENCH_EVALUATION_REQUIRE_CANDIDATE"
CANDIDATE_ROOT_ENV = "WORKBENCH_EVALUATION_CANDIDATE_ROOT"


def _require_module_provenance(module_name: str, module: ModuleType) -> None:
    """Make strict evaluations prove that a module came from the candidate."""

    candidate_root_value = os.environ.get(CANDIDATE_ROOT_ENV)
    if not candidate_root_value:
        pytest.fail("strict candidate root is not set")
    module_file = getattr(module, "__file__", None)
    if not module_file:
        pytest.fail(f"candidate module has no __file__: {module_name}")
    candidate_root = Path(candidate_root_value).resolve()
    resolved_module_file = Path(module_file).resolve()
    if not resolved_module_file.is_relative_to(candidate_root):
        pytest.fail(
            f"candidate module loaded outside supplied candidate root: "
            f"{module_name} -> {resolved_module_file}"
        )


def _clear_foreign_workbench_modules(candidate_root: Path) -> None:
    """Prevent pytest collection from lending the evaluator's package cache."""

    candidate_backend = (candidate_root / "backend").resolve()
    sys.path[:] = [
        str(candidate_backend),
        *[
            entry
            for entry in sys.path
            if not entry or Path(entry).resolve() != candidate_backend
        ],
    ]
    for name, loaded in tuple(sys.modules.items()):
        if name != "workbench" and not name.startswith("workbench."):
            continue
        module_file = getattr(loaded, "__file__", None)
        if not module_file or not Path(module_file).resolve().is_relative_to(candidate_root):
            del sys.modules[name]
    importlib.invalidate_caches()


def require_candidate_module(module_name: str) -> ModuleType:
    """Load a supplied feature module or make an absent candidate explicit.

    A standalone Evaluation Lane intentionally starts before Feature Lane code
    exists. Local authoring runs therefore skip unavailable candidate-only
    checks. The evidence collector sets ``STRICT_CANDIDATE_ENV=1`` after its
    Git preflight, turning the same absence into a failed evaluation.
    """

    if os.environ.get(STRICT_CANDIDATE_ENV) == "1":
        candidate_root_value = os.environ.get(CANDIDATE_ROOT_ENV)
        if not candidate_root_value:
            pytest.fail("strict candidate root is not set")
        _clear_foreign_workbench_modules(Path(candidate_root_value).resolve())
    try:
        module = importlib.import_module(module_name)
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
    if os.environ.get(STRICT_CANDIDATE_ENV) == "1":
        _require_module_provenance(module_name, module)
    return module
