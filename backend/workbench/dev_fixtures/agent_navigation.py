"""Seed a real Agent/Graph navigation relationship for local smoke tests.

This module intentionally uses the same stores and orchestration seams as the
Workbench application.  It does not create synthetic graph files, call an LLM,
or modify an existing project.  The caller supplies a fresh scratch directory;
the production run and confirmed-rerun paths then create the durable records.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from ..agent.context_tools import NodeOperationContextProvider
from ..agent.core import AgentCore
from ..agent.events import AgentEventStream
from ..agent.navigation import AgentNavigationProjector
from ..agent.orchestrator import WorkbenchOrchestrator
from ..agent.session import JsonlSessionRepository
from ..artifacts import read_json, write_json
from ..events import get_event_manager
from ..graph_store import GraphStore
from ..lineage.node_write_validation import build_rerun_operation_context
from ..projects import create_project
from ..services.run_service import _submit_run


TERMINAL_RUN_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "interrupted", "partial", "blocked"}
)
DEFAULT_DATASET = (
    Path(__file__).resolve().parents[3] / "examples" / "datasets" / "cross_section.csv"
)


@dataclass(frozen=True)
class AgentNavigationSmokeFixture:
    """Durable IDs and browser selectors produced by the seeder."""

    project_root: Path
    source_run_id: str
    child_run_id: str
    source_node_ref: str
    source_node_hash: str
    source_forest_node_key: str
    child_forest_node_key: str
    main_session_id: str
    source_session_id: str
    child_session_id: str
    source_chain_id: str
    child_chain_id: str
    operation_record_id: str
    execution_key: str
    proposal_id: str
    fork_id: str
    source_message_entry_id: str
    effect_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["project_root"] = str(self.project_root)
        value["manifest_path"] = str(self.project_root / "workbench" / "agent-navigation-smoke.json")
        project_root = str(self.project_root)
        value["urls"] = {
            "source_graph": _browser_url(
                self.source_run_id,
                project_root=project_root,
                focus=self.source_forest_node_key,
            ),
            "source_agent": _browser_url(
                self.source_run_id,
                project_root=project_root,
                panel="agent",
                agent_session=self.source_session_id,
                agent_entry=self.source_message_entry_id,
                operation=self.operation_record_id,
            ),
            "operation": _browser_url(
                self.source_run_id,
                project_root=project_root,
                panel="agent",
                agent_session=self.source_session_id,
                operation=self.operation_record_id,
            ),
            "child_graph": _browser_url(
                self.child_run_id,
                project_root=project_root,
                focus=self.child_forest_node_key,
            ),
            "child_agent": _browser_url(
                self.child_run_id,
                project_root=project_root,
                panel="agent",
                agent_session=self.child_session_id,
            ),
        }
        value["proxy_scope"] = {
            "project_root_query": project_root,
            "api_prefix": "/api",
            "backend_target": "http://127.0.0.1:8000",
        }
        return value


@dataclass(frozen=True)
class AgentRerunSmokeFixture:
    """A fresh graph/session with one pending model.rerun proposal."""

    project_root: Path
    source_run_id: str
    source_node_ref: str
    source_node_hash: str
    source_forest_node_key: str
    session_id: str
    chain_id: str
    proposal_id: str
    source_message_entry_id: str

    def to_dict(self) -> dict[str, Any]:
        project_root = str(self.project_root)
        value = asdict(self)
        value["project_root"] = project_root
        value["manifest_path"] = str(
            self.project_root / "workbench" / "agent-rerun-smoke.json"
        )
        value["urls"] = {
            "source_graph": _browser_url(
                self.source_run_id,
                project_root=project_root,
                focus=self.source_forest_node_key,
            ),
            "source_agent": _browser_url(
                self.source_run_id,
                project_root=project_root,
                panel="agent",
                agent_session=self.session_id,
                agent_entry=self.source_message_entry_id,
            ),
        }
        value["proxy_scope"] = {
            "project_root_query": project_root,
            "api_prefix": "/api",
            "backend_target": "http://127.0.0.1:8000",
        }
        return value


class _NoopModelAdapter:
    """Satisfy AgentCore's adapter seam without making a provider request."""

    async def stream(self, request):
        if False:
            yield request


