from __future__ import annotations

import json
import asyncio
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import sha256_file, write_json
from workbench.graph_model import BranchRef, Edge, Graph, Node, NodeKind, Stage, Trust
from workbench.graph_store import GraphStore


def _source_project(tmp_path: Path, frame: pd.DataFrame) -> tuple[Path, str, str]:
    project = tmp_path / "project"
    run_id = "run_source"
    run_root = project / "runs" / run_id
    run_root.mkdir(parents=True)
    source_path = run_root / "data.csv"
    frame.to_csv(source_path, index=False)
    artifact_id = "source_data"
    write_json(
        run_root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": artifact_id,
                    "path": "data.csv",
                    "artifact_type": "raw_data",
                    "step": "fixture",
                    "sha256": sha256_file(source_path),
                    "inputs": [],
                }
            ],
        },
    )
    node = Node(
        id="stage:source",
        kind=NodeKind.DATASET_STAGE,
        display_label="Source data",
        created_at="2026-07-15T00:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        payload_ref="data.csv",
        summary=f"Source: {len(frame)} rows",
        stage=Stage.SOURCE,
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id=run_id,
            nodes={node.id: node},
            edges={},
            branches={"main": BranchRef("main", None, (node.id,))},
        )
    )
    return project, run_id, artifact_id


def test_column_cast_preview_is_strict_and_deterministic(tmp_path: Path) -> None:
    from workbench.data_operations import (
        DataColumnCastSpecV1,
        preview_data_column_cast,
    )

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {"observed_at": ["2024-01-01", "2024-01-02", None], "name": ["a", "b", "c"]}
        ),
    )
    spec = DataColumnCastSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        column="observed_at",
        target_dtype="datetime",
    )

    first = preview_data_column_cast(project, spec)
    second = preview_data_column_cast(project, spec)

    assert first.status == "ready"
    assert first.failure_count == 0
    assert first.success_count == 2
    assert first.new_missing_count == 0
    assert first.before_dtype == "str"
    assert first.after_dtype.startswith("datetime64[")
    assert first.schema_fingerprint_before != first.schema_fingerprint_after
    assert first.fingerprint == second.fingerprint
    assert first.to_dict() == second.to_dict()
    assert not (project / "workbench").exists()


def test_column_cast_preview_blocks_unparseable_non_null_values(tmp_path: Path) -> None:
    from workbench.data_operations import DataColumnCastSpecV1, preview_data_column_cast

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "not-a-number", None]}),
    )
    preview = preview_data_column_cast(
        project,
        DataColumnCastSpecV1(
            source_run_id=run_id,
            source_node_id="stage:source",
            source_artifact_id=artifact_id,
            column="age",
            target_dtype="numeric",
        ),
    )

    assert preview.status == "blocked"
    assert preview.failure_count == 1
    assert preview.success_count == 1
    assert preview.new_missing_count == 1
    assert preview.failure_examples == ("not-a-number",)


def test_column_cast_preview_rejects_unknown_column_and_dtype(tmp_path: Path) -> None:
    from workbench.data_operations import (
        DataColumnCastSpecV1,
        DataColumnCastValidationError,
        preview_data_column_cast,
    )

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [10, 11]}),
    )
    with pytest.raises(DataColumnCastValidationError, match="column"):
        preview_data_column_cast(
            project,
            DataColumnCastSpecV1(
                source_run_id=run_id,
                source_node_id="stage:source",
                source_artifact_id=artifact_id,
                column="missing",
                target_dtype="numeric",
            ),
        )

    with pytest.raises(ValueError, match="target_dtype"):
        DataColumnCastSpecV1(
            source_run_id=run_id,
            source_node_id="stage:source",
            source_artifact_id=artifact_id,
            column="age",
            target_dtype="python",
        )


