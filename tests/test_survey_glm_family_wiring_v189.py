"""v1.8.9 P1 — survey variance must be reached by every supported GLM family."""

from __future__ import annotations

from pathlib import Path

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
