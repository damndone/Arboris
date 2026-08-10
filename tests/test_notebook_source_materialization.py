"""Upload-only Notebook source materialization acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_notebook_support import make_project
from workbench.api import app
from workbench.agent.notebook import NotebookService
from workbench.agent.notebook.planning_agent import NotebookPlanningAgent
from workbench.agent.notebook.proposal import TypedProposal
from workbench.agent.notebook.workflow_artifacts import (
    WORKFLOW_RESULT_ARTIFACT_TYPE,
    workflow_result_artifact_id,
)
from workbench.lineage.upload_store import store_upload_bytes
from workbench.services.notebook_source_materialization import (
    materialize_notebook_upload_source,
)


def test_upload_only_notebook_materializes_its_source_only_after_confirmation(
    tmp_path: Path,
) -> None:
    """A normal upload can plan and execute P7 without a user-created model Run."""

    project = make_project(tmp_path)
    frame = pd.DataFrame(
        {
            "outcome": [1.0, None, 3.0, 4.0],
            "group": ["a", "a", None, "b"],
        }
    )
    upload_sha = store_upload_bytes(
        project,
        frame.to_csv(index=False).encode("utf-8"),
        filename="upload.csv",
    )
    client = TestClient(app)
    params = {"project_root": str(project)}
    created_response = client.post(
        "/notebooks/projection",
        params=params,
        json={
            "dataset": {
                "upload_sha256": upload_sha,
                "filename": "upload.csv",
                "sheet_names": [],
            },
            "created_by": "ui",
        },
    )
    created = created_response.json()
    notebook_id = created["notebook_id"]
    service = NotebookService(project)
    notebook = service.get_notebook(notebook_id)
    workflow_source = notebook.projection_source.workflow_source
    source_run_root = project / "runs" / workflow_source.run_id
    context = service.compile_context(notebook_id)

    assert (
        workflow_source.source_kind == "dataset_upload"
        and not source_run_root.exists()
        and "operation.multi_step"
        in NotebookPlanningAgent._typed_operation_contracts(context)
    )

    pin = NotebookPlanningAgent._execution_pins(context)["workflow_source"]
    proposal = {
        "proposal_id": "proposal_upload_missingness",
        "proposal_revision": 1,
        "operation_id": "operation.multi_step",
        "operation_version": "v1",
        "target": pin["target"],
        "preconditions": pin["preconditions"],
        "changes": {
            "steps": [
                {
                    "step_id": "profile_missingness",
                    "operation_id": "missingness.profile",
                    "spec": {
                        "input_mode": "frame",
                        "column_bindings": {},
                        "options": {},
                    },
                }
            ]
        },
    }
    option_id = "opt_upload_missingness"
    result_artifact_id = workflow_result_artifact_id(
        notebook_id=notebook_id,
        option_id=option_id,
        proposal_hash=TypedProposal.from_dict(proposal).canonical_hash(),
    )
    proposed = client.post(
        f"/notebooks/{notebook_id}/options/propose",
        params=params,
        json={
            "drafts": [
                {
                    "rank": 1,
                    "rationale": "Describe the missing values in my data.",
                    "proposal": proposal,
                    "expected_artifacts": [
                        {
                            "artifact_id": result_artifact_id,
                            "artifact_type": WORKFLOW_RESULT_ARTIFACT_TYPE,
                            "required": True,
                            "count": 1,
                            "step": None,
                        }
                    ],
                    "option_id": option_id,
                    "capability_id": "missingness.profile",
                }
            ]
        },
    )
    assert proposed.status_code == 200, proposed.text
    option = proposed.json()["options"][0]
    client.post(
        f"/notebooks/{notebook_id}/options/{option_id}/decision",
        params=params,
        json={"decision": "selected", "actor": "ui"},
    )
    confirmed = client.post(
        f"/notebooks/{notebook_id}/options/{option_id}/confirm",
        params=params,
        json={
            "option_revision": option["option_revision"],
            "proposal_id": option["typed_proposal_id"],
            "proposal_revision": option["typed_proposal_revision"],
        },
    )

    assert confirmed.status_code == 200, confirmed.text
    result = client.get(
        f"/notebooks/{notebook_id}/options", params=params
    ).json()["execution_results"][option_id]
    source_index = json.loads((source_run_root / "artifacts_index.json").read_text())
    projected_analysis_ids = result["workflow_execution"][
        "post_estimation_artifact_ids"
    ]
    assert (
        source_run_root.is_dir()
        and result["committed"] is True
        and result["artifact_validation"]["issues"] == []
        and len(projected_analysis_ids) == 1
        and any(
            item["artifact_id"] == projected_analysis_ids[0]
            and item["artifact_type"] == "p7_analysis"
            for item in source_index["artifacts"]
        )
        and {item["artifact_type"] for item in source_index["artifacts"]}
        >= {"raw_data", "p7_analysis", WORKFLOW_RESULT_ARTIFACT_TYPE}
    )


def test_upload_source_materialization_never_repairs_an_inconsistent_reserved_run(
    tmp_path: Path,
) -> None:
    """A conflicting reserved Run is rejected byte-for-byte, never repaired."""

    project = make_project(tmp_path)
    payload = b"outcome,group\n1,a\n2,b\n"
    upload_sha = store_upload_bytes(project, payload, filename="upload.csv")
    service = NotebookService(project)
    notebook = service.ensure_default_projection(
        dataset={
            "kind": "dataset",
            "upload_sha256": upload_sha,
            "filename": "upload.csv",
            "sheet_names": [],
        },
        created_by="ui",
    )
    source = notebook.projection_source
    assert source is not None and source.workflow_source is not None
    run_root = project / "runs" / source.workflow_source.run_id
    run_root.mkdir(parents=True)
    conflicting_manifest = b'{"mode":"foreign","status":"completed"}\n'
    sentinel = b"do-not-repair"
    (run_root / "run_manifest.json").write_bytes(conflicting_manifest)
    (run_root / "sentinel.bin").write_bytes(sentinel)

    with pytest.raises(
        ValueError,
        match="reserved Notebook source Run is incomplete or inconsistent",
    ):
        materialize_notebook_upload_source(
            project,
            source=source,
            run_family_id=notebook.run_family_id,
        )

    assert (run_root / "run_manifest.json").read_bytes() == conflicting_manifest
    assert (run_root / "sentinel.bin").read_bytes() == sentinel
    assert sorted(path.name for path in run_root.iterdir()) == [
        "run_manifest.json",
        "sentinel.bin",
    ]
