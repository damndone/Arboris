from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest


def _options() -> dict[str, object]:
    return {"subject_id": "subject", "time": "week", "group": "arm", "fit_method": "reml", "random_slope": True}


def _binding() -> dict[str, str]:
    return {
        "owner_model_type": "linear_mixed_effects",
        "owner_model_id": "linear_mixed_effects_1",
        "producer_version": "linear_mixed_effects@1.0",
        "input_contract_version": "1.0",
        "normalized_options_hash": "a" * 64,
    }


def test_bg_run_hands_the_exact_admission_object_to_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import workbench.services.run_service as service

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    upload = run_root / "input.csv"
    upload.write_text("y,x\n1,2\n")
    sentinel = object()
    captured: dict[str, object] = {}

    monkeypatch.setattr(service, "load_config", lambda _: type("Config", (), {"run_timeout_s": 60})())
    monkeypatch.setattr(service, "_resolve_project_root", lambda _: tmp_path)
    monkeypatch.setattr(service, "_admit_lmm_execution_for_bg_run", lambda **_: sentinel)
    monkeypatch.setattr(service, "_run_workflow", lambda *args, **kwargs: captured.update(kwargs) or {"status": "complete"})
    monkeypatch.setattr(service, "get_event_manager", lambda: type("Events", (), {"is_cancel_requested": lambda *_: False, "emit": lambda *_: None, "emit_terminal": lambda *_: None, "release_slot": lambda *_: None})())

    service._bg_run(run_root, "run-1", upload, "auto", "y", ["x"], "2026-07-19T00:00:00Z", model_type="linear_mixed_effects", model_options=_options(), model_options_binding=_binding())
    assert captured["lmm_execution_admission"] is sentinel


def test_admission_rejects_request_that_differs_from_pinned_run_inputs(tmp_path: Path) -> None:
    from workbench.lineage.run_inputs import write_run_inputs
    from workbench.services.run_service import LmmExecutionAdmissionError, _admit_lmm_execution_for_bg_run

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    write_run_inputs(run_root, form={"model_type": "linear_mixed_effects", "model_options": _options(), "model_options_binding": _binding()}, upload={"sha256": "a" * 64, "filename": "x.csv"}, rerun_of=None, from_node=None, rerun_reason="initial", override_hash=None, dag_hash="b" * 64)
    changed = _options() | {"random_slope": False}
    with pytest.raises(LmmExecutionAdmissionError, match="LMM_EXECUTION_BINDING_REQUIRED"):
        _admit_lmm_execution_for_bg_run(run_root=run_root, run_id="run-1", model_type="linear_mixed_effects", model_options=changed, model_options_binding=_binding())
    assert not (run_root / "artifacts" / "model_results" / "linear_mixed_effects_1.result.json").exists()


def test_non_lmm_workflow_receives_no_admission_keyword() -> None:
    import inspect
    from workbench.orchestrator import _run_workflow

    assert inspect.signature(_run_workflow).parameters["lmm_execution_admission"].default is None


def test_lmm_packet_is_unwrapped_for_legacy_downstream_stages() -> None:
    """The internal stages consume public result facts, never an envelope shell."""

    from workbench.engine.stages.estimation import _result_for_downstream
    from workbench.engine.stages.recording import _primary_payload_ref

    packet = {
        "contract": "linear_mixed_effects.result",
        "contract_version": "1.0",
        "producer_version": "linear_mixed_effects@1.0",
        "payload": {
            "model_id": "linear_mixed_effects_1",
            "model_type": "linear_mixed_effects",
            "status": "complete",
            "coefficients": {},
        },
    }

    assert _result_for_downstream("linear_mixed_effects", packet) == packet["payload"]
    assert _primary_payload_ref("linear_mixed_effects_1", packet["payload"]) == (
        "artifacts/model_results/linear_mixed_effects_1.result.json"
    )


