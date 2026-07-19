from __future__ import annotations

from pathlib import Path


def test_strict_fixture_root_is_resolved_from_the_candidate_checkout(
    monkeypatch, tmp_path: Path
) -> None:
    from tests.evaluation.linear_mixed_effects import _fixtures

    candidate = tmp_path / "candidate"
    fixture_root = candidate / "tests" / "fixtures" / "models" / "linear_mixed_effects"
    fixture_root.mkdir(parents=True)
    monkeypatch.setenv(_fixtures.CANDIDATE_ROOT_ENV, str(candidate))
    monkeypatch.setenv(_fixtures.STRICT_CANDIDATE_ENV, "1")

    assert _fixtures.lmm_fixture_root() == fixture_root