def test_column_cast_effect_is_immutable_provenant_and_idempotent(tmp_path: Path) -> None:
    from workbench.data_operations import (
        DataColumnCastSpecV1,
        apply_data_column_cast,
        preview_data_column_cast,
    )

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "name": ["a", "b"]}),
    )
    source_path = project / "runs" / run_id / "data.csv"
    source_bytes = source_path.read_bytes()
    GraphStore(project / "runs").mutate(
        run_id,
        lambda graph: Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes={
                **graph.nodes,
                "model:ols": Node(
                    id="model:ols",
                    kind=NodeKind.MODEL,
                    display_label="OLS",
                    created_at="2026-07-15T00:00:00+00:00",
                    parent_stage_id=None,
                    branch_id="main",
                    payload_ref="model.json",
                    stage=Stage.MODEL,
                ),
            },
            edges={
                **graph.edges,
                "edge:model": Edge(
                    id="edge:model",
                    source_id="stage:source",
                    target_id="model:ols",
                    op="fit",
                ),
            },
            branches=graph.branches,
        ),
    )
    spec = DataColumnCastSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        column="age",
        target_dtype="numeric",
    )
    preview = preview_data_column_cast(project, spec)

    first = apply_data_column_cast(project, spec, preview)
    second = apply_data_column_cast(project, spec, preview)

    assert first.to_dict() == second.to_dict()
    assert source_path.read_bytes() == source_bytes
    index = json.loads(
        (project / "runs" / run_id / "artifacts_index.json").read_text()
    )
    output_records = [
        item for item in index["artifacts"] if item["artifact_id"] == first.artifact_id
    ]
    assert len(output_records) == 1
    assert output_records[0]["inputs"] == [artifact_id]
    child_frame = pd.read_csv(project / "runs" / run_id / first.artifact_path)
    assert str(child_frame["age"].dtype) == "int64"

    graph = GraphStore(project / "runs").read(run_id)
    assert graph.nodes["stage:source"].payload_ref == "data.csv"
    assert first.child_node_id in graph.nodes
    assert any(
        edge.source_id == "stage:source"
        and edge.target_id == first.child_node_id
        and edge.op == "data.column.cast"
        for edge in graph.edges.values()
    )
    assert graph.nodes["model:ols"].trust == Trust.CAUTION
    assert "rerun_required" in json.dumps(graph.nodes["model:ols"].annotations)


def test_column_cast_confirmed_operation_uses_shared_lifecycle(tmp_path: Path) -> None:
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.orchestrator import WorkbenchOrchestrator
    from workbench.agent.session import JsonlSessionRepository
    from workbench.data_operations import DataColumnCastSpecV1, preview_data_column_cast

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "name": ["a", "b"]}),
    )
    spec = DataColumnCastSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        column="age",
        target_dtype="numeric",
    )
    preview = preview_data_column_cast(project, spec)
    repository = JsonlSessionRepository(project / "workbench")
    events = AgentEventStream(project / "workbench")
    repository.create_session("agent_main", chain_id="project", role="main")
    repository.create_session("agent_data", chain_id="chain_data", role="chain")

    class NoopAdapter:
        async def stream(self, request):
            if False:
                yield request

    agent = AgentCore(repository, events, NoopAdapter(), session_id="agent_data")
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="agent_main",
    )
    orchestrator.register_chain("chain_data", "agent_data", agent)
    proposal = orchestrator.create_proposal(
        chain_id="chain_data",
        operation_id="data.column.cast",
        target={
            "run_id": run_id,
            "node_ref": spec.source_node_id,
            "artifact_id": artifact_id,
            "column": spec.column,
            "target_dtype": spec.target_dtype,
        },
        preconditions={
            "context_version": "data-column-cast.v1",
            "context_fingerprint": preview.fingerprint,
            "active_head_run_id": run_id,
            "owner_resolution": "typed_data_node",
        },
        changes={"column": spec.column, "target_dtype": spec.target_dtype},
        evidence_refs=["test:preview"],
        expected_effect=["create one child data artifact"],
        risks=["downstream model rerun required"],
    )
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="human_ui",
        current_context_fingerprint=preview.fingerprint,
        current_active_head_run_id=run_id,
    )

    completed = asyncio.run(
        orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=project,
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=run_id,
        )
    )

    assert completed.status == "completed"
    assert completed.operation_id == "data.column.cast"
    assert completed.effect_status == "committed"
    assert completed.projection_status == "complete"
    assert completed.execution["bindings"]["data_artifact_id"].startswith("data_cast_")
    assert completed.verification["passed"] is True


