from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_MODEL_TYPE,
    LmmModelInput,
)
from workbench.analysis_loop.canonical import sha256_canonical
from workbench.engine.registry import MODEL_REGISTRY, ModelHandler
from workbench.engine.stages.estimation import _persist_model_options_execution_binding
from workbench.graph_store import GraphStore
from workbench.lineage.op_contract import OperationContract, validate_overrides
from workbench.lineage.op_spec import op_spec_for_stage
from workbench.lineage.run_inputs import read_run_inputs, write_run_inputs
from workbench.model_options import (
    ModelOptionsContract,
    ModelOptionsError,
    bind_new_model_options,
    canonical_options_hash,
    parse_model_options,
)
from workbench.projects import create_project
from workbench.orchestrator import run_workflow
from workbench.services.rerun_service import (
    RerunService,
    RerunServiceError,
    RerunSubmissionRequest,
)
from workbench.services.run_service import _submit_run, merge_form_overrides


def _lmm_options(*, random_slope: bool = True) -> dict[str, object]:
    return {
        "subject_id": "participant_id",
        "time": "week",
        "group": "arm",
        "fit_method": "reml",
        "random_slope": random_slope,
    }


@pytest.fixture
def lmm_handler(monkeypatch: pytest.MonkeyPatch) -> ModelHandler:
    """Exercise the future handler contract without registering an LMM pack."""

    handler = ModelHandler(
        model_type=LMM_MODEL_TYPE,
        model_id="linear_mixed_effects_1",
        serves_y_types=("continuous",),
        fit=lambda ctx, _env: (
            "linear_mixed_effects_1",
            {
                "model_type": LMM_MODEL_TYPE,
                "nobs": len(ctx.data.frame),
                "coefficients": {},
            },
            None,
        ),
        validate_model_options=lambda value: LmmModelInput.from_dict(value),
        model_options_contract=ModelOptionsContract(
            producer_version="linear_mixed_effects@1.0",
            input_contract_version=LMM_CONTRACT_VERSION,
        ),
    )
    monkeypatch.setitem(MODEL_REGISTRY, LMM_MODEL_TYPE, handler)
    return handler


def _source_form(*, binding: dict[str, object] | None) -> dict[str, object]:
    form: dict[str, object] = {
        "mode": "auto",
        "model_type": LMM_MODEL_TYPE,
        "y": "y",
        "x": "x",
        "covariance": "robust",
        "model_options": _lmm_options(),
    }
    if binding is not None:
        form["model_options_binding"] = binding
    return form


def _fake_events() -> SimpleNamespace:
    return SimpleNamespace(
        executor=SimpleNamespace(submit=lambda *_args, **_kwargs: None),
        register_run=lambda *_args, **_kwargs: None,
        mark_active=lambda *_args, **_kwargs: None,
    )


def test_server_binding_is_canonical_and_has_stable_owner_facts(
    lmm_handler: ModelHandler,
) -> None:
    del lmm_handler
    first = bind_new_model_options(
        LMM_MODEL_TYPE,
        {
            "random_slope": True,
            "fit_method": "reml",
            "group": "arm",
            "time": "week",
            "subject_id": "participant_id",
        },
    )
    second = bind_new_model_options(LMM_MODEL_TYPE, _lmm_options())

    expected_hash = "a5bfb0cb983acb1fd5909622ec3fe9eed7d04de2a2b7c3f21d6b49f66f7457e5"
    whitespace_and_reordered = parse_model_options(
        """ {\n  \"time\" : \"week\",\n  \"random_slope\" : true,\n  \"group\" : \"arm\",\n  \"subject_id\" : \"participant_id\",\n  \"fit_method\" : \"reml\"\n} """
    )

    assert first.payload == _lmm_options()
    assert first.binding is not None
    assert first.binding.to_dict() == {
        "owner_model_type": LMM_MODEL_TYPE,
        "owner_model_id": "linear_mixed_effects_1",
        "producer_version": "linear_mixed_effects@1.0",
        "input_contract_version": "1.0",
        "normalized_options_hash": expected_hash,
    }
    assert second.binding == first.binding
    assert canonical_options_hash(_lmm_options()) == expected_hash
    assert canonical_options_hash(whitespace_and_reordered) == expected_hash
    assert canonical_options_hash(_lmm_options(random_slope=False)) != (
        canonical_options_hash(_lmm_options())
    )


