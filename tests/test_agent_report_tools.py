"""The Agent writes a run's report through the versioned store, under the rule for numbers."""
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from workbench.agent import report_tools
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tools import ToolVisibleError
from workbench.services import manual_reports

FACT = {"id": "fact_1", "label": "education", "value": 0.1721}


@pytest.fixture
def project(tmp_path, monkeypatch):
    run_root = tmp_path / "runs" / "run_1"
    run_root.mkdir(parents=True)
    draft = {"source_fingerprint": "sha256:" + "a" * 64, "title": "Analysis report", "text": "Draft [[v:fact_1]].",
             "facts": [FACT], "figures": [], "limitations": ["limit"]}
    saved = []

    def save(root, request, *, author="user"):
        record = {**request.model_dump(), "author": author, "created_at": f"2026-11-0{len(saved) + 1}", "run_id": root.name,
                  "revision_number": len(saved) + 1, "facts": [FACT], "figures": []}
        saved.insert(0, record)
        return {"record": record}

    monkeypatch.setattr(report_tools, "_report_store", lambda: SimpleNamespace(
        resolve=lambda root, run: Path(root) / "runs" / run, list_ai_reports=lambda root: [],
        manual=SimpleNamespace(build_manual_report_draft=lambda root: draft, list_manual_reports=lambda root: saved,
                               save_manual_report=save, ManualReportRequest=manual_reports.ManualReportRequest)))
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    repository.append("s", "message", {"role": "tool", "name": "read_reports", "content": '{"r2": 0.3711}'})
    return SimpleNamespace(root=tmp_path, saved=saved)


def run(tool, arguments, session="s"):
    return tool.handler(arguments, SimpleNamespace(session_id=session))


def test_loading_the_tools_leaves_the_workflow_steps_complete():
    """Importing the report service with the tools once dropped imputation.mice from the step registry."""
    code = ("from workbench.agent.context_tools_support import registration; "
            "from workbench.agent.workflow_contracts import workflow_step_vocabulary as v; "
            "assert 'imputation.mice' in v()['step_operations']")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "backend")}
    subprocess.run([sys.executable, "-B", "-c", code], env=env, check=True, capture_output=True)


def test_with_no_report_it_reads_the_draft_and_the_facts(project):
    result = run(report_tools.report_read_tool(project.root, session_id="s"), {"run_id": "run_1"})
    assert result["versions"] == [] and result["text"] == "Draft [[v:fact_1]]."
    assert result["facts"] == [FACT] and result["report_id"] is None


def test_a_saved_version_is_the_agents_and_the_next_one_revises_it(project):
    save = report_tools.report_save_tool(project.root, session_id="s")
    first = run(save, {"run_id": "run_1", "title": "T", "text": "R squared 0.3711; education [[v:fact_1]]."})
    second = run(save, {"run_id": "run_1", "title": "T", "text": "Education [[v:fact_1]]."})
    assert first["revision_number"] == 1 and second["revision_number"] == 2
    assert project.saved[0]["author"] == "agent" and project.saved[0]["parent_report_id"] == first["report_id"]
    read = run(report_tools.report_read_tool(project.root, session_id="s"), {"run_id": "run_1"})
    assert [item["revision_number"] for item in read["versions"]] == [2, 1] and read["text"] == "Education [[v:fact_1]]."


def test_a_number_from_nowhere_is_refused_and_nothing_is_saved(project):
    save = report_tools.report_save_tool(project.root, session_id="s")
    with pytest.raises(ToolVisibleError, match="REPORT_NUMBER_UNVERIFIED.*0.9876"):
        run(save, {"run_id": "run_1", "title": "T", "text": "The effect is 0.9876."})
    assert project.saved == []


@pytest.mark.parametrize("text,code", [
    ("Effect [v:fact_1].", "REPORT_MARKER_MALFORMED"),
    ("| a | b |\n|---|---|\n| [[v:fact_1]] | x |", "REPORT_TABLE_UNSUPPORTED")])
def test_what_the_reader_would_see_as_raw_text_is_refused(project, text, code):
    with pytest.raises(ToolVisibleError, match=code):
        run(report_tools.report_save_tool(project.root, session_id="s"), {"run_id": "run_1", "title": "T", "text": text})
    assert project.saved == []


def test_another_sessions_tool_is_refused(project):
    with pytest.raises(ToolVisibleError, match="SESSION_MISMATCH"):
        run(report_tools.report_read_tool(project.root, session_id="s"), {"run_id": "run_1"}, session="other")
