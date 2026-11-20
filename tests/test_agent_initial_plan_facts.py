from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.artifacts import register_artifact, write_json
from workbench.canonical import sha256_canonical
from workbench.graph_model import Graph, Node, NodeKind
from workbench.graph_store import GraphStore


RUN_ID = "seed-run"
SOURCE_REF = "stage:cleaned"
MODEL_ID = "ols_1"
MODEL_REF = f"model:{MODEL_ID}"
SELECTOR = "coef:" + sha256_canonical({"model": "ols", "model_id": MODEL_ID, "term": "dose"})


@pytest.fixture
def panel_seed(tmp_path):
    run = tmp_path / "runs" / RUN_ID
    cleaned = run / "processed" / "cleaned_dataset.parquet"
    result = run / "model_results" / f"{MODEL_ID}.json"
    for path in (cleaned, result):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private observations or estimates")
    GraphStore(run.parent).write(Graph(
        schema_version=1, run_id=RUN_ID, edges={}, branches={},
        nodes={
            SOURCE_REF: Node(SOURCE_REF, NodeKind.DATASET_STAGE, "Cleaned", "", None, "main",
                             payload_ref=cleaned.relative_to(run).as_posix()),
            MODEL_REF: Node(MODEL_REF, NodeKind.MODEL, "OLS", "", None, "main",
                            payload_ref=result.relative_to(run).as_posix()),
        },
    ))
    write_json(run / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    register_artifact(run, "cleaned_dataset", cleaned, "processed_data", "cleaning", [])
    register_artifact(run, MODEL_ID, result, "model_result", "estimation", ["cleaned_dataset"])
    profile_path = run / "staged" / "data_profile.json"
    write_json(profile_path, {
        "row_count": 18,
        "column_count": 4,
        "columns": {
            "site": {"dtype": "int64", "unique_count": 6, "missing_rate": 0, "top_values": ["private label"]},
            "quarter": {"dtype": "int64", "unique_count": 3, "missing_rate": 0},
            "outcome": {"dtype": "float64", "missing_rate": 0},
            "dose": {"dtype": "float64", "missing_rate": 0},
        },
        "sample": ["private row"],
    })
    register_artifact(run, "data_profile", profile_path, "profile", "profiling", ["cleaned_dataset"])
    routing_path = run / "staged" / "analysis_router.json"
    write_json(routing_path, {"kind": "panel", "evidence": ["id=site", "time=quarter"]})
    register_artifact(run, "analysis_router", routing_path, "metadata", "analysis_router", ["data_profile"])
    write_json(run / "run_manifest.json", {
        "run_id": RUN_ID,
        "status": "completed",
        "y": "outcome",
        "x": ["dose"],
        "model_routing": {"effective_model_id": MODEL_ID, "effective_model_type": "ols"},
        "result_contract": {
            "contract_version": "ols_result_contract_v1", "model": "ols", "model_type": "ols",
            "covariance": "unadjusted", "source_eligible": True, "entity_col": None,
            "stable_result_ids": [SELECTOR], "candidate_result_ids": [SELECTOR],
        },
    })
    write_json(run / "node_index.json", {MODEL_REF: {"node_hash": "a" * 64}})
    return NodeOperationContextProvider(tmp_path), run


def test_initial_plan_facts_gives_exact_scoped_seed_references_without_opening_data(panel_seed, monkeypatch):
    from workbench.agent.initial_plan_facts import initial_plan_facts

    provider, run = panel_seed
    other_run = run.parent / "unrelated"
    other_run.mkdir()
    write_json(other_run / "run_inputs.json", {"private": "other run"})
    allowed = {"graph.json", "artifacts_index.json", "data_profile.json", "analysis_router.json",
               "run_manifest.json", "node_index.json"}
    original_open = Path.open

    def scoped_open(path, *args, **kwargs):
        assert path.is_relative_to(run) and path.name in allowed, path
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", scoped_open)
        facts = initial_plan_facts(provider, owner_run_id=RUN_ID, active_head_run_id=RUN_ID)

    assert facts is not None
    assert facts["content_role"] == "untrusted_data"
    assert facts["source"] == {
        "run_id": RUN_ID, "node_ref": SOURCE_REF, "artifact_id": "cleaned_dataset",
        "sha256": facts["source"]["sha256"],
    }
    assert len(facts["source"]["sha256"]) == 64
    assert facts["dataset"]["row_count"] == 18
    assert facts["dataset"]["column_count"] == 4
    assert facts["dataset"]["columns"][0] == {"name": "site", "dtype": "int64", "unique_count": 6, "missing_rate": 0}
    assert facts["panel"] == {"entity_col": "site", "time_col": "quarter"}
    model = facts["model"]
    assert model["outcome"] == "outcome"
    assert model["predictors"] == ["dose"]
    assert model["coefficient_selectors"] == [{"term": "dose", "result_id": SELECTOR}]
    assert model["rerun"] == {
        "operation_id": "model.rerun", "operation_version": "v1",
        "target": {"run_id": RUN_ID, "node_ref": MODEL_REF},
        "preconditions": {"active_head_run_id": RUN_ID},
    }
    assert model["rerun_context_request"] == {"owner_run_id": RUN_ID, "op_node_id": MODEL_REF,
                                              "active_head_run_id": RUN_ID}
    assert model["clustered_ols_rerun"] == {
        **model["rerun"], "target": {**model["rerun"]["target"], "result_id": SELECTOR},
        "changes": {"covariance": "clustered", "entity_col": "site"},
    }
    assert model["panel_ols_rerun"] == {
        **model["rerun"],
        "changes": {"model_type": "panel_ols", "model_options": {"covariance": "clustered", "cluster": "site"}},
    }
    assert "private" not in json.dumps(facts)


def test_initial_plan_facts_missing_binding_or_wrong_scope_fails_closed(panel_seed):
    from workbench.agent.initial_plan_facts import initial_plan_facts

    provider, run = panel_seed
    assert initial_plan_facts(provider, owner_run_id=RUN_ID, active_head_run_id="another-run") is None
    assert initial_plan_facts(provider, owner_run_id="../seed-run", active_head_run_id="../seed-run") is None
    write_json(run / "staged" / "data_profile.json", {"row_count": 55})
    assert initial_plan_facts(provider, owner_run_id=RUN_ID, active_head_run_id=RUN_ID) is None


def test_initial_plan_facts_rejects_registered_profile_symlink_outside_run(panel_seed):
    from workbench.agent.initial_plan_facts import initial_plan_facts

    provider, run = panel_seed
    profile = run / "staged" / "data_profile.json"
    external = profile.rename(run.parent / "outside_profile.json")
    profile.symlink_to(external)

    assert initial_plan_facts(provider, owner_run_id=RUN_ID, active_head_run_id=RUN_ID) is None


def test_initial_plan_facts_bounds_wide_profiles_and_omits_unregistered_coefficient(panel_seed):
    from workbench.agent.initial_plan_facts import initial_plan_facts

    provider, run = panel_seed
    profile = run / "staged" / "data_profile.json"
    value = json.loads(profile.read_text())
    value["columns"].update({f"wide_{index}": {"dtype": "float64"} for index in range(100)})
    value["column_count"] = len(value["columns"])
    write_json(profile, value)
    index = run / "artifacts_index.json"
    registry = json.loads(index.read_text())
    registry["artifacts"] = [item for item in registry["artifacts"] if item["artifact_id"] != "data_profile"]
    write_json(index, registry)
    register_artifact(run, "data_profile", profile, "profile", "profiling", ["cleaned_dataset"])
    manifest = run / "run_manifest.json"
    value = json.loads(manifest.read_text())
    value["result_contract"]["candidate_result_ids"] = ["coef:" + "b" * 64]
    write_json(manifest, value)

    facts = initial_plan_facts(provider, owner_run_id=RUN_ID, active_head_run_id=RUN_ID)
    assert facts is not None
    columns = facts["dataset"]["columns"]
    assert 4 <= len(columns) <= 32
    assert facts["dataset"]["columns_omitted"] == 104 - len(columns)
    assert facts["model"]["coefficient_selectors"] == []
    assert "clustered_ols_rerun" not in facts["model"]
    assert len(json.dumps(facts)) < 4096
