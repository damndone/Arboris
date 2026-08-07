"""v1.8.7 P1 — factorial ANOVA and ANCOVA as a model family.

What exists today is a one-way `stats.f_oneway` inside the statistical tests,
plus post-hoc comparisons and effect sizes as separate tests.  There is no
factorial design, no covariate adjustment, and no sums-of-squares decomposition
-- so the most common analysis in the SPSS world cannot be run at all.

The load-bearing constraint here is that the sums-of-squares type must be
DECLARED.  SPSS's GLM defaults to Type III, R's `aov` gives Type I, and on an
unbalanced design they disagree: on this fixture SS(factor_a) is 166.74 under
Type I and 104.05 under Type III, a 60% gap with nothing on screen to explain
it.  A user moving from SPSS who is silently given Type I gets different F
statistics and different p values from the same data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "anova"

#: Type II/III against `car::Anova`. Both fit by ordinary least squares, so the
#: agreement should be tight; a loose band here would hide a wrong decomposition.
SS_TOLERANCE = 1e-8


def _oracle() -> dict:
    return json.loads((FIXTURES / "oracle.json").read_text())


def _frame() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "anova.csv")


def _run(tmp_path, name: str, **kwargs):
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    project = create_project(tmp_path, name)
    source_dir = tmp_path / f"src_{name}"
    source_dir.mkdir()
    source = source_dir / "data.csv"
    _frame().to_csv(source, index=False)
    outcome = run_workflow(project.root, [source], mode="auto", **kwargs)
    return project, outcome


def _result(project, outcome, model_id: str) -> dict:
    from workbench.artifacts import read_json

    path = project.root / "runs" / outcome["run_id"] / "model_results" / f"{model_id}.json"
    assert path.exists(), (
        f"expected {path.name}; found {[p.name for p in path.parent.glob('*.json')]}"
    )
    return read_json(path)


# --------------------------------------------------------------------------
# 1. The family exists and is reachable
# --------------------------------------------------------------------------

def test_anova_is_a_declared_model_family():
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS

    assert "anova" in MODEL_FAMILY_CONTRACTS, (
        "ANOVA is still only a one-way test, not a model family"
    )
    contract = MODEL_FAMILY_CONTRACTS["anova"]
    assert contract.result_shape, "the family must declare a result shape"


def test_anova_appears_in_the_capability_projection():
    """Not reachable from the UI is not delivered."""
    import workbench.orchestrator  # noqa: F401  -- avoids the stages import cycle
    from workbench.engine.capabilities import build_capabilities

    keys = {entry.get("key") for entry in build_capabilities()["model_types"]}
    assert "anova" in keys


# --------------------------------------------------------------------------
# 2. The sums-of-squares type is declared, never assumed
# --------------------------------------------------------------------------

def test_unspecified_sums_of_squares_type_is_refused(tmp_path):
    """Silence here is the SPSS-versus-R trap, so there is no default.

    Picking one quietly would hand a user numbers that differ from the software
    they came from, with nothing indicating a choice was made on their behalf.

    The refusal lands in model-options validation, before the run starts, so it
    surfaces as a raised error rather than a failed outcome -- earlier than a
    persisted failure, and fail-closed either way.
    """
    from workbench.model_options import ModelOptionsError

    with pytest.raises(ModelOptionsError) as excinfo:
        _run(
            tmp_path, "anova_nodecl", model_type="anova", y="score",
            x=["factor_a", "factor_b"],
            model_options={"categorical": ["factor_a", "factor_b"]},
        )
    assert "SUMS_OF_SQUARES" in str(excinfo.value)


@pytest.mark.parametrize("ss_type", [2, 3])
def test_factorial_anova_matches_car_anova(tmp_path, ss_type):
    project, outcome = _run(
        tmp_path, f"anova_t{ss_type}", model_type="anova", y="score",
        x=["factor_a", "factor_b"],
        model_options={
            "categorical": ["factor_a", "factor_b"],
            "interactions": [["factor_a", "factor_b"]],
            "sums_of_squares": ss_type,
        },
    )
    assert outcome["status"] == "completed", outcome
    result = _result(project, outcome, "anova_1")

    oracle = _oracle()["anova"][f"type_{ss_type}"]
    table = {row["term"]: row for row in result["anova_table"]}
    for term, expected in oracle.items():
        assert term in table, f"missing term {term}"
        assert table[term]["sum_sq"] == pytest.approx(expected["sum_sq"], rel=SS_TOLERANCE)
        assert table[term]["df"] == pytest.approx(expected["df"])
        if expected.get("f") is not None:
            assert table[term]["f"] == pytest.approx(expected["f"], rel=SS_TOLERANCE)


def test_type_one_and_type_three_actually_differ(tmp_path):
    """The fixture is unbalanced so the choice is observable, not cosmetic."""
    oracle = _oracle()["anova"]
    assert oracle["type_1"]["factor_a"]["sum_sq"] != pytest.approx(
        oracle["type_3"]["factor_a"]["sum_sq"], rel=1e-6
    ), "the fixture stopped discriminating between sums-of-squares types"


# --------------------------------------------------------------------------
# 3. ANCOVA: the covariate is adjusted for, not treated as a factor
# --------------------------------------------------------------------------

def test_ancova_matches_car_anova(tmp_path):
    project, outcome = _run(
        tmp_path, "ancova", model_type="anova", y="score",
        x=["covariate", "factor_a", "factor_b"],
        model_options={
            "categorical": ["factor_a", "factor_b"],
            "interactions": [["factor_a", "factor_b"]],
            "sums_of_squares": 3,
        },
    )
    assert outcome["status"] == "completed", outcome
    result = _result(project, outcome, "anova_1")

    oracle = _oracle()["ancova"]["type_3"]
    table = {row["term"]: row for row in result["anova_table"]}
    assert "covariate" in table, "the covariate has no line in the table"
    for term, expected in oracle.items():
        assert table[term]["sum_sq"] == pytest.approx(expected["sum_sq"], rel=SS_TOLERANCE)


# --------------------------------------------------------------------------
# 4. Effect sizes and post-hoc travel with the result
# --------------------------------------------------------------------------

def test_partial_eta_squared_matches_the_oracle(tmp_path):
    project, outcome = _run(
        tmp_path, "anova_eta", model_type="anova", y="score",
        x=["factor_a", "factor_b"],
        model_options={
            "categorical": ["factor_a", "factor_b"],
            "interactions": [["factor_a", "factor_b"]],
            "sums_of_squares": 3,
        },
    )
    result = _result(project, outcome, "anova_1")
    oracle = _oracle()["anova"]["partial_eta_squared_type_3"]

    effects = result["effect_sizes"]["partial_eta_squared"]
    for term, expected in oracle.items():
        assert effects[term] == pytest.approx(expected, rel=1e-8)


def test_posthoc_comparisons_are_present_and_corrected(tmp_path):
    """An omnibus F says something differs; it does not say which."""
    project, outcome = _run(
        tmp_path, "anova_posthoc", model_type="anova", y="score",
        x=["factor_a", "factor_b"],
        model_options={
            "categorical": ["factor_a", "factor_b"],
            "sums_of_squares": 3,
            "posthoc": "tukey",
        },
    )
    result = _result(project, outcome, "anova_1")

    comparisons = result["posthoc"]["comparisons"]
    assert comparisons, "post-hoc requested but no comparisons produced"
    assert result["posthoc"]["correction"] == "tukey"
    # group1/group2 is the naming the repository's existing post-hoc output
    # already uses; inventing a second one here would leave consumers reading
    # pairwise comparisons two different ways.
    for row in comparisons:
        assert {"group1", "group2", "p_value"} <= set(row)


# --------------------------------------------------------------------------
# 5. Reuse, not a second regression engine
# --------------------------------------------------------------------------

def test_anova_reuses_the_ols_design_matrix():
    """The family may not carry its own least-squares implementation.

    Factors, interactions and contrasts already exist in the declarative term
    layer; a parallel engine would be a second place for the same statistics to
    drift, which is the shape of duplication P0 has just finished removing.
    """
    from pathlib import Path as _Path

    source = (
        _Path(__file__).resolve().parents[1]
        / "backend/workbench/engine/packs/anova/estimation.py"
    ).read_text()
    for forbidden in ("np.linalg.lstsq", "np.linalg.solve", "class _OLS"):
        assert forbidden not in source, (
            f"the ANOVA pack implements its own least squares ({forbidden})"
        )
