"""A clean checkout can record and strictly replay a real offline CLI analysis."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
from shutil import copytree
import socket
import sys

import pytest
from typer.testing import CliRunner

from tests.test_agent_routes import _config
from tests.test_read_only_analysis import FINGERPRINT, _Fixture, _explore, _t_test
from workbench import cli_agent
from workbench.agent.model import ModelStreamEvent
from workbench.agent.turn_store import TurnStore
from workbench.cli import app


PROMPT = "Tabulate region, compare wage by group, and save the workflow report."


class ScriptedAnalysis:
    """Only model events are scripted; product tools compute and save all results."""

    def __init__(self, with_plan: bool):
        self.with_plan = with_plan
        self.calls = 0

    async def stream(self, request):
        self.calls += 1
        if self.with_plan and self.calls == 1:
            call = {
                "tool_call_id": "analysis-plan", "tool_id": "update_plan",
                "arguments": {
                    "question": PROMPT, "criteria": ["Analysis and report saved."],
                    "steps": [{"step_id": "analysis", "title": "Analyze and report",
                               "operation_ids": ["statistical.explore", "test.t_tests", "report.compose"]}],
                },
            }
        elif self.calls == (2 if self.with_plan else 1):
            call = {
                "tool_call_id": "analysis", "tool_id": "run_operation",
                "arguments": {
                    "operation_id": "operation.multi_step", "operation_version": "v1",
                    "target": {"run_id": "run_source", "node_ref": "stage:source", "artifact_id": "source_data"},
                    "preconditions": {
                        "context_version": "node-operation-context/v1", "context_fingerprint": FINGERPRINT,
                        "active_head_run_id": "run_source", "owner_resolution": "single_candidate",
                    },
                    "changes": {"steps": [_explore("tab", "region"), _t_test("tt"), {
                        "step_id": "report", "operation_id": "report.compose", "depends_on": ["tab", "tt"],
                        "spec": {"sections": ["descriptives", "tests"]},
                    }]},
                    "evidence_refs": ["profile:fixture"], "expected_effect": ["Save analysis and report"], "risks": [],
                },
            }
        else:
            yield ModelStreamEvent.text_delta(request.request_id, "The analysis and report are saved.")
            yield ModelStreamEvent.done(request.request_id)
            return
        yield ModelStreamEvent.tool_call_delta(request.request_id, call)
        yield ModelStreamEvent.done(request.request_id, "tool_calls")


@contextmanager
def _guarded_cli(monkeypatch, scripted: ScriptedAnalysis | None = None):
    """Record permits one fake provider; replay permits no current provider path."""
    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append("current config, upstream adapter, or socket")
        raise AssertionError("Product replay must not call a current provider or the network")

    with monkeypatch.context() as guard:
        # Cover loaded aliases as well as source symbols used by later imports.
        for module in list(sys.modules.values()):
            if not getattr(module, "__name__", "").startswith("workbench"):
                continue
            for name in ("load_llm_config", "OpenAICompatibleModelAdapter"):
                if name in vars(module):
                    replacement = _config if scripted is not None and name == "load_llm_config" else forbidden
                    guard.setattr(module, name, replacement)
        if scripted is not None:
            guard.setattr(cli_agent, "OpenAICompatibleModelAdapter", lambda config: scripted)
        for owner, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                            (socket, "create_connection"), (socket, "getaddrinfo")):
            guard.setattr(owner, name, forbidden)
        yield
    assert forbidden_calls == []


def _analysis_results(root: Path) -> dict:
    records = [json.loads(path.read_text().splitlines()[-1])
               for path in (root / "workbench/operation-records").glob("oprec_*.jsonl")]
    assert len(records) == 4 and all(record["status"] == "completed" for record in records)
    assert {record["operation_id"] for record in records} == {
        "operation.multi_step", "statistical.explore", "test.t_tests", "report.compose",
    }
    parent = next(record for record in records if record["operation_id"] == "operation.multi_step")
    run = root / "runs/run_source"
    workflow_id = parent["outputs"]["workflow_id"]
    reports = [run / "reports" / f"{workflow_id}.html", run / "reports" / f"{workflow_id}.pdf",
               run / "exports" / f"{workflow_id}.xlsx"]
    # Container metadata can differ; byte identity is not a report requirement.
    assert all(path.is_file() and path.stat().st_size > 0 for path in reports)
    welch = parent["outputs"]["post_estimation_results"][0]["result"]["result"]["results"][0]
    assert welch["test_type"] == "welch_t_test" and welch["nobs"] == 60
    assert welch["p_value"] < 0.001
    assert welch["effect"]["difference"] == pytest.approx(2.6761333333333326, abs=1e-12)
    tab_id = parent["outputs"]["workflow_state"]["steps"]["tab"]["artifact_ids"][0]
    index = json.loads((run / "artifacts_index.json").read_text())
    tab = next(artifact for artifact in index["artifacts"] if artifact["artifact_id"] == tab_id)
    tabulation = json.loads((run / tab["path"]).read_text())["result"]
    assert {row["value"]: row["count"] for row in tabulation["rows"]} == {"south": 23, "west": 21, "north": 16}
    assert tabulation["filtered_row_count"] == 60
    assert TurnStore(root).list_active() == []
    return {"outputs": parent["outputs"], "tabulation": tabulation}


def _receipt(result) -> dict:
    assert result.exit_code == 0, result.output
    receipt = json.loads(result.stdout.strip().splitlines()[-1])
    assert receipt["type"] == "agent_result" and receipt["status"] == "idle"
    assert receipt["pending_proposals"] == []
    return receipt


@pytest.mark.parametrize("with_plan", [False, True], ids=["analysis", "plan-and-analysis"])
def test_cli_records_and_strictly_replays_actual_analysis_and_reports(tmp_path, monkeypatch, with_plan):
    fixture = _Fixture(tmp_path)
    root = fixture.project_root
    run = root / "runs/run_source"
    (run / "node_index.json").write_text(json.dumps({"stage:source": {
        "node_hash": hashlib.sha256((run / "data.csv").read_bytes()).hexdigest(),
    }}))
    (run / "run_manifest.json").write_text(json.dumps({
        "status": "completed", "started_at": "2026-07-15T00:00:00+00:00",
    }))
    (run / "run_inputs.json").write_text(json.dumps({"rerun_of": None, "form": {}}))
    (root / "workbench/agent-permissions.json").write_text(json.dumps({"allow": [{"class": "derive"}]}))
    initial = tmp_path / "initial-project"
    copytree(root, initial)
    fixture_hash = cli_agent._fixture_sha256(root)
    journal = tmp_path / "journal"
    journal.mkdir()
    command = ["agent", "run", "--project", str(root), "--session", "chain-session",
               "--prompt", PROMPT, "--mode", "ask"]
    scripted = ScriptedAnalysis(with_plan)
    runner = CliRunner()
    with _guarded_cli(monkeypatch, scripted):
        recorded = _receipt(runner.invoke(app, [*command, "--record-journal", str(journal)]))
    assert scripted.calls == (3 if with_plan else 2)
    expected = _analysis_results(root)
    manifest = json.loads((journal / "runtime.json").read_text())
    assert manifest["complete"] is True and manifest["fixture_sha256"] == fixture_hash
    assert "api_key" not in manifest["config"]
    root.rename(tmp_path / "recorded-project")
    copytree(initial, root)
    assert cli_agent._fixture_sha256(root) == fixture_hash
    assert list((root / "workbench/operation-records").glob("oprec_*.jsonl")) == []
    assert list(run.rglob("*.pdf")) == []
    # CLI itself asserts strict ReplayAdapter and business journal exhaustion;
    # no adapter wrapper, ID normalization, or result substitution is installed.
    with _guarded_cli(monkeypatch):
        replayed = _receipt(runner.invoke(app, [*command, "--replay-journal", str(journal)]))
    assert _analysis_results(root) == expected
    assert replayed["assistant"]["content"] == recorded["assistant"]["content"]
    assert replayed["plan"] == recorded["plan"]
    assert (replayed["plan"] is not None) is with_plan
