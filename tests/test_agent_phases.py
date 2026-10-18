"""A phase advances at the same provider step as ordinary Agent turns."""

import ast
import asyncio
import importlib
import importlib.util
from pathlib import Path

import pytest


def test_core_owns_phase_progress_and_notebook_has_no_provider_loop():
    assert importlib.util.find_spec("workbench.agent.phases") is not None
    from workbench.agent.core import AgentCore
    from workbench.agent.notebook.planning_agent import NotebookPlanningAgent
    assert callable(getattr(AgentCore, "enter_phase", None))
    assert callable(getattr(AgentCore, "run_phase", None))
    module = importlib.import_module("workbench.agent.planning.notebook_phase")
    tree = ast.parse(Path(module.__file__).read_text())
    assert not any(isinstance(n, ast.Attribute) and n.attr in {"adapter", "stream", "plan_async", "run_phase"} for n in ast.walk(tree))
    assert not hasattr(NotebookPlanningAgent, "_collect_model_events")


def test_entering_phase_reuses_current_core_and_budget_then_resumes_ordinary_loop(tmp_path):
    assert importlib.util.find_spec("workbench.agent.phases") is not None
    from workbench.agent.phases import PhaseRequest, PhaseStep
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.session import JsonlSessionRepository
    from workbench.agent.tools import ToolDefinition, ToolRegistry

    class Phase:
        episode_id = "episode"
        def __init__(self):
            self.calls = 0
        def request(self, transcript):
            return PhaseRequest(list(transcript) or [{"role": "user", "content": "phase"}], [], provider_timeout_s=1)
        async def consume(self, events, *, error=None):
            assert error is None
            self.calls += 1
            if self.calls == 1:
                return PhaseStep("continue", ({"role": "user", "content": "second phase step"},))
            return PhaseStep("completed", (), "phase done", {"result": "phase done"})
        def checkpoint(self):
            return {"episode_id": self.episode_id, "calls": self.calls}
        def failure(self, reason, error=None):
            return RuntimeError(reason)

    class Model:
        def __init__(self):
            self.requests = []
        async def stream(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {"tool_call_id": "enter", "tool_id": "enter", "arguments": {}})
                yield ModelStreamEvent.done(request.request_id, "tool_calls")
            else:
                yield ModelStreamEvent.text_delta(request.request_id, "finished")
                yield ModelStreamEvent.done(request.request_id)

    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("s", chain_id="c", role="chain")
    model = Model()
    core = AgentCore(repository, AgentEventStream(tmp_path), model, session_id="s")
    phase = Phase()
    seen = []
    def enter(arguments, context):
        seen.append((id(core), core._steps_used, core._active_command_id))
        core.enter_phase(phase)
        assert core._steps_used == 1
        return {"phase_started": phase.episode_id}
    tools = ToolRegistry()
    tools.register(ToolDefinition("enter", "v1", {"type": "object"}, "none", enter))
    core.attach_tools(tools.descriptors(), tools)
    assert asyncio.run(core.prompt("start", budget={"max_steps": 4})) == "finished"
    assert phase.calls == 2 and len(model.requests) == 4
    assert len(seen) == 1 and seen[0][0] == id(core)
    states = [entry.payload for entry in repository.get_branch("s") if entry.entry_type == "phase_state"]
    assert states and {entry["episode_id"] for entry in states} == {"episode"}
    assert max(entry["steps_used"] for entry in states) == 3
    assert all("phase done" not in str(request.messages) for request in model.requests[1:3])
    assert "phase done" in str(model.requests[-1].messages)
    snapshot = core.context_builder.build("s")
    private_entries = {entry.entry_id for entry in repository.get_branch("s")
                       if entry.entry_type in {"phase_message", "phase_state", "phase_provider_result"}}
    assert not private_entries.intersection(snapshot.source_entry_ids)
    assert "second phase step" not in str(snapshot.messages)
    assert core._core_phase is None and core._phase_messages == []
    with pytest.raises(Exception):
        core.enter_phase(phase)


