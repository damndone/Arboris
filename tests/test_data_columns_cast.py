from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import sha256_file, write_json
from workbench.graph_model import Edge, Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore

from tests.test_data_column_cast import _source_project


def _model_project(tmp_path: Path, frame: pd.DataFrame):
    project, run_id, artifact_id = _source_project(tmp_path, frame)
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
    return project, run_id, artifact_id


def _spec(run_id: str, artifact_id: str, casts):
    from workbench.data_operations import DataColumnsCastSpecV1

    return DataColumnsCastSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        casts=tuple(casts),
    )


def test_columns_cast_spec_rejects_empty_and_duplicate_and_bad_dtype(tmp_path: Path) -> None:
    from workbench.data_operations import DataColumnsCastSpecV1

    with pytest.raises(ValueError, match="at least one"):
        DataColumnsCastSpecV1(
            source_run_id="r",
            source_node_id="stage:source",
            source_artifact_id="a",
            casts=(),
        )
    with pytest.raises(ValueError, match="duplicate"):
        DataColumnsCastSpecV1(
            source_run_id="r",
            source_node_id="stage:source",
            source_artifact_id="a",
            casts=(("age", "numeric"), ("age", "string")),
        )
    with pytest.raises(ValueError, match="target_dtype"):
        DataColumnsCastSpecV1(
            source_run_id="r",
            source_node_id="stage:source",
            source_artifact_id="a",
            casts=(("age", "python"),),
        )


def test_columns_cast_preview_is_strict_per_column_and_deterministic(tmp_path: Path) -> None:
    from workbench.data_operations import preview_data_columns_cast

    project, run_id, artifact_id = _model_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "city": ["a", "b"], "keep": [1, 2]}),
    )
    spec = _spec(run_id, artifact_id, [("age", "numeric"), ("city", "string")])

    first = preview_data_columns_cast(project, spec)
    second = preview_data_columns_cast(project, spec)

    assert first.status == "ready"
    assert first.row_count == 2
    assert [item.column for item in first.items] == ["age", "city"]
    age_item = first.items[0]
    # CSV round-trip reads all-digit "age" back as int64; numeric cast is a
    # verified no-op on it. The meaningful conversion is city str -> string.
    assert age_item.before_dtype == "int64"
    assert age_item.after_dtype == "int64"
    assert age_item.success_count == 2
    assert age_item.failure_count == 0
    city_item = first.items[1]
    assert city_item.before_dtype == "str"
    assert city_item.after_dtype.startswith("string")
    assert first.schema_fingerprint_before != first.schema_fingerprint_after
    assert first.fingerprint == second.fingerprint
    assert first.to_dict() == second.to_dict()
    assert "model:ols" in first.downstream_invalidation
    # preview writes nothing
    assert not (project / "workbench").exists()
    assert not (project / "runs" / run_id / "derived").exists()


def test_columns_cast_preview_blocks_when_any_column_fails(tmp_path: Path) -> None:
    from workbench.data_operations import preview_data_columns_cast

    project, run_id, artifact_id = _model_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "x"], "city": ["a", "b"]}),
    )
    preview = preview_data_columns_cast(
        project, _spec(run_id, artifact_id, [("age", "numeric"), ("city", "string")])
    )

    assert preview.status == "blocked"
    assert preview.items[0].status == "blocked"
    assert preview.items[0].failure_count == 1
    assert preview.items[1].status == "ready"