@pytest.mark.parametrize("admission", (None, object()))
def test_runner_rejects_missing_or_forged_admission_before_fit(admission: object | None) -> None:
    from types import SimpleNamespace
    from workbench.engine.packs.linear_mixed_effects.runner import fit_from_context

    ctx = SimpleNamespace(artifacts={}, y_col="y", x_cols=[])
    env = SimpleNamespace(run_root=Path("/tmp/run-1"), lmm_execution_admission=admission)
    with pytest.raises(RuntimeError, match="LMM_EXECUTION_BINDING_REQUIRED"):
        fit_from_context(ctx, env)


def test_runner_rejects_closed_admission_before_fit(tmp_path: Path) -> None:
    from types import SimpleNamespace
    from workbench.engine.packs.linear_mixed_effects.runner import fit_from_context
    from workbench.services.pinned_run_directory import _new_test_lmm_execution_admission, open_pinned_run_directory, seal_executed_input_v1

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    pinned = open_pinned_run_directory(tmp_path, "run-1")
    admission = _new_test_lmm_execution_admission(pinned, seal_executed_input_v1(pinned, {"schema_version": 1, "model_type": "linear_mixed_effects", "model_options": _options(), "model_options_binding": _binding()}))
    admission._close_for_test()
    with pytest.raises(RuntimeError, match="LMM_EXECUTION_BINDING_REQUIRED"):
        fit_from_context(SimpleNamespace(artifacts={}, y_col="y", x_cols=[]), SimpleNamespace(run_root=run_root, lmm_execution_admission=admission))
    pinned.close()


