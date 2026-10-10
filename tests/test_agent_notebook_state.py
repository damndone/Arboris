from pathlib import Path

import pytest

from workbench.agent.context_tools_support.notebook_state import read_notebook_state
from workbench.agent.notebook.store import Notebook, NotebookStore


def test_empty_plan_is_distinct_from_committed_workflow_results(tmp_path: Path):
    store = NotebookStore(tmp_path)
    store.create_notebook(Notebook(
        notebook_id="nb_test", project_id="project", run_family_id="family",
        title="Private title", created_by="user", created_at="2026-10-10T00:00:00Z",
        active_head_run_id="completed", focused_run_id="focused", last_attempt_run_id="failed",
    ))
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = read_notebook_state(tmp_path, "nb_test")
    assert result["option_count"] == 0
    assert result["active_head_run_id"] == "completed"
    assert result["last_attempt_run_id"] == "failed"
    assert result["execution_authorized"] is False
    assert "Private title" not in str(result)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_notebook_reader_rejects_escape(tmp_path: Path):
    with pytest.raises(ValueError):
        read_notebook_state(tmp_path, "../other")
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "notebooks" / "nb_outside").symlink_to(tmp_path.parent)
    with pytest.raises(ValueError, match="outside"):
        read_notebook_state(tmp_path, "nb_outside")


def test_notebook_tool_registration_and_egress_classification(tmp_path: Path):
    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.tools import ToolContext
    from workbench.egress import tool_content_class

    definitions = NodeOperationContextProvider(tmp_path).global_tool_definitions(session_id="allowed")
    tool = next(item for item in definitions if item.tool_id == "inspect_notebook_state")
    assert tool_content_class(tool.tool_id) == "workbench_state"
    with pytest.raises(ValueError, match="session"):
        tool.handler({"notebook_id": "nb_test"}, ToolContext(session_id="other"))