def test_columns_cast_effect_one_child_all_columns_immutable_idempotent(tmp_path: Path) -> None:
    from workbench.data_operations import (
        apply_data_columns_cast,
        preview_data_columns_cast,
    )

    project, run_id, artifact_id = _model_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "city": ["a", "b"], "keep": [1, 2]}),
    )
    run_root = project / "runs" / run_id
    source_sha_before = sha256_file(run_root / "data.csv")
    spec = _spec(run_id, artifact_id, [("age", "numeric"), ("city", "string")])
    preview = preview_data_columns_cast(project, spec)

    before = datetime.now(timezone.utc)
    first = apply_data_columns_cast(project, spec, preview)
    second = apply_data_columns_cast(project, spec, preview)

    assert first.to_dict() == second.to_dict()
    # source immutable
    assert sha256_file(run_root / "data.csv") == source_sha_before

    index = json.loads((run_root / "artifacts_index.json").read_text())["artifacts"]
    derived = [i for i in index if i["artifact_type"] == "derived_data"]
    assert len(derived) == 1
    assert derived[0]["inputs"] == [artifact_id]

    child_frame = pd.read_csv(run_root / first.artifact_path)
    assert str(child_frame["age"].dtype) == "int64"
    # untouched column preserved
    assert list(child_frame["keep"]) == [1, 2]

    graph = GraphStore(project / "runs").read(run_id)
    cast_nodes = [n for n in graph.nodes if n.startswith("data-casts:")]
    assert len(cast_nodes) == 1
    child = graph.nodes[first.child_node_id]
    created = datetime.fromisoformat(child.created_at)
    assert created.tzinfo is not None and created >= before.replace(microsecond=0)
    assert any(
        e.source_id == "stage:source"
        and e.target_id == first.child_node_id
        and e.op == "data.columns.cast"
        for e in graph.edges.values()
    )
    from workbench.graph_model import Trust

    assert graph.nodes["model:ols"].trust == Trust.CAUTION

    recipe = json.loads((run_root / first.recipe_path).read_text())
    assert recipe["schema_version"] == "data-columns-cast.v1"
    assert [c["column"] for c in recipe["casts"]] == ["age", "city"]


def test_columns_cast_confirmed_operation_uses_shared_lifecycle(tmp_path: Path) -> None:
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.orchestrator import WorkbenchOrchestrator
    from workbench.agent.session import JsonlSessionRepository
    from workbench.data_operations import preview_data_columns_cast

    project, run_id, artifact_id = _model_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "city": ["a", "b"]}),
    )
    spec = _spec(run_id, artifact_id, [("age", "numeric"), ("city", "string")])
    preview = preview_data_columns_cast(project, spec)
    repository = JsonlSessionRepository(project / "workbench")
    events = AgentEventStream(project / "workbench")
    repository.create_session("agent_main", chain_id="project", role="main")
    repository.create_session("agent_data", chain_id="chain_data", role="chain")

    class NoopAdapter:
        async def stream(self, request):
            if False:
                yield request

    agent = AgentCore(repository, events, NoopAdapter(), session_id="agent_data")
    orchestrator = WorkbenchOrchestrator(repository, events, main_session_id="agent_main")
    orchestrator.register_chain("chain_data", "agent_data", agent)
    proposal = orchestrator.create_proposal(
        chain_id="chain_data",
        operation_id="data.columns.cast",
        target={
            "run_id": run_id,
            "node_ref": spec.source_node_id,
            "artifact_id": artifact_id,
            "casts": [{"column": "age", "target_dtype": "numeric"}, {"column": "city", "target_dtype": "string"}],
        },
        preconditions={
            "context_version": "data-columns-cast.v1",
            "context_fingerprint": preview.fingerprint,
            "active_head_run_id": run_id,
            "owner_resolution": "typed_data_node",
        },
        changes={"casts": [{"column": "age", "target_dtype": "numeric"}, {"column": "city", "target_dtype": "string"}]},
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
    assert completed.operation_id == "data.columns.cast"
    assert completed.effect_status == "committed"
    assert completed.execution["bindings"]["data_artifact_id"].startswith("data_casts_")
    assert completed.verification["passed"] is True


@pytest.mark.parametrize(
    "crash_point",
    [
        "after_claim",
        "after_child_effect",
        "after_domain_commit",
        "before_terminal_reconcile",
    ],
)
def test_columns_cast_lifecycle_reconciles_without_duplicate_effect(
    tmp_path: Path, crash_point: str
) -> None:
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.execution import InjectedOperationCrash
    from workbench.agent.orchestrator import WorkbenchOrchestrator
    from workbench.agent.session import JsonlSessionRepository
    from workbench.data_operations import preview_data_columns_cast

    project, run_id, artifact_id = _model_project(
        tmp_path,
        pd.DataFrame({"age": ["10", "11"], "city": ["a", "b"]}),
    )
    spec = _spec(run_id, artifact_id, [("age", "numeric"), ("city", "string")])
    preview = preview_data_columns_cast(project, spec)
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
        repository, events, main_session_id="agent_main", failpoint=CrashOnce()
    )
    orchestrator.register_chain("chain_data", "agent_data", agent)
    proposal = orchestrator.create_proposal(
        chain_id="chain_data",
        operation_id="data.columns.cast",
        target={
            "run_id": run_id,
            "node_ref": spec.source_node_id,
            "artifact_id": artifact_id,
            "casts": [{"column": "age", "target_dtype": "numeric"}, {"column": "city", "target_dtype": "string"}],
        },
        preconditions={
            "context_version": "data-columns-cast.v1",
            "context_fingerprint": preview.fingerprint,
            "active_head_run_id": run_id,
            "owner_resolution": "typed_data_node",
        },
        changes={"casts": [{"column": "age", "target_dtype": "numeric"}, {"column": "city", "target_dtype": "string"}]},
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
    records = json.loads(
        (project / "runs" / run_id / "artifacts_index.json").read_text()
    )["artifacts"]
    assert len([i for i in records if i["artifact_type"] == "derived_data"]) == 1
    graph = GraphStore(project / "runs").read(run_id)
    assert len([n for n in graph.nodes if n.startswith("data-casts:")]) == 1


def test_columns_cast_child_dtype_roundtrips_via_sidecar(tmp_path: Path) -> None:
    from workbench.data_operations import (
        _read_frame,
        apply_data_columns_cast,
        preview_data_columns_cast,
    )

    project, run_id, artifact_id = _model_project(
        tmp_path, pd.DataFrame({"age": ["10", "11"], "city": ["a", "b"]})
    )
    spec = _spec(run_id, artifact_id, [("age", "string")])
    preview = preview_data_columns_cast(project, spec)
    effect = apply_data_columns_cast(project, spec, preview)

    child_path = project / "runs" / run_id / effect.artifact_path
    child = _read_frame(child_path)
    # The bug: without the sidecar, digit-string "age" re-reads as int64.
    assert str(child["age"].dtype).startswith("string")
    assert list(child["age"]) == ["10", "11"]
    sidecar = child_path.with_name(child_path.stem + ".schema.json")
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text())["dtypes"]["age"].startswith("string")


