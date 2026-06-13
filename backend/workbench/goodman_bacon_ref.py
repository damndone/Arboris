"""Reference TWFE DiD coefficient used to validate the Bacon decomposition
identity (weighted_avg == TWFE). Kept tiny and dependency-light (statsmodels
OLS with entity+time dummies) so the test does not depend on linearmodels."""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm


def twfe_did_coefficient(frame: pd.DataFrame, *, y, entity, time, cohort) -> float:
    df = frame.copy()
    cv = pd.to_numeric(df[cohort], errors="coerce")
    t = pd.to_numeric(df[time], errors="coerce")
    df["_D"] = ((t >= cv) & cv.notna()).astype(float)
    X = pd.concat(
        [df["_D"],
         pd.get_dummies(df[entity], prefix="e", drop_first=True).astype(float),
         pd.get_dummies(df[time], prefix="t", drop_first=True).astype(float)],
        axis=1,
    )
    X = sm.add_constant(X)
    model = sm.OLS(df[y].astype(float), X).fit()
    return float(model.params["_D"])
