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
    result = run_prediction_model_v186(
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
    assert projection["sample_spec_hash"] == result["sample_spec"]["sample_spec_hash"]
    assert projection["dataset_sha256"] == result["sample_spec"]["dataset_ref"]["dataset_sha256"]
    assert projection["structure"] == result["sample_spec"]["structure"]
    assert projection["split_plan_hash"] == result["split_plan"]["content_hash"]
    assert projection["split_parameters"] == result["split_plan"]["effective_parameters"]
    assert projection["oos"] == result["evaluation_packet"]["oos"]
    assert projection["development"]["cv"] == result["evaluation_packet"]["cv"]
    assert projection["baseline"] == result["evaluation_packet"]["baseline"]
    assert projection["controls"] == result["control_packet"]["controls"]
    assert projection["limits"] == result["evaluation_packet"]["limits"]
    assert projection["payload_versions"] == {
        "workbench.prediction.sample-spec": 1,
        "workbench.prediction.split-plan": 1,
        "workbench.prediction.prediction-packet": 1,
        "workbench.prediction.evaluation-packet": 1,
        "workbench.prediction.negative-control-packet": 1,
    }


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


def test_result_summary_tool_advertises_the_statistics_evidence_it_carries(tmp_path) -> None:
    """The Agent picks tools from their descriptors alone.

    inspect_result_summary is the only place post-hoc, effect-size and
    assumption tests are reachable, so a descriptor that does not say so makes
    the Agent report that those tests were never run.
    """
    from workbench.agent.context_tools import NodeOperationContextProvider

    provider = NodeOperationContextProvider(tmp_path)
    definition = next(
        item
        for item in provider.tool_definitions(chain_id="c", session_id="s")
        if item.tool_id == "inspect_result_summary"
    )

    descriptor = definition.descriptor()
    description = str(descriptor.get("description") or "")
    assert description, "inspect_result_summary exposes no description to the model"
    lowered = description.lower()
    assert "statistic" in lowered
    assert "post-hoc" in lowered or "posthoc" in lowered


def test_a_dedicated_statistical_evidence_tool_is_offered_to_the_agent(tmp_path) -> None:
    """Tool choice is name-driven in practice.

    A statistics question has to meet a tool whose name says "statistical
    evidence"; burying the packet inside a result-summary tool leaves the model
    answering "those tests were never run".
    """
    from workbench.agent.context_tools import NodeOperationContextProvider

    provider = NodeOperationContextProvider(tmp_path)
    definitions = {
        item.tool_id: item
        for item in provider.tool_definitions(chain_id="c", session_id="s")
    }

    assert "inspect_statistical_evidence" in definitions
    definition = definitions["inspect_statistical_evidence"]
    assert definition.side_effect == "none"
    assert "owner_run_id" in definition.input_schema["required"]
    assert "post-hoc" in str(definition.descriptor().get("description") or "").lower()


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
