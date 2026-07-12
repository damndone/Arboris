"""V4 compatibility regression coverage for legacy project graph loading."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


_GRAPH_SMOKE = r"""
import sys

from fastapi.testclient import TestClient

from workbench.api import app

assert "matplotlib" not in sys.modules, (
    "GET /graph must not initialize run-only plotting dependencies during app startup"
)
response = TestClient(app).get("/graph", params={"project_root": sys.argv[1]})
assert response.status_code == 200, response.text
body = response.json()
assert body["nodes"] == {}
assert body["heads"] == []
assert body["legacy"] is False
"""


def test_legacy_graph_does_not_block_on_plotting_import(tmp_path: Path) -> None:
    """A v1.5-style project must reach the graph response without Matplotlib startup."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    legacy_run = runs_dir / "2026-05-29_065220_NVDA"
    legacy_run.mkdir()
    (legacy_run / "manifest.json").write_text("{}", encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(repo_root / "backend"),
            "MPLCONFIGDIR": str(tmp_path / "mplconfig"),
            "LC_ALL": "en_US.UTF-8",
            "LANG": "en_US.UTF-8",
        }
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", _GRAPH_SMOKE, str(tmp_path)],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"legacy /graph smoke timed out: {exc}")

    assert result.returncode == 0, (
        f"legacy /graph smoke failed\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
