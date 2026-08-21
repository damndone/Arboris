"""v1.8.9 P1 — survey variance must be reached by every supported GLM family."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "survey"


def _survey_frame(*, with_replicates: bool) -> pd.DataFrame:
    name = "design_with_replicate_weights.csv" if with_replicates else "design.csv"
    frame = pd.read_csv(FIXTURES / name)
    rng = np.random.default_rng(20260819)
    probability = 1.0 / (1.0 + np.exp(-(0.35 * frame["x1"] - 0.08 * frame["x2"])))
    frame["binary_y"] = rng.binomial(1, probability)
    mean = np.exp(0.55 + 0.12 * frame["x1"] - 0.025 * frame["x2"])
    frame["count_y"] = rng.poisson(mean)
    return frame


def _run_family(
    tmp_path: Path,
    family: str,
    *,
    replicate: bool,
) -> tuple[Path, dict[str, str]]:
    frame = _survey_frame(with_replicates=replicate)
    source = tmp_path / f"{family}-{'replicate' if replicate else 'linearization'}.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, source.stem)
    y = "count_y" if family == "poisson" else "binary_y"
    kwargs: dict[str, object] = {
        "sampling_weight": "weight",
        "survey_strata_col": "stratum",
        "survey_psu_col": "psu",
        "survey_lonely_psu": "remove",
        "survey_subpop": "subpop == 1",
    }
    if replicate:
        kwargs.update(
            survey_replicate_type="provided",
            survey_replicate_weights=sorted(
                column for column in frame.columns if column.startswith("repw")
            ),
        )
    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type=family,
        y=y,
        x=["x1", "x2"],
        **kwargs,
    )
    return project.root / "runs" / outcome["run_id"], outcome


@pytest.mark.parametrize("family", ["logit", "probit", "poisson"])
@pytest.mark.parametrize("replicate", [False, True], ids=["linearization", "replicate"])
def test_glm_family_workflow_calls_shared_survey_variance_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, family: str, replicate: bool
):
    """The output must prove the engine ran, not merely accept a declaration."""
    import workbench.survey.engine as survey_engine

    calls: list[dict[str, object]] = []
    original = survey_engine.estimate_with_design

    def instrumented(*args, **kwargs):
        estimator = args[1]
        calls.append(
            {
                "method": kwargs.get("method"),
                "replicate_type": kwargs.get("replicate_type"),
                "estimator": dict(estimator.metadata),
            }
        )
        result = original(*args, **kwargs)
        calls[-1]["estimates"] = dict(result.estimates)
        calls[-1]["standard_errors"] = dict(result.standard_errors)
        return result

    monkeypatch.setattr(survey_engine, "estimate_with_design", instrumented)
    run_root, outcome = _run_family(tmp_path, family, replicate=replicate)

    assert outcome["status"] == "completed", outcome
    assert len(calls) == 1, "the family workflow never called the shared survey engine"
    call = calls[0]
    assert call["method"] == ("replicate" if replicate else "linearization")
    assert call["replicate_type"] == ("provided" if replicate else None)
    expected_glm_family = {
        "logit": "binomial",
        "probit": "binomial_probit",
        "poisson": "poisson",
    }[family]
    assert call["estimator"]["glm_family"] == expected_glm_family

    result = read_json(run_root / "model_results" / f"{family}_1.json")
    design = result["survey_design"]
    assert design["variance_method"] == ("replicate" if replicate else "linearization")
    assert design["degf"] > 0
    assert design["residual_degf"] > 0
    assert design["subpopulation"] == "subpop == 1"
    assert design["lonely_psu_policy"] == "remove"
    assert design["design_effect"] > 0
    assert design["effective_sample_size"] > 0
    if replicate:
        assert design["replicates_attempted"] == 12
        assert design["replicates_succeeded"] + design["replicates_failed"] == 12
        assert isinstance(design["replicate_failure_reasons"], dict)
    else:
        assert design["replicates_attempted"] is None

    for coefficient in result["coefficients"].values():
        assert coefficient["variance_source"] == "survey_design"
        assert coefficient["std_error"] > 0
        assert coefficient["ci_lower"] < coefficient["ci_upper"]
        assert coefficient["p_value"] >= 0
        assert coefficient["source_id"].startswith("model_results.")

    for term, coefficient in result["coefficients"].items():
        design_term = "(Intercept)" if term == "Intercept" else term
        assert coefficient["estimate"] == pytest.approx(call["estimates"][design_term])
        assert coefficient["std_error"] == pytest.approx(
            call["standard_errors"][design_term]
        )


def test_survey_fpc_is_explicitly_blocked_when_not_supported(tmp_path: Path):
    frame = _survey_frame(with_replicates=False)
    source = tmp_path / "fpc.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "fpc")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="logit",
        y="binary_y",
        x=["x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum",
        survey_psu_col="psu",
        survey_fpc_col="fpc",
    )

    assert outcome["status"] == "failed", outcome
    errors = read_json(project.root / "runs" / outcome["run_id"] / "errors.json")
    assert any(issue["code"] == "SURVEY_FPC_UNSUPPORTED" for issue in errors["issues"])


def test_fpc_without_sampling_weight_cannot_fall_back_to_naive_ols(tmp_path: Path):
    """An FPC declaration is survey intent even when the weight is omitted."""
    frame = _survey_frame(with_replicates=False)
    source = tmp_path / "fpc-without-weight.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "fpc-without-weight")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="ols",
        y="y",
        x=["x1", "x2"],
        survey_fpc_col="fpc",
    )

    assert outcome["status"] == "failed", outcome
    run_root = project.root / "runs" / outcome["run_id"]
    errors = read_json(run_root / "errors.json")
    assert any(issue["code"] == "SURVEY_FPC_UNSUPPORTED" for issue in errors["issues"])
    assert not (run_root / "model_results" / "ols_1.json").exists()


def test_unsupported_survey_family_cannot_emit_a_naive_model_artifact(tmp_path: Path):
    """A design declaration must be applied or rejected, never relabelled by omission."""
    frame = _survey_frame(with_replicates=False)
    source = tmp_path / "unsupported-family.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "unsupported-family")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="negative_binomial",
        y="count_y",
        x=["x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum",
        survey_psu_col="psu",
    )

    assert outcome["status"] == "failed", outcome
    run_root = project.root / "runs" / outcome["run_id"]
    errors = read_json(run_root / "errors.json")
    assert any(
        issue["code"] == "SURVEY_GLM_FAMILY_UNSUPPORTED"
        for issue in errors["issues"]
    )
    assert not (run_root / "model_results" / "negative_binomial_1.json").exists()


@pytest.mark.parametrize(
    ("invalid_value", "reason"),
    [
        (10**400, "not_float_representable"),
        (-1, "nonpositive"),
        (float("nan"), "nonfinite"),
        (float("inf"), "nonfinite"),
        (object(), "non_numeric"),
        (True, "boolean"),
    ],
)
def test_poisson_exposure_rejects_unrepresentable_values_with_typed_errors(
    invalid_value, reason
):
    """Exposure validation must fail before pandas/numpy float conversion."""
    from workbench.survey import SurveyEngineError
    from workbench.survey.adapters import validate_poisson_exposure

    frame = pd.DataFrame(
        {"exposure": pd.Series([invalid_value, 1], dtype=object)}
    )

    with pytest.raises(SurveyEngineError) as excinfo:
        validate_poisson_exposure(frame, "exposure")

    assert excinfo.value.code == "SURVEY_POISSON_EXPOSURE_INVALID"
    assert excinfo.value.context["reason"] == reason
    assert "OverflowError" not in str(excinfo.value)


def test_auto_count_workflow_uses_survey_poisson_alias_with_sampling_weight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Auto count routing must execute the same weighted survey Poisson path."""
    from workbench.agent.workflow_contracts import model_family_contract

    assert model_family_contract("poisson_rate").family == "poisson"
    frame = _survey_frame(with_replicates=False)
    source = tmp_path / "auto-count.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "auto-count")

    import workbench.survey.engine as survey_engine

    calls: list[dict[str, object]] = []
    original = survey_engine.estimate_with_design

    def instrumented(*args, **kwargs):
        calls.append(
            {
                "method": kwargs.get("method"),
                "replicate_type": kwargs.get("replicate_type"),
                "estimator": dict(args[1].metadata),
            }
        )
        result = original(*args, **kwargs)
        calls[-1]["estimates"] = dict(result.estimates)
        return result

    monkeypatch.setattr(survey_engine, "estimate_with_design", instrumented)
    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="auto",
        y="count_y",
        x=["x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum",
        survey_psu_col="psu",
        survey_lonely_psu="remove",
        survey_subpop="subpop == 1",
    )

    assert outcome["status"] == "completed", outcome
    assert len(calls) == 1, "auto count never called the shared survey engine"
    assert calls[0]["method"] == "linearization"
    assert calls[0]["estimator"]["glm_family"] == "poisson"

    run_root = project.root / "runs" / outcome["run_id"]
    result = read_json(run_root / "model_results" / "poisson_1.json")
    assert result["survey_design"]["weight_column"] == "weight"
    assert result["survey_design"]["variance_method"] == "linearization"
    assert all(
        coefficient["variance_source"] == "survey_design"
        for coefficient in result["coefficients"].values()
    )