@pytest.mark.parametrize("late_error", [False, True])
def test_notebook_phase_reads_to_eof_and_preserves_late_provider_failures(tmp_path, late_error):
    from tests.test_notebook_planning_agent import _context, _evidence, _submit_call, make_project
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.notebook.planning_agent import NotebookPlanningAgent, NotebookPlanningUnavailable
    reached_eof = []

    class Model:
        async def stream(self, request):
            yield ModelStreamEvent.done(request.request_id, "tool_calls")
            # The legacy planning collector processes the whole stream, rather
            # than stopping at done like the ordinary conversation path.
            yield ModelStreamEvent.tool_call_delta(request.request_id, {
                "tool_call_id": "submit", "tool_id": "submit_notebook_option_batch", "arguments": _submit_call(),
            })
            reached_eof.append(True)
            if late_error:
                raise OSError("late stream failure")

    planner = NotebookPlanningAgent(adapter=Model(), capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}})
    if late_error:
        with pytest.raises(NotebookPlanningUnavailable, match="model provider failed: OSError"):
            planner.plan(context=_context(make_project(tmp_path)), initial_evidence=_evidence())
    else:
        result = planner.plan(context=_context(make_project(tmp_path)), initial_evidence=_evidence())
        assert result.rounds == 1
    assert reached_eof == [True]


def test_phase_preserves_configuration_and_episode_id_across_corrections(tmp_path):
    from tests.test_notebook_planning_agent import _context, _evidence, _submit_call, make_project
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.notebook.planning_agent import NotebookPlanningAgent
    from workbench.agent.session import JsonlSessionRepository

    class Model:
        def __init__(self):
            self.requests = []
        def planning_request_config(self):
            return {"temperature": 0.25, "extra_body": {"thinking": {"type": "disabled"}}}
        async def stream(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                yield ModelStreamEvent.text_delta(request.request_id, "untyped answer")
            else:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {
                    "tool_call_id": "submit", "tool_id": "submit_notebook_option_batch", "arguments": _submit_call(),
                })
            yield ModelStreamEvent.done(request.request_id, "tool_calls")

    model = Model()
    planner = NotebookPlanningAgent(adapter=model, capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}})
    phase = planner.create_phase(context=_context(make_project(tmp_path)), initial_evidence=_evidence(), episode_id="stable-episode")
    repository = JsonlSessionRepository(tmp_path / "runtime")
    repository.create_session("s", chain_id="c", role="planning")
    core = AgentCore(repository, AgentEventStream(repository.root), model, session_id="s")
    result = asyncio.run(core.run_phase(phase))
    assert result.rounds == 2 and result.decision.batch_id.endswith("stable-episode")
    assert all(request.model_config == model.planning_request_config() for request in model.requests)
    states = [entry.payload for entry in repository.get_branch("s") if entry.entry_type == "phase_state"]
    assert {entry["episode_id"] for entry in states} == {"stable-episode"}
    assert states[-1]["phase"]["contract_corrections"] == 1
    assert states[-1]["steps_used"] == 2
    # Seed and correction messages are committed once, without adding generic
    # Agent system prompts to the provider-facing phase transcript.
    messages = [entry.payload["message"] for entry in repository.get_branch("s") if entry.entry_type == "phase_message"]
    assert messages[:2] == model.requests[0].messages
    assert len(messages) == len(model.requests[1].messages)


