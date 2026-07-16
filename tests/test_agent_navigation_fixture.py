from __future__ import annotations

import json
from pathlib import Path

from workbench.agent.navigation import AgentNavigationProjector
from workbench.agent.operations import OperationRecordStore
from workbench.agent.proposals import ProposalStore
from workbench.dev_fixtures.agent_navigation import (
    seed_agent_navigation_fixture,
    seed_agent_rerun_smoke_fixture,
)


DATASET = Path(__file__).resolve().parents[1] / "examples" / "datasets" / "cross_section.csv"


def test_seed_agent_navigation_fixture_creates_real_linked_records(tmp_path: Path) -> None:
    fixture = seed_agent_navigation_fixture(
        tmp_path / "agent-navigation-smoke",
        input_file=DATASET,
    )

    source_run = fixture.project_root / "runs" / fixture.source_run_id
    child_run = fixture.project_root / "runs" / fixture.child_run_id
    assert json.loads((source_run / "run_manifest.json").read_text())[
        "status"
    ] == "completed"
    assert json.loads((child_run / "run_manifest.json").read_text())["status"] == "completed"

    child_inputs = json.loads((child_run / "run_inputs.json").read_text())
    assert child_inputs["rerun_of"] == fixture.source_run_id
    assert child_inputs["from_node"] == fixture.source_node_ref
    assert child_inputs["workbench_context"]["operation_record_id"] == fixture.operation_record_id

    operation = OperationRecordStore(fixture.project_root / "workbench").get(
        fixture.operation_record_id
    )
    assert operation.status == "completed"
    assert operation.execution["execution_key"] == fixture.execution_key
    assert operation.outputs["target_run_id"] == fixture.child_run_id
    assert operation.verification["passed"] is True

    proposal = ProposalStore(fixture.project_root / "workbench").latest_revision(
        fixture.proposal_id
    )
    assert proposal.status == "pending"

    fork = json.loads(
        (fixture.project_root / "workbench" / "forks" / f"{fixture.fork_id}.json").read_text()
    )
    chain = json.loads(
        (
            fixture.project_root
            / "workbench"
            / "chains"
            / f"{fixture.child_chain_id}.json"
        ).read_text()
    )
    assert fork["child_chain_id"] == fixture.child_chain_id
    assert fork["child_session_id"] == fixture.child_session_id
    assert chain["active_head_run_id"] == fixture.child_run_id
    assert chain["status"] == "active"
    manifest = json.loads(
        (fixture.project_root / "workbench" / "agent-navigation-smoke.json").read_text()
    )
    assert manifest["schema_version"] == "agent-navigation-smoke.v2"
    assert manifest["fixture"]["effect_counts"] == {
        "child_agent_sessions": 1,
        "child_chains": 1,
        "child_runs": 1,
        "forks": 1,
    }
    assert manifest["recovery_contract"]["same_proposal_effects"] == "zero-or-one"

    source_projection = AgentNavigationProjector(fixture.project_root).graph(
        run_id=fixture.source_run_id,
        node_ref=fixture.source_node_ref,
        forest_node_key=fixture.source_forest_node_key,
    )
    source_kinds = {link.kind for link in source_projection.links if link.available}
    assert {"agent_session", "operation", "run", "fork"} <= source_kinds

    message_projection = AgentNavigationProjector(fixture.project_root).entry(
        fixture.source_session_id,
        fixture.source_message_entry_id,
    )
    assert any(
        link.kind == "operation" and link.id == fixture.operation_record_id
        for link in message_projection.links
    )

    child_projection = AgentNavigationProjector(fixture.project_root).graph(
        run_id=fixture.child_run_id,
        node_ref=fixture.source_node_ref,
        forest_node_key=fixture.child_forest_node_key,
    )
    assert any(
        link.kind == "agent_session" and link.id == fixture.child_session_id
        for link in child_projection.links
    )


def test_seed_agent_navigation_fixture_refuses_nonempty_project(tmp_path: Path) -> None:
    project_root = tmp_path / "existing-project"
    project_root.mkdir()
    (project_root / "user-data.txt").write_text("preserve me", encoding="utf-8")

    try:
        seed_agent_navigation_fixture(project_root, input_file=DATASET)
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("seeder overwrote a non-empty project")

    assert (project_root / "user-data.txt").read_text(encoding="utf-8") == "preserve me"


def test_seed_agent_rerun_smoke_fixture_leaves_one_pending_typed_proposal(
    tmp_path: Path,
) -> None:
    fixture = seed_agent_rerun_smoke_fixture(
        tmp_path / "agent-rerun-smoke",
        input_file=DATASET,
    )

    proposal_store = ProposalStore(fixture.project_root / "workbench")
    proposal = proposal_store.latest_revision(fixture.proposal_id)

    assert proposal.operation_id == "model.rerun"
    assert proposal.status == "pending"
    assert proposal.target["run_id"] == fixture.source_run_id
    assert proposal.target["node_ref"] == fixture.source_node_ref
    assert proposal.preconditions["active_head_run_id"] == fixture.source_run_id
    assert not list((fixture.project_root / "workbench" / "operation-records").glob("*.jsonl"))
    assert json.loads(
        (fixture.project_root / "workbench" / "agent-rerun-smoke.json").read_text()
    )["schema_version"] == "agent-rerun-smoke.v1"