def seed_agent_navigation_fixture(
    project_root: Path | str,
    *,
    input_file: Path | str | None = None,
    timeout_s: float = 120.0,
) -> AgentNavigationSmokeFixture:
    """Create one complete, local Agent navigation fixture.

    ``project_root`` must not contain any entries.  A non-empty directory is
    rejected before any Workbench storage is created so a smoke command cannot
    overwrite a user's project by accident.
    """

    root = Path(project_root).expanduser().resolve()
    _assert_empty_project(root)
    dataset = Path(input_file).expanduser().resolve() if input_file else DEFAULT_DATASET
    if not dataset.is_file():
        raise ValueError(f"fixture input file does not exist: {dataset}")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    create_project(root.parent, root.name)
    original_cache_flag = os.environ.get("WORKBENCH_INCREMENTAL_CACHE")
    os.environ["WORKBENCH_INCREMENTAL_CACHE"] = "1"
    try:
        source_run_id = _seed_source_run(root, dataset, timeout_s=timeout_s)
        source_node_ref = _model_node_ref(root, source_run_id)
        context = build_rerun_operation_context(
            root / "runs",
            request_id="agent-navigation-smoke-context",
            owner_run_id=source_run_id,
            op_node_id=source_node_ref,
            active_head_run_id=source_run_id,
        )

        workbench_root = root / "workbench"
        repository = JsonlSessionRepository(workbench_root)
        main_session_id = "agent_main"
        source_session_id = "agent_chain_navigation_smoke"
        source_chain_id = "chain_navigation_smoke"
        repository.create_session(main_session_id, chain_id="project", role="main")
        repository.create_session(
            source_session_id,
            chain_id=source_chain_id,
            role="chain",
        )
        source_message = repository.append(
            source_session_id,
            "message",
            {
                "role": "user",
                "content": (
                    "检查这个 OLS 模型，并准备一个只修改 covariance 的可审计 rerun 提案。"
                ),
                "command_id": "command_navigation_smoke",
            },
        )
        events = AgentEventStream(workbench_root)
        agent = AgentCore(
            repository,
            events,
            _NoopModelAdapter(),
            session_id=source_session_id,
        )
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id=main_session_id,
            context_provider=NodeOperationContextProvider(root),
        )
        orchestrator.register_chain(source_chain_id, source_session_id, agent)

        proposal = orchestrator.create_proposal(
            chain_id=source_chain_id,
            operation_id="model.rerun",
            target={
                "run_id": source_run_id,
                "node_ref": source_node_ref,
                "node_hash": context.node_hash,
                # Production operation records use the canonical hash.  The
                # browser selector below is the separate hash::node_ref key.
                "forest_node_key": context.forest_node_key,
            },
            preconditions={
                "context_version": context.context_version,
                "context_fingerprint": context.context_fingerprint,
                "active_head_run_id": context.active_head_run_id,
                "owner_resolution": context.owner_resolution,
                "run_family_id": f"legacy-family:{source_run_id}",
            },
            changes={"covariance": {"old": "robust", "new": "unadjusted"}},
            evidence_refs=["diagnostic:heteroskedasticity:smoke-fixture"],
            expected_effect=["standard errors may change"],
            risks=["inference assumptions change"],
            command_id="command_navigation_smoke",
            proposal_id="proposal_navigation_smoke",
        )
        operation = orchestrator.confirm_proposal(
            proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="user",
            current_context_fingerprint=context.context_fingerprint,
            current_active_head_run_id=source_run_id,
        )
        operation = asyncio.run(
            orchestrator.execute_confirmed_proposal(
                operation.record_id,
                current_context_fingerprint=context.context_fingerprint,
                current_active_head_run_id=source_run_id,
                executor=orchestrator.model_rerun_executor(root),
            )
        )
        child_run_id = str(operation.outputs.get("target_run_id") or "")
        if not child_run_id:
            raise RuntimeError("fixture rerun did not persist a child run id")
        _wait_for_terminal_run(root, child_run_id, timeout_s=timeout_s)
        operation = asyncio.run(
            orchestrator.reconcile_confirmed_proposal(
                operation.record_id,
                project_root=root,
            )
        )
        if operation.status != "completed":
            raise RuntimeError(
                f"fixture operation did not reconcile: {operation.status} "
                f"{operation.error or ''}".strip()
            )

        child_session_id = str(operation.execution["child_session_id"])
        repository.append(
            child_session_id,
            "message",
            {
                "role": "assistant",
                "content": (
                    "Child Agent 已继承该分叉上下文；operation record 已完成并通过确定性校验。"
                ),
            },
        )
        child_node_ref = _model_node_ref(root, child_run_id)
        child_node_hash = _indexed_node_hash(root, child_run_id, child_node_ref)
        fixture = AgentNavigationSmokeFixture(
            project_root=root,
            source_run_id=source_run_id,
            child_run_id=child_run_id,
            source_node_ref=source_node_ref,
            source_node_hash=context.node_hash,
            source_forest_node_key=f"{context.node_hash}::{source_node_ref}",
            child_forest_node_key=f"{child_node_hash}::{child_node_ref}",
            main_session_id=main_session_id,
            source_session_id=source_session_id,
            child_session_id=child_session_id,
            source_chain_id=source_chain_id,
            child_chain_id=str(operation.execution["child_chain_id"]),
            operation_record_id=operation.record_id,
            execution_key=str(operation.execution["execution_key"]),
            proposal_id=proposal.proposal_id,
            fork_id=str(operation.execution["fork_id"]),
            source_message_entry_id=source_message.entry_id,
            effect_counts={
                "child_runs": 1,
                "forks": 1,
                "child_chains": 1,
                "child_agent_sessions": 1,
            },
        )
        _write_fixture_manifest(fixture)
        _assert_fixture_navigation(fixture)
        return fixture
    finally:
        if original_cache_flag is None:
            os.environ.pop("WORKBENCH_INCREMENTAL_CACHE", None)
        else:
            os.environ["WORKBENCH_INCREMENTAL_CACHE"] = original_cache_flag


