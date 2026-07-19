from __future__ import annotations

import io
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.agent.operations import OperationRegistry, OperationValidationError
from workbench.agent.orchestrator import _overrides_from_proposal_changes
from workbench.analysis_loop.adapters import AnalysisLoopAdapter, AnalysisLoopAdapterRegistry
from workbench.analysis_loop.compare import ComparePacket
from workbench.artifacts import read_json
from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_MODEL_TYPE,
    LmmModelInput,
)
from workbench.engine.capabilities import (
    CapabilityDeclaration,
    build_capabilities,
    register_capability_declaration,
)
from workbench.engine.registry import MODEL_REGISTRY, ModelHandler
from workbench.engine.packs.builtin_declarations import BUILTIN_PACK_DECLARATIONS
from workbench.engine.packs.loader import (
    PackDeclaration,
    bootstrap_builtin_packs,
    load_declared_packs,
)
from workbench.lineage.op_spec import op_spec_for_stage
from workbench.lineage.manual_patch_validation import (
    ManualPatchValidationError,
    ManualRerunPatch,
    validate_manual_patch,
)
from workbench.lineage.pipeline_drafts import _validate_control_value
from workbench.model_options import (
    ModelOptionsContract,
    ModelOptionsError,
    bind_new_model_options,
)
from workbench.http.agent_routes import CHAIN_AGENT_PROTOCOL
from workbench.orchestrator import run_workflow
from workbench.orchestrator import _map_model_type, _validate_requested_model_type
from workbench.projects import create_project
from workbench.services.run_service import merge_model_options, parse_model_options


RESTRICTED_MESSAGE = (
    "两个模型使用 REML 且固定效应结构不同；似然、AIC 和似然比检验不作为有效的直接比较依据。"
)


def _csv() -> bytes:
    return pd.DataFrame(
        {
            "y": [1.0, 2.0, 3.0, 4.0],
            "x": [1.0, 2.0, 3.0, 4.0],
            "firm": ["a", "a", "b", "b"],
        }
    ).to_csv(index=False).encode()


def _compare_packet_kwargs(compare_status: str = "complete") -> dict[str, object]:
    return {
        "compare_status": compare_status,
        "source_run_id": "source",
        "child_run_id": "child",
        "target": {"result_id": "group_time_interaction"},
        "data_diff": {},
        "parameter_diff": {},
        "result_diff": {},
        "conclusion_diff": {"classification": "NOT_COMPARABLE"},
        "validation_status": "pass",
        "integrity_findings": [],
        "logical_key": f"compare:{compare_status}",
        "strategy_version": "linear_mixed_effects_v1",
        "schema_version": "compare_packet_v1",
    }


def _model_rerun_target() -> dict[str, object]:
    return {
        "run_id": "run-1",
        "node_ref": "model:1",
        "node_hash": "node-hash",
        "forest_node_key": "forest:1",
    }


def _model_rerun_preconditions() -> dict[str, object]:
    return {
        "context_version": "context-v1",
        "context_fingerprint": "fingerprint",
        "active_head_run_id": "run-1",
        "owner_resolution": "active_head",
    }


def test_pack_loader_rejects_duplicate_model_type() -> None:
    declarations = (
        PackDeclaration("workbench.engine.packs.fake_one.declaration", "fake_model"),
        PackDeclaration("workbench.engine.packs.fake_two.declaration", "fake_model"),
    )

    with pytest.raises(ValueError, match="duplicate declared model type"):
        load_declared_packs(declarations)


def test_pack_loader_rejects_multiple_model_types_for_one_declaration_module() -> None:
    declarations = (
        PackDeclaration("workbench.engine.packs.fake.declaration", "first_model"),
        PackDeclaration("workbench.engine.packs.fake.declaration", "second_model"),
    )

    with pytest.raises(ValueError, match="duplicate declared pack module"):
        load_declared_packs(declarations)