def test_bg_run_routes_admitted_lmm_persistence_failure_to_private_sink_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An admitted LMM persistence error must never enter generic lifecycle I/O."""

    import workbench.services.run_service as service
    from workbench.services.pinned_run_directory import LmmPersistenceError

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    upload = run_root / "input.csv"
    upload.write_text("y,x\n1,2\n")
    admission = object()
    calls: dict[str, object] = {}
    terminals: list[tuple[str, str]] = []

    monkeypatch.setattr(service, "load_config", lambda _: type("Config", (), {"run_timeout_s": 60})())
    monkeypatch.setattr(service, "_resolve_project_root", lambda _: tmp_path)
    monkeypatch.setattr(service, "_admit_lmm_execution_for_bg_run", lambda **_: admission)
    monkeypatch.setattr(
        service,
        "_run_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(LmmPersistenceError("LMM_PERSISTENCE_IO_FAILED")),
    )
    monkeypatch.setattr(
        service,
        "_record_lmm_persistence_failure",
        lambda **kwargs: calls.update(kwargs),
    )
    monkeypatch.setattr(service, "write_json", lambda *args, **kwargs: pytest.fail("generic write_json must not run"))
    monkeypatch.setattr(service, "_write_manifest", lambda *args, **kwargs: pytest.fail("generic manifest must not run"))
    monkeypatch.setattr(
        service,
        "get_event_manager",
        lambda: type("Events", (), {
            "is_cancel_requested": lambda *_: False,
            "emit": lambda *_: None,
            "emit_terminal": lambda _self, _run_id, status, message: terminals.append((status, message)),
            "release_slot": lambda *_: None,
        })(),
    )

    service._bg_run(
        run_root, "run-1", upload, "auto", "y", ["x"], "2026-07-19T00:00:00Z",
        model_type="linear_mixed_effects", model_options=_options(), model_options_binding=_binding(),
    )

    assert calls == {
        "admission": admission,
        "code": "LMM_PERSISTENCE_IO_FAILED",
        "retryable": True,
    }
    assert terminals == [("PERSISTENCE_INCOMPLETE", "LMM persistence incomplete: LMM_PERSISTENCE_IO_FAILED")]


def test_bg_run_keeps_generic_error_persistence_for_non_lmm_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.services.run_service as service

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    upload = run_root / "input.csv"
    upload.write_text("y,x\n1,2\n")
    writes: list[Path] = []
    manifests: list[str] = []

    monkeypatch.setattr(service, "load_config", lambda _: type("Config", (), {"run_timeout_s": 60})())
    monkeypatch.setattr(service, "_resolve_project_root", lambda _: tmp_path)
    monkeypatch.setattr(service, "_run_workflow", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ordinary failure")))
    monkeypatch.setattr(service, "write_json", lambda path, payload: writes.append(path))
    monkeypatch.setattr(service, "_write_manifest", lambda *args, **kwargs: manifests.append(args[3]))
    monkeypatch.setattr(
        service,
        "get_event_manager",
        lambda: type("Events", (), {
            "is_cancel_requested": lambda *_: False,
            "emit": lambda *_: None,
            "emit_terminal": lambda *_: None,
            "release_slot": lambda *_: None,
        })(),
    )

    service._bg_run(run_root, "run-1", upload, "auto", "y", ["x"], "2026-07-19T00:00:00Z", model_type="ols")

    assert manifests == ["failed"]
    assert writes == [run_root / "errors.json"]


@pytest.mark.parametrize(
    ("reason", "code"),
    (("cancelled", "LMM_EXECUTION_CANCELLED"), ("timeout", "LMM_EXECUTION_TIMEOUT")),
)
def test_bg_run_routes_admitted_lmm_interruption_to_private_sink_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str, code: str,
) -> None:
    """An admitted LMM interruption cannot downgrade into generic lifecycle I/O."""

    import workbench.services.run_service as service
    from workbench.engine.context import RunInterruptionRequested

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    upload = run_root / "input.csv"
    upload.write_text("y,x\n1,2\n")
    admission = object()
    sink: dict[str, object] = {}
    terminals: list[tuple[str, str]] = []

    monkeypatch.setattr(service, "load_config", lambda _: type("Config", (), {"run_timeout_s": 60})())
    monkeypatch.setattr(service, "_resolve_project_root", lambda _: tmp_path)
    monkeypatch.setattr(service, "_admit_lmm_execution_for_bg_run", lambda **_: admission)
    monkeypatch.setattr(
        service,
        "_run_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(RunInterruptionRequested(reason)),
    )
    monkeypatch.setattr(service, "_record_lmm_persistence_failure", lambda **kwargs: sink.update(kwargs))
    monkeypatch.setattr(service, "write_json", lambda *args, **kwargs: pytest.fail("generic errors.json must not run"))
    monkeypatch.setattr(service, "_write_manifest", lambda *args, **kwargs: pytest.fail("generic manifest must not run"))
    monkeypatch.setattr(
        service,
        "get_event_manager",
        lambda: type("Events", (), {
            "is_cancel_requested": lambda *_: False,
            "emit": lambda *_: None,
            "emit_terminal": lambda _self, _run_id, status, message: terminals.append((status, message)),
            "release_slot": lambda *_: None,
        })(),
    )

    service._bg_run(
        run_root, "run-1", upload, "auto", "y", ["x"], "2026-07-19T00:00:00Z",
        model_type="linear_mixed_effects", model_options=_options(), model_options_binding=_binding(),
    )

    assert sink == {"admission": admission, "code": code, "retryable": False}
    assert terminals == [("PERSISTENCE_INCOMPLETE", f"LMM persistence incomplete: {code}")]


def test_bg_run_keeps_generic_interruption_persistence_for_non_lmm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LMM-only containment boundary cannot change ordinary run semantics."""

    import workbench.services.run_service as service
    from workbench.engine.context import RunInterruptionRequested

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    upload = run_root / "input.csv"
    upload.write_text("y,x\n1,2\n")
    writes: list[Path] = []
    manifests: list[str] = []
    terminals: list[tuple[str, str]] = []

    monkeypatch.setattr(service, "load_config", lambda _: type("Config", (), {"run_timeout_s": 60})())
    monkeypatch.setattr(service, "_resolve_project_root", lambda _: tmp_path)
    monkeypatch.setattr(
        service,
        "_run_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(RunInterruptionRequested("cancelled")),
    )
    monkeypatch.setattr(service, "write_json", lambda path, payload: writes.append(path))
    monkeypatch.setattr(service, "_write_manifest", lambda *args, **kwargs: manifests.append(args[3]))
    monkeypatch.setattr(
        service,
        "get_event_manager",
        lambda: type("Events", (), {
            "is_cancel_requested": lambda *_: False,
            "emit": lambda *_: None,
            "emit_terminal": lambda _self, _run_id, status, message: terminals.append((status, message)),
            "release_slot": lambda *_: None,
        })(),
    )

    service._bg_run(run_root, "run-1", upload, "auto", "y", ["x"], "2026-07-19T00:00:00Z", model_type="ols")

    assert manifests == ["interrupted"]
    assert writes == [run_root / "errors.json"]
    assert terminals == [("interrupted", "Workflow interrupted by user cancellation.")]


