"""A broken permission document must never become an unrestricted document."""
from workbench.http import agent_turn_routes
from workbench.http import agent_route_permissions, agent_route_runtime

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from threading import Barrier

from fastapi.testclient import TestClient
import pytest

from tests.test_agent_continue_route import _session
from tests.test_agent_routes import _config
from workbench.api_errors import WorkbenchAPIError
from workbench.app import app


PROJECT_PERMISSIONS = "/projects/agent-permissions"


def test_settings_save_rules_used_by_both_modes_and_keep_the_confirmation_floor(tmp_path):
    from workbench.agent.permission_config import project_permission_rules
    from workbench.agent.permissions import Mode, Outcome, PermissionClass, Request, decide

    project = tmp_path / "project"
    project.mkdir()
    params = {"project_root": str(project)}
    document = {
        "allow": [{"class": "derive"}, {"class": "high"}],
        "ask": [{"class": "analyze", "operation_id": "test.means"}],
        "deny": [{"class": "derive", "operation_id": "model.genesis"}],
    }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        initial = client.get(PROJECT_PERMISSIONS, params=params)
        assert initial.status_code == 200, initial.text
        assert initial.json()["rules"] == {"allow": [], "ask": [], "deny": []}
        assert not (project / "workbench").exists()
        response = client.put(
            PROJECT_PERMISSIONS, params=params,
            json={"expected_revision": initial.json()["revision"], "rules": document},
        )
        assert response.status_code == 200, response.text
        assert response.json()["rules"] == document
        assert response.json()["revision"] != initial.json()["revision"]
        assert client.get(PROJECT_PERMISSIONS, params=params).json() == response.json()

    saved = project_permission_rules(project)
    for mode in Mode:
        assert decide(mode, Request("model.genesis", PermissionClass.DERIVE), saved).outcome is Outcome.DENY
        assert decide(mode, Request("test.means", PermissionClass.ANALYZE), saved).outcome is Outcome.ASK
        assert decide(mode, Request("model.rerun", PermissionClass.DERIVE), saved).outcome is Outcome.ALLOW
        floor = decide(mode, Request("model.custom", PermissionClass.HIGH), saved)
        assert floor.outcome is Outcome.ASK and floor.floor


def test_settings_refuse_to_overwrite_a_new_deny_at_a_stale_revision(tmp_path):
    params = {"project_root": str(tmp_path)}
    permission_path = tmp_path / "workbench" / "agent-permissions.json"
    permission_path.parent.mkdir()
    permission_path.write_text("{}", encoding="utf-8")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        loaded = client.get(PROJECT_PERMISSIONS, params=params)
        assert loaded.status_code == 200, loaded.text
        document = '{"deny":[{"class":"derive"}]}'
        permission_path.write_text(document, encoding="utf-8")
        response = client.put(
            PROJECT_PERMISSIONS, params=params,
            json={"expected_revision": loaded.json()["revision"], "rules": loaded.json()["rules"]},
        )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "AGENT_PERMISSION_RULES_CONFLICT"
        assert permission_path.read_text(encoding="utf-8") == document


def test_only_one_settings_writer_can_save_an_expected_revision(tmp_path):
    from workbench.agent.permission_config import (
        permission_rules_document,
        read_project_permission_settings,
        save_project_permission_settings,
    )

    _, revision = read_project_permission_settings(tmp_path)
    ready = Barrier(2)

    def save(permission_class):
        rules = {"allow": [], "ask": [], "deny": [{"class": permission_class}]}
        ready.wait(timeout=5)
        try:
            save_project_permission_settings(tmp_path, expected_revision=revision, payload=rules)
        except WorkbenchAPIError as exc:
            assert exc.code == "AGENT_PERMISSION_RULES_CONFLICT"
            return None
        return rules

    with ThreadPoolExecutor(max_workers=2) as workers:
        winners = [result for result in workers.map(save, ("derive", "high")) if result is not None]
    current, _ = read_project_permission_settings(tmp_path)
    assert winners == [permission_rules_document(current)]


@pytest.mark.parametrize("rule", [
    {"class": "derive", "operation_id": None},
    {"class": "derive", "target": "an-unimplemented-scope"},
    {"class": "unregistered"},
])
def test_settings_refuse_invalid_rules_without_creating_a_file(tmp_path, rule):
    params = {"project_root": str(tmp_path)}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        loaded = client.get(PROJECT_PERMISSIONS, params=params)
        assert loaded.status_code == 200, loaded.text
        response = client.put(
            PROJECT_PERMISSIONS, params=params,
            json={"expected_revision": loaded.json()["revision"], "rules": {"allow": [rule], "ask": [], "deny": []}},
        )
        assert response.status_code == 422, response.text
    assert not (tmp_path / "workbench").exists()


