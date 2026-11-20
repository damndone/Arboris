"""linearmodels models built from plain float columns instead of through formulaic."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pandas as pd

from .ols_contract import _linearmodels_term


def formula_free_columns(data: pd.DataFrame, columns: Sequence[str]) -> bool:
    """Distinct float64 columns with identifier names: formulaic's matrices are the columns."""
    return len(set(columns)) == len(columns) and all(
        column.isidentifier() and column in data.columns and data[column].dtype == np.float64
        for column in columns)


def panel_formula(y: str, regressors: Sequence[str], *, entity_effects: bool, time_effects: bool) -> str:
    terms = ["1", *[_linearmodels_term(column) for column in regressors]]
    terms += ["EntityEffects"] * entity_effects + ["TimeEffects"] * time_effects
    return f"{_linearmodels_term(y)} ~ {' + '.join(terms)}"


def panel_ols_model(panel_module: Any, data: pd.DataFrame, *, y: str, regressors: Sequence[str],
                    entity_effects: bool, time_effects: bool) -> Any:
    """The model ``PanelOLS.from_formula(panel_formula(...), data)`` builds.

    For float64 columns with identifier names, formulaic's model matrices are those columns of
    ``PanelData(data).dataframe`` plus an ``Intercept`` of ones, byte for byte (checked on the
    1M-row DID, event-study and panel inputs and in tests/test_panel_design.py). Building them
    directly gives PanelOLS the same matrices without formulaic's materialized copy of the data,
    which stayed in reference cycles until a full collection (about 300 MiB per 1M-row fit,
    2026-11-09 footprint diagnostics). Any other column goes through the formula.
    """
    from linearmodels.panel.data import PanelData

    formula = panel_formula(y, regressors, entity_effects=entity_effects, time_effects=time_effects)
    if not formula_free_columns(data, [y, *regressors]):
        return panel_module.PanelOLS.from_formula(formula, data=data)
    frame = PanelData(data, convert_dummies=False, copy=False).dataframe
    exog = frame[list(regressors)]
    exog.insert(0, "Intercept", np.ones(len(frame)))
    model = panel_module.PanelOLS(frame[[y]], exog, entity_effects=entity_effects, time_effects=time_effects)
    model.formula = formula
    return model
