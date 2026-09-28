"""v1.8.9 step 4 — the Agent reads the user's declared variable metadata.

Without it the Agent answers "gender = 2" when the user wrote 女, cannot name a
treatment-coded term such as C(Q('region'))[T.2], and never learns that -99
was declared missing.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.agent.context_tools import (
    InspectProjectDatasetSchemaRequest,
    InspectProjectModelCoefficientsRequest,
    ListProjectDatasetsRequest,
    NodeOperationContextProvider,
)
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

LABELS = {
    "variable_labels": {"educ": "受教育年限", "region": "地区"},
    "value_labels": {"region": {"1": "北方", "2": "南方", "3": "西部"}},
    "measurement_level": {"region": "nominal"},
    "user_missing_values": {"educ": [-99]},
}


@pytest.fixture(scope="module")
def labelled_run(tmp_path_factory) -> tuple[Path, str]:
    tmp_path = tmp_path_factory.mktemp("agent-metadata")
    rng = np.random.default_rng(11)
    n = 200
    frame = pd.DataFrame(
        {
            "wage": rng.normal(20, 4, n).round(3),
            "educ": rng.integers(9, 20, n).astype(float),
            "region": rng.integers(1, 4, n),
        }
    )
    frame.loc[:4, "educ"] = -99
    source = tmp_path / "wages.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "p")
    outcome = run_workflow(
        project.root, [source], mode="auto", model_type="ols", y="wage",
        x=["educ", "region"], labels=LABELS,
    )
    assert outcome["status"] == "completed", outcome
    return project.root, outcome["run_id"]


def test_the_dataset_schema_tool_carries_the_declared_metadata(labelled_run) -> None:
    root, run_id = labelled_run
    schema = NodeOperationContextProvider(root).inspect_project_dataset_schema(
        InspectProjectDatasetSchemaRequest(run_id=run_id)
    )
    columns = {column["name"]: column for column in schema["columns"]}
    assert columns["educ"]["variable_label"] == "受教育年限"
    assert columns["educ"]["user_missing_values"] == [-99]
    assert columns["region"]["value_labels"] == {"1": "北方", "2": "南方", "3": "西部"}
    assert columns["region"]["measurement_level"] == "nominal"
    assert "variable_label" not in columns["wage"]


def test_listing_datasets_names_the_declared_metadata(labelled_run) -> None:
    root, run_id = labelled_run
    listing = NodeOperationContextProvider(root).list_project_datasets(ListProjectDatasetsRequest())
    entries = [entry for entry in listing["datasets"] if entry["run_id"] == run_id]
    assert entries
    metadata = entries[0]["declared_metadata"]
    assert metadata["variable_labels"]["region"] == "地区"
    assert metadata["user_missing_values"] == {"educ": [-99]}


def test_coefficients_come_back_with_readable_labels(labelled_run) -> None:
    root, run_id = labelled_run
    result = NodeOperationContextProvider(root).inspect_project_model_coefficients(
        InspectProjectModelCoefficientsRequest(
            run_ids=(run_id,), terms=("educ", "C(Q('region'))[T.2]")
        )
    )
    coefficients = {item["term"]: item for item in result["models"][0]["coefficients"]}
    assert coefficients["educ"]["label"] == "受教育年限"
    assert coefficients["C(Q('region'))[T.2]"]["label"] == "地区: 南方"


def test_a_missing_term_lists_the_terms_the_model_does_have(labelled_run) -> None:
    """An Agent that asks for `region` must learn the real term names."""

    root, run_id = labelled_run
    result = NodeOperationContextProvider(root).inspect_project_model_coefficients(
        InspectProjectModelCoefficientsRequest(run_ids=(run_id,), terms=("region",))
    )
    model = result["models"][0]
    available = {item["term"]: item["label"] for item in model["available_terms"]}
    assert available["C(Q('region'))[T.2]"] == "地区: 南方"
    assert available["educ"] == "受教育年限"


def test_the_agent_can_export_a_dataset_with_a_loss_report(labelled_run) -> None:
    from workbench.agent.tools import ToolContext, ToolVisibleError

    root, run_id = labelled_run
    provider = NodeOperationContextProvider(root)
    tools = {definition.tool_id: definition for definition in provider.tool_definitions(chain_id="c1", session_id="s1")}
    export = tools["export_dataset"]
    assert export.side_effect == "artifact"
    context = ToolContext(session_id="s1", metadata={})
    result = export.handler({"run_id": run_id, "node_id": "stage:raw", "format": "dta"}, context)
    assert result["filename"].endswith(".dta")
    assert any(note["field"] == "user_missing_values" for note in result["notes"])  # -99 has no Stata form
    # Recorded like a UI export, as the Agent's own action.
    from workbench import analysis_ledger

    [entry] = [e for e in analysis_ledger.read(root) if e["source"] == "agent.export_dataset"]
    assert entry["actor"] == "agent" and entry["session_id"] == "s1"
    assert [step["operation_id"] for step in entry["steps"]] == ["export.dataset"]
    with pytest.raises(ToolVisibleError, match="DATASET_EXPORT_UNAVAILABLE"):
        export.handler({"run_id": run_id, "node_id": "model:ols_1", "format": "sav"}, context)
    with pytest.raises(ToolVisibleError):
        export.handler({"run_id": "../../etc", "node_id": "stage:raw", "format": "sav"}, context)
