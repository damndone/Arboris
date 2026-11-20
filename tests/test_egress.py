"""v1.8.9 step 8 — what may leave this computer in a provider request.

The checkpoint is asserted on the HTTP body the provider would receive, not on
an intermediate structure: that body is the only thing that leaves.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest

from workbench import egress
from workbench.egress import (
    TOOL_CONTENT_CLASSES,
    EgressPolicy,
    egress_project,
    guard_outgoing_messages,
    read_audit,
    save_policy,
    suggested_sensitivity,
)
from workbench.llm import client as llm_client
from workbench.llm.client import LLMUpstreamError
from workbench.llm.config import LLMConfig

BACKEND = Path(__file__).resolve().parents[1] / "backend" / "workbench"
REMOTE = LLMConfig(base_url="https://api.deepseek.com", api_key="k", model="deepseek-chat", provider_id="deepseek")
LOCAL = LLMConfig(base_url="http://127.0.0.1:11434/v1", api_key="k", model="qwen", provider_id="ollama", data_location="local")

ROWS_RESULT = {
    "tool_call_id": "call-rows",
    "tool_id": "show_dataset_rows",
    "ok": True,
    "output": {
        "columns": ["wage", "educ"],
        "rows": [{"wage": 18.731, "educ": 12.0}, {"wage": 22.404, "educ": 16.0}],
        "egress_summary": "Rows 1-2 of 200 (2 columns) of stage:raw in run r1 are shown to the user in Workbench.",
    },
}


def _conversation(tool_id: str, result: dict) -> list[dict]:
    return [
        {"role": "system", "content": "You are the Workbench agent."},
        {"role": "user", "content": "把前20行发给我看"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": tool_id, "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": "call-1", "content": json.dumps(result, ensure_ascii=False)},
    ]


def _send(monkeypatch, messages: list[dict], config: LLMConfig) -> dict:
    """Send through the real client and return the body the provider received."""

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]})

    monkeypatch.setattr(
        llm_client,
        "_client_factory",
        lambda actual: httpx.Client(transport=httpx.MockTransport(handler), timeout=actual.timeout_s),
    )
    llm_client.chat_completion(messages, config)
    assert len(seen) == 1
    return json.loads(seen[0].content)


def _tool_content(body: dict) -> dict:
    return json.loads(next(message for message in body["messages"] if message["role"] == "tool")["content"])


# -- every tool is classified ------------------------------------------------


def _declared_tool_ids() -> set[str]:
    ids: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # Context tools keep their static fields in tool_specs.py as dict(tool_id=...).
            constructor = getattr(node.func, "id", None) if isinstance(node, ast.Call) else None
            if constructor == "ToolDefinition" or (constructor == "dict" and path.name == "tool_specs.py"):
                for keyword in node.keywords:
                    if keyword.arg == "tool_id" and isinstance(keyword.value, ast.Constant):
                        ids.add(keyword.value.value)
    from workbench.agent.notebook.planning_agent import NOTEBOOK_TOOLS

    ids.update(tool["tool_id"] for tool in NOTEBOOK_TOOLS)
    return ids


@pytest.mark.parametrize("tool_id", ["propose_operation", "propose_analysis_loop"])
def test_retired_tool_results_keep_their_original_content_class(monkeypatch, tmp_path: Path, tool_id) -> None:
    assert tool_id not in _declared_tool_ids()
    historical = {"ok": True, "output": {"requires_confirmation": True}}
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation(tool_id, historical), REMOTE)
    assert _tool_content(body) == historical
    assert read_audit(tmp_path)[0]["decisions"][0]["content_class"] == "workbench_state"


def test_every_tool_declares_what_it_can_send() -> None:
    declared = _declared_tool_ids()
    assert "show_dataset_rows" in declared
    assert declared - set(TOOL_CONTENT_CLASSES) == set(), "classify new tools in workbench/egress.py"
    assert set(TOOL_CONTENT_CLASSES) - declared == set(), "remove classes of deleted tools"
    assert set(TOOL_CONTENT_CLASSES.values()) <= set(egress.CONTENT_CLASSES)


# -- the default policy ------------------------------------------------------


def test_rows_never_reach_a_remote_provider_by_default(monkeypatch, tmp_path: Path) -> None:
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("show_dataset_rows", ROWS_RESULT), REMOTE)
    wire = json.dumps(body, ensure_ascii=False)
    assert "18.731" not in wire and "22.404" not in wire
    note = _tool_content(body)
    assert note["egress_withheld"] is True
    assert note["content_class"] == "rows"
    assert note["shown_to_user"].startswith("Rows 1-2 of 200")
    # The user's own words go as written.
    assert body["messages"][1]["content"] == "把前20行发给我看"

    [record] = read_audit(tmp_path)
    assert record["provider_id"] == "deepseek"
    assert record["provider_locality"] == "remote"
    assert record["withheld_count"] == 1
    assert record["decisions"] == [
        {"index": 3, "role": "tool", "tool_id": "show_dataset_rows", "content_class": "rows", "decision": "withheld"}
    ]
    assert record["payload_bytes"] == len(json.dumps(body["messages"], ensure_ascii=False, sort_keys=True).encode())


def test_a_local_provider_receives_rows(monkeypatch, tmp_path: Path) -> None:
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("show_dataset_rows", ROWS_RESULT), LOCAL)
    assert _tool_content(body)["output"]["rows"][0]["wage"] == 18.731
    assert read_audit(tmp_path)[0]["provider_locality"] == "local"


@pytest.mark.parametrize("base_url", ["http://127.0.0.1:3425/v1", "http://localhost:3425/v1", "http://[::1]:3425/v1"])
@pytest.mark.parametrize("tool_id,result", [
    ("show_dataset_rows", ROWS_RESULT),
    ("brand_new_tool", {"ok": True, "output": {"secret": "unclassified-value"}}),
    ("inspect_project_model_coefficients", {"ok": True, "output": {"estimate": 1.234}}),
])
def test_unknown_loopback_gateway_has_remote_wire_policy(monkeypatch, tmp_path, base_url, tool_id, result):
    gateway = replace(REMOTE, base_url=base_url, provider_id="magpie-workbuddy-ai",
                      model="workbuddy-ai/deepseek-v4.1-flash")
    with egress_project(tmp_path):
        remote_body = _send(monkeypatch, _conversation(tool_id, result), REMOTE)
        gateway_body = _send(monkeypatch, _conversation(tool_id, result), gateway)
    assert gateway_body["messages"] == remote_body["messages"]
    assert gateway_body["model"] == "workbuddy-ai/deepseek-v4.1-flash"
    assert read_audit(tmp_path)[-1]["provider_locality"] == "remote"


def test_gateway_column_protection_and_policy_view_match_wire(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from workbench.api import app
    from workbench.http import egress_routes

    gateway = replace(REMOTE, base_url="http://127.0.0.1:3425/v1", provider_id="magpie-workbuddy-ai")
    save_policy(tmp_path, EgressPolicy(columns={"age": "restricted"},
        providers={gateway.provider_id: frozenset(egress.CONTENT_CLASSES)}))
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("inspect_data_schema", SCHEMA_RESULT), gateway)
    output = _tool_content(body)["output"]
    assert output["value_labels"] == {"phone": egress.WITHHELD, "age": egress.WITHHELD}
    assert output["frequencies"]["name"] == egress.WITHHELD
    record = read_audit(tmp_path)[-1]
    assert record["provider_host"] == "127.0.0.1"
    assert record["provider_locality"] == "remote"
    monkeypatch.setattr(egress_routes, "load_llm_config", lambda: gateway)
    view = TestClient(app).get("/projects/egress", params={"project_root": str(tmp_path)})
    assert view.status_code == 200, view.text
    assert view.json()["active_provider"]["locality"] == record["provider_locality"]


def test_aggregates_and_model_results_reach_a_remote_provider(monkeypatch, tmp_path: Path) -> None:
    result = {"ok": True, "output": {"models": [{"coefficients": [{"term": "educ", "estimate": 1.234}]}]}}
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("inspect_project_model_coefficients", result), REMOTE)
    assert _tool_content(body)["output"]["models"][0]["coefficients"][0]["estimate"] == 1.234


def test_a_failed_rows_call_reaches_the_model_as_the_error_it_is(monkeypatch, tmp_path: Path) -> None:
    """Found live: the rows call failed, the guard withheld its error as 'rows',
    and the model told the user the table was on screen."""

    failed = {
        "ok": False, "output": None, "error": "ToolVisibleError",
        "error_details": [{"message": "DATASET_ROWS_UNAVAILABLE: source graph node was not found"}],
    }
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("show_dataset_rows", failed), REMOTE)
    assert _tool_content(body) == failed
    assert read_audit(tmp_path)[0]["decisions"][0]["content_class"] == "workbench_state"


def test_an_unclassified_tool_is_treated_as_the_most_restrictive(monkeypatch, tmp_path: Path) -> None:
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("brand_new_tool", {"ok": True, "output": {"x": 1}}), REMOTE)
    note = _tool_content(body)
    assert note == {**note, "egress_withheld": True, "content_class": "unclassified"}
    # Nothing was shown to the user, so the note must not say it was.
    assert "shown_to_user" not in note and "Workbench" not in note["guidance"]


def test_a_project_may_allow_rows_for_one_provider(monkeypatch, tmp_path: Path) -> None:
    save_policy(
        tmp_path,
        EgressPolicy(providers={"deepseek": frozenset(egress.REMOTE_DEFAULT_ALLOW | {"rows"})}),
    )
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("show_dataset_rows", ROWS_RESULT), REMOTE)
    assert _tool_content(body)["output"]["rows"][1]["educ"] == 16.0
    assert read_audit(tmp_path)[0]["policy_source"].endswith("policy.json")


def test_a_broken_policy_blocks_the_call_instead_of_falling_back(monkeypatch, tmp_path: Path) -> None:
    egress.policy_path(tmp_path).parent.mkdir(parents=True)
    egress.policy_path(tmp_path).write_text("{not json", encoding="utf-8")
    with egress_project(tmp_path), pytest.raises(LLMUpstreamError, match="policy is invalid"):
        _send(monkeypatch, _conversation("show_dataset_rows", ROWS_RESULT), LOCAL)


def test_calls_outside_a_project_are_still_guarded_and_audited(monkeypatch) -> None:
    body = _send(monkeypatch, _conversation("show_dataset_rows", ROWS_RESULT), REMOTE)
    assert _tool_content(body)["egress_withheld"] is True
    assert read_audit(None)[0]["project_root"] is None


# -- column sensitivity ------------------------------------------------------


SCHEMA_RESULT = {
    "ok": True,
    "output": {
        "columns": [
            {"name": "name", "dtype": "object", "unique_count": 200, "top_values": ["Alice", "Bob"]},
            {"name": "phone", "dtype": "object", "variable_label": "手机号", "min": "13800000000"},
            {"name": "age", "dtype": "float64", "unique_count": 40},
        ],
        "value_labels": {"phone": {"1": "13800000000"}, "age": {"99": "refused"}},
        "frequencies": {"name": {"Alice": 1, "Bob": 1}},
        "terms": ["C(Q('name'))[T.Bob]", "age"],
    },
}


def test_personal_columns_keep_their_names_but_not_their_values(monkeypatch, tmp_path: Path) -> None:
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("inspect_data_schema", SCHEMA_RESULT), REMOTE)
    wire = json.dumps(body, ensure_ascii=False)
    for value in ("Alice", "Bob", "13800000000"):
        assert value not in wire
    output = _tool_content(body)["output"]
    name, phone, age = output["columns"]
    assert name == {"name": "name", "dtype": "object", "unique_count": 200, "values_withheld": True}
    assert phone == {"name": "phone", "dtype": "object", "variable_label": "手机号", "values_withheld": True}
    # `name` is a structural key in every column entry: only the column's values go.
    assert age == {"name": "age", "dtype": "float64", "unique_count": 40}
    assert output["value_labels"] == {"phone": egress.WITHHELD, "age": {"99": "refused"}}
    assert output["frequencies"] == {"name": egress.WITHHELD}
    assert output["terms"] == ["C(Q('name'))[withheld]", "age"]
    assert read_audit(tmp_path)[0]["redacted_columns"] == ["name", "phone"]


def test_the_user_can_mark_a_suggested_column_public(monkeypatch, tmp_path: Path) -> None:
    save_policy(tmp_path, EgressPolicy(columns={"name": "public"}))
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("inspect_data_schema", SCHEMA_RESULT), REMOTE)
    output = _tool_content(body)["output"]
    assert output["frequencies"] == {"name": {"Alice": 1, "Bob": 1}}
    assert output["value_labels"]["phone"] == egress.WITHHELD


def test_restricted_values_reach_no_provider_and_sensitive_values_reach_local_ones(monkeypatch, tmp_path: Path) -> None:
    save_policy(tmp_path, EgressPolicy(columns={"age": "restricted"}))
    with egress_project(tmp_path):
        body = _send(monkeypatch, _conversation("inspect_data_schema", SCHEMA_RESULT), LOCAL)
    output = _tool_content(body)["output"]
    assert output["value_labels"] == {"phone": {"1": "13800000000"}, "age": egress.WITHHELD}
    assert output["frequencies"] == {"name": {"Alice": 1, "Bob": 1}}


@pytest.mark.parametrize(
    ("column", "level"),
    [
        ("name", "sensitive"), ("full_name", "sensitive"), ("姓名", "sensitive"), ("phone", "sensitive"),
        ("手机号", "sensitive"), ("email", "sensitive"), ("身份证号", "sensitive"), ("address", "sensitive"),
        ("country_name", "internal"), ("countryname", "internal"), ("wage", "internal"),
        ("telecom_share", "internal"), ("id", "internal"),
    ],
)
def test_the_name_heuristic_only_suggests_personal_columns(column: str, level: str) -> None:
    assert suggested_sensitivity(column) == level


# -- server-built evidence ---------------------------------------------------


def test_notebook_sample_rows_are_withheld_from_the_planning_prompt(monkeypatch, tmp_path: Path) -> None:
    """Notebook planning sends its evidence pack in the user turn, not as a tool
    result; the sample records in it are rows all the same."""

    evidence = {
        "records": [
            {"protocol_version": "profile/v1", "status": "completed",
             "observations": {"row_count": 200}, "metrics": {"missing_rate": 0.0}},
            {"protocol_version": "sample/v1", "status": "completed",
             "observations": {"columns": ["wage"], "rows": [{"wage": 18.731}]}, "metrics": {}},
        ]
    }
    messages = [{"role": "user", "content": json.dumps({"context": {}, "evidence": evidence})}]
    with egress_project(tmp_path):
        body = _send(monkeypatch, messages, REMOTE)
    records = json.loads(body["messages"][0]["content"])["evidence"]["records"]
    assert records[0]["observations"] == {"row_count": 200}
    assert records[1]["observations"]["egress_withheld"] is True
    assert "18.731" not in json.dumps(body)
    [decision] = read_audit(tmp_path)[0]["decisions"]
    assert decision["withheld_protocols"] == ["sample/v1"]


@pytest.mark.parametrize("allow_metadata", [True, False])
def test_initial_plan_facts_respect_metadata_and_protected_columns(monkeypatch, tmp_path, allow_metadata):
    classes = {"workbench_state", "schema", "aggregate"}
    if allow_metadata:
        classes.add("metadata")
    save_policy(tmp_path, EgressPolicy(providers={REMOTE.provider_id: frozenset(classes)},
                                       columns={"site_code": "restricted"}))
    guidance = "Draft a research plan using the available evidence."
    facts = {"source": {"run_id": "private-run"}, "dataset": {"columns": [
        {"name": "site_code", "dtype": "string", "unique_count": 47, "missing_rate": 0.375},
        {"name": "age", "dtype": "float64", "unique_count": 31, "missing_rate": 0.25},
    ]}}
    content = {"guidance": guidance, "context": {
        "protocol_version": "initial-plan-facts/v1", "observations": facts,
    }}
    with egress_project(tmp_path):
        body = _send(monkeypatch, [{"role": "system", "content": json.dumps(content)}], REMOTE)

    sent = json.loads(body["messages"][0]["content"])
    assert sent["guidance"] == guidance
    observations = sent["context"]["observations"]
    [decision] = read_audit(tmp_path)[0]["decisions"]
    if allow_metadata:
        assert observations.get("egress_withheld") is not True
        assert observations["source"] == facts["source"]
        protected, ordinary = observations["dataset"]["columns"]
        assert protected == {"name": "site_code", "dtype": "string", "values_withheld": True}
        assert ordinary == facts["dataset"]["columns"][1]
        assert decision["redacted_columns"] == ["site_code"]
    else:
        assert observations["egress_withheld"] is True
        assert observations["content_class"] == "metadata"
        assert set(observations) == {"egress_withheld", "content_class", "reason"}
        assert decision["withheld_protocols"] == ["initial-plan-facts/v1"]


def test_plain_conversation_is_sent_unchanged() -> None:
    messages = [{"role": "user", "content": "educ 的系数是多少？"}, {"role": "assistant", "content": "1.23"}]
    assert guard_outgoing_messages(messages, base_url=REMOTE.base_url) == messages


# -- the rows tool -----------------------------------------------------------


@pytest.fixture(scope="module")
def project_run(tmp_path_factory) -> tuple[Path, str]:
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    tmp_path = tmp_path_factory.mktemp("egress-rows")
    rng = np.random.default_rng(3)
    frame = pd.DataFrame({"wage": rng.normal(20, 4, 60).round(3), "educ": rng.integers(9, 20, 60).astype(float)})
    source = tmp_path / "wages.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "p")
    outcome = run_workflow(project.root, [source], mode="auto", model_type="ols", y="wage", x=["educ"])
    assert outcome["status"] == "completed", outcome
    return project.root, outcome["run_id"]


def _rows_tool(root: Path):
    from workbench.agent.context_tools import NodeOperationContextProvider

    definitions = NodeOperationContextProvider(root).tool_definitions(chain_id="c1", session_id="s1")
    return {definition.tool_id: definition for definition in definitions}["show_dataset_rows"]


def test_the_rows_tool_shows_rows_and_says_what_it_showed(project_run) -> None:
    from workbench.agent.tools import ToolContext

    root, run_id = project_run
    tool = _rows_tool(root)
    result = tool.handler(
        {"run_id": run_id, "node_id": "stage:raw", "limit": 20, "columns": ["educ"]},
        ToolContext(session_id="s1", metadata={}),
    )
    assert result["columns"] == ["educ"]
    assert len(result["rows"]) == 20 and set(result["rows"][0]) == {"educ"}
    assert result["row_numbers"][:2] == [1, 2]
    assert result["egress_summary"] == f"Rows 1-20 of 60 (1 column) of stage:raw in run {run_id} are shown to the user in Workbench."


def test_the_rows_tool_accepts_the_forest_node_key_the_main_agent_sees(project_run) -> None:
    from workbench.agent.tools import ToolContext

    root, run_id = project_run
    result = _rows_tool(root).handler(
        {"run_id": run_id, "node_id": f"{'6d' * 32}::stage:raw", "limit": 2},
        ToolContext(session_id="s1", metadata={}),
    )
    assert result["node_id"] == "stage:raw" and len(result["rows"]) == 2


def test_the_main_agent_can_show_rows_too(project_run) -> None:
    from workbench.agent.context_tools import NodeOperationContextProvider

    root, _run_id = project_run
    tools = {tool.tool_id: tool for tool in NodeOperationContextProvider(root).global_tool_definitions(session_id="m")}
    assert tools["show_dataset_rows"].scope_requirements == ("project",)


def test_the_rows_tool_names_the_real_columns_when_asked_for_an_absent_one(project_run) -> None:
    from workbench.agent.tools import ToolContext, ToolVisibleError

    root, run_id = project_run
    with pytest.raises(ToolVisibleError, match="salary"):
        _rows_tool(root).handler(
            {"run_id": run_id, "node_id": "stage:raw", "columns": ["salary"]},
            ToolContext(session_id="s1", metadata={}),
        )


# -- the policy API ----------------------------------------------------------


def test_the_policy_api_edits_column_levels_and_shows_the_audit(project_run, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from workbench.api import app

    root, run_id = project_run
    client = TestClient(app)
    params = {"project_root": str(root)}
    view = client.get("/projects/egress", params=params).json()
    assert view["defaults"]["remote"] == ["workbench_state", "schema", "metadata", "aggregate", "model_result"]
    assert view["policy"]["columns"] == {}

    variables = client.get(
        f"/runs/{run_id}/datasets/variables", params={**params, "node_id": "stage:raw"}
    ).json()["variables"]
    assert {(item["name"], item["sensitivity"], item["sensitivity_source"]) for item in variables} == {
        ("wage", "internal", "suggested"), ("educ", "internal", "suggested"),
    }

    patched = client.patch("/projects/egress/columns", params=params, json={"columns": {"wage": "restricted"}})
    assert patched.status_code == 200, patched.text
    assert patched.json()["policy"]["columns"] == {"wage": "restricted"}
    variables = client.get(
        f"/runs/{run_id}/datasets/variables", params={**params, "node_id": "stage:raw"}
    ).json()["variables"]
    assert {item["name"]: item["sensitivity_source"] for item in variables}["wage"] == "project"

    cleared = client.patch("/projects/egress/columns", params=params, json={"columns": {"wage": None}})
    assert cleared.json()["policy"]["columns"] == {}

    refused = client.put(
        "/projects/egress/policy", params=params, json={"providers": {"deepseek": {"allow": ["everything"]}}}
    )
    assert refused.status_code == 422
    assert "everything" in refused.json()["error"]["message"]

    replaced = client.put(
        "/projects/egress/policy", params=params,
        json={"providers": {"deepseek": {"allow": ["workbench_state", "schema"]}}, "columns": {"educ": "sensitive"}},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["policy"]["providers"] == {"deepseek": {"allow": ["schema", "workbench_state"]}}
    assert replaced.json()["policy"]["columns"] == {"educ": "sensitive"}
    assert replaced.json()["policy_source"].endswith("workbench/egress/policy.json")
    client.put("/projects/egress/policy", params=params, json={})

    with egress_project(root):
        _send(monkeypatch, _conversation("show_dataset_rows", ROWS_RESULT), REMOTE)
    records = client.get("/projects/egress/audit", params=params).json()["records"]
    assert records[0]["withheld_count"] == 1


def test_research_review_packet_obeys_model_result_sharing_at_the_wire_boundary(monkeypatch, tmp_path):
    save_policy(tmp_path, EgressPolicy(providers={'remote': frozenset({'workbench_state', 'aggregate'})}))
    packet = {'protocol_version': 'research-review/v1', 'observations': {
        'candidate': 'PRIVATE MODEL CANDIDATE', 'models': [{'estimate': 18.731}],
        'diagnostics': [{'p_value': .0041}]}}
    with egress_project(tmp_path):
        body = _send(monkeypatch, [{'role': 'user', 'content': json.dumps(packet)}], REMOTE)
    sent = json.loads(body['messages'][0]['content'])
    assert sent['observations']['egress_withheld'] is True
    assert 'PRIVATE MODEL CANDIDATE' not in json.dumps(body)
    assert '18.731' not in json.dumps(body)
