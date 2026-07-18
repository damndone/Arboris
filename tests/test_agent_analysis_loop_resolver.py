from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.analysis_loop.resolver import (
    AnalysisLoopSourceResolutionError,
    resolve_analysis_loop_inputs,
)
from workbench.econometrics.runner import run_ols
from workbench.lineage.run_inputs import write_run_inputs


def _write_source(project_root: Path, *, covariance: str = "unadjusted") -> str:
    run_id = "run-source"
    run_root = project_root / "runs" / run_id
    (run_root / "model_results").mkdir(parents=True)
    (run_root / "processed").mkdir(parents=True)
    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, 1.5, 3.0, 2.5, 4.0],
            "x": [0.0, 1.0, 0.5, 2.0, 1.5, 3.0],
            "company_id": ["a", "a", "b", "b", "c", "c"],
        }
    )
    result, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=covariance != "unadjusted",
        covariance=covariance,
        covariance_explicit=True,
        cluster_col="company_id" if covariance == "clustered" else None,
        model_id="ols_1",
        row_ids=[str(index) for index in frame.index],
    )
    (run_root / "model_results" / "ols_1.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    frame.to_parquet(run_root / "processed" / "cleaned_dataset.parquet", index=False)
    (run_root / "run_manifest.json").write_text(
        json.dumps({"run_id": run_id, "status": "completed"}), encoding="utf-8"
    )
    write_run_inputs(
        run_root,
        form={
            "model_type": "ols",
            "covariance": covariance,
            "y": "y",
            "x": "x",
        },
        upload={"sha256": "a" * 64, "filename": "source.csv"},
        rerun_of=None,
        from_node=None,
        rerun_reason="initial",
        override_hash=None,
        dag_hash="b" * 64,
        source_lineage={"source_run_id": None, "from_node": None},
    )
    return run_id


def test_resolver_reads_ols_contract_and_row_aligned_cluster_values(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    run_id = _write_source(project_root)

    resolved = resolve_analysis_loop_inputs(
        project_root,
        run_id=run_id,
        cluster_variable="company_id",
    )

    assert resolved.source.run_id == run_id
    assert resolved.source.covariance == "unadjusted"
    assert resolved.source.contract_version == "ols_result_contract_v1"
    assert resolved.model_row_ids == tuple(str(index) for index in range(6))
    assert resolved.cluster_values == ("a", "a", "b", "b", "c", "c")
    assert resolved.model_input_artifact == "cleaned_dataset"


@pytest.mark.parametrize(
    ("covariance", "code"),
    [("robust", "SOURCE_COVARIANCE_UNSUPPORTED"), ("clustered", "SOURCE_COVARIANCE_UNSUPPORTED")],
)
def test_resolver_rejects_non_conventional_source(
    tmp_path: Path,
    covariance: str,
    code: str,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_source(project_root, covariance=covariance)

    with pytest.raises(AnalysisLoopSourceResolutionError) as exc_info:
        resolve_analysis_loop_inputs(
            project_root,
            run_id="run-source",
            cluster_variable="company_id",
        )

    assert exc_info.value.code == code


def test_resolver_rejects_non_exact_cluster_column(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_source(project_root)

    with pytest.raises(AnalysisLoopSourceResolutionError) as exc_info:
        resolve_analysis_loop_inputs(
            project_root,
            run_id="run-source",
            cluster_variable="company",
        )

    assert exc_info.value.code == "CLUSTER_VARIABLE_NOT_FOUND"
