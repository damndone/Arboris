from __future__ import annotations

import pytest

from pathlib import Path

import pandas as pd

from workbench.artifacts import write_json
from workbench.agent.context_tools import read_prediction_research_evidence
from workbench.prediction import run_prediction_model_v186


class MeanEstimator:
    def fit(self, features: pd.DataFrame, target: pd.Series) -> "MeanEstimator":
        self.mean_ = float(target.mean())
        return self

    def predict(self, features: pd.DataFrame) -> list[float]:
        return [self.mean_] * len(features)


def test_agent_reads_only_hash_and_schema_verified_prediction_evidence(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    run_prediction_model_v186(
        pd.DataFrame({"y": [float(i + 1) for i in range(10)], "x": [float(i) for i in range(10)]}),
        run_root,
        y="y",
        x=["x"],
        model_type="test_mean",
        model_id="prediction_test_mean_1",
        final_holdout_fraction=0.2,
        cv_folds=2,
        shuffle=True,
        random_seed=3,
        data_structure="iid",
        estimator_factory=MeanEstimator,
    )

    projection = read_prediction_research_evidence(run_root, consumer="agent")

    assert projection["status"] == "validated"
    assert projection["model_id"] == "prediction_test_mean_1"


def test_agent_statistics_evidence_covers_every_test_family_not_just_the_largest(tmp_path) -> None:
    """A bounded budget must sample across families, not fill up with one.

    Pairwise Cohen's d dominates the packet by count, so a first-N budget hides
    the post-hoc, effect-size and assumption tests entirely and the Agent
    reports that they do not exist.
    """
    from workbench.agent.context_tools import _bounded_statistics_evidence
    from workbench.artifacts import write_json

    run_root = tmp_path / "run"
    (run_root / "statistical_tests").mkdir(parents=True)
    results = [
        {"test_id": f"cohens_d:y:g:{index}", "test_type": "cohens_d", "p_value": 0.5}
        for index in range(108)
    ]
    results.append({"test_id": "anova_posthoc:y:g", "test_type": "anova_posthoc", "p_value": 0.01})
    results.append({"test_id": "eta_squared:y:g", "test_type": "eta_squared", "p_value": None})
    results.append({"test_id": "levene:y:g", "test_type": "levene", "p_value": 0.4})
    write_json(
        run_root / "statistical_tests" / "evidence.json",
        {
            "payload_schema": "workbench.statistics.evidence-packet",
            "schema_version": 1,
            "results": results,
        },
    )

    projected = _bounded_statistics_evidence(run_root)

    observed = {row["test_type"] for row in projected["results"]}
    # A first-N budget yields only cohens_d; these three prove the round-robin.
    assert {"anova_posthoc", "eta_squared", "cohens_d"} <= observed, observed


def test_global_agent_can_reach_statistical_evidence(tmp_path) -> None:
    """The bottom-panel Agent runs on global_tool_definitions, not the chain set.

    None of those seven tools exposed the statistics packet, so the Agent
    answered "those tests were never run" for a run that had persisted 138
    statistical evidence rows.
    """
    from workbench.agent.context_tools import (
        InspectProjectStatisticalEvidenceRequest,
        NodeOperationContextProvider,
    )
    from workbench.artifacts import write_json

    project = tmp_path / "project"
    run_id = "20260803_000000_000000_probe"
    run_root = project / "runs" / run_id
    (run_root / "statistical_tests").mkdir(parents=True)
    write_json(run_root / "run_manifest.json", {"run_id": run_id, "status": "completed"})
    write_json(
        run_root / "statistical_tests" / "evidence.json",
        {
            "payload_schema": "workbench.statistics.evidence-packet",
            "schema_version": 1,
            "results": [
                {
                    "test_id": "anova_posthoc:wage:region",
                    "test_type": "anova_posthoc",
                    "statistic": 0.30106559564465674,
                    "p_value": 0.82461235192019,
                    "correction": "tukey",
                }
            ],
        },
    )

    provider = NodeOperationContextProvider(project)
    tool_ids = {
        item.tool_id for item in provider.global_tool_definitions(session_id="s")
    }
    assert "inspect_project_statistical_evidence" in tool_ids

    payload = provider.inspect_project_statistical_evidence(
        InspectProjectStatisticalEvidenceRequest(run_ids=(run_id,))
    )
    rows = payload["runs"][0]["statistical_evidence"]["results"]
    posthoc = next(row for row in rows if row["test_type"] == "anova_posthoc")
    assert posthoc["statistic"] == pytest.approx(0.30106559564465674)
    assert posthoc["correction"] == "tukey"