def test_rerun_merge_requires_a_valid_same_owner_and_never_inherits_across_models(
    lmm_handler: ModelHandler,
) -> None:
    del lmm_handler
    bound = bind_new_model_options(LMM_MODEL_TYPE, _lmm_options())
    assert bound.binding is not None
    source = _source_form(binding=bound.binding.to_dict())

    child = merge_form_overrides(
        source,
        {"model_options": {"random_slope": False}},
    )

    assert child["model_options"] == _lmm_options(random_slope=False)
    assert "model_options_binding" not in child
    assert source["model_options"] == _lmm_options()

    with pytest.raises(ModelOptionsError) as missing_replacement:
        merge_form_overrides(source, {"model_type": "ols"})
    assert missing_replacement.value.code == "MODEL_OPTIONS_REPLACEMENT_REQUIRED"

    cleared = merge_form_overrides(
        source,
        {"model_type": "ols", "model_options": {}},
    )
    assert cleared["model_type"] == "ols"
    assert cleared["model_options"] == {}
    assert "subject_id" not in cleared["model_options"]

    legacy_empty = merge_form_overrides(
        {"model_type": "ols", "model_options": {}},
        {"model_type": "iv_2sls"},
    )
    assert legacy_empty["model_type"] == "iv_2sls"
    assert legacy_empty["model_options"] == {}


def test_rerun_rejects_tampered_or_unowned_source_before_reusing_options(
    lmm_handler: ModelHandler,
) -> None:
    del lmm_handler
    bound = bind_new_model_options(LMM_MODEL_TYPE, _lmm_options())
    assert bound.binding is not None
    tampered = bound.binding.to_dict() | {"normalized_options_hash": "0" * 64}

    with pytest.raises(ModelOptionsError) as integrity:
        merge_form_overrides(
            _source_form(binding=tampered),
            {"x": ["x2"]},
        )
    assert integrity.value.code == "MODEL_OPTIONS_INTEGRITY_ERROR"

    with pytest.raises(ModelOptionsError) as missing_owner:
        merge_form_overrides(
            _source_form(binding=None),
            {"x": ["x2"]},
        )
    assert missing_owner.value.code == "MODEL_OPTIONS_OWNER_MISSING"

    cleared = merge_form_overrides(
        _source_form(binding=None),
        {"model_type": "ols", "model_options": {}},
    )
    assert cleared["model_options"] == {}

    # A complete cross-model replacement does not inspect a retired source,
    # including source integrity facts that are no longer relevant.
    tampered_cleared = merge_form_overrides(
        _source_form(binding=tampered),
        {"model_type": "ols", "model_options": {}},
    )
    assert tampered_cleared["model_options"] == {}


