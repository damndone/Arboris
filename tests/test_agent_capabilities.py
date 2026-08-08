import json

import pytest
from fastapi.testclient import TestClient

from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.operations import OperationRegistry
from workbench.agent.session import JsonlSessionRepository
from workbench.app import app


@pytest.mark.parametrize(
    ("operation_id", "scope", "executor_key"),
    [
        ("model.rerun", "model node", "model.rerun"),
        ("graph.fork", "current chain/node", "graph.fork"),
    ],
)
def test_registered_operation_exposes_capability_metadata(
    operation_id: str,
    scope: str,
    executor_key: str,
) -> None:
    definition = OperationRegistry().require(operation_id)

    assert definition.scope == scope
    assert definition.risk_level == "mutating"
    assert definition.confirmation_policy == "required"
    assert definition.executor_key == executor_key
    assert definition.reconciler_key == operation_id
    assert definition.diff_builder_key
    assert definition.verification_builder_key
    assert definition.ui_description
    assert definition.example_prompts
    assert definition.proposal_schema["type"] == "object"
    assert definition.editable_schema["type"] == "object"


def test_capability_projection_is_sorted_json_safe_and_secret_free() -> None:
    capabilities = OperationRegistry().capabilities()

    assert [item["operation_id"] for item in capabilities] == [
        "code.execute",
        "data.aggregate",
        "data.append",
        "data.column.cast",
        "data.columns.cast",
        "data.dedupe",
        "data.feature_recipe",
        "data.fill_missing",
        "data.lag",
        "data.merge",
        "data.rename",
        "data.reshape",
        "data.subset",
        "data.tsset",
        "graph.fork",
        "model.custom",
        "model.genesis",
        "model.joint_f_test",
        "model.quadratic_stationary_point",
        "model.rerun",
        "model.white_test",
        "operation.multi_step",
        "report.compose",
        "statistical.derive_boolean",
        "statistical.derive_numeric",
        "statistical.derived_group_summarize",
        "statistical.explore",
    ]
    assert all(isinstance(item["executor"], str) for item in capabilities)
    assert all("api_key" not in json.dumps(item) for item in capabilities)
    assert all("<function" not in json.dumps(item) for item in capabilities)


def test_model_custom_is_registered_high_risk_but_not_a_generic_nl_execution_tool() -> None:
    definition = OperationRegistry().require("model.custom")

    assert definition.risk_level == "high"
    assert definition.confirmation_policy == "required"
    assert definition.natural_language_enabled is False
    assert definition.executor_key == "capability_factory.custom_dispatcher"
    assert definition.proposal_schema["properties"]["changes"]["required"] == [
        "capability_ref",
        "binding_ref",
        "operation",
    ]


def test_data_column_cast_is_registered_but_not_natural_language_enabled() -> None:
    definition = OperationRegistry().require("data.column.cast")

    assert definition.scope == "dataset node"
    assert definition.confirmation_policy == "required"
    assert definition.natural_language_enabled is False
    assert definition.proposal_schema["properties"]["target"]["required"] == [
        "run_id",
        "node_ref",
        "artifact_id",
        "column",
        "target_dtype",
    ]


def test_natural_language_allowlist_is_registry_owned() -> None:
    registry = OperationRegistry()

    assert registry.natural_language_operation_ids(
        scope_requirements=("chain", "active_head")
    ) == [
        "data.append",
        "data.columns.cast",
        "data.feature_recipe",
        "data.merge",
        "data.reshape",
        "data.subset",
        "graph.fork",
        "model.rerun",
        "operation.multi_step",
    ]


def test_batch_cast_asks_the_model_for_intent_and_never_for_the_artifact_id() -> None:
    """v1.7 priority 6: the model proposes; the backend supplies its own facts.

    A model that could name `artifact_id` could aim a confirmed operation at
    data the user never selected, so it is bound during canonicalization and
    kept out of the model-facing schema entirely.
    """

    registry = OperationRegistry()
    definition = registry.require("data.columns.cast")
    assert definition.natural_language_enabled is True

    schema = registry.proposal_tool_schema()
    assert "data.columns.cast" in schema["properties"]["operation_id"]["enum"]
    cast_schema = next(
        item
        for item in schema["oneOf"]
        if item["properties"]["operation_id"]["const"] == "data.columns.cast"
    )
    assert cast_schema["properties"]["target"]["required"] == ["run_id", "node_ref", "casts"]

    # `casts` is an array of {column, target_dtype}. Declaring it a string (the
    # default for target fields) made the operation unproposable: the live
    # DeepSeek smoke retried five times and correctly concluded the schema, not
    # its own output, was wrong.
    casts = cast_schema["properties"]["target"]["properties"]["casts"]
    assert casts["type"] == "array"
    assert casts["items"]["properties"]["target_dtype"]["enum"] == [
        "numeric",
        "string",
        "datetime",
    ]

    # The model supplies only the head it is standing on; every other
    # precondition is re-derived from the real data during canonicalization.
    assert cast_schema["properties"]["preconditions"]["required"] == ["active_head_run_id"]

    # The durable operation contract still demands them — only the model is spared.
    assert "artifact_id" in definition.proposal_schema["properties"]["target"]["required"]
    assert "context_fingerprint" in definition.proposal_schema["properties"][
        "preconditions"
    ]["required"]