@pytest.mark.parametrize("symlink_name", ["workbench", "agent-permissions.json"])
def test_settings_refuse_symlinks_to_permission_files_outside_the_project(tmp_path, symlink_name):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    filename = "agent-permissions.json"
    outside_policy = outside / filename
    document = '{"deny":[{"class":"derive"}]}'
    outside_policy.write_text(document, encoding="utf-8")
    directory = project / "workbench"
    if symlink_name == "workbench":
        directory.symlink_to(outside, target_is_directory=True)
    else:
        directory.mkdir()
        (directory / filename).symlink_to(outside_policy)
    params = {"project_root": str(project)}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        loaded = client.get(PROJECT_PERMISSIONS, params=params)
        assert loaded.status_code == 503, loaded.text
        response = client.put(
            PROJECT_PERMISSIONS, params=params,
            json={"expected_revision": sha256(document.encode()).hexdigest(),
                  "rules": {"allow": [], "ask": [], "deny": []}},
        )
        assert response.status_code == 503, response.text
    assert outside_policy.read_text(encoding="utf-8") == document


def test_settings_do_not_replace_a_malformed_permission_file(tmp_path):
    params = {"project_root": str(tmp_path)}
    permission_path = tmp_path / "workbench" / "agent-permissions.json"
    permission_path.parent.mkdir()
    document = '{"deny":[{"class":"derive"}],"deny":[]}'
    permission_path.write_text(document, encoding="utf-8")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        loaded = client.get(PROJECT_PERMISSIONS, params=params)
        assert loaded.status_code == 503, loaded.text
        response = client.put(
            PROJECT_PERMISSIONS, params=params,
            json={"expected_revision": sha256(document.encode()).hexdigest(),
                  "rules": {"allow": [], "ask": [], "deny": []}},
        )
        assert response.status_code == 503, response.text
    assert permission_path.read_text(encoding="utf-8") == document


@pytest.mark.parametrize("endpoint", ["turns", "continue"])
@pytest.mark.parametrize("document", [
    '{"deny":',
    '{"allow":[{"class":"derive","operation_id":[]}]}',
    '{"deny":[{"class":"derive"}],"deny":[]}',
    '{"ask":[{"class":"nonsense"}]}',
])
def test_invalid_rules_stop_before_provider_or_session_mutation(tmp_path, monkeypatch, endpoint, document):
    from workbench.http import agent_routes as routes

    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(agent_route_runtime, "load_llm_config", _config)
    with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as client:
        session = _session(client, project)
        directory = project / "workbench" / "agent-sessions"
        before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        (project / "workbench" / "agent-permissions.json").write_text(document)

        def must_not_run(*args, **kwargs):
            raise AssertionError("invalid permissions must stop before provider setup or outcome writes")
        monkeypatch.setattr(agent_route_runtime, "load_llm_config", must_not_run)
        monkeypatch.setattr(agent_turn_routes, "_tell_agent_finished_outcomes", must_not_run)
        body = {"execution_mode": "auto"}
        if endpoint == "turns":
            body["question"] = "Do not record or execute this request."
        response = client.post(f"/agent/sessions/{session}/{endpoint}",
                               params={"project_root": str(project)}, json=body)
        assert response.status_code == 503, response.text
        assert response.json()["error"]["code"] == "AGENT_PERMISSION_RULES_INVALID"
        assert {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()} == before
        key = routes._active_turn_key(project, session)
        assert key not in routes.turn_registry.reserved
        assert key not in routes.turn_registry.tasks


def test_missing_permissions_are_empty_but_unreadable_or_non_file_are_errors(tmp_path, monkeypatch):
    from workbench.agent.permissions import Rules
    from workbench.http import agent_routes as routes

    assert agent_route_permissions._project_permission_rules(tmp_path) == Rules()
    path = tmp_path / "workbench" / "agent-permissions.json"
    path.parent.mkdir()
    path.mkdir()
    with pytest.raises(WorkbenchAPIError) as directory:
        agent_route_permissions._project_permission_rules(tmp_path)
    assert directory.value.code == "AGENT_PERMISSION_RULES_INVALID"
    # Use a separate regular file and injected I/O error rather than relying
    # on platform-specific chmod semantics for the current test account.
    other = tmp_path / "other"
    target = other / "workbench" / "agent-permissions.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"deny":[{"class":"derive"}]}')
    original = Path.read_text
    def deny_read(self, *args, **kwargs):
        if self == target:
            raise PermissionError("test denied read")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", deny_read)
    with pytest.raises(WorkbenchAPIError) as unreadable:
        agent_route_permissions._project_permission_rules(other)
    assert unreadable.value.code == "AGENT_PERMISSION_RULES_INVALID"
