"""Behaviour and ownership guards for the Agent HTTP/application boundary."""

from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from workbench.api_errors import WorkbenchAPIError


def _boundary(name: str):
    module = f"workbench.agent.{name}"
    assert importlib.util.find_spec(module) is not None, f"Missing Agent service: {module}"
    return importlib.import_module(module)


def test_protocol_service_preserves_the_current_approved_prompt_contract() -> None:
    protocol = _boundary("protocol")
    expected = {
        "CHAIN_AGENT_PROTOCOL": "bdf72b48490efeadd57238ab7bf32aed25b76af44bb78c06c1810ff2188b9baa",
        "MAIN_AGENT_PROTOCOL": "a32ad013a644c64594f428ba92ce86685abc4cab4d2c4936374f5be6f7fc3f36",
        "CONTINUATION_NOTE": "472088888439a73be1782e92ab48d0e2118d84c668ac85e549331fbb08afa75c",
    }
    for name, digest in expected.items():
        assert hashlib.sha256(getattr(protocol, name).encode("utf-8")).hexdigest() == digest


def test_protocol_rendering_has_no_dependency_on_http_routes() -> None:
    protocol = _boundary("protocol")
    from workbench.agent.operations import OperationRegistry
    from workbench.http import agent_routes

    registry = OperationRegistry()
    rendered = protocol.chain_agent_protocol(registry)
    assert rendered == agent_routes._chain_agent_protocol(registry)
    assert "{step_vocabulary}" not in rendered
    assert protocol.step_vocabulary_lines() in rendered


def test_protocol_revision_uses_explicit_current_text_once(tmp_path: Path) -> None:
    protocol = _boundary("protocol")
    from workbench.agent.session import JsonlSessionRepository

    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("main", chain_id=None, role="main")
    protocol.ensure_current_global_protocol(repository, "main", protocol="current protocol")
    protocol.ensure_current_global_protocol(repository, "main", protocol="current protocol")
    revisions = [entry for entry in repository.get_branch("main")
                 if entry.payload.get("name") == "workbench_global_agent_protocol"]
    assert len(revisions) == 1
    assert revisions[0].payload["content"] == "current protocol"
    protocol.ensure_current_global_protocol(repository, "main", protocol="next protocol")
    assert repository.get_branch("main")[-1].payload["content"] == "next protocol"


def test_budget_service_preserves_defaults_and_returns_an_independent_budget() -> None:
    runtime = _boundary("turn_runtime")
    assert runtime.DEFAULT_MAX_STEPS == 10
    assert runtime.DEFAULT_TIMEOUT_S == 300.0
    assert runtime.turn_budget(None) == {"max_steps": 10, "timeout_s": 300.0}
    assert runtime.turn_budget("unknown") == runtime.turn_budget(None)
    assert runtime.turn_budget("ask") == {"max_steps": 25, "timeout_s": 600.0}
    assert runtime.turn_budget("auto") == {"max_steps": 40, "timeout_s": 1200.0}
    runtime.turn_budget("ask")["max_steps"] = 1
    assert runtime.turn_budget("ask")["max_steps"] == 25


def test_turn_registry_reserves_atomically_across_request_threads(tmp_path: Path) -> None:
    runtime = _boundary("turn_runtime")
    registry = runtime.TurnRegistry()
    barrier = Barrier(2)

    def reserve() -> tuple[str, str] | str:
        barrier.wait()
        try:
            return registry.reserve(tmp_path, "session")
        except WorkbenchAPIError as exc:
            assert exc.status_code == 409
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    key = runtime.active_turn_key(tmp_path, "session")
    assert results.count(key) == 1
    assert results.count("AGENT_TURN_IN_PROGRESS") == 1
    registry.release(key)
    assert registry.reserve(tmp_path, "session") == key
    registry.release(key)


def test_turn_registry_tracks_active_identity_and_keeps_legacy_aliases(tmp_path: Path) -> None:
    runtime = _boundary("turn_runtime")
    from workbench.http import agent_routes

    assert agent_routes._ACTIVE_TURNS is runtime.turn_registry.active
    assert agent_routes._RESERVED_TURNS is runtime.turn_registry.reserved
    assert agent_routes._TURN_RESERVATION_LOCK is runtime.turn_registry.lock
    registry = runtime.TurnRegistry()
    key = registry.reserve(tmp_path, "session")
    agent = object()
    registry.activate(key, agent)
    assert registry.get(tmp_path, "session") is agent
    registry.release(key)
    with pytest.raises(WorkbenchAPIError, match="running turn"):
        registry.reserve(tmp_path, "session")
    registry.deactivate(key, object())
    assert registry.get(tmp_path, "session") is agent
    registry.deactivate(key, agent)
    assert registry.get(tmp_path, "session") is None
    assert registry.reserve(tmp_path, "session") == key
    registry.release(key)


def test_http_consumes_services_without_owning_protocol_or_turn_state() -> None:
    from workbench.http import agent_routes

    tree = ast.parse(Path(agent_routes.__file__).read_text())
    definitions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    assert "_step_vocabulary_lines" not in definitions
    assert "_chain_agent_protocol" not in definitions
    assert "turn_budget" not in definitions
    assert "_reserve_turn" not in definitions
    assert "_release_turn" not in definitions
    for name in ("protocol", "turn_runtime"):
        module = _boundary(name)
        source = Path(module.__file__).read_text()
        imports = [node.module for node in ast.walk(ast.parse(source))
                   if isinstance(node, ast.ImportFrom) and node.module]
        assert not any("http" in module.split(".") for module in imports)
        assert "globals().update" not in source
        assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                       and node.func.id == "exec" for node in ast.walk(ast.parse(source)))