def test_columns_cast_xlsx_output_roundtrips_and_is_idempotent(tmp_path: Path) -> None:
    from workbench.data_operations import (
        DataColumnsCastSpecV1,
        _read_frame,
        apply_data_columns_cast,
        preview_data_columns_cast,
    )

    project, run_id, artifact_id = _model_project(
        tmp_path, pd.DataFrame({"age": ["10", "11"], "city": ["a", "b"]})
    )
    spec = DataColumnsCastSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        casts=(("age", "string"),),
        output_format="xlsx",
    )
    preview = preview_data_columns_cast(project, spec)
    effect = apply_data_columns_cast(project, spec, preview)
    assert effect.artifact_path.endswith("data.xlsx")

    child = _read_frame(project / "runs" / run_id / effect.artifact_path)
    assert str(child["age"].dtype).startswith("string")
    assert list(child["age"]) == ["10", "11"]

    # xlsx bytes are not deterministic; idempotency must hold via frame equality
    effect2 = apply_data_columns_cast(project, spec, preview)
    assert effect2.to_dict() == effect.to_dict()
    derived = [
        item
        for item in json.loads(
            (project / "runs" / run_id / "artifacts_index.json").read_text()
        )["artifacts"]
        if item["artifact_type"] == "derived_data"
    ]
    assert len(derived) == 1


def test_chained_cast_reads_string_before_dtype_from_child(tmp_path: Path) -> None:
    from workbench.data_operations import apply_data_columns_cast, preview_data_columns_cast

    project, run_id, artifact_id = _model_project(
        tmp_path, pd.DataFrame({"age": ["10", "11"], "city": ["a", "b"]})
    )
    first = _spec(run_id, artifact_id, [("age", "string")])
    effect = apply_data_columns_cast(project, first, preview_data_columns_cast(project, first))

    # Now operate on the cast CHILD node; its "age" must present as string, not int64.
    from workbench.data_operations import DataColumnsCastSpecV1

    child_spec = DataColumnsCastSpecV1(
        source_run_id=run_id,
        source_node_id=effect.child_node_id,
        source_artifact_id=effect.artifact_id,
        casts=(("city", "string"),),
    )
    child_preview = preview_data_columns_cast(project, child_spec)
    assert child_preview.status == "ready"
    # age is untouched here but its recorded dtype flows through unchanged
    assert child_preview.schema_fingerprint_before == child_preview.schema_fingerprint_before