def test_survey_workflow_rejects_object_integer_weight_as_typed_failure(tmp_path: Path):
    """The source-to-estimation workflow must not leak pandas' float overflow."""
    frame = pd.read_csv(FIXTURES / "design.csv")
    frame["weight"] = pd.Series(
        [10**400] + [1] * (len(frame) - 1),
        index=frame.index,
        dtype=object,
    )
    source = tmp_path / "huge-weight.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "huge-weight")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="ols",
        y="y",
        x=["x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum",
        survey_psu_col="psu",
    )

    assert outcome["status"] == "failed", outcome
    errors = read_json(project.root / "runs" / outcome["run_id"] / "errors.json")
    issue = next(
        issue for issue in errors["issues"]
        if issue["code"] == "SURVEY_INVALID_SAMPLING_WEIGHTS"
    )
    assert "OverflowError" not in issue["message"]
    assert issue["evidence"]["reason"] == "not_float_representable"


@pytest.mark.parametrize(
    "invalid_exposure",
    [
        lambda n: np.array([0.0] + [1.0] * (n - 1)),
        lambda n: np.array([-1.0] + [1.0] * (n - 1)),
        lambda n: np.array([np.nan] + [1.0] * (n - 1)),
        lambda n: np.array([np.inf] + [1.0] * (n - 1)),
    ],
    ids=["zero", "negative", "nan", "infinite"],
)
def test_survey_poisson_rejects_invalid_exposure_before_predictor_fit(
    tmp_path: Path, invalid_exposure
):
    """An invalid exposure must not fall back to an ordinary predictor."""
    frame = _survey_frame(with_replicates=False)
    frame["exposure"] = invalid_exposure(len(frame))
    source = tmp_path / "invalid-exposure.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "invalid-exposure")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="poisson",
        y="count_y",
        x=["exposure", "x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum",
        survey_psu_col="psu",
        survey_lonely_psu="remove",
    )

    assert outcome["status"] == "failed", outcome
    run_root = project.root / "runs" / outcome["run_id"]
    errors = read_json(run_root / "errors.json")
    assert any(
        issue["code"] == "SURVEY_POISSON_EXPOSURE_INVALID"
        for issue in errors["issues"]
    )
    assert not (run_root / "model_results" / "poisson_1.json").exists()