def test_pack_loader_rolls_back_a_failed_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.capabilities as capabilities
    import workbench.engine.packs.loader as loader
    import workbench.engine.stages.estimation  # noqa: F401

    original_handlers = dict(MODEL_REGISTRY)
    original_declarations = dict(capabilities._DECLARED_CAPABILITIES)
    declaration = PackDeclaration("test.failed_declaration", "half_loaded_model")

    def declare_pack() -> None:
        MODEL_REGISTRY["half_loaded_model"] = ModelHandler(
            model_type="half_loaded_model",
            model_id="half_loaded_1",
            serves_y_types=("continuous",),
            fit=lambda _ctx, _env: ("half_loaded_1", {}, None),
        )
        register_capability_declaration(
            CapabilityDeclaration(
                model_type="half_loaded_model",
                label="Half loaded",
                group="Panel",
                description="Must not survive a declaration failure.",
                requires=(),
                params=(),
            )
        )
        raise RuntimeError("declaration failed after registration")

    monkeypatch.setattr(loader, "_LOADED_MODEL_TYPES", set())
    monkeypatch.setattr(loader, "_LOADING_MODEL_TYPES", set(), raising=False)
    monkeypatch.setattr(loader, "_DECLARED_PACK_MODULES", {}, raising=False)
    monkeypatch.setattr(
        loader,
        "import_module",
        lambda _module: SimpleNamespace(declare_pack=declare_pack),
    )

    with pytest.raises(RuntimeError, match="declaration failed"):
        loader.load_declared_packs((declaration,))

    assert dict(MODEL_REGISTRY) == original_handlers
    assert dict(capabilities._DECLARED_CAPABILITIES) == original_declarations
    assert "half_loaded_model" not in loader._LOADED_MODEL_TYPES


def test_pack_loader_rejects_a_declaration_without_its_declared_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.loader as loader
    import workbench.engine.stages.estimation  # noqa: F401

    original_handlers = dict(MODEL_REGISTRY)
    declaration = PackDeclaration("test.wrong_handler", "declared_model")

    def declare_pack() -> None:
        MODEL_REGISTRY["unrelated_model"] = ModelHandler(
            model_type="unrelated_model",
            model_id="unrelated_1",
            serves_y_types=("continuous",),
            fit=lambda _ctx, _env: ("unrelated_1", {}, None),
        )

    monkeypatch.setattr(loader, "_LOADED_MODEL_TYPES", set())
    monkeypatch.setattr(loader, "_LOADING_MODEL_TYPES", set(), raising=False)
    monkeypatch.setattr(loader, "_DECLARED_PACK_MODULES", {}, raising=False)
    monkeypatch.setattr(
        loader,
        "import_module",
        lambda _module: SimpleNamespace(declare_pack=declare_pack),
    )

    with pytest.raises(ValueError, match="did not register declared model type"):
        loader.load_declared_packs((declaration,))

    assert dict(MODEL_REGISTRY) == original_handlers


def test_pack_loader_rejects_and_rolls_back_a_core_handler_overwrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.loader as loader
    import workbench.engine.stages.estimation  # noqa: F401

    original_handlers = dict(MODEL_REGISTRY)
    declaration = PackDeclaration("test.core_override", "future_model")

    def declare_pack() -> None:
        MODEL_REGISTRY["ols"] = ModelHandler(
            model_type="ols",
            model_id="compromised_ols",
            serves_y_types=("continuous",),
            fit=lambda _ctx, _env: ("compromised_ols", {}, None),
        )
        MODEL_REGISTRY["future_model"] = ModelHandler(
            model_type="future_model",
            model_id="future_model_1",
            serves_y_types=("continuous",),
            fit=lambda _ctx, _env: ("future_model_1", {}, None),
        )

    monkeypatch.setattr(loader, "_LOADED_MODEL_TYPES", set())
    monkeypatch.setattr(loader, "_LOADING_MODEL_TYPES", set(), raising=False)
    monkeypatch.setattr(loader, "_DECLARED_PACK_MODULES", {}, raising=False)
    monkeypatch.setattr(
        loader,
        "import_module",
        lambda _module: SimpleNamespace(declare_pack=declare_pack),
    )

    with pytest.raises(ValueError, match="overwrote existing model handler"):
        loader.load_declared_packs((declaration,))

    assert dict(MODEL_REGISTRY) == original_handlers


