from __future__ import annotations

from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf


FIXTURE = (
    Path(__file__).parents[2]
    / "fixtures"
    / "models"
    / "linear_mixed_effects"
    / "known_truth.csv"
)
FORMULA = "score ~ C(arm, Treatment(reference='control')) * week + baseline_score"
INTERACTION = "C(arm, Treatment(reference='control'))[T.treated]:week"


def test_existing_environment_fits_reml_and_ml() -> None:
    frame = pd.read_csv(FIXTURE, float_precision="round_trip")
    reml = smf.mixedlm(
        FORMULA, frame, groups=frame["participant_id"], re_formula="1 + week"
    ).fit(reml=True, method="lbfgs", maxiter=200, disp=False)
    ml = smf.mixedlm(
        FORMULA, frame, groups=frame["participant_id"], re_formula="1 + week"
    ).fit(reml=False, method="lbfgs", maxiter=200, disp=False)

    assert reml.converged is True
    assert ml.converged is True
    assert INTERACTION in reml.params