def test_poisson_survey_result_postprocessing_lives_in_family_adapter():
    """Survey variance injection must not grow a model-type branch in estimation."""
    estimation_source = (
        Path(__file__).parents[1]
        / "backend"
        / "workbench"
        / "engine"
        / "stages"
        / "estimation.py"
    ).read_text()
    assert 'if model_type == "poisson"' not in estimation_source
    assert "if model_type == 'poisson'" not in estimation_source

    from workbench.survey.adapters import (
        apply_result_postprocessor,
        glm_estimator_spec,
    )

    estimator = glm_estimator_spec(
        family="poisson",
        glm_family="poisson",
        y="count_y",
        x=["x1"],
    )
    primary = {"irr": {"x1": {}}}
    entry: dict[str, float] = {}
    apply_result_postprocessor(
        estimator,
        primary=primary,
        term="x1",
        entry=entry,
        estimate=0.5,
        ci_lower=0.25,
        ci_upper=0.75,
    )

    assert entry["irr"] == pytest.approx(np.exp(0.5))
    assert primary["irr"]["x1"]["irr_ci_lower"] == pytest.approx(np.exp(0.25))


def test_poisson_postprocessor_rejects_unbounded_exponentials_as_typed_failure():
    from workbench.survey import SurveyEngineError
    from workbench.survey.adapters import apply_result_postprocessor, glm_estimator_spec

    estimator = glm_estimator_spec(
        family="poisson", glm_family="poisson", y="count_y", x=["x1"]
    )
    with pytest.raises(SurveyEngineError) as excinfo:
        apply_result_postprocessor(
            estimator,
            primary={"irr": {"x1": {}}},
            term="x1",
            entry={},
            estimate=10_000.0,
            ci_lower=-10_000.0,
            ci_upper=10_000.0,
        )

    assert excinfo.value.code == "SURVEY_POSTPROCESS_INVALID"


def test_survey_p_value_display_is_regenerated_from_replaced_p_value(tmp_path):
    run_root, outcome = _run_family(tmp_path, "logit", replicate=False)
    assert outcome["status"] == "completed", outcome
    result = read_json(run_root / "model_results" / "logit_1.json")
    for coefficient in result["coefficients"].values():
        p_value = coefficient["p_value"]
        expected = "< 0.001" if round(p_value, 4) < 0.001 else None
        assert coefficient.get("p_value_display") == expected


def test_clean_process_capability_bootstrap_returns_typed_survey_status():
    """A clean process publishes the executable survey family contract."""
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "backend")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from workbench.engine.capabilities import "
                "survey_capability_bootstrap_status; "
                "print(json.dumps(survey_capability_bootstrap_status(), sort_keys=True))"
            ),
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr
    status = json.loads(probe.stdout)
    assert status == {
        "code": None,
        "sampling_weight_families": ["logit", "ols", "poisson", "probit"],
        "status": "available",
    }
