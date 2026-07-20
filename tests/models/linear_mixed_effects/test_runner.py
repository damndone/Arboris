from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import write_json
from workbench.canonical import sha256_canonical
from workbench.services.lmm_result_adapter import read_lmm_public_results
from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_MODEL_TYPE,
)
from workbench.contracts.common.envelope import PacketEnvelope
from workbench.engine.context import DataHandle, ModelingContext, RunEnv
from workbench.engine.packs.linear_mixed_effects.runner import (
    fit_from_context,
    fit_linear_mixed_effects,
)
from workbench.engine.packs.linear_mixed_effects.input import LmmInputError
from workbench.model_options import ModelOptionsBinding, canonical_options_hash
from workbench.services.pinned_run_directory import (
    open_pinned_run_directory,
    seal_executed_input_v1,
)


ROOT = Path(__file__).parents[2] / "fixtures" / "models" / "linear_mixed_effects"


def _sealed_lmm_execution(run_root: Path, options: dict[str, object]):
    """Test fixture mirroring the production pre-fit sealed-capability handoff."""

    run_root.mkdir(parents=True, exist_ok=True)
    binding = ModelOptionsBinding(
        owner_model_type="linear_mixed_effects",
        owner_model_id="linear_mixed_effects_1",
        producer_version="linear_mixed_effects@1.0",
        input_contract_version="1.0",
        normalized_options_hash=canonical_options_hash(options),
    ).to_dict()
    representation = {
        "schema_version": 1,
        "model_type": "linear_mixed_effects",
        "model_options": options,
        "model_options_binding": binding,
    }
    pinned = open_pinned_run_directory(run_root.parent, run_root.name)
    return pinned, seal_executed_input_v1(pinned, representation), binding