@pytest.mark.parametrize("failure", ["budget", "consume"])
def test_phase_failure_cleans_up_without_obtaining_new_steps(tmp_path, failure):
    from workbench.agent.core import AgentCore
    from workbench.agent.events import AgentEventStream
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.phases import PhaseRequest, PhaseStep
    from workbench.agent.session import JsonlSessionRepository
    from workbench.agent.tools import ToolDefinition, ToolRegistry

    class Phase:
        episode_id = "limited"
        def request(self, transcript):
            return PhaseRequest([{"role": "user", "content": "phase"}], [])
        async def consume(self, events, *, error=None):
            if failure == "consume":
                raise RuntimeError("consume")
            return PhaseStep("continue")
        def checkpoint(self):
            return {}
        def failure(self, reason, error=None):
            return RuntimeError(reason)

    class Model:
        calls = 0
        async def stream(self, request):
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent.tool_call_delta(request.request_id, {"tool_call_id": "enter", "tool_id": "enter", "arguments": {}})
            yield ModelStreamEvent.done(request.request_id, "tool_calls")

    repository = JsonlSessionRepository(tmp_path)
    repository.create_session("s", chain_id="c", role="chain")
    model = Model()
    core = AgentCore(repository, AgentEventStream(tmp_path), model, session_id="s")
    def enter(arguments, context):
        core.enter_phase(Phase())
        return {"phase_started": True}
    tools = ToolRegistry()
    tools.register(ToolDefinition("enter", "v1", {"type": "object"}, "none", enter))
    core.attach_tools(tools.descriptors(), tools)
    with pytest.raises(RuntimeError, match=failure):
        asyncio.run(core.prompt("start", budget={"max_steps": 2}))
    assert model.calls == 2
    assert core._core_phase is None and core._phase_messages == []
    assert core.phase == "idle"
    states = [entry.payload for entry in repository.get_branch("s") if entry.entry_type == "phase_state"]
    assert states[-1]["status"] == "failed"


def test_production_notebook_factory_injects_a_project_owned_core_runner(tmp_path, monkeypatch):
    from tests.test_notebook_routes import make_project, store_upload_bytes, _trace
    from workbench.agent.model import ModelStreamEvent
    from workbench.agent.notebook.service import NotebookService
    from workbench.agent.notebook.evidence import DataEvidencePackV1
    from workbench.agent.session import JsonlSessionRepository
    from workbench.http import notebook_routes
    from workbench.llm.config import LLMConfig

    class Refusal:
        async def stream(self, request):
            yield ModelStreamEvent.tool_call_delta(request.request_id, {
                "tool_call_id": "decline", "tool_id": "decline_notebook_plan",
                "arguments": {"reason_code": "missing_required_information", "message": "Need a research question."},
            })
            yield ModelStreamEvent.done(request.request_id, "tool_calls")

    project = make_project(tmp_path)
    upload = store_upload_bytes(project, b"y,x\n1,2\n3,4\n", filename="data.csv")
    service = NotebookService(project)
    notebook = service.ensure_default_projection(dataset={
        "kind": "dataset", "upload_sha256": upload, "filename": "data.csv", "sheet_names": [],
    }, created_by="test", available_capabilities=["ols"])
    monkeypatch.setattr(notebook_routes, "load_llm_config", lambda: LLMConfig(base_url="https://provider.invalid", api_key="fake", model="fake"))
    monkeypatch.setattr(notebook_routes, "CancellableOpenAICompatibleModelAdapter", lambda config: Refusal())
    planner = notebook_routes._planning_agent(project, service, notebook.notebook_id,
        service.compile_context(notebook.notebook_id), _trace(project, notebook.notebook_id, notebook.run_family_id))
    assert planner.phase_runner is not None
    result = planner.plan(context=service.compile_context(notebook.notebook_id), initial_evidence=DataEvidencePackV1("dataset", ()))
    assert result.reason_code == "missing_required_information"
    repository = JsonlSessionRepository(project / "workbench")
    sessions = [m for m in repository.list_metadata() if m["role"] == "planning"]
    assert len(sessions) == 1 and sessions[0]["chain_id"] == notebook.notebook_id
    assert any(entry.entry_type == "phase_state" for entry in repository.get_branch(sessions[0]["session_id"]))