@pytest.mark.parametrize(
    "crash_point",
    [
        "after_claim",
        "before_child_effect",
        "after_child_effect",
        "after_effect_binding",
        "before_domain_commit",
        "after_domain_commit",
        "before_terminal_reconcile",
    ],
)
def test_column_cast_lifecycle_reconciles_without_duplicate_child_effect(
    tmp_path: Path,
    crash_point: str,
) -> None:
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.execution import InjectedOperationCrash
    from workbench.agent.orchestrator import WorkbenchOrchestrator
    from workbench.agent.session import JsonlSessionRepository
    from workbench.data_operations import DataColumnCastSpecV1, preview_data_column_cast

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "name": ["a", "b"]}),
    )
    spec = DataColumnCastSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        column="age",
        target_dtype="numeric",
    )
    preview = preview_data_column_cast(project, spec)
    repository = JsonlSessionRepository(project / "workbench")
    events = AgentEventStream(project / "workbench")
    repository.create_session("agent_main", chain_id="project", role="main")
    repository.create_session("agent_data", chain_id="chain_data", role="chain")

    class NoopAdapter:
        async def stream(self, request):
            if False:
                yield request

    class CrashOnce:
        triggered = False

        def hit(self, point: str, record) -> None:
            if point == crash_point and not self.triggered:
                self.triggered = True
                raise InjectedOperationCrash(point)

    agent = AgentCore(repository, events, NoopAdapter(), session_id="agent_data")
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="agent_main",
        failpoint=CrashOnce(),
    )
    orchestrator.register_chain("chain_data", "agent_data", agent)
    proposal = orchestrator.create_proposal(
        chain_id="chain_data",
        operation_id="data.column.cast",
        target={
            "run_id": run_id,
            "node_ref": spec.source_node_id,
            "artifact_id": artifact_id,
            "column": spec.column,
            "target_dtype": spec.target_dtype,
        },
        preconditions={
            "context_version": "data-column-cast.v1",
            "context_fingerprint": preview.fingerprint,
            "active_head_run_id": run_id,
            "owner_resolution": "typed_data_node",
        },
        changes={"column": spec.column, "target_dtype": spec.target_dtype},
        evidence_refs=["test:preview"],
        expected_effect=["create one child data artifact"],
        risks=["downstream model rerun required"],
    )
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="human_ui",
        current_context_fingerprint=preview.fingerprint,
        current_active_head_run_id=run_id,
    )

    source_sha_before = sha256_file(project / "runs" / run_id / "data.csv")
    with pytest.raises(InjectedOperationCrash):
        asyncio.run(
            orchestrator.execute_confirmed_operation(
                record.record_id,
                project_root=project,
                current_context_fingerprint=preview.fingerprint,
                current_active_head_run_id=run_id,
            )
        )
    completed = asyncio.run(
        orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=project,
            current_context_fingerprint=preview.fingerprint,
            current_active_head_run_id=run_id,
            allow_recovery=True,
        )
    )

    assert completed.status == "completed"
    assert completed.effect_status == "committed"
    assert completed.projection_status == "complete"
    records = json.loads(
        (project / "runs" / run_id / "artifacts_index.json").read_text()
    )["artifacts"]
    assert len([item for item in records if item["artifact_type"] == "derived_data"]) == 1
    source_entry = next(item for item in records if item["artifact_id"] == artifact_id)
    assert sha256_file(project / "runs" / run_id / "data.csv") == source_sha_before
    assert source_entry["sha256"] == source_sha_before
    graph = GraphStore(project / "runs").read(run_id)
    assert len([node_id for node_id in graph.nodes if node_id.startswith("data-cast:")]) == 1


def test_column_cast_child_created_at_is_real_and_node_index_updates(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from workbench.data_operations import (
        DataColumnCastSpecV1,
        apply_data_column_cast,
        preview_data_column_cast,
    )
    from workbench.lineage.node_index import NODE_INDEX_FILENAME

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "name": ["a", "b"]}),
    )
    run_root = project / "runs" / run_id
    write_json(
        run_root / NODE_INDEX_FILENAME,
        {
            "stage:source": {
                "node_hash": "a" * 64,
                "producing_stage": "cleaning",
                "cas_ref": {"node_hash": "a" * 64, "artifact": "data.csv"},
            }
        },
    )
    spec = DataColumnCastSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        column="age",
        target_dtype="numeric",
    )
    preview = preview_data_column_cast(project, spec)

    before = datetime.now(timezone.utc)
    first = apply_data_column_cast(project, spec, preview)
    index_after_first = json.loads((run_root / NODE_INDEX_FILENAME).read_text())
    second = apply_data_column_cast(project, spec, preview)

    graph = GraphStore(project / "runs").read(run_id)
    child = graph.nodes[first.child_node_id]
    created = datetime.fromisoformat(child.created_at)
    assert created.tzinfo is not None
    assert created >= before.replace(microsecond=0)
    assert child.created_at != "2026-07-15T00:00:00+00:00"

    derived_sha = sha256_file(run_root / first.artifact_path)
    index = json.loads((run_root / NODE_INDEX_FILENAME).read_text())
    assert index["stage:source"]["node_hash"] == "a" * 64
    entry = index[first.child_node_id]
    assert entry["node_hash"] == derived_sha
    assert entry["producing_stage"] == "data.column.cast"
    assert entry["cas_ref"] == {"node_hash": derived_sha, "artifact": first.artifact_path}
    assert index == index_after_first
    assert second.to_dict() == first.to_dict()


def test_column_cast_leaves_legacy_runs_without_node_index(tmp_path: Path) -> None:
    from workbench.data_operations import (
        DataColumnCastSpecV1,
        apply_data_column_cast,
        preview_data_column_cast,
    )
    from workbench.lineage.node_index import NODE_INDEX_FILENAME

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"]}),
    )
    spec = DataColumnCastSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        column="age",
        target_dtype="numeric",
    )
    preview = preview_data_column_cast(project, spec)

    apply_data_column_cast(project, spec, preview)

    assert not (project / "runs" / run_id / NODE_INDEX_FILENAME).exists()
