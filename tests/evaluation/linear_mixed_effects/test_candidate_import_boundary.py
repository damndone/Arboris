from __future__ import annotations

import os
from types import ModuleType

import pytest

from tests.evaluation.linear_mixed_effects import _candidate


if os.environ.get("WORKBENCH_EVALUATION_REQUIRE_CANDIDATE") == "1":
    pytest.skip(
        "strict entrypoint meta-tests run outside the candidate evaluation suite",
        allow_module_level=True,
    )


def test_strict_mode_rejects_a_candidate_module_loaded_outside_candidate_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    foreign = ModuleType("workbench.engine.packs.linear_mixed_effects.runner")
    foreign.__file__ = str(tmp_path / "foreign" / "runner.py")
    monkeypatch.setenv(_candidate.STRICT_CANDIDATE_ENV, "1")
    monkeypatch.setenv(_candidate.CANDIDATE_ROOT_ENV, str(candidate_root))
    monkeypatch.setattr(_candidate.importlib, "import_module", lambda _name: foreign)

    with pytest.raises(pytest.fail.Exception, match="outside supplied candidate root"):
        _candidate.require_candidate_module(
            "workbench.engine.packs.linear_mixed_effects.runner"
        )
