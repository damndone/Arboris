"""A broken permission document must never become an unrestricted document."""

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from tests.test_agent_continue_route import _session
from tests.test_agent_routes import _config
from workbench.api_errors import WorkbenchAPIError
from workbench.app import app


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
    monkeypatch.setattr(routes, "load_llm_config", _config)
    with TestClient(app, base_url="http://127.0.0.1", raise_server_exceptions=False) as client:
        session = _session(client, project)
        directory = project / "workbench" / "agent-sessions"
        before = {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}
        (project / "workbench" / "agent-permissions.json").write_text(document)

        def must_not_run(*args, **kwargs):
            raise AssertionError("invalid permissions must stop before provider setup or outcome writes")
        monkeypatch.setattr(routes, "load_llm_config", must_not_run)
        monkeypatch.setattr(routes, "_tell_agent_finished_outcomes", must_not_run)
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

    assert routes._project_permission_rules(tmp_path) == Rules()
    path = tmp_path / "workbench" / "agent-permissions.json"
    path.parent.mkdir()
    path.mkdir()
    with pytest.raises(WorkbenchAPIError) as directory:
        routes._project_permission_rules(tmp_path)
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
        routes._project_permission_rules(other)
    assert unreadable.value.code == "AGENT_PERMISSION_RULES_INVALID"