def test_pack_loader_is_reentrant_safe_while_a_pack_declares_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.loader as loader

    declaration = PackDeclaration("test.reentrant", "reentrant_model")
    calls = 0

    def declare_pack() -> None:
        nonlocal calls
        calls += 1
        MODEL_REGISTRY["reentrant_model"] = ModelHandler(
            model_type="reentrant_model",
            model_id="reentrant_1",
            serves_y_types=("continuous",),
            fit=lambda _ctx, _env: ("reentrant_1", {}, None),
        )
        loader.load_declared_packs((declaration,))

    monkeypatch.setattr(loader, "_LOADED_MODEL_TYPES", set())
    monkeypatch.setattr(loader, "_LOADING_MODEL_TYPES", set(), raising=False)
    monkeypatch.setattr(loader, "_DECLARED_PACK_MODULES", {}, raising=False)
    monkeypatch.setattr(
        loader,
        "import_module",
        lambda _module: SimpleNamespace(declare_pack=declare_pack),
    )

    try:
        loader.load_declared_packs((declaration,))
        assert calls == 1
    finally:
        MODEL_REGISTRY.pop("reentrant_model", None)


def test_adapter_registry_fails_closed_for_unknown_model() -> None:
    registry = AnalysisLoopAdapterRegistry()

    with pytest.raises(KeyError, match="no analysis-loop adapter"):
        registry.resolve("linear_mixed_effects")

    adapter = AnalysisLoopAdapter(
        model_type="test_model",
        build_source_facts=lambda _: {},
        build_validation=lambda _: {},
        build_compare=lambda _: {},
    )
    registry.register(adapter)
    assert registry.resolve("test_model") is adapter
    with pytest.raises(ValueError, match="duplicate analysis-loop adapter"):
        registry.register(adapter)


def test_compare_packet_accepts_restricted_status_with_safe_reason() -> None:
    packet = ComparePacket(
        **_compare_packet_kwargs("restricted"),
        reason_code="REML_FIXED_EFFECTS_DIFFER",
        user_safe_message=RESTRICTED_MESSAGE,
    )

    assert packet.to_dict()["compare_status"] == "restricted"
    assert packet.to_dict()["reason_code"] == "REML_FIXED_EFFECTS_DIFFER"
    assert packet.to_dict()["user_safe_message"] == RESTRICTED_MESSAGE
    assert ComparePacket.from_dict(packet.to_dict()) == packet


@pytest.mark.parametrize(
    "compare_status", ("complete", "partial", "not_comparable", "blocked_by_integrity")
)
def test_existing_compare_statuses_keep_their_exact_wire_shape(
    compare_status: str,
) -> None:
    packet = ComparePacket(**_compare_packet_kwargs(compare_status))

    assert packet.to_dict() == _compare_packet_kwargs(compare_status)
    assert ComparePacket.from_dict(packet.to_dict()) == packet


@pytest.mark.parametrize(
    "kwargs",
    (
        {},
        {"reason_code": ""},
        {"user_safe_message": ""},
        {"reason_code": "REML_FIXED_EFFECTS_DIFFER"},
        {"user_safe_message": RESTRICTED_MESSAGE},
    ),
)
def test_restricted_compare_requires_both_nonempty_safe_fields(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="restricted"):
        ComparePacket(**_compare_packet_kwargs("restricted"), **kwargs)


def test_empty_builtin_pack_declarations_do_not_change_current_capabilities() -> None:
    import workbench.engine.stages.estimation  # noqa: F401

    before = build_capabilities()
    bootstrap_builtin_packs()

    assert BUILTIN_PACK_DECLARATIONS == ()
    assert build_capabilities() == before


def test_declared_capability_stays_hidden_without_a_registered_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.capabilities as capabilities

    monkeypatch.setattr(capabilities, "_DECLARED_CAPABILITIES", {})
    declaration = CapabilityDeclaration(
        model_type="future_model",
        label="Future model",
        group="Panel",
        description="Only exposed once a handler exists.",
        requires=("entity",),
        params=(),
    )
    register_capability_declaration(declaration)

    keys = {entry["key"] for entry in build_capabilities()["model_types"]}
    assert "future_model" not in keys