@pytest.fixture(autouse=True)
def _supply_explicit_test_only_seal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep model-math tests sealed; production itself has no bare fallback."""

    original_direct = fit_linear_mixed_effects
    original_context = fit_from_context

    def sealed_direct(**kwargs):
        if kwargs.get("sealed_execution_input") is None:
            from workbench.services.pinned_run_directory import _new_lmm_execution_admission
            pinned, seal, binding = _sealed_lmm_execution(kwargs["run_root"], dict(kwargs["options"]))
            admission = _new_lmm_execution_admission(pinned, seal)
            try:
                kwargs["pinned_run"] = pinned
                kwargs["sealed_execution_input"] = seal
                kwargs["model_options_binding"] = binding
                kwargs["lmm_execution_admission"] = admission
                return original_direct(**kwargs)
            finally:
                admission._close_for_test()
        return original_direct(**kwargs)

    def sealed_context(ctx, env):
        if getattr(env, "lmm_execution_admission", None) is None:
            from workbench.services.pinned_run_directory import _new_lmm_execution_admission
            pinned, seal, binding = _sealed_lmm_execution(env.run_root, dict(ctx.artifacts["_model_options"]))
            ctx.artifacts["_model_options_binding"] = binding
            admission = _new_lmm_execution_admission(pinned, seal)
            env.lmm_execution_admission = admission
            try:
                return original_context(ctx, env)
            finally:
                admission._close_for_test()
                env.lmm_execution_admission = None
        return original_context(ctx, env)

    monkeypatch.setitem(globals(), "fit_linear_mixed_effects", sealed_direct)
    monkeypatch.setitem(globals(), "fit_from_context", sealed_context)


@pytest.fixture(autouse=True)
def _initialize_artifact_index(tmp_path: Path) -> None:
    """Model-result registration requires the normal run-owned artifact index."""

    write_json(tmp_path / "artifacts_index.json", {"schema_version": 1, "artifacts": []})


def _terminal_result_path(run_root: Path) -> Path:
    return run_root / "artifacts" / "model_results" / "linear_mixed_effects_1.result.json"


def _indexed_packet(run_root: Path, artifact_type: str) -> PacketEnvelope:
    records = json.loads((run_root / "artifacts_index.json").read_text())["artifacts"]
    record = next(item for item in records if item["artifact_type"] == artifact_type)
    assert record["path"].startswith("artifacts/")
    return PacketEnvelope.from_dict(json.loads((run_root / record["path"]).read_text()))


def _packet_payload(packet: dict[str, object]) -> dict[str, object]:
    return PacketEnvelope.from_dict(packet).to_dict()["payload"]


def test_runner_persists_only_parsable_fixture_compatible_lmm_packets(
    tmp_path: Path,
) -> None:
    packet, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    result = PacketEnvelope.from_dict(packet)
    persisted_result = PacketEnvelope.from_dict(json.loads(_terminal_result_path(tmp_path).read_text()))
    diagnostic = _indexed_packet(tmp_path, "lmm_diagnostic_packet")
    recovery = _indexed_packet(tmp_path, "lmm_recovery_packet")

    assert result == persisted_result
    assert (result.contract, result.contract_version, result.producer_version) == (
        "linear_mixed_effects.result",
        "1.0",
        "linear_mixed_effects@1.0",
    )
    assert {
        "status",
        "fit_method",
        "figure_context",
    }.issubset(result.payload)
    assert not {"result_id", "estimate", "inference_method"} & set(result.payload)
    artifacts = json.loads((tmp_path / "artifacts_index.json").read_text())["artifacts"]
    terminal_record = next(item for item in artifacts if item["artifact_type"] == "model_result_packet")
    assert terminal_record["artifact_id"] == "linear_mixed_effects_1.result"
    assert terminal_record["path"] == "artifacts/model_results/linear_mixed_effects_1.result.json"
    assert terminal_record["step"] == "estimation"
    assert terminal_record["sha256"] == __import__("hashlib").sha256(_terminal_result_path(tmp_path).read_bytes()).hexdigest()
    assert terminal_record["inputs"] == [f"executed_input_sha256:{result.payload['execution_binding']['executed_input_digest']}"]
    assert diagnostic.contract == "linear_mixed_effects.diagnostic"
    assert {
        "status",
        "diagnostics",
    }.issubset(diagnostic.payload)
    assert recovery.contract == "linear_mixed_effects.recovery_proposal"
    assert recovery.payload["proposal_status"] == "pending_confirmation"


def test_runner_normalizes_primary_interaction_and_result_identity(tmp_path: Path) -> None:
    packet, fitted = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    result = _packet_payload(packet)
    primary = result["coefficients"]["group_time_interaction"]
    assert abs(primary["estimate"] - 0.9) <= 0.35
    assert primary["inference_method"] == "asymptotic_wald_z_v1"
    assert result["primary_target_id"] == "group_time_interaction"
    assert len(result["result_identity"]) == 64
    assert fitted.converged is True
    stored = PacketEnvelope.from_dict(
        json.loads(_terminal_result_path(tmp_path).read_text())
    ).to_dict()["payload"]
    assert stored["result_identity"] == result["result_identity"]


def test_runner_emits_complete_data_only_result_and_trajectory_context(
    tmp_path: Path,
) -> None:
    packet, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    result = _packet_payload(packet)
    assert {
        "schema_version",
        "model_id",
        "model_type",
        "engine",
        "fit_method",
        "converged",
        "optimizer",
        "nobs",
        "n_groups",
        "observations_per_group",
        "excluded_rows",
        "fixed_effects_formula",
        "random_effects_specification",
        "reference_group",
        "comparison_group",
        "result_identity",
        "primary_target_id",
        "coefficients",
        "random_effects",
        "diagnostics",
        "figure_context",
        "warnings",
    }.issubset(result)
    assert result["fit_method"] == "reml"
    assert result["status"] == "complete"
    assert result["nobs"] == 480
    assert result["n_groups"] == 80
    assert result["random_effects"]["intercept_variance"] > 0
    assert result["random_effects"]["slope_variance"] is not None
    assert result["random_effects"]["covariance"] is not None
    assert result["random_effects"]["n_groups"] == result["n_groups"]
    assert result["random_effects"]["observations_per_group"] == result[
        "observations_per_group"
    ]
    assert result["figure_context"]["chart_type"] == "lmm_group_trajectory"
    assert result["figure_context"]["time"] == sorted(result["figure_context"]["time"])
    assert {group["label"] for group in result["figure_context"]["groups"]} == {
        "control",
        "treated",
    }
    assert all(
        len(group["observed_mean"]) == len(result["figure_context"]["time"])
        and len(group["fitted_mean"]) == len(result["figure_context"]["time"])
        for group in result["figure_context"]["groups"]
    )


def test_context_adapter_uses_bound_options_and_emits_progress(tmp_path: Path) -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv", float_precision="round_trip")
    context = ModelingContext(
        data=DataHandle.of(
            frame,
            artifact_id="cleaned:known-truth",
            provenance=("source:known-truth",),
        ),
        y_col="score",
        x_cols=["baseline_score"],
        requested_model_type="linear_mixed_effects",
        y_type="continuous",
        artifacts={
            "_normalized_y": "score",
            "_normalized_x": ["baseline_score"],
            "_model_options": {
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": True,
            },
            "_upload_hash": "known-truth-upload",
        },
    )
    events: list[tuple[str, str, str]] = []
    checkpoints = 0

    def stop_reason() -> None:
        nonlocal checkpoints
        checkpoints += 1
        return None

    env = RunEnv(
        run_root=tmp_path,
        run_id="lmm-context",
        recorder=None,
        on_step=lambda name, state, message: events.append((name, state, message)),
        stop_reason=stop_reason,
    )

    model_id, packet, fitted = fit_from_context(context, env)
    result = _packet_payload(packet)

    assert model_id == "linear_mixed_effects_1"
    assert result["model_type"] == "linear_mixed_effects"
    assert fitted.converged is True
    assert context.artifacts["_linear_mixed_effects_result"] == packet
    assert events == [
        ("linear_mixed_effects", "progress", "Starting Linear Mixed Effects fit."),
        ("linear_mixed_effects", "progress", "Linear Mixed Effects fit completed."),
    ]
    assert checkpoints >= 3


def test_declaration_exposes_the_locked_options_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.engine.packs.linear_mixed_effects.declaration as declaration

    captured: list[object] = []
    monkeypatch.setattr(declaration, "register_pack", captured.append)
    monkeypatch.setattr(declaration, "register_capability_declaration", captured.append)

    declaration.declare_pack()

    pack = captured[0]
    capability = captured[1]
    assert capability.model_type == LMM_MODEL_TYPE
    handler = pack.model_handlers[0]
    assert handler.model_type == LMM_MODEL_TYPE
    assert handler.model_id == "linear_mixed_effects_1"
    assert handler.model_options_contract is not None
    assert handler.model_options_contract.producer_version == "linear_mixed_effects@1.0"
    assert handler.model_options_contract.input_contract_version == LMM_CONTRACT_VERSION
    assert handler.validate_model_options is not None
    assert handler.validate_model_options(
        {
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        }
    ).to_dict() == {
        "subject_id": "participant_id",
        "time": "week",
        "group": "arm",
        "fit_method": "reml",
        "random_slope": True,
    }


def test_runner_keeps_estimator_warnings_internal_and_emits_covariance_diagnostics(
    tmp_path: Path, recwarn: pytest.WarningsRecorder
) -> None:
    packet, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    assert not recwarn
    assert _packet_payload(packet)["warnings"] == ["LMM_RANDOM_EFFECTS_SINGULAR"]


def test_runner_honors_explicit_ml_and_changes_result_identity(tmp_path: Path) -> None:
    common = {
        "csv_path": ROOT / "known_truth.csv",
        "outcome": "score",
        "controls": ["baseline_score"],
    }
    reml_packet, _ = fit_linear_mixed_effects(
        **common,
        run_root=tmp_path / "reml",
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
    )
    ml_packet, fitted = fit_linear_mixed_effects(
        **common,
        run_root=tmp_path / "ml",
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "ml",
            "random_slope": True,
        },
    )

    assert fitted.reml is False
    ml = _packet_payload(ml_packet)
    reml = _packet_payload(reml_packet)
    assert ml["fit_method"] == "ml"
    assert ml["result_identity"] != reml["result_identity"]


def test_non_converged_fit_has_no_substantive_coefficient_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.engine.packs.linear_mixed_effects.runner as runner

    class NonConvergedFitted:
        converged = False
        nobs = 480

    monkeypatch.setattr(runner, "_fit_prepared", lambda _prepared: NonConvergedFitted())

    packet, fitted = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    result = _packet_payload(packet)
    assert fitted.converged is False
    assert result["status"] == "failed"
    assert result["coefficients"] == {}
    assert result["diagnostics"] == [
        {
            "code": "LMM_CONVERGENCE_FAILED",
            "severity": "error",
            "status": "failed",
            "evidence": {"optimizer": "lbfgs"},
            "action_candidate": None,
        }
    ]
    assert result["figure_context"] is None


def test_invalid_random_slope_covariance_fails_closed_as_a_terminal_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.engine.packs.linear_mixed_effects.runner as runner

    class InvalidCovarianceFitted:
        converged = True
        nobs = 480
        cov_re = pd.DataFrame([[0.0]])
        scale = 0.5

    monkeypatch.setattr(
        runner, "_fit_prepared", lambda _prepared: InvalidCovarianceFitted()
    )

    packet, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    result = PacketEnvelope.from_dict(packet).payload
    diagnostic = _indexed_packet(tmp_path, "lmm_diagnostic_packet").payload
    assert result["status"] == "failed"
    assert result["coefficients"] == {}
    assert result["figure_context"] is None
    assert diagnostic["diagnostics"][0]["code"] == "LMM_CONVERGENCE_FAILED"
    assert not (tmp_path / "linear_mixed_effects_recovery_proposal.json").exists()


def test_negative_random_slope_variance_fails_before_recovery_and_persists_no_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.engine.packs.linear_mixed_effects.runner as runner

    class NegativeVarianceFitted:
        converged = True
        nobs = 480
        cov_re = pd.DataFrame([[1.0, 0.0], [0.0, -1e-9]])
        scale = 0.5

    monkeypatch.setattr(
        runner, "_fit_prepared", lambda _prepared: NegativeVarianceFitted()
    )

    packet, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    result = _packet_payload(packet)
    diagnostic = _indexed_packet(tmp_path, "lmm_diagnostic_packet").to_dict()["payload"]
    assert result["status"] == "failed"
    assert result["coefficients"] == {}
    assert result["figure_context"] is None
    assert diagnostic["diagnostics"][0] == {
        "code": "LMM_CONVERGENCE_FAILED",
        "severity": "error",
        "status": "failed",
        "evidence": {"optimizer": "lbfgs"},
        "action_candidate": None,
    }
    assert not (tmp_path / "linear_mixed_effects_recovery_proposal.json").exists()


def test_runner_is_deterministic_for_the_same_locked_input(tmp_path: Path) -> None:
    options = {
        "subject_id": "participant_id",
        "time": "week",
        "group": "arm",
        "fit_method": "reml",
        "random_slope": True,
    }
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    first, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options=options,
        run_root=first_root,
    )
    second, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options=options,
        run_root=second_root,
    )

    # The result facts are deterministic; their execution binding intentionally
    # differs because each terminal packet is bound to its own trusted run.
    assert first["payload"].copy() | {"execution_binding": None} == second["payload"].copy() | {"execution_binding": None}
    assert first["payload"]["execution_binding"]["run_id"] == "first"
    assert second["payload"]["execution_binding"]["run_id"] == "second"
    assert (
        first["payload"]["execution_binding"]["executed_input_digest"]
        == second["payload"]["execution_binding"]["executed_input_digest"]
    )


def test_runner_fails_closed_for_missing_subject_column(tmp_path: Path) -> None:
    with pytest.raises(LmmInputError, match="LMM_SUBJECT_ID_MISSING") as error:
        fit_linear_mixed_effects(
            csv_path=ROOT / "missing_subject_id.csv",
            outcome="score",
            controls=["baseline_score"],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
            run_root=tmp_path,
        )

    assert error.value.code == "LMM_SUBJECT_ID_MISSING"
    assert not _terminal_result_path(tmp_path).exists()


@pytest.mark.parametrize(
    ("csv_name", "random_slope", "expected_code"),
    [
        ("missing_subject_id.csv", False, "LMM_SUBJECT_ID_MISSING"),
        (
            "singular_random_slope.csv",
            True,
            "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION",
        ),
    ],
)
def test_input_errors_persist_their_existing_terminal_diagnostic_facts(
    tmp_path: Path,
    csv_name: str,
    random_slope: bool,
    expected_code: str,
) -> None:
    with pytest.raises(LmmInputError) as error:
        fit_linear_mixed_effects(
            csv_path=ROOT / csv_name,
            outcome="score",
            controls=["baseline_score"],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": random_slope,
            },
            run_root=tmp_path,
        )

    diagnostic = _indexed_packet(tmp_path, "lmm_diagnostic_packet")
    diagnostic_payload = diagnostic.to_dict()["payload"]
    fact = diagnostic_payload["diagnostics"][0]
    assert diagnostic.contract == "linear_mixed_effects.diagnostic"
    assert diagnostic_payload["status"] == "blocked"
    assert fact == {
        "code": expected_code,
        "severity": "error",
        "status": "blocked",
        "evidence": error.value.evidence,
        "action_candidate": None,
    }
    assert not _terminal_result_path(tmp_path).exists()
    records = json.loads((tmp_path / "artifacts_index.json").read_text())["artifacts"]
    assert [record["artifact_type"] for record in records] == ["lmm_diagnostic_packet"]


def test_runner_supports_a_random_intercept_only_model(tmp_path: Path) -> None:
    packet, fitted = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": False,
        },
        run_root=tmp_path,
    )

    result = _packet_payload(packet)
    assert fitted.converged is True
    assert result["random_effects_specification"] == "1"
    assert result["random_effects"]["slope_variance"] is None
    assert result["random_effects"]["intercept_slope_covariance"] is None
    assert result["diagnostics"] == []


def test_context_adapter_supports_a_binary_numeric_group(tmp_path: Path) -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv", float_precision="round_trip")
    frame["arm"] = frame["arm"].map({"control": 0, "treated": 1})
    context = ModelingContext(
        data=DataHandle.of(
            frame,
            artifact_id="cleaned:numeric-groups",
            provenance=("source:known-truth",),
        ),
        y_col="score",
        x_cols=[],
        requested_model_type="linear_mixed_effects",
        y_type="continuous",
        artifacts={
            "_normalized_y": "score",
            "_normalized_x": [],
            "_model_options": {
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
        },
    )
    env = RunEnv(run_root=tmp_path, run_id="numeric-group", recorder=None)

    _, packet, fitted = fit_from_context(context, env)
    result = _packet_payload(packet)

    assert fitted.converged is True
    assert result["reference_group"] == "0"
    assert result["comparison_group"] == "1"
    assert {group["label"] for group in result["figure_context"]["groups"]} == {
        "0",
        "1",
    }


def test_runner_blocks_an_unidentified_random_time_slope(tmp_path: Path) -> None:
    with pytest.raises(
        LmmInputError, match="LMM_INVALID_RANDOM_SLOPE_CONFIGURATION"
    ) as error:
        fit_linear_mixed_effects(
            csv_path=ROOT / "singular_random_slope.csv",
            outcome="score",
            controls=["baseline_score"],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": True,
            },
            run_root=tmp_path,
        )

    assert error.value.code == "LMM_INVALID_RANDOM_SLOPE_CONFIGURATION"


def test_runner_registers_one_terminal_packet_after_the_controlled_fit_path(
    tmp_path: Path,
) -> None:
    packet, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    assert PacketEnvelope.from_dict(json.loads(_terminal_result_path(tmp_path).read_text())) == PacketEnvelope.from_dict(packet)
    records = json.loads((tmp_path / "artifacts_index.json").read_text())["artifacts"]
    assert {record["artifact_type"] for record in records} >= {"model_result_packet", "lmm_diagnostic_packet"}


def test_runner_preflight_block_writes_diagnostic_but_never_model_result(
    tmp_path: Path,
) -> None:
    with pytest.raises(LmmInputError, match="LMM_SUBJECT_ID_MISSING"):
        fit_linear_mixed_effects(
            csv_path=ROOT / "missing_subject_id.csv",
            outcome="score",
            controls=["baseline_score"],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": False,
            },
            run_root=tmp_path,
        )

    assert not _terminal_result_path(tmp_path).exists()
    records = json.loads((tmp_path / "artifacts_index.json").read_text())["artifacts"]
    assert [record["artifact_type"] for record in records] == ["lmm_diagnostic_packet"]
    assert not (tmp_path / "linear_mixed_effects_diagnostic.json").exists()
    assert not any(record["artifact_type"] == "lmm_recovery_packet" for record in records)


def test_runner_turns_an_unexpected_fit_exception_into_a_safe_terminal_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.engine.packs.linear_mixed_effects.runner as runner

    def _raise_unexpected(_prepared: object) -> object:
        raise RuntimeError("private estimator traceback detail")

    monkeypatch.setattr(runner, "_fit_prepared", _raise_unexpected)

    packet, fitted = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    payload = _packet_payload(packet)
    assert fitted is None
    assert payload["status"] == "failed"
    assert payload["coefficients"] == {}
    assert payload["figure_context"] is None
    assert payload["diagnostics"] == [
        {
            "code": "LMM_UNEXPECTED_FIT_EXCEPTION",
            "severity": "error",
            "status": "failed",
            "evidence": {},
            "action_candidate": None,
        }
    ]
    assert "private estimator traceback detail" not in _terminal_result_path(tmp_path).read_text()
    assert {item["artifact_type"] for item in json.loads((tmp_path / "artifacts_index.json").read_text())["artifacts"]} == {"model_result_packet", "lmm_diagnostic_packet"}


def test_runner_uses_canonical_balanced_group_trajectory_context(tmp_path: Path) -> None:
    packet, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    context = _packet_payload(packet)["figure_context"]
    assert set(context) == {"chart_type", "time", "groups"}
    assert context["chart_type"] == "lmm_group_trajectory"
    assert context["time"] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    assert [set(group) for group in context["groups"]] == [
        {"label", "observed_mean", "fitted_mean"},
        {"label", "observed_mean", "fitted_mean"},
    ]
    assert [group["label"] for group in context["groups"]] == ["control", "treated"]


def test_runner_marks_unbalanced_group_support_without_truncating_or_imputing(
    tmp_path: Path,
) -> None:
    frame = pd.read_csv(ROOT / "known_truth.csv", float_precision="round_trip")
    unbalanced = frame.loc[~((frame["arm"] == "treated") & (frame["week"] == 5))]
    csv_path = tmp_path / "unbalanced.csv"
    unbalanced.to_csv(csv_path, index=False)

    packet, _ = fit_linear_mixed_effects(
        csv_path=csv_path,
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    payload = _packet_payload(packet)
    expected_evidence = {
        "reason": "unbalanced_observed_time_support",
        "group_support": [
            {"label": "control", "observed_time_sha256": sha256_canonical([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])},
            {"label": "treated", "observed_time_sha256": sha256_canonical([0.0, 1.0, 2.0, 3.0, 4.0])},
        ],
        "first_nonshared_time": 5.0,
    }
    figure_diagnostics = [
        diagnostic
        for diagnostic in payload["diagnostics"]
        if diagnostic["code"] == "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME"
    ]
    assert payload["status"] == "complete"
    assert payload["figure_context"] is None
    assert figure_diagnostics == [
        {
            "code": "LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME",
            "severity": "warning",
            "status": "complete",
            "evidence": expected_evidence,
            "action_candidate": None,
        }
    ]
    assert payload["warnings"].count("LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME") == 1
    assert read_lmm_public_results(tmp_path)[0]["payload"] == payload


def test_covariance_terminal_failure_has_converged_false_and_is_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.engine.packs.linear_mixed_effects.runner as runner

    class InvalidCovarianceFitted:
        converged = True
        nobs = 480
        cov_re = pd.DataFrame([[0.0]])
        scale = 0.5

    monkeypatch.setattr(runner, "_fit_prepared", lambda _prepared: InvalidCovarianceFitted())
    packet, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=tmp_path,
    )

    payload = _packet_payload(packet)
    assert payload["status"] == "failed"
    assert payload["converged"] is False
    assert read_lmm_public_results(tmp_path)[0]["payload"] == payload


def test_second_terminal_attempt_fails_without_overwrite_or_duplicate_index_record(
    tmp_path: Path,
) -> None:
    options = {
        "subject_id": "participant_id",
        "time": "week",
        "group": "arm",
        "fit_method": "reml",
        "random_slope": True,
    }
    first, _ = fit_linear_mixed_effects(
        csv_path=ROOT / "known_truth.csv",
        outcome="score",
        controls=["baseline_score"],
        options=options,
        run_root=tmp_path,
    )
    original_snapshot = _terminal_result_path(tmp_path).read_bytes()
    original_index = (tmp_path / "artifacts_index.json").read_bytes()

    second, _ = fit_linear_mixed_effects(
            csv_path=ROOT / "known_truth.csv",
            outcome="score",
            controls=["baseline_score"],
            options=options,
            run_root=tmp_path,
        )

    assert _terminal_result_path(tmp_path).read_bytes() == original_snapshot
    assert (tmp_path / "artifacts_index.json").read_bytes() == original_index
    assert _packet_payload(second) == _packet_payload(first)
    assert read_lmm_public_results(tmp_path)[0]["payload"] == _packet_payload(first)


def test_result_build_failure_propagates_after_a_successful_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.engine.packs.linear_mixed_effects.runner as runner

    def _raise_build_failure(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("result normalization failed")

    monkeypatch.setattr(runner, "build_lmm_result_packet", _raise_build_failure)

    with pytest.raises(RuntimeError, match="result normalization failed"):
        fit_linear_mixed_effects(
            csv_path=ROOT / "known_truth.csv",
            outcome="score",
            controls=["baseline_score"],
            options={
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": True,
            },
            run_root=tmp_path,
        )

    assert not _terminal_result_path(tmp_path).exists()