def seed_agent_rerun_smoke_fixture(
    project_root: Path | str,
    *,
    input_file: Path | str | None = None,
    timeout_s: float = 120.0,
) -> AgentRerunSmokeFixture:
    """Create a fresh source graph and one pending typed rerun proposal.

    This is deliberately separate from the completed navigation fixture: the
    browser owns confirmation and execution for this smoke, while the seeder
    only uses production run, session, proposal, and context contracts.
    """

    root = Path(project_root).expanduser().resolve()
    _assert_empty_project(root)
    dataset = Path(input_file).expanduser().resolve() if input_file else DEFAULT_DATASET
    if not dataset.is_file():
        raise ValueError(f"fixture input file does not exist: {dataset}")
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")

    create_project(root.parent, root.name)
    original_cache_flag = os.environ.get("WORKBENCH_INCREMENTAL_CACHE")
    os.environ["WORKBENCH_INCREMENTAL_CACHE"] = "1"
    try:
        source_run_id = _seed_source_run(root, dataset, timeout_s=timeout_s)
        source_node_ref = _model_node_ref(root, source_run_id)
        context = build_rerun_operation_context(
            root / "runs",
            request_id="agent-rerun-smoke-context",
            owner_run_id=source_run_id,
            op_node_id=source_node_ref,
            active_head_run_id=source_run_id,
        )
        workbench_root = root / "workbench"
        repository = JsonlSessionRepository(workbench_root)
        main_session_id = "agent_main"
        session_id = "agent_chain_rerun_smoke"
        chain_id = "chain_rerun_smoke"
        repository.create_session(main_session_id, chain_id="project", role="main")
        repository.create_session(session_id, chain_id=chain_id, role="chain")
        source_message = repository.append(
            session_id,
            "message",
            {
                "role": "user",
                "content": "请确认这个预制的 covariance rerun 提案。",
            },
        )
        events = AgentEventStream(workbench_root)
        agent = AgentCore(
            repository,
            events,
            _NoopModelAdapter(),
            session_id=session_id,
        )
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id=main_session_id,
            context_provider=NodeOperationContextProvider(root),
        )
        orchestrator.register_chain(chain_id, session_id, agent)
        proposal = orchestrator.create_proposal(
            chain_id=chain_id,
            operation_id="model.rerun",
            target={
                "run_id": source_run_id,
                "node_ref": source_node_ref,
                "node_hash": context.node_hash,
                "forest_node_key": context.forest_node_key,
            },
            preconditions={
                "context_version": context.context_version,
                "context_fingerprint": context.context_fingerprint,
                "active_head_run_id": source_run_id,
                "owner_resolution": context.owner_resolution,
                "run_family_id": f"legacy-family:{source_run_id}",
            },
            changes={"covariance": {"old": "robust", "new": "unadjusted"}},
            evidence_refs=["fixture:pending-rerun"],
            expected_effect=["create exactly one child run with updated covariance"],
            risks=["inference assumptions change"],
            proposal_id="proposal_rerun_smoke",
        )
        fixture = AgentRerunSmokeFixture(
            project_root=root,
            source_run_id=source_run_id,
            source_node_ref=source_node_ref,
            source_node_hash=context.node_hash,
            source_forest_node_key=f"{context.node_hash}::{source_node_ref}",
            session_id=session_id,
            chain_id=chain_id,
            proposal_id=proposal.proposal_id,
            source_message_entry_id=source_message.entry_id,
        )
        write_json(
            root / "workbench" / "agent-rerun-smoke.json",
            {
                "schema_version": "agent-rerun-smoke.v1",
                "fixture": fixture.to_dict(),
                "provider": "noop_local_adapter",
                "confirmation": "browser_required",
                "expected_effects": ["one child run", "diff", "verification"],
            },
        )
        return fixture
    finally:
        if original_cache_flag is None:
            os.environ.pop("WORKBENCH_INCREMENTAL_CACHE", None)
        else:
            os.environ["WORKBENCH_INCREMENTAL_CACHE"] = original_cache_flag


def _assert_empty_project(root: Path) -> None:
    if root.exists() and not root.is_dir():
        raise ValueError(f"fixture project root is not a directory: {root}")
    if root.is_dir() and any(root.iterdir()):
        raise ValueError(f"fixture project root must be non-empty scratch directory: {root}")