@pytest.mark.parametrize("model_type", ("auto", "glm", "poisson_rate"))
def test_capability_declaration_cannot_publish_reserved_core_model_types(
    model_type: str,
) -> None:
    with pytest.raises(ValueError, match="reserved model type"):
        register_capability_declaration(
            CapabilityDeclaration(
                model_type=model_type,
                label="Invalid public alias",
                group="Panel",
                description="Must not expose a core-only execution alias.",
                requires=(),
                params=(),
            )
        )


def test_declared_model_type_is_accepted_without_a_central_model_map_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.capabilities as capabilities

    monkeypatch.setattr(capabilities, "_DECLARED_CAPABILITIES", {})
    handler = ModelHandler(
        model_type="future_model",
        model_id="future_model_1",
        serves_y_types=("continuous",),
        fit=lambda _ctx, _env: ("future_model_1", {}, None),
    )
    monkeypatch.setitem(MODEL_REGISTRY, "future_model", handler)
    register_capability_declaration(
        CapabilityDeclaration(
            model_type="future_model",
            label="Future model",
            group="Panel",
            description="A declared future model.",
            requires=(),
            params=(),
        )
    )

    assert _validate_requested_model_type("future_model") is None
    assert _map_model_type("future_model") == "continuous"


@pytest.mark.parametrize(
    ("raw", "code"),
    (("{", "MODEL_OPTIONS_INVALID_JSON"), ("[]", "MODEL_OPTIONS_NOT_OBJECT")),
)
def test_model_options_parser_fails_closed(raw: str, code: str) -> None:
    with pytest.raises(ModelOptionsError) as error:
        parse_model_options(raw)

    assert error.value.code == code


def test_model_options_merge_is_one_level_and_leaves_sources_unchanged() -> None:
    source = {"fit_method": "reml", "random_slope": True}
    patch = {"random_slope": False}

    merged = merge_model_options(source, patch)

    assert merged == {"fit_method": "reml", "random_slope": False}
    assert source == {"fit_method": "reml", "random_slope": True}
    assert patch == {"random_slope": False}


def test_model_options_are_an_estimation_only_lineage_input() -> None:
    form = {"model_type": "ols", "model_options": {"unused": True}}

    assert op_spec_for_stage("source", form=form, config={}) == {}
    assert op_spec_for_stage("estimation", form=form, config={})["model_options"] == {
        "unused": True
    }


