from __future__ import annotations

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _frame() -> pd.DataFrame:
    import numpy as np

    rng = np.random.default_rng(11)
    before = rng.normal(10.0, 2.0, 120)
    return pd.DataFrame({
        "before": before.round(4),
        "after": (before + rng.normal(1.5, 1.0, 120)).round(4),
        "score": (0.4 * before + rng.normal(0.0, 1.0, 120)).round(4),
    })


def _run(tmp_path, name, **kwargs):
    source = tmp_path / f"{name}.csv"
    _frame().to_csv(source, index=False)
    project = create_project(tmp_path, name)
    outcome = run_workflow(
        project.root, [source], mode="auto", y="score", x=["before"], **kwargs
    )
    return project.root / "runs" / outcome["run_id"], outcome


def _evidence(run_root):
    path = run_root / "statistical_tests" / "evidence.json"
    return read_json(path)["results"] if path.exists() else []


def test_declared_pairs_produce_paired_tests_in_an_ordinary_run(tmp_path) -> None:
    """Deliverable 14 asks for paired tests in the user-reachable packet."""
    run_root, outcome = _run(
        tmp_path, "paired", statistical_tests={"paired_columns": [["before", "after"]]}
    )
    assert outcome["status"] == "completed", outcome
    kinds = {row["test_type"] for row in _evidence(run_root)}
    assert "paired_t_test" in kinds, kinds
    assert "wilcoxon_signed_rank" in kinds, kinds


def test_declared_reference_mean_produces_a_one_sample_test(tmp_path) -> None:
    run_root, outcome = _run(
        tmp_path, "onesample", statistical_tests={"reference_means": {"score": 6.0}}
    )
    assert outcome["status"] == "completed", outcome
    rows = [row for row in _evidence(run_root) if row["test_type"] == "one_sample_t_test"]
    assert rows, {row["test_type"] for row in _evidence(run_root)}
    assert rows[0]["test_id"] == "one_sample_t_test:score"


def test_pairing_is_never_guessed_from_column_order(tmp_path) -> None:
    """A malformed pair must fail closed with an actionable code, not be guessed."""
    from workbench.orchestrator._errors import WorkflowValidationError

    with pytest.raises(WorkflowValidationError) as error:
        _run(tmp_path, "guess", statistical_tests={"paired_columns": [["before"]]})

    assert error.value.error_code == "STATISTICAL_TESTS_PAIR_INVALID"
    assert "never inferred from column" in str(error.value)


def test_absent_reference_column_fails_closed(tmp_path) -> None:
    from workbench.orchestrator._errors import WorkflowValidationError

    with pytest.raises(WorkflowValidationError) as error:
        _run(tmp_path, "absent", statistical_tests={"reference_means": {"nope": 1.0}})

    assert error.value.error_code == "STATISTICAL_TESTS_REFERENCE_MEAN_INVALID"


def test_http_run_accepts_declared_paired_columns(tmp_path) -> None:
    """The declaration has to be reachable from the API, not only in-process."""
    import io
    import time

    from fastapi.testclient import TestClient

    from workbench.app import app

    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "paired-http"}
    ).json()["project_root"]
    response = client.post(
        "/runs",
        data={
            "project_root": root,
            "mode": "auto",
            "model_type": "ols",
            "y": "score",
            "x": "before",
            "statistical_tests": '{"paired_columns": [["before", "after"]]}',
        },
        files={
            "file": (
                "paired.csv",
                io.BytesIO(_frame().to_csv(index=False).encode()),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    for _ in range(200):
        detail = client.get(f"/runs/{run_id}", params={"project_root": root}).json()
        if detail.get("status") in {"completed", "failed", "blocked", "partial"}:
            break
        time.sleep(0.1)
    assert detail["status"] == "completed", detail

    kinds = {row["test_type"] for row in detail["statistical_evidence"]["results"]}
    assert "paired_t_test" in kinds, kinds
    assert "wilcoxon_signed_rank" in kinds, kinds