def _seed_source_run(root: Path, dataset: Path, *, timeout_s: float) -> str:
    events = get_event_manager()
    deadline = time.monotonic() + timeout_s
    while not events.try_acquire_slot():
        if time.monotonic() >= deadline:
            raise TimeoutError("timed out waiting for the Workbench run slot")
        time.sleep(0.05)
    try:
        result = _submit_run(
            root,
            form={
                "mode": "auto",
                "model_type": "ols",
                "covariance": "robust",
                "y": "wage",
                "x": "education,experience",
            },
            upload_bytes=dataset.read_bytes(),
            upload_filename=dataset.name,
            started_at="agent-navigation-smoke",
        )
    except Exception:
        events.release_slot(None)
        raise
    run_id = result["run_id"]
    _wait_for_terminal_run(root, run_id, timeout_s=timeout_s)
    return run_id


def _wait_for_terminal_run(root: Path, run_id: str, *, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    manifest_path = root / "runs" / run_id / "run_manifest.json"
    while True:
        manifest = read_json(manifest_path)
        status = manifest.get("status")
        if status in TERMINAL_RUN_STATUSES:
            if status != "completed":
                errors = read_json(root / "runs" / run_id / "errors.json")
                raise RuntimeError(f"fixture run {run_id} ended {status}: {errors}")
            return manifest
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for fixture run {run_id}")
        time.sleep(0.05)


def _model_node_ref(root: Path, run_id: str) -> str:
    graph = GraphStore(root / "runs").read(run_id)
    candidates = [
        node_id
        for node_id, node in graph.nodes.items()
        if getattr(node.stage, "value", node.stage) == "model"
    ]
    if not candidates:
        raise RuntimeError(f"fixture run {run_id} has no model graph node")
    return sorted(candidates)[0]


def _indexed_node_hash(root: Path, run_id: str, node_ref: str) -> str:
    index = read_json(root / "runs" / run_id / "node_index.json")
    try:
        value = index[node_ref]["node_hash"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"fixture run {run_id} has no indexed node {node_ref}") from exc
    return str(value)


def _write_fixture_manifest(fixture: AgentNavigationSmokeFixture) -> None:
    payload = {
        "schema_version": "agent-navigation-smoke.v2",
        "fixture": fixture.to_dict(),
        "recovery_contract": {
            "execution_key": fixture.execution_key,
            "crash_points": [
                "after_claim",
                "before_child_effect",
                "after_child_effect",
                "after_effect_binding",
                "before_domain_commit",
                "after_domain_commit",
                "before_terminal_reconcile",
            ],
            "projection_recovery": {
                "effect_status": "committed before terminal projection",
                "projection_status": "pending until terminal record is durable",
            },
            "jsonl_tail": "ignore only an unterminated final record",
            "deployment": "single_worker_only",
            "same_proposal_effects": "zero-or-one",
            "competing_active_head": "fail-closed",
        },
        "links": [
            "graph node -> source Agent message",
            "source Agent message -> operation record",
            "operation record -> fork -> child run",
            "child run -> child graph -> child Agent",
        ],
    }
    write_json(fixture.project_root / "workbench" / "agent-navigation-smoke.json", payload)


def _browser_url(run_id: str, *, project_root: str, **params: str) -> str:
    query = {"project_root": project_root, "tab": "lineage", **params}
    return f"http://localhost:5173/runs/{run_id}?{urlencode(query)}"


def _assert_fixture_navigation(fixture: AgentNavigationSmokeFixture) -> None:
    projector = AgentNavigationProjector(fixture.project_root)
    source_projection = projector.graph(
        run_id=fixture.source_run_id,
        node_ref=fixture.source_node_ref,
        forest_node_key=fixture.source_forest_node_key,
    )
    source_kinds = {link.kind for link in source_projection.links if link.available}
    required_source = {"agent_session", "operation", "run", "fork"}
    if not required_source <= source_kinds:
        raise RuntimeError(
            "fixture navigation missing source links: "
            f"{sorted(required_source - source_kinds)}"
        )
    message_projection = projector.entry(
        fixture.source_session_id,
        fixture.source_message_entry_id,
    )
    if not any(
        link.kind == "operation" and link.id == fixture.operation_record_id
        for link in message_projection.links
    ):
        raise RuntimeError("fixture navigation did not link source message to operation")
    child_projection = projector.graph(
        run_id=fixture.child_run_id,
        node_ref=fixture.source_node_ref,
        forest_node_key=fixture.child_forest_node_key,
    )
    if not any(
        link.kind == "agent_session" and link.id == fixture.child_session_id
        for link in child_projection.links
    ):
        raise RuntimeError("fixture navigation did not link child graph to child Agent")