def test_cross_model_replacement_uses_only_the_target_payload(
    lmm_handler: ModelHandler,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del lmm_handler

    def _validate_target(value: dict[str, object]) -> None:
        if value != {"regularization": "ridge"}:
            raise ValueError("target options must be complete and exact")

    target_handler = ModelHandler(
        model_type="configured_target",
        model_id="configured_target_1",
        serves_y_types=("continuous",),
        fit=lambda _ctx, _env: ("configured_target_1", {}, None),
        validate_model_options=_validate_target,
        model_options_contract=ModelOptionsContract(
            producer_version="configured_target@1.0",
            input_contract_version="1.0",
        ),
    )
    monkeypatch.setitem(MODEL_REGISTRY, "configured_target", target_handler)
    source_bound = bind_new_model_options(LMM_MODEL_TYPE, _lmm_options())
    assert source_bound.binding is not None

    poisoned_source = _source_form(binding={"not": "a binding"})
    poisoned_source["model_options"] = {"api_key": "retired-secret"}
    replacement = merge_form_overrides(
        poisoned_source,
        {
            "model_type": "configured_target",
            "model_options": {"regularization": "ridge"},
        },
    )

    assert replacement["model_options"] == {"regularization": "ridge"}
    assert "subject_id" not in replacement["model_options"]


def test_same_model_owner_contract_change_requires_replacement(
    lmm_handler: ModelHandler,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del lmm_handler
    source_bound = bind_new_model_options(LMM_MODEL_TYPE, _lmm_options())
    assert source_bound.binding is not None
    monkeypatch.setitem(
        MODEL_REGISTRY,
        LMM_MODEL_TYPE,
        ModelHandler(
            model_type=LMM_MODEL_TYPE,
            model_id="linear_mixed_effects_2",
            serves_y_types=("continuous",),
            fit=lambda _ctx, _env: ("linear_mixed_effects_2", {}, None),
            validate_model_options=lambda value: LmmModelInput.from_dict(value),
            model_options_contract=ModelOptionsContract(
                producer_version="linear_mixed_effects@2.0",
                input_contract_version="2.0",
            ),
        ),
    )

    tampered_source = _source_form(
        binding=source_bound.binding.to_dict()
        | {"normalized_options_hash": "0" * 64}
    )
    tampered_source["model_options"] = {"api_key": "retired-secret"}

    with pytest.raises(ModelOptionsError) as error:
        merge_form_overrides(
            tampered_source,
            {"x": ["x2"]},
        )
    assert error.value.code == "MODEL_OPTIONS_REPLACEMENT_REQUIRED"

    replacement = merge_form_overrides(
        tampered_source,
        {"model_options": _lmm_options(random_slope=False)},
    )
    assert replacement["model_options"] == _lmm_options(random_slope=False)


def test_submission_overwrites_forged_binding_and_persists_child_audit_chain(
    tmp_path: Path,
    lmm_handler: ModelHandler,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del lmm_handler
    import workbench.services.run_service as run_service

    monkeypatch.setattr(run_service, "get_event_manager", _fake_events)
    project = create_project(tmp_path, "owner-binding")
    forged = {
        "owner_model_type": "forged",
        "owner_model_id": "forged",
        "producer_version": "forged",
        "input_contract_version": "0",
        "normalized_options_hash": "0" * 64,
    }
    submitted = _submit_run(
        project.root,
        form={
            "mode": "auto",
            "model_type": LMM_MODEL_TYPE,
            "y": "y",
            "x": "x",
            "model_options": _lmm_options(),
            "model_options_binding": forged,
        },
        upload_bytes=b"y,x\n1,2\n3,4\n",
        upload_filename="source.csv",
        started_at="2026-07-18T00:00:00+00:00",
    )
    source_inputs = json.loads(
        (project.root / "runs" / submitted["run_id"] / "run_inputs.json").read_text()
    )
    expected_binding = bind_new_model_options(LMM_MODEL_TYPE, _lmm_options()).binding
    assert expected_binding is not None
    for payload in (source_inputs["form"], source_inputs["executable_payload"]):
        assert payload["model_options_binding"] == expected_binding.to_dict()
        assert payload["model_options_binding"] != forged

    child_form = merge_form_overrides(
        source_inputs["form"],
        {"model_options": {"random_slope": False}},
    )
    child = _submit_run(
        project.root,
        form=child_form,
        upload_bytes=b"y,x\n1,2\n3,4\n",
        upload_filename="source.csv",
        started_at="2026-07-18T00:01:00+00:00",
        rerun_of=submitted["run_id"],
        from_node="model:source",
        rerun_reason="owner_binding_test",
        op_overrides={"model_options": {"random_slope": False}},
    )
    child_inputs = json.loads(
        (project.root / "runs" / child["run_id"] / "run_inputs.json").read_text()
    )
    expected_child = bind_new_model_options(
        LMM_MODEL_TYPE, _lmm_options(random_slope=False)
    ).binding
    assert expected_child is not None
    for payload in (
        child_inputs["form"],
        child_inputs["executable_payload"],
        child_inputs["confirmed_payload"],
    ):
        assert payload["model_options"] == _lmm_options(random_slope=False)
        assert payload["model_options_binding"] == expected_child.to_dict()


def test_rerun_service_keeps_parent_immutable_and_audits_bound_child(
    tmp_path: Path,
    lmm_handler: ModelHandler,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the public rerun boundary without adding an LMM runtime pack."""

    del lmm_handler
    import workbench.orchestrator as orchestrator

    # Test-only execution seam: production C1.1 still has no LMM pack,
    # declaration, or public model-type mapping.
    monkeypatch.setitem(orchestrator._MODEL_TYPE_MAP, LMM_MODEL_TYPE, "continuous")
    source = tmp_path / "source.csv"
    source.write_bytes(
        (
            "y,x\n"
            + "\n".join(f"{1 + 2 * index},{index}" for index in range(35))
            + "\n"
        ).encode()
    )
    project = create_project(tmp_path, "rerun-owner-binding")
    parent = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="ols",
        model_options={},
    )
    assert parent["status"] == "completed"

    parent_root = project.root / "runs" / parent["run_id"]
    parent_inputs_path = parent_root / "run_inputs.json"
    parent_inputs = json.loads(parent_inputs_path.read_text(encoding="utf-8"))
    parent_bound = bind_new_model_options(LMM_MODEL_TYPE, _lmm_options())
    assert parent_bound.binding is not None
    parent_inputs["form"].update(
        {
            "model_type": LMM_MODEL_TYPE,
            "model_options": parent_bound.payload,
            "model_options_binding": parent_bound.binding.to_dict(),
        }
    )
    parent_inputs_path.write_text(json.dumps(parent_inputs), encoding="utf-8")
    source_before = parent_inputs_path.read_text(encoding="utf-8")

    graph = GraphStore(project.root / "runs").read(parent["run_id"])
    model_node_id = next(
        node_id
        for node_id, node in graph.nodes.items()
        if getattr(node.stage, "value", node.stage) == "model"
    )
    child = RerunService(project.root).submit(
        RerunSubmissionRequest(
            source_run_id=parent["run_id"],
            from_node=model_node_id,
            op_overrides={"model_options": {"random_slope": False}},
        )
    )
    assert parent_inputs_path.read_text(encoding="utf-8") == source_before

    child_root = project.root / "runs" / child.run_id
    expected = bind_new_model_options(
        LMM_MODEL_TYPE, _lmm_options(random_slope=False)
    )
    assert expected.binding is not None
    child_inputs = json.loads((child_root / "run_inputs.json").read_text(encoding="utf-8"))
    for payload in (
        child_inputs["form"],
        child_inputs["executable_payload"],
        child_inputs["confirmed_payload"],
    ):
        assert payload["model_options"] == expected.payload
        assert payload["model_options_binding"] == expected.binding.to_dict()

    for _ in range(100):
        manifest = json.loads((child_root / "run_manifest.json").read_text(encoding="utf-8"))
        if manifest["status"] in {"completed", "failed", "cancelled", "interrupted", "partial"}:
            break
        time.sleep(0.05)
    assert manifest["status"] == "completed"
    child_inputs = json.loads((child_root / "run_inputs.json").read_text(encoding="utf-8"))
    assert child_inputs["confirmed_payload"] == child_inputs["executed_payload"]


def test_rerun_service_maps_second_submit_owner_error_to_stable_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dynamic handler change cannot leak a raw model-options exception."""

    import workbench.services.rerun_service as rerun_service

    source = tmp_path / "source.csv"
    source.write_bytes(
        (
            "y,x\n"
            + "\n".join(f"{1 + 2 * index},{index}" for index in range(35))
            + "\n"
        ).encode()
    )
    project = create_project(tmp_path, "rerun-owner-error")
    parent = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="ols",
        model_options={},
    )
    assert parent["status"] == "completed"
    graph = GraphStore(project.root / "runs").read(parent["run_id"])
    model_node_id = next(
        node_id
        for node_id, node in graph.nodes.items()
        if getattr(node.stage, "value", node.stage) == "model"
    )

    def _raise_on_second_bind(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise ModelOptionsError(
            "MODEL_OPTIONS_UNSUPPORTED", "handler changed after rerun merge"
        )

    monkeypatch.setattr(rerun_service, "_submit_run", _raise_on_second_bind)
    with pytest.raises(RerunServiceError) as error:
        RerunService(project.root).submit(
            RerunSubmissionRequest(
                source_run_id=parent["run_id"],
                from_node=model_node_id,
                op_overrides={},
            )
        )
    assert error.value.code == "MODEL_OPTIONS_UNSUPPORTED"


def test_successful_generic_options_execution_matches_confirmed_payload(
    tmp_path: Path,
    lmm_handler: ModelHandler,
) -> None:
    """Terminal generic persistence preserves the full confirmed wire contract."""

    del lmm_handler
    bound = bind_new_model_options(LMM_MODEL_TYPE, _lmm_options())
    assert bound.binding is not None
    confirmed_payload = {
        # A resolved glm handler uses the registry key "glm", but the audit
        # contract must retain the caller's wire alias.
        "model_type": "glm:poisson",
        "covariance": "robust",
        "entity_col": "firm",
        "y": "y",
        "x": ["x"],
        "model_options": bound.payload,
        "model_options_binding": bound.binding.to_dict(),
    }
    run_root = tmp_path / "successful-generic-handler"
    run_root.mkdir()
    write_run_inputs(
        run_root,
        form={
            "model_type": "glm:poisson",
            "model_options": bound.payload,
            "model_options_binding": bound.binding.to_dict(),
        },
        upload={"sha256": "0" * 64, "filename": "source.csv"},
        rerun_of=None,
        from_node=None,
        rerun_reason="test",
        override_hash=None,
        dag_hash="1" * 64,
        confirmed_payload=confirmed_payload,
    )

    _persist_model_options_execution_binding(
        run_root,
        model_type="glm",
        model_options=bound.payload,
        model_options_binding=bound.binding.to_dict(),
    )

    inputs = read_run_inputs(run_root)
    assert inputs["executed_payload"] == confirmed_payload
    assert sha256_canonical(inputs["executed_payload"]) == sha256_canonical(
        inputs["confirmed_payload"]
    )


def test_direct_workflow_and_lineage_form_include_server_binding(
    tmp_path: Path,
    lmm_handler: ModelHandler,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del lmm_handler
    import workbench.orchestrator as orchestrator

    source = tmp_path / "source.csv"
    source.write_bytes(b"y,x\n1,2\n3,4\n")
    project = create_project(tmp_path, "direct-owner-binding")
    captured: dict[str, object] = {}

    def _fake_workflow(*args: object, **kwargs: object) -> dict[str, str]:
        captured.update(kwargs)
        return {"run_id": str(args[1]), "status": "completed"}

    monkeypatch.setattr(orchestrator, "_run_workflow", _fake_workflow)
    result = orchestrator.run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type=LMM_MODEL_TYPE,
        model_options=_lmm_options(),
    )
    inputs = json.loads(
        (project.root / "runs" / result["run_id"] / "run_inputs.json").read_text()
    )

    assert captured["model_options_binding"] == inputs["form"]["model_options_binding"]
    assert inputs["executable_payload"]["model_options_binding"] == inputs["form"]["model_options_binding"]
    assert op_spec_for_stage("estimation", form=inputs["form"], config={})[
        "model_options_binding"
    ] == inputs["form"]["model_options_binding"]


def test_nonempty_options_fail_closed_without_an_explicit_supported_owner() -> None:
    with pytest.raises(ModelOptionsError) as unresolved:
        bind_new_model_options(LMM_MODEL_TYPE, _lmm_options())
    assert unresolved.value.code == "MODEL_OPTIONS_OWNER_UNRESOLVED"

    with pytest.raises(ModelOptionsError) as automatic:
        bind_new_model_options("auto", {"future_option": True})
    assert automatic.value.code == "MODEL_OPTIONS_EXPLICIT_MODEL_REQUIRED"

    with pytest.raises(ModelOptionsError) as unsupported:
        bind_new_model_options("ols", {"future_option": True})
    assert unsupported.value.code == "MODEL_OPTIONS_UNSUPPORTED"

    with pytest.raises(ModelOptionsError) as secret:
        bind_new_model_options("ols", {"api_key": "not-allowed"})
    assert secret.value.code == "MODEL_OPTIONS_SECRET_KEY_FORBIDDEN"


def test_hidden_rerun_transport_accepts_only_object_payloads() -> None:
    contract = OperationContract(op_type="ols", schema_id="ols@v1", editable_schema=[])

    validate_overrides(contract, {"model_options": {}})
    with pytest.raises(ValueError, match="model_options"):
        validate_overrides(contract, {"model_options": ["not", "an", "object"]})
