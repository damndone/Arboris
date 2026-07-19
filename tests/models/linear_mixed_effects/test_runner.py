from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.contracts.model.linear_mixed_effects import (
    LMM_CONTRACT_VERSION,
    LMM_MODEL_TYPE,
)
from workbench.engine.context import DataHandle, ModelingContext, RunEnv
from workbench.engine.packs.linear_mixed_effects.runner import (
    fit_from_context,
    fit_linear_mixed_effects,
)
from workbench.engine.packs.linear_mixed_effects.input import LmmInputError


ROOT = Path(__file__).parents[2] / "fixtures" / "models" / "linear_mixed_effects"


def test_runner_normalizes_primary_interaction_and_result_identity(tmp_path: Path) -> None:
    result, fitted = fit_linear_mixed_effects(
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

    primary = result["coefficients"]["group_time_interaction"]
    assert abs(primary["estimate"] - 0.9) <= 0.35
    assert primary["inference_method"] == "asymptotic_wald_z_v1"
    assert result["primary_target_id"] == "group_time_interaction"
    assert len(result["result_identity"]) == 64
    assert fitted.converged is True
    stored = json.loads((tmp_path / "linear_mixed_effects_contract.json").read_text())
    assert stored["result_identity"] == result["result_identity"]


def test_runner_emits_complete_data_only_result_and_trajectory_context(
    tmp_path: Path,
) -> None:
    result, _ = fit_linear_mixed_effects(
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
    assert {series["group"] for series in result["figure_context"]["series"]} == {
        "control",
        "treated",
    }
    assert all(
        series["time"] == result["figure_context"]["time"]
        for series in result["figure_context"]["series"]
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

    model_id, result, fitted = fit_from_context(context, env)

    assert model_id == "linear_mixed_effects_1"
    assert result["model_type"] == "linear_mixed_effects"
    assert fitted.converged is True
    assert context.artifacts["_linear_mixed_effects_result"] == result
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

    declaration.declare_pack()

    pack = captured[0]
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


def test_runner_converts_estimator_warnings_into_locked_diagnostics(
    tmp_path: Path, recwarn: pytest.WarningsRecorder
) -> None:
    result, _ = fit_linear_mixed_effects(
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
    assert result["warnings"] == ["LMM_RANDOM_EFFECTS_SINGULAR"]


def test_runner_honors_explicit_ml_and_changes_result_identity(tmp_path: Path) -> None:
    common = {
        "csv_path": ROOT / "known_truth.csv",
        "outcome": "score",
        "controls": ["baseline_score"],
        "run_root": tmp_path,
    }
    reml, _ = fit_linear_mixed_effects(
        **common,
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
    )
    ml, fitted = fit_linear_mixed_effects(
        **common,
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "ml",
            "random_slope": True,
        },
    )

    assert fitted.reml is False
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

    result, fitted = fit_linear_mixed_effects(
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

    assert first == second


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
    assert not (tmp_path / "linear_mixed_effects_contract.json").exists()


def test_runner_supports_a_random_intercept_only_model(tmp_path: Path) -> None:
    result, fitted = fit_linear_mixed_effects(
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

    _, result, fitted = fit_from_context(context, env)

    assert fitted.converged is True
    assert result["reference_group"] == "0"
    assert result["comparison_group"] == "1"
    assert {series["group"] for series in result["figure_context"]["series"]} == {
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