def test_bg_run_keeps_admitted_lmm_persistence_incomplete_when_sink_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.services.run_service as service
    from workbench.services.pinned_run_directory import LmmPersistenceError

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    upload = run_root / "input.csv"
    upload.write_text("y,x\n1,2\n")
    terminals: list[tuple[str, str]] = []

    monkeypatch.setattr(service, "load_config", lambda _: type("Config", (), {"run_timeout_s": 60})())
    monkeypatch.setattr(service, "_resolve_project_root", lambda _: tmp_path)
    monkeypatch.setattr(service, "_admit_lmm_execution_for_bg_run", lambda **_: object())
    monkeypatch.setattr(
        service,
        "_run_workflow",
        lambda *args, **kwargs: (_ for _ in ()).throw(LmmPersistenceError("LMM_PERSISTENCE_IO_FAILED")),
    )
    monkeypatch.setattr(service, "_record_lmm_persistence_failure", lambda **kwargs: (_ for _ in ()).throw(OSError("sink storage /secret/path")))
    monkeypatch.setattr(service, "write_json", lambda *args, **kwargs: pytest.fail("generic write_json must not run"))
    monkeypatch.setattr(service, "_write_manifest", lambda *args, **kwargs: pytest.fail("generic manifest must not run"))
    monkeypatch.setattr(
        service,
        "get_event_manager",
        lambda: type("Events", (), {
            "is_cancel_requested": lambda *_: False,
            "emit": lambda *_: None,
            "emit_terminal": lambda _self, _run_id, status, message: terminals.append((status, message)),
            "release_slot": lambda *_: None,
        })(),
    )

    service._bg_run(
        run_root, "run-1", upload, "auto", "y", ["x"], "2026-07-19T00:00:00Z",
        model_type="linear_mixed_effects", model_options=_options(), model_options_binding=_binding(),
    )

    assert terminals == [("PERSISTENCE_INCOMPLETE", "LMM persistence incomplete: LMM_PERSISTENCE_IO_FAILED")]


def test_estimation_does_not_fall_back_to_generic_lifecycle_after_handled_lmm_input_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.artifacts as artifacts
    import workbench.engine.stages.estimation as estimation
    import workbench.orchestrator as orchestrator
    from workbench.engine.context import DataHandle, ModelingContext, RunEnv
    from workbench.engine.packs.linear_mixed_effects.input import LmmInputError

    ctx = ModelingContext(
        data=DataHandle.of(
            pd.DataFrame({"y": [1.0]}), artifact_id="cleaned:test", provenance=("source:test",)
        ),
        y_col="y",
        x_cols=[],
        requested_model_type="linear_mixed_effects",
        y_type="continuous",
        artifacts={
            "_normalized_y": "y",
            "_normalized_x": [],
            "_issue_dicts": [],
            "_model_options": {},
        },
    )
    env = RunEnv(run_root=tmp_path / "run-1", run_id="run-1", recorder=None, lmm_execution_admission=object())

    def handled_input_block(context, _env):
        context.artifacts["_linear_mixed_effects_diagnostic"] = {"code": "LMM_SUBJECT_ID_MISSING"}
        raise LmmInputError("LMM_SUBJECT_ID_MISSING", "private path /secret/input.csv")

    monkeypatch.setattr(estimation, "resolve", lambda _: SimpleNamespace(
        model_type="linear_mixed_effects", validate_model_options=None, fit=handled_input_block,
    ))
    monkeypatch.setattr(artifacts, "write_json", lambda *args, **kwargs: pytest.fail("generic errors.json must not run"))
    monkeypatch.setattr(orchestrator, "_write_manifest", lambda *args, **kwargs: pytest.fail("generic manifest must not run"))

    result = estimation.EstimationStage().run(ctx, env)

    assert result.terminal_status == "blocked"
    assert result.artifacts["_linear_mixed_effects_diagnostic"] == {"code": "LMM_SUBJECT_ID_MISSING"}


