"""Startup discovers registered projects without executing an analysis or provider."""
import asyncio
import importlib
from pathlib import Path

from workbench.agent.turn_store import TurnStore


def _catalog(directory):
    assert importlib.util.find_spec("workbench.agent.startup_recovery") is not None, (
        "M1 needs a persistent project catalog and startup orphan reconciliation"
    )
    return importlib.import_module("workbench.agent.startup_recovery").RecoveryProjectCatalog(directory)


def _running(project, *, pending=True):
    project.mkdir()
    store = TurnStore(project)
    record = store.create("session", "entry", budget={"max_steps": 8, "timeout_s": 300})
    record = store.claim(record.turn_id, expected_version=record.version, owner="old", lease_seconds=360)
    record = store.transition(record.turn_id, "running", expected_version=record.version,
                              owner="old", fence=record.lease_epoch)
    record = store.checkpoint(record.turn_id, expected_version=record.version, owner="old",
        fence=record.lease_epoch, steps_used=3, wall_s_used=17, checkpoint={"entry_id": "checkpoint"})
    if pending:
        record = store.record_tool_call(record.turn_id, "call", operation_key=None,
            checkpoint={"entry_id": "tool_intent"}, expected_version=record.version,
            owner="old", fence=record.lease_epoch)
    return store, record


def test_registered_projects_survive_catalog_restart_and_remember_is_idempotent(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    catalog = _catalog(tmp_path / "catalog")
    catalog.remember(project)
    catalog.remember(project)
    assert [Path(item["canonical_path"]) for item in _catalog(tmp_path / "catalog").projects()] == [project]


def test_startup_interrupts_orphan_without_refunding_budget_or_touching_receipts(tmp_path, monkeypatch):
    store, original = _running(tmp_path / "project")
    catalog = _catalog(tmp_path / "catalog")
    catalog.remember(tmp_path / "project")
    monkeypatch.setenv("WORKBENCH_AGENT_RECOVERY_DIR", str(tmp_path / "catalog"))
    from workbench.app import app
    from workbench.http import agent_turn_routes

    def forbidden(*args, **kwargs):
        raise AssertionError("Startup reconciliation must not load a provider or execute a model")

    monkeypatch.setattr(agent_turn_routes, "_agent_llm_config", forbidden)
    monkeypatch.setattr(agent_turn_routes, "_agent_model_adapter", forbidden)

    async def start():
        async with app.router.lifespan_context(app):
            return app.state.agent_startup_recovery

    outcomes = asyncio.run(start())
    final = store.get(original.turn_id)
    assert final.status == "interrupted" and final.requires_reconcile
    for field in ("command_id", "input_entry_id", "steps_used", "wall_s_used", "checkpoint", "tool_calls", "budget"):
        assert getattr(final, field) == getattr(original, field)
    assert any(outcome.get("turn_id") == original.turn_id and outcome["status"] == "interrupted" for outcome in outcomes)
    assert catalog.reconcile() == []


def test_startup_does_not_steal_live_local_execution(tmp_path):
    project = tmp_path / "project"
    store, original = _running(project)
    catalog = _catalog(tmp_path / "catalog")
    catalog.remember(project)
    with store.execution_guard("session"):
        outcomes = catalog.reconcile()
    assert store.get(original.turn_id) == original
    assert outcomes[0]["status"] == "busy"


def test_startup_preserves_awaiting_approval_and_original_checkpoint(tmp_path):
    project = tmp_path / "project"
    store, original = _running(project, pending=False)
    original = store.transition(original.turn_id, "awaiting_approval", expected_version=original.version,
                                owner="old", fence=original.lease_epoch)
    catalog = _catalog(tmp_path / "catalog")
    catalog.remember(project)
    assert catalog.reconcile() == []
    assert store.get(original.turn_id) == original


def test_replaced_project_root_is_reported_without_opening_new_turn_storage(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    catalog = _catalog(tmp_path / "catalog")
    catalog.remember(project)
    project.rename(tmp_path / "original-project")
    project.mkdir()
    assert catalog.reconcile()[0]["status"] == "project_binding_changed"
    assert not (project / "workbench").exists()


def test_accepted_headless_command_registers_its_project(tmp_path, monkeypatch):
    from tests.test_agent_routes import _config
    from tests.test_read_only_analysis import _Fixture
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.runtime_adapter import headless_runtime_scope
    from workbench.cli_agent import run_headless

    fixture = _Fixture(tmp_path)
    catalog = _catalog(tmp_path / "catalog")
    monkeypatch.setenv("WORKBENCH_AGENT_RECOVERY_DIR", str(tmp_path / "catalog"))

    class FinalAnswer:
        async def stream(self, request):
            yield ModelStreamEvent.text_delta(request.request_id, "Hello.")
            yield ModelStreamEvent.done(request.request_id)

    async def run():
        with headless_runtime_scope(adapter_factory=lambda config: FinalAnswer(), config=_config()):
            return await run_headless(fixture.project_root, "Hello", session_id="chain-session",
                                      on_event=lambda event: None)

    assert asyncio.run(run())["status"] == "idle"
    assert [Path(item["canonical_path"]) for item in catalog.projects()] == [fixture.project_root]
