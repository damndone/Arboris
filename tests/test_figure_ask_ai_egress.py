"""Chart Ask AI obeys the project's data-sharing policy at the wire.

2026-11-06 risk review, finding 1 (rechecked at 9e09502e): /llm/chat bound no project, so a
project's column levels never applied, and the context packet was appended to the system
prompt as prose, so even a bound policy could not see the values inside it. A restricted
column's values in a time-trend chart's numeric source reached the provider.
"""

from __future__ import annotations

import json

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_figure_context import _run_with_figures
from workbench.app import app
from workbench.artifacts import read_json, write_json
from workbench.egress import EgressPolicy, read_audit, save_policy
from workbench.llm import client as llm_client


@pytest.fixture(autouse=True)
def configured(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBENCH_LLM_CONFIG_PATH", raising=False)
    monkeypatch.setattr("workbench.llm.provider_store.Path.home", lambda: tmp_path)
    monkeypatch.setenv("WORKBENCH_LLM_BASE_URL", "https://llm.example.com")
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("WORKBENCH_LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("WORKBENCH_EGRESS_AUDIT_DIR", str(tmp_path / "user-audit"))


@pytest.fixture
def seen(monkeypatch):
    requests: list[httpx.Request] = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"model": "deepseek-chat", "choices": [
            {"message": {"role": "assistant", "content": "The trend rises."}, "finish_reason": "stop"}]})

    monkeypatch.setattr(llm_client, "_client_factory",
                        lambda config: httpx.Client(transport=httpx.MockTransport(respond), timeout=config.timeout_s))
    return requests


def _trend_project(tmp_path):
    project, run_id = _run_with_figures(tmp_path)
    run_root = project / "runs" / run_id
    (run_root / "figures" / "time_trend.png").write_bytes(b"\x89PNG trend")
    (run_root / "processed").mkdir(parents=True)
    pd.DataFrame({"year": [1, 2], "salary": [7654321.123, 8765432.234], "hours": [40.5, 41.5]}).to_parquet(
        run_root / "processed" / "cleaned_dataset.parquet", index=False)
    write_json(run_root / "run_inputs.json", {"form": {"time_col": "year"}})
    index = read_json(run_root / "artifacts_index.json")
    index["artifacts"].extend([
        {"artifact_id": "time_trend", "path": "figures/time_trend.png", "artifact_type": "figure",
         "step": "visualization", "sha256": "g", "inputs": []},
        {"artifact_id": "cleaned_dataset", "path": "processed/cleaned_dataset.parquet", "artifact_type": "dataset",
         "step": "cleaning", "sha256": "h", "inputs": []},
    ])
    write_json(run_root / "artifacts_index.json", index)
    save_policy(project, EgressPolicy(columns={"salary": "restricted"}))
    return project, run_id


def _ask(api, project, run_id):
    packet = api.get("/figures/ai-context", params={
        "project_root": str(project), "run_id": run_id, "artifact_id": "time_trend"}).json()
    assert "7654321.123" in json.dumps(packet)  # the chart's numeric source does carry the values
    return api.post("/llm/chat", json={
        "mode": "workbench_figure_context_v1", "question": "Explain this chart", "packet": packet,
        "response_guardrails": packet["response_guardrails"], "project_root": str(project)})


def test_a_restricted_column_s_chart_values_never_reach_the_provider(tmp_path, seen):
    project, run_id = _trend_project(tmp_path)
    with TestClient(app) as api:
        response = _ask(api, project, run_id)
    assert response.status_code == 200, response.text
    wire = seen[-1].content.decode()
    assert "7654321.123" not in wire and "8765432.234" not in wire
    assert "40.5" in wire and "41.5" in wire  # an unprotected series still reaches the chart assistant
    [record] = read_audit(project)
    assert any("salary" in decision.get("redacted_columns", ()) for decision in record["decisions"])


def test_the_system_prompt_keeps_its_instructions_and_packet_after_the_guard(tmp_path, seen):
    project, run_id = _trend_project(tmp_path)
    with TestClient(app) as api:
        assert _ask(api, project, run_id).status_code == 200
    messages = json.loads(seen[-1].content)["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert set(messages[0]) == {"role", "content"}
    assert "CANNOT see the image" in messages[0]["content"] and "Context packet:\n" in messages[0]["content"]
    assert "time trend of numeric variables" in messages[0]["content"]


def test_an_unknown_project_root_is_refused(tmp_path, seen):
    with TestClient(app) as api:
        response = api.post("/llm/chat", json={
            "mode": "workbench_figure_context_v1", "question": "Explain this chart",
            "packet": {"figure_context_version": "figure-ai-context/v1"}, "project_root": str(tmp_path / "absent")})
    assert response.status_code == 404 and not seen
