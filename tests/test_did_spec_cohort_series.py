"""The cohort of each DID unit, against the per-entity definition it replaced."""
import numpy as np
import pandas as pd
import pytest

from workbench.engine.did_spec import DIDSpecError, _coerce_cohort_value, _cohort_series


def per_entity(frame, mode):
    out = {}
    t_numeric = pd.to_numeric(frame["year"], errors="coerce")
    for ent, grp in frame.groupby("unit"):
        if mode == "cohort":
            out[ent] = _coerce_cohort_value(grp["first"].iloc[0])
        elif mode == "two_by_two":
            treated_periods = t_numeric[frame["post"].astype(float) == 1]
            first_post = treated_periods.min() if treated_periods.notna().any() else np.nan
            out[ent] = float(first_post) if (grp["treat"].astype(float) == 1).any() else np.nan
        else:
            on = t_numeric.loc[grp.index[grp["status"].astype(float) == 1]]
            out[ent] = float(on.min()) if len(on) else np.nan
    return out


def panel(seed):
    rng = np.random.default_rng(seed)
    units, years = 60, 6
    frame = pd.DataFrame({"unit": np.repeat(rng.permutation(units), years), "year": np.tile(np.arange(2000, 2000 + years), units)})
    first = {u: (np.nan if rng.random() < .3 else float(rng.integers(2001, 2006))) for u in range(units)}
    frame["first"] = frame["unit"].map(first)
    frame["treat"] = frame["first"].notna().astype(int)
    frame["post"] = (frame["year"] >= 2003).astype(int)
    frame["status"] = ((frame["year"] >= frame["first"]) & frame["first"].notna()).astype(int)
    return frame.sample(frac=1, random_state=seed).reset_index(drop=True)


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("mode", ["cohort", "two_by_two", "status"])
def test_cohorts_match_the_per_entity_definition(seed, mode):
    frame = panel(seed)
    got = _cohort_series(frame, mode=mode, entity="unit", time="year", cohort="first", treat="treat", post="post", status="status")
    want = per_entity(frame, mode)
    assert list(got) == list(want)
    for unit in want:
        assert got[unit] == want[unit] or (pd.isna(got[unit]) and pd.isna(want[unit]))


def test_string_entities_and_missing_entities_keep_groupby_order():
    frame = panel(1)
    frame["unit"] = "u" + frame["unit"].astype(str)
    frame.loc[0, "unit"] = None
    got = _cohort_series(frame, mode="cohort", entity="unit", time="year", cohort="first", treat="treat", post="post", status="status")
    assert list(got) == sorted(frame["unit"].dropna().unique())


def test_the_first_inconsistent_or_non_absorbing_unit_is_named():
    frame = panel(2)
    frame.loc[frame["unit"] == 7, "first"] = [2001.0, 2002.0, 2002.0, 2002.0, 2002.0, 2002.0]
    frame.loc[frame["unit"] == 3, "first"] = [2001.0, 2002.0, 2002.0, 2002.0, 2002.0, 2002.0]
    with pytest.raises(DIDSpecError, match="DID_INCONSISTENT_COHORT: entity '3'"):
        _cohort_series(frame, mode="cohort", entity="unit", time="year", cohort="first", treat="treat", post="post", status="status")
    frame = panel(2).sort_values(["unit", "year"]).reset_index(drop=True)
    frame.loc[frame["unit"] == 5, "status"] = [1, 1, 0, 0, 1, 1]
    with pytest.raises(DIDSpecError, match="DID_NON_ABSORBING: treatment for unit '5'"):
        _cohort_series(frame, mode="status", entity="unit", time="year", cohort="first", treat="treat", post="post", status="status")
