"""The design side of the composition.

A `SurveyDesign` describes how the sample was drawn -- strata, primary sampling
units, weights, finite population correction, the single-PSU policy and an
optional subpopulation.  It knows nothing about estimators, and estimators know
nothing about it; the engine joins them.

The subpopulation is the sharpest edge here.  Restricting the *design* keeps the
full variance structure, while filtering the rows first silently discards it and
understates the standard error -- the coefficients come out identical, so nothing
about the result looks wrong.  Stata warns about exactly this (`subpop()` versus
`if`), and the fixture backing these paths is built so the two genuinely differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .errors import SurveyEngineError
from .estimator import VARIANCE_METHOD_REQUIREMENTS, EstimatorSpec, missing_capabilities

LONELY_PSU_POLICIES = ("fail", "remove", "adjust", "average", "certainty")
REPLICATE_TYPES = ("brr", "jackknife", "bootstrap", "provided")


@dataclass(frozen=True)
class DesignEffects:
    deff: float
    kish_n_eff: float
    n_obs: int
    mean: float
    standard_error: float


@dataclass
class SurveyDesign:
    frame: pd.DataFrame
    weight: str
    strata: str | None = None
    psu: str | None = None
    fpc: str | None = None
    lonely_psu: str = "fail"
    subpop: str | None = None
    replicate_type: str | None = None
    replicate_weight_columns: list[str] = field(default_factory=list)
    #: Optional balanced set for BRR.  BRR's answer depends on this choice, so
    #: comparing against another implementation means fixing the same set.
    hadamard_matrix: list[list[int]] | None = None

    def __post_init__(self) -> None:
        if self.lonely_psu not in LONELY_PSU_POLICIES:
            raise SurveyEngineError(
                "SURVEY_LONELY_PSU_POLICY_INVALID",
                f"unknown policy {self.lonely_psu!r}",
                allowed=list(LONELY_PSU_POLICIES),
            )
        if self.replicate_type is not None and self.replicate_type not in REPLICATE_TYPES:
            raise SurveyEngineError(
                "SURVEY_REPLICATE_TYPE_INVALID",
                f"unknown replicate type {self.replicate_type!r}",
                allowed=list(REPLICATE_TYPES),
            )
        for column in filter(None, (self.weight, self.strata, self.psu, self.fpc)):
            if column not in self.frame.columns:
                raise SurveyEngineError(
                    "SURVEY_DESIGN_COLUMN_MISSING", f"column {column!r} is not in the frame"
                )
        if self.replicate_type == "provided" and not self.replicate_weight_columns:
            raise SurveyEngineError(
                "SURVEY_REPLICATE_WEIGHTS_MISSING",
                "replicate_type='provided' requires replicate_weight_columns",
            )

    # -- structure ---------------------------------------------------------

    @property
    def weights(self) -> np.ndarray:
        return self.frame[self.weight].to_numpy(dtype=float)

    @property
    def _stratum_key(self) -> pd.Series:
        if self.strata is None:
            return pd.Series(["__all__"] * len(self.frame), index=self.frame.index)
        return self.frame[self.strata].astype(str)

    @property
    def _psu_key(self) -> pd.Series:
        if self.psu is None:
            # No clustering: every observation is its own PSU.
            return pd.Series([f"__obs{i}" for i in range(len(self.frame))], index=self.frame.index)
        return self._stratum_key + "||" + self.frame[self.psu].astype(str)

    @property
    def n_obs(self) -> int:
        return int(len(self.frame))

    @property
    def n_strata(self) -> int:
        return int(self._stratum_key.nunique())

    @property
    def n_psu(self) -> int:
        return int(self._psu_key.nunique())

    @property
    def degf(self) -> int:
        return self.n_psu - self.n_strata

    def psu_counts(self) -> pd.Series:
        return self._psu_key.groupby(self._stratum_key).nunique()

    def lonely_strata(self) -> list[str]:
        counts = self.psu_counts()
        return sorted(str(k) for k, v in counts.items() if v < 2)

    # -- composition -------------------------------------------------------

    def supported_variance_methods(self, spec: EstimatorSpec) -> dict[str, bool]:
        """Derived from declared capabilities -- never from a family lookup."""
        return {
            method: not missing_capabilities(spec, method)
            for method in VARIANCE_METHOD_REQUIREMENTS
        }

    # -- subpopulation -----------------------------------------------------

    def subpop_mask(self) -> np.ndarray:
        if not self.subpop:
            return np.ones(len(self.frame), dtype=bool)
        mask = self.frame.eval(self.subpop)
        return np.asarray(mask, dtype=bool)

    # -- design effect -----------------------------------------------------

    def design_effects(self, column: str) -> DesignEffects:
        """DEFF, DEFT and the Kish effective sample size.

        Reported by default rather than on request: a user who does not know to
        ask is exactly the user for whom `DEFF = 1.7` -- 200 observations behaving
        like 168 -- changes how much the result can carry.
        """
        if column not in self.frame.columns:
            raise SurveyEngineError(
                "SURVEY_DESIGN_COLUMN_MISSING", f"column {column!r} is not in the frame"
            )
        mask = self.subpop_mask()
        values = self.frame.loc[mask, column].to_numpy(dtype=float)
        w = self.weights[mask]

        total = w.sum()
        mean = float((w * values).sum() / total)

        # Design variance of the weighted mean via its influence contributions.
        infl = w * (values - mean) / total
        var_design = float(self._design_variance(infl[:, None], mask=mask)[0, 0])

        # The simple-random-sampling reference carries a finite-population
        # correction in which the summed weights stand in for the population
        # size:  vsrs = S^2 * (N - n) / (N * n),  N = sum(w), n = observations.
        # Dividing the weighted variance by an effective sample size instead is
        # the intuitive guess and lands about 9% low, which looks plausible
        # enough on screen to go unquestioned.
        # The population variance estimate is itself design-based: a weighted
        # *mean* of squared deviations, corrected by n/(n-1) on the observation
        # count -- not by the summed weights.  Dividing by (sum(w) - 1) is the
        # natural-looking alternative and lands about 1% out, close enough to
        # read as rounding.
        n_obs = int(mask.sum())
        s2 = float((w * (values - mean) ** 2).sum() / total) * n_obs / (n_obs - 1)
        var_srs = s2 * (total - n_obs) / (total * n_obs)

        # Kish's effective sample size is a separate, weight-only summary: how
        # many equally-weighted observations this sample behaves like.
        n_eff = float(total**2 / (w**2).sum())

        return DesignEffects(
            deff=var_design / var_srs,
            kish_n_eff=n_eff,
            n_obs=int(mask.sum()),
            mean=mean,
            standard_error=float(np.sqrt(var_design)),
        )

    # -- linearization -----------------------------------------------------

    def _design_variance(self, contributions: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
        """Stratified multistage variance of a total of influence contributions.

            V = sum_h  n_h/(n_h-1) * sum_i (u_hi - ubar_h)(u_hi - ubar_h)'

        Contributions outside the subpopulation are zeroed rather than dropped:
        that is precisely what keeps a subpopulation analysis honest, because the
        PSUs and strata they belong to still shape the variance.
        """
        contrib = np.asarray(contributions, dtype=float)
        if mask is not None:
            full = np.zeros((len(self.frame), contrib.shape[1]), dtype=float)
            full[mask] = contrib
            contrib = full

        strata = self._stratum_key.to_numpy()
        psu = self._psu_key.to_numpy()
        p = contrib.shape[1]

        # First pass: PSU-level sums per stratum.  The lonely-PSU policies need
        # information from the whole design (the grand mean, or the average of
        # the well-behaved strata), so nothing can be decided stratum by stratum
        # in a single sweep.
        per_stratum: dict[str, np.ndarray] = {}
        for stratum in pd.unique(strata):
            rows = strata == stratum
            psu_ids = pd.unique(psu[rows])
            per_stratum[str(stratum)] = np.array(
                [contrib[rows & (psu == pid)].sum(axis=0) for pid in psu_ids]
            )

        healthy = {h: u for h, u in per_stratum.items() if len(u) >= 2}
        lonely = [h for h, u in per_stratum.items() if len(u) < 2]

        if lonely and self.lonely_psu == "fail":
            raise SurveyEngineError(
                "SURVEY_LONELY_PSU",
                f"single-PSU stratum: {', '.join(sorted(lonely))}",
                strata=sorted(lonely),
                policies=[policy for policy in LONELY_PSU_POLICIES if policy != "fail"],
            )

        total = np.zeros((p, p), dtype=float)
        for u in healthy.values():
            n_h = len(u)
            centered = u - u.mean(axis=0)
            total += (n_h / (n_h - 1)) * (centered.T @ centered)

        if not lonely:
            return total

        if self.lonely_psu in ("remove", "certainty"):
            # Self-representing: the stratum contributes no sampling variance.
            return total

        if self.lonely_psu == "adjust":
            # Centre at the grand mean of all PSU totals rather than at the
            # stratum mean, which is undefined with one unit.
            all_u = np.vstack(list(per_stratum.values()))
            grand = all_u.mean(axis=0)
            for h in lonely:
                centered = per_stratum[h] - grand
                total += centered.T @ centered
            return total

        if self.lonely_psu == "average":
            # Borrow the mean per-stratum variance from the strata that have one.
            if healthy:
                contributions = []
                for u in healthy.values():
                    n_h = len(u)
                    centered = u - u.mean(axis=0)
                    contributions.append((n_h / (n_h - 1)) * (centered.T @ centered))
                total += np.mean(contributions, axis=0) * len(lonely)
            return total

        raise SurveyEngineError("SURVEY_LONELY_PSU_POLICY_INVALID", self.lonely_psu)