def test_bg_run_maps_admitted_pinned_error_without_generic_lifecycle_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.services.run_service as service
    from workbench.services.pinned_run_directory import PinnedRunError

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    upload = run_root / "input.csv"
    upload.write_text("y,x\n1,2\n")
    admission = object()
    sink: dict[str, object] = {}
    terminals: list[tuple[str, str]] = []

    monkeypatch.setattr(service, "load_config", lambda _: type("Config", (), {"run_timeout_s": 60})())
    monkeypatch.setattr(service, "_resolve_project_root", lambda _: tmp_path)
    monkeypatch.setattr(service, "_admit_lmm_execution_for_bg_run", lambda **_: admission)
    monkeypatch.setattr(service, "_run_workflow", lambda *args, **kwargs: (_ for _ in ()).throw(PinnedRunError("LMM_EXECUTION_INVALIDATED")))
    monkeypatch.setattr(service, "_record_lmm_persistence_failure", lambda **kwargs: sink.update(kwargs))
    monkeypatch.setattr(service, "write_json", lambda *args, **kwargs: pytest.fail("generic write_json must not run"))
    monkeypatch.setattr(service, "_write_manifest", lambda *args, **kwargs: pytest.fail("generic manifest must not run"))
    monkeypatch.setattr(
        service,
        "get_event_manager",
        lambda: type("Events", (), {
            "is_cancel_requested": lambda *_: False,
            "emit": lambda *_: None,
            "emit_terminal": lambda _self, _run_id, status, message: terminals.append((status, message)),
            "release_slot": lambda *_: None,
        })(),
    )

    service._bg_run(
        run_root, "run-1", upload, "auto", "y", ["x"], "2026-07-19T00:00:00Z",
        model_type="linear_mixed_effects", model_options=_options(), model_options_binding=_binding(),
    )

    assert sink == {"admission": admission, "code": "LMM_EXECUTION_INVALIDATED", "retryable": False}
    assert terminals == [("PERSISTENCE_INCOMPLETE", "LMM persistence incomplete: LMM_EXECUTION_INVALIDATED")]


def test_bg_run_maps_lmm_admission_error_without_generic_lifecycle_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.services.run_service as service

    run_root = tmp_path / "run-1"
    run_root.mkdir()
    upload = run_root / "input.csv"
    upload.write_text("y,x\n1,2\n")
    terminals: list[tuple[str, str]] = []

    monkeypatch.setattr(service, "load_config", lambda _: type("Config", (), {"run_timeout_s": 60})())
    monkeypatch.setattr(service, "_resolve_project_root", lambda _: tmp_path)
    monkeypatch.setattr(service, "_admit_lmm_execution_for_bg_run", lambda **_: (_ for _ in ()).throw(service.LmmExecutionAdmissionError("LMM_EXECUTION_BINDING_REQUIRED")))
    monkeypatch.setattr(service, "write_json", lambda *args, **kwargs: pytest.fail("generic write_json must not run"))
    monkeypatch.setattr(service, "_write_manifest", lambda *args, **kwargs: pytest.fail("generic manifest must not run"))
    monkeypatch.setattr(
        service,
        "get_event_manager",
        lambda: type("Events", (), {
            "is_cancel_requested": lambda *_: False,
            "emit": lambda *_: None,
            "emit_terminal": lambda _self, _run_id, status, message: terminals.append((status, message)),
            "release_slot": lambda *_: None,
        })(),
    )

    service._bg_run(
        run_root, "run-1", upload, "auto", "y", ["x"], "2026-07-19T00:00:00Z",
        model_type="linear_mixed_effects", model_options=_options(), model_options_binding=_binding(),
    )

    assert terminals == [("PERSISTENCE_INCOMPLETE", "LMM persistence incomplete: LMM_EXECUTION_BINDING_REQUIRED")]