def test_the_proposal_envelope_does_not_impose_model_rerun_shape_on_every_operation() -> None:
    """Regression: the exact payload a live DeepSeek run produced, five times.

    `proposal_tool_schema` copies its envelope from model.rerun. A JSON Schema
    `oneOf` is an AND with its parent, so the copied `target` demanded
    node_hash/forest_node_key from every operation and rejected `casts` as an
    unexpected property — data.columns.cast was literally unproposable, and the
    only signal the model got back was `invalid_tool_arguments`.
    """

    jsonschema = pytest.importorskip("jsonschema")
    schema = OperationRegistry().proposal_tool_schema()

    deepseek_payload = {
        "operation_id": "data.columns.cast",
        "operation_version": "v1",
        "target": {
            "run_id": "20260715_030535_362519_82ccf7de",
            "node_ref": "stage:cleaned",
            "casts": [
                {"column": "wage", "target_dtype": "string"},
                {"column": "education", "target_dtype": "string"},
            ],
        },
        "preconditions": {"active_head_run_id": "20260715_030535_362519_82ccf7de"},
        "changes": {
            "casts": [
                {"column": "wage", "target_dtype": "string"},
                {"column": "education", "target_dtype": "string"},
            ]
        },
        "evidence_refs": ["inspect_data_schema: wage=int64, education=int64"],
        "expected_effect": ["wage 列从 int64 转为 string"],
        "risks": ["下游模型需重新拟合"],
    }
    assert list(jsonschema.Draft7Validator(schema).iter_errors(deepseek_payload)) == []

    # The operations that already worked must keep working.
    rerun = {
        "operation_id": "model.rerun",
        "operation_version": "v1",
        "target": {"run_id": "r", "node_ref": "n", "node_hash": "h", "forest_node_key": "k"},
        "preconditions": {
            "context_version": "v",
            "context_fingerprint": "f",
            "active_head_run_id": "r",
            "owner_resolution": "o",
        },
        "changes": {"covariance": "unadjusted"},
        "evidence_refs": ["e"],
        "expected_effect": ["x"],
        "risks": ["r"],
    }
    assert list(jsonschema.Draft7Validator(schema).iter_errors(rerun)) == []


def test_code_execute_stays_off_the_natural_language_surface() -> None:
    """Arbitrary code is not something a sentence should be able to reach yet."""

    registry = OperationRegistry()

    assert registry.require("code.execute").natural_language_enabled is False
    assert "code.execute" not in registry.proposal_tool_schema()["properties"][
        "operation_id"
    ]["enum"]


def test_capabilities_route_is_read_only_and_scope_filterable(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        response = client.get(
            "/agent/capabilities",
            params={"project_root": str(project_root), "scope": "model node"},
        )

    assert response.status_code == 200
    assert [item["operation_id"] for item in response.json()["capabilities"]] == [
        "model.rerun"
    ]
    assert response.json()["boundary"]["unsupported"]
    assert not (project_root / "workbench").exists()


def test_proposal_tool_schema_is_projected_from_registered_capability(tmp_path) -> None:
    repository = JsonlSessionRepository(tmp_path)
    events = AgentEventStream(tmp_path)
    repository.create_session("main", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    agent = AgentCore(repository, events, object(), session_id="chain-session")
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main",
    )
    orchestrator.register_chain("chain-a", "chain-session", agent)

    proposal_tool = next(
        item
        for item in orchestrator.tool_registry("chain-a").descriptors()
        if item["tool_id"] == "propose_operation"
    )
    schemas = proposal_tool["input_schema"]["oneOf"]

    fork_schema = next(
        schema
        for schema in schemas
        if schema["properties"]["operation_id"].get("const") == "graph.fork"
    )
    assert "source_session_entry_id" not in fork_schema["properties"]["target"]["required"]
    assert "current Chain leaf" in fork_schema["properties"]["target"]["description"]


def test_proposal_tool_schema_excludes_typed_operations_not_enabled_for_natural_language(
    tmp_path,
) -> None:
    registry = OperationRegistry()

    schema = registry.proposal_tool_schema()

    assert schema["properties"]["operation_id"]["enum"] == [
        "data.append",
        "data.columns.cast",
        "data.feature_recipe",
        "data.merge",
        "data.reshape",
        "data.subset",
        "graph.fork",
        "model.rerun",
        "operation.multi_step",
    ]
    # The singular cast and code.execute stay off the NL surface: the batch
    # cast is the shape a sentence maps onto ("cast these columns" is one
    # intent), and arbitrary code has not earned a natural-language path.
    for excluded in ("data.column.cast", "code.execute"):
        assert all(
            item["properties"]["operation_id"].get("const") != excluded
            for item in schema["oneOf"]
        )