@pytest.mark.parametrize(
    ("model_type", "code"),
    (
        ("ols", "MODEL_OPTIONS_UNSUPPORTED"),
        ("auto", "MODEL_OPTIONS_EXPLICIT_MODEL_REQUIRED"),
    ),
)
def test_legacy_model_fails_closed_before_creating_a_run_for_nonempty_model_options(
    tmp_path, model_type: str, code: str
) -> None:
    source = tmp_path / "source.csv"
    pd.DataFrame(
        {
            "y": [1.0 + 2.0 * index for index in range(35)],
            "x": list(range(35)),
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "model-options")

    with pytest.raises(ModelOptionsError) as error:
        run_workflow(
            project.root,
            [source],
            mode="auto",
            y="y",
            x=["x"],
            model_type=model_type,
            model_options={"future_option": True},
        )

    assert error.value.code == code
    assert not list((project.root / "runs").iterdir())


def test_ols_terminal_metadata_retains_empty_model_options(tmp_path) -> None:
    source = tmp_path / "source.csv"
    pd.DataFrame(
        {
            "y": [1.0 + 2.0 * index for index in range(35)],
            "x": list(range(35)),
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "ols-empty-model-options")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="ols",
        model_options={},
    )

    assert result["status"] == "completed"
    inputs = read_json(project.root / "runs" / result["run_id"] / "run_inputs.json")
    assert inputs["form"]["model_options"] == {}
    assert inputs["executable_payload"]["model_options"] == {}
    assert inputs["executed_payload"]["model_options"] == {}


def test_child_submission_persists_the_exact_one_level_model_options_merge(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.services.run_service as run_service

    project = create_project(tmp_path, "child-model-options")
    source_options = {
        "subject_id": "participant_id",
        "time": "week",
        "group": "arm",
        "fit_method": "reml",
        "random_slope": True,
    }
    handler = ModelHandler(
        model_type=LMM_MODEL_TYPE,
        model_id="linear_mixed_effects_1",
        serves_y_types=("continuous",),
        fit=lambda _ctx, _env: ("linear_mixed_effects_1", {}, None),
        validate_model_options=lambda value: LmmModelInput.from_dict(value),
        model_options_contract=ModelOptionsContract(
            producer_version="linear_mixed_effects@1.0",
            input_contract_version=LMM_CONTRACT_VERSION,
        ),
    )
    monkeypatch.setitem(MODEL_REGISTRY, LMM_MODEL_TYPE, handler)
    source_binding = bind_new_model_options(LMM_MODEL_TYPE, source_options).binding
    assert source_binding is not None
    child_form = run_service.merge_form_overrides(
        {
            "mode": "auto",
            "model_type": LMM_MODEL_TYPE,
            "y": "y",
            "x": "x",
            "covariance": "robust",
            "model_options": source_options,
            "model_options_binding": source_binding.to_dict(),
        },
        {"model_options": {"random_slope": False}},
    )

    class FakeExecutor:
        def submit(self, *_args: object, **_kwargs: object) -> None:
            return None

    class FakeEvents:
        executor = FakeExecutor()

        def register_run(self, *_args: object, **_kwargs: object) -> None:
            return None

        def mark_active(self, *_args: object, **_kwargs: object) -> None:
            return None

    with patch(
        "workbench.services.run_service.get_event_manager",
        return_value=FakeEvents(),
    ):
        submitted = run_service._submit_run(
            project.root,
            form=child_form,
            upload_bytes=_csv(),
            upload_filename="source.csv",
            started_at="2026-07-18T00:00:00+00:00",
            rerun_of="run-source",
            from_node="model:source",
            rerun_reason="model_options_test",
            op_overrides={"model_options": {"random_slope": False}},
        )

    inputs = read_json(project.root / "runs" / submitted["run_id"] / "run_inputs.json")
    expected_options = {**source_options, "random_slope": False}
    expected_binding = bind_new_model_options(
        LMM_MODEL_TYPE, expected_options
    ).binding
    assert expected_binding is not None
    assert inputs["form"]["model_options"] == expected_options
    assert inputs["executable_payload"]["model_options"] == expected_options
    assert inputs["confirmed_payload"]["model_options"] == expected_options
    assert inputs["form"]["model_options_binding"] == expected_binding.to_dict()
    assert inputs["executable_payload"]["model_options_binding"] == expected_binding.to_dict()
    assert inputs["confirmed_payload"]["model_options_binding"] == expected_binding.to_dict()


def test_model_rerun_accepts_only_object_model_options() -> None:
    definition = OperationRegistry().require("model.rerun")

    definition.validate(
        target=_model_rerun_target(),
        preconditions=_model_rerun_preconditions(),
        changes={"model_options": {"random_slope": False}},
    )
    with pytest.raises(OperationValidationError, match="model_options"):
        definition.validate(
            target=_model_rerun_target(),
            preconditions=_model_rerun_preconditions(),
            changes={"model_options": ["not", "an", "object"]},
        )
    definition.validate(
        target=_model_rerun_target(),
        preconditions=_model_rerun_preconditions(),
        changes={
            "model_options": {
                "old": {"a": 1},
                "new": ["a legitimate future option value"],
                "additional_option": True,
            }
        },
    )


def test_agent_override_translation_preserves_a_literal_new_model_option() -> None:
    literal_options = {
        "old": {"nested": "a legitimate future option"},
        "new": ["another legitimate future option"],
        "additional_option": True,
    }

    assert _overrides_from_proposal_changes(
        {"model_options": literal_options}
    ) == {"model_options": literal_options}


def test_agent_protocol_marks_model_options_as_a_direct_patch() -> None:
    assert "model_options must be a direct one-level object patch" in CHAIN_AGENT_PROTOCOL
    assert "never wrap it as an old/new field diff" in CHAIN_AGENT_PROTOCOL


def test_object_controls_reject_nonobject_values_at_draft_and_manual_patch_boundaries() -> None:
    draft_checks = _validate_control_value(
        "model_options",
        ["not", "an", "object"],
        {"key": "model_options", "kind": "object", "editable": True},
        node_id="model:linear_mixed_effects",
    )
    assert [item["code"] for item in draft_checks] == ["INVALID_PARAM_TYPE"]

    nonfinite_checks = _validate_control_value(
        "model_options",
        {"nested": float("nan")},
        {"key": "model_options", "kind": "object", "editable": True},
        node_id="model:linear_mixed_effects",
    )
    assert [item["code"] for item in nonfinite_checks] == [
        "MODEL_OPTIONS_INVALID_JSON"
    ]

    patch = ManualRerunPatch(
        patch_id="patch-model-options",
        patch_source="MANUAL_EDIT",
        source_context_fingerprint="context",
        editable_schema_version="run_inputs@v1",
        target={
            "owner_run_id": "run-source",
            "op_node_id": "model:linear_mixed_effects",
            "node_hash": "node-hash",
        },
        changes=[
            {
                "field_id": "model_options",
                "old_value": {},
                "new_value": ["not", "an", "object"],
            }
        ],
    )

    with pytest.raises(ManualPatchValidationError, match="INVALID_FIELD_VALUE"):
        validate_manual_patch(
            patch=patch,
            current_values={"model_options": {}},
            editable_schema=[
                {"key": "model_options", "kind": "object", "editable": True}
            ],
            editable_schema_version="run_inputs@v1",
        )


def test_ols_empty_model_options_preserve_model_and_covariance_over_http(
    tmp_path,
) -> None:
    from workbench.api import app

    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    with patch(
        "workbench.services.run_service._run_workflow",
        return_value={"run_id": "r", "status": "succeeded"},
    ) as workflow:
        response = client.post(
            "/runs",
            data={
                "project_root": root,
                "mode": "auto",
                "model_type": "ols",
                "y": "y",
                "x": "x",
                "covariance": "robust",
                "model_options": "{}",
            },
            files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
        )
        for _ in range(100):
            if workflow.call_args is not None:
                break
            time.sleep(0.05)

    assert response.status_code == 200
    kwargs = workflow.call_args.kwargs
    assert kwargs["model_type"] == "ols"
    assert kwargs["covariance"] == "robust"
    assert kwargs["model_options"] == {}


@pytest.mark.parametrize(
    ("raw", "code"),
    (("{", "MODEL_OPTIONS_INVALID_JSON"), ("[]", "MODEL_OPTIONS_NOT_OBJECT")),
)
def test_run_endpoint_rejects_invalid_model_options_before_execution(
    tmp_path, raw: str, code: str
) -> None:
    from workbench.api import app

    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    response = client.post(
        "/runs",
        data={
            "project_root": root,
            "mode": "auto",
            "model_type": "ols",
            "y": "y",
            "x": "x",
            "model_options": raw,
        },
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == code


def test_run_endpoint_rejects_unresolved_lmm_options_owner_before_creating_a_run(
    tmp_path,
) -> None:
    from workbench.api import app

    client = TestClient(app)
    root = client.post(
        "/projects", json={"parent": str(tmp_path), "name": "demo"}
    ).json()["project_root"]

    response = client.post(
        "/runs",
        data={
            "project_root": root,
            "mode": "auto",
            "model_type": LMM_MODEL_TYPE,
            "y": "y",
            "x": "x",
            "model_options": json.dumps(
                {
                    "subject_id": "participant_id",
                    "time": "week",
                    "group": "arm",
                    "fit_method": "reml",
                    "random_slope": True,
                }
            ),
        },
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "MODEL_OPTIONS_OWNER_UNRESOLVED"
    assert not list((Path(root) / "runs").iterdir())
