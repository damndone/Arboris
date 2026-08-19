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

import ast
from dataclasses import dataclass, field
from decimal import Decimal, DecimalException

import numpy as np
import pandas as pd

from .errors import SurveyEngineError
from .estimator import VARIANCE_METHOD_REQUIREMENTS, EstimatorSpec, missing_capabilities

LONELY_PSU_POLICIES = ("fail", "remove", "adjust", "average", "certainty")
REPLICATE_TYPES = ("brr", "jackknife", "bootstrap", "provided")
SURVEY_WEIGHT_FRAME_VALUES = ("cross_sectional", "longitudinal")
_MAX_INVALID_WEIGHT_ROWS = 16
_MAX_SUBPOP_EXPRESSION_LENGTH = 512
_MAX_SURVEY_WEIGHT = Decimal("1000000000000")
SURVEY_INVALID_SAMPLING_WEIGHTS = "SURVEY_INVALID_SAMPLING_WEIGHTS"


def _weight_failure(
    *,
    code: str,
    column: str,
    reason: str,
    invalid_rows: list[str] | None = None,
    detail: str | None = None,
    **context: object,
) -> SurveyEngineError:
    return SurveyEngineError(
        code,
        detail or f"weight column {column!r} violates the survey weight contract",
        weight_column=column,
        reason=reason,
        invalid_rows=list(invalid_rows or []),
        **context,
    )


def _validated_weight_array(
    frame: pd.DataFrame,
    column: str,
    *,
    allow_zero: bool,
    error_code: str,
) -> np.ndarray:
    """Validate one weight vector before converting it to floating point.

    Pandas/numpy will try to coerce an object integer such as ``10**400`` to a
    float while constructing an array, which raises a raw ``OverflowError``.
    Survey weights are an executable boundary, so parse each value as a
    decimal first, apply the finite/sign/positive-total rules there, and only
    then perform the bounded float conversion required by the variance math.
    """
    if column not in frame.columns:
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="missing",
            detail=f"weight column {column!r} is not in the frame",
        )
    try:
        raw_values = frame[column].to_numpy(dtype=object)
    except (OverflowError, TypeError, ValueError) as exc:
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="non_numeric",
            detail=f"weight column {column!r} is not numeric",
        ) from exc
    if raw_values.ndim != 1 or len(raw_values) != len(frame):
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="shape",
            detail=f"weight column {column!r} must be one value per row",
        )
    if len(raw_values) == 0:
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="empty",
            detail=f"weight column {column!r} cannot be empty",
        )

    decimals: list[Decimal] = []
    non_numeric_rows: list[str] = []
    nonfinite_rows: list[str] = []
    negative_rows: list[str] = []
    nonpositive_rows: list[str] = []
    absolute_bound_rows: list[str] = []
    for index, raw_value in zip(frame.index, raw_values, strict=True):
        try:
            if isinstance(raw_value, (bool, np.bool_)):
                raise ValueError("boolean is not a numeric survey weight")
            parsed = Decimal(str(raw_value).strip())
        except (DecimalException, OverflowError, TypeError, ValueError, UnicodeError):
            non_numeric_rows.append(str(index))
            continue
        decimals.append(parsed)
        if not parsed.is_finite():
            nonfinite_rows.append(str(index))
        elif parsed < 0:
            negative_rows.append(str(index))
        elif not allow_zero and parsed == 0:
            nonpositive_rows.append(str(index))

    if non_numeric_rows:
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="non_numeric",
            invalid_rows=non_numeric_rows[:_MAX_INVALID_WEIGHT_ROWS],
            detail=f"weight column {column!r} contains values that cannot be parsed safely",
        )
    if len(decimals) != len(raw_values):
        # Defensive guard: the row lists above should make this unreachable,
        # but never let a future parser change turn into a raw failure.
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="non_numeric",
            detail=f"weight column {column!r} is not numeric",
        )
    if nonfinite_rows:
        rows = nonfinite_rows[:_MAX_INVALID_WEIGHT_ROWS]
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="nonfinite",
            invalid_rows=rows,
        )

    if negative_rows:
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="negative" if allow_zero else "nonpositive",
            invalid_rows=negative_rows[:_MAX_INVALID_WEIGHT_ROWS],
        )

    if not allow_zero and nonpositive_rows:
        all_zero = all(value == 0 for value in decimals)
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="all_zero" if all_zero else "nonpositive",
            invalid_rows=nonpositive_rows[:_MAX_INVALID_WEIGHT_ROWS],
        )

    if allow_zero and not any(value > 0 for value in decimals):
        raise _weight_failure(code=error_code, column=column, reason="all_zero")

    # The decimal checks above establish finite/nonnegative/positive-total
    # semantics without a float conversion.  This second conversion boundary
    # rejects values that are mathematically valid but cannot be represented by
    # the numpy float arrays used by the estimator.
    float_values: list[float] = []
    float_overflow_rows: list[str] = []
    for index, parsed in zip(frame.index, decimals, strict=True):
        try:
            converted = float(parsed)
        except (DecimalException, OverflowError, TypeError, ValueError):
            float_overflow_rows.append(str(index))
            continue
        float_values.append(converted)
        if not np.isfinite(converted):
            float_overflow_rows.append(str(index))
        elif abs(parsed) > _MAX_SURVEY_WEIGHT:
            absolute_bound_rows.append(str(index))
    if float_overflow_rows:
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="not_float_representable",
            invalid_rows=float_overflow_rows[:_MAX_INVALID_WEIGHT_ROWS],
            detail=f"weight column {column!r} cannot be represented as finite float values",
        )
    if absolute_bound_rows:
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="absolute_bound",
            invalid_rows=absolute_bound_rows[:_MAX_INVALID_WEIGHT_ROWS],
            maximum=str(_MAX_SURVEY_WEIGHT),
        )

    values = np.asarray(float_values, dtype=float)
    with np.errstate(over="ignore", invalid="ignore"):
        total = float(np.sum(values, dtype=float))
    if not np.isfinite(total) or total <= 0:
        raise _weight_failure(
            code=error_code,
            column=column,
            reason="not_float_representable" if not np.isfinite(total) else "nonpositive_sum",
            total=total,
        )
    return values


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
    weight_frame: str | None = None
    subpop: str | None = None
    replicate_type: str | None = None
    replicate_weight_columns: list[str] = field(default_factory=list)
    #: Optional balanced set for BRR.  BRR's answer depends on this choice, so
    #: comparing against another implementation means fixing the same set.
    hadamard_matrix: list[list[int]] | None = None

    def __post_init__(self) -> None:
        if self.fpc:
            raise SurveyEngineError(
                "SURVEY_FPC_UNSUPPORTED",
                "finite population correction is declared but this survey variance "
                "engine does not apply FPC",
                fpc_column=self.fpc,
            )
        if self.lonely_psu not in LONELY_PSU_POLICIES:
            raise SurveyEngineError(
                "SURVEY_LONELY_PSU_POLICY_INVALID",
                f"unknown policy {self.lonely_psu!r}",
                allowed=list(LONELY_PSU_POLICIES),
            )
        if self.weight_frame is not None and self.weight_frame not in SURVEY_WEIGHT_FRAME_VALUES:
            raise SurveyEngineError(
                "SURVEY_WEIGHT_FRAME_INVALID",
                f"unknown survey weight frame {self.weight_frame!r}",
                allowed=list(SURVEY_WEIGHT_FRAME_VALUES),
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
        if self.replicate_type == "provided":
            missing_replicates = [
                column for column in self.replicate_weight_columns
                if column not in self.frame.columns
            ]
            if missing_replicates:
                raise SurveyEngineError(
                    "SURVEY_REPLICATE_WEIGHTS_MISSING",
                    "provided replicate weight columns are missing",
                    columns=missing_replicates[:16],
                )
        # Sampling weights are part of the executable design, not a declaration
        # that can be trusted until a later matrix operation.  Validate at
        # construction and again through ``weights`` because the frame remains
        # mutable for subpopulation and test workflows.
        _validated_weight_array(
            self.frame,
            self.weight,
            allow_zero=False,
            error_code=SURVEY_INVALID_SAMPLING_WEIGHTS,
        )

    # -- structure ---------------------------------------------------------

    @property
    def weights(self) -> np.ndarray:
        return _validated_weight_array(
            self.frame,
            self.weight,
            allow_zero=False,
            error_code=SURVEY_INVALID_SAMPLING_WEIGHTS,
        )

    def validate_for_estimation(self, mask: np.ndarray | None = None) -> None:
        """Re-check executable design constraints immediately before fitting."""
        values = self.weights
        if mask is None:
            return
        mask_array = np.asarray(mask, dtype=bool)
        if mask_array.shape != (len(self.frame),):
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation mask must contain one boolean per design row",
                mask_shape=list(mask_array.shape),
                n_obs=len(self.frame),
            )
        if not mask_array.any():
            raise SurveyEngineError(
                "SURVEY_SUBPOP_EMPTY",
                "the declared subpopulation contains no design rows",
                subpopulation=self.subpop,
            )
        selected = values[mask_array]
        with np.errstate(over="ignore", invalid="ignore"):
            total = float(np.sum(selected, dtype=float))
        if not np.isfinite(total) or total <= 0:
            raise _weight_failure(
                code=SURVEY_INVALID_SAMPLING_WEIGHTS,
                column=self.weight,
                reason=(
                    "subpopulation_not_float_representable"
                    if not np.isfinite(total)
                    else "subpopulation_nonpositive_sum"
                ),
                total=total,
            )

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
        if self.subpop is None:
            return np.ones(len(self.frame), dtype=bool)
        expression = self.subpop
        if not isinstance(expression, str) or not expression.strip():
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation expression must be a non-empty string",
            )
        if len(expression) > _MAX_SUBPOP_EXPRESSION_LENGTH:
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation expression exceeds the supported length",
                expression_length=len(expression),
            )

        allowed_nodes = (
            ast.Expression,
            ast.BoolOp,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
            ast.Name,
            ast.Load,
            ast.Constant,
            ast.And,
            ast.Or,
            ast.Not,
            ast.Invert,
            ast.UAdd,
            ast.USub,
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.Mod,
            ast.BitAnd,
            ast.BitOr,
            ast.Eq,
            ast.NotEq,
            ast.Lt,
            ast.LtE,
            ast.Gt,
            ast.GtE,
            ast.In,
            ast.NotIn,
        )
        try:
            parsed = ast.parse(expression, mode="eval")
        except (SyntaxError, ValueError, TypeError, MemoryError) as exc:
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation expression is not valid",
                reason="syntax",
            ) from exc

        names = {
            node.id
            for node in ast.walk(parsed)
            if isinstance(node, ast.Name)
        }
        allowed_names = set(self.frame.columns) | {"index"}
        unknown_names = sorted(names - allowed_names)
        if unknown_names:
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation expression references an unknown column",
                reason="unknown_column",
                columns=[name[:128] for name in unknown_names[:16]],
            )
        if any(not isinstance(node, allowed_nodes) for node in ast.walk(parsed)):
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation expression uses an unsupported operation",
                reason="unsupported_operation",
            )

        try:
            mask = self.frame.eval(expression, engine="python", parser="pandas")
            mask_array = np.asarray(mask)
        except Exception as exc:  # noqa: BLE001 - expose one bounded survey error
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation expression could not be evaluated safely",
                reason="evaluation",
            ) from exc
        if mask_array.shape != (len(self.frame),):
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation expression must produce one boolean per row",
                reason="shape",
                mask_shape=list(mask_array.shape),
            )
        if mask_array.dtype != np.dtype(bool):
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation expression must produce boolean values",
                reason="not_boolean",
                dtype=str(mask_array.dtype),
            )
        if pd.isna(mask_array).any():
            raise SurveyEngineError(
                "SURVEY_SUBPOP_INVALID",
                "subpopulation expression must not contain missing values",
                reason="missing_values",
            )
        return mask_array

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
        try:
            values = self.frame.loc[mask, column].to_numpy(dtype=float)
        except (OverflowError, TypeError, ValueError) as exc:
            raise SurveyEngineError(
                "SURVEY_INFERENCE_UNAVAILABLE",
                "design effects require finite numeric observations",
                reason="nonfinite_design_effect",
            ) from exc
        w = self.weights[mask]
        n_obs = int(mask.sum())
        if n_obs <= 1 or not np.isfinite(values).all():
            raise SurveyEngineError(
                "SURVEY_INFERENCE_UNAVAILABLE",
                "design effects require at least two finite observations",
                reason="nonfinite_design_effect",
                n_obs=n_obs,
            )

        with np.errstate(over="raise", divide="raise", invalid="raise"):
            try:
                total = float(w.sum(dtype=float))
                mean = float((w * values).sum(dtype=float) / total)

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
                s2 = float((w * (values - mean) ** 2).sum(dtype=float) / total) * n_obs / (n_obs - 1)
                var_srs = s2 * (total - n_obs) / (total * n_obs)

                # Kish's effective sample size is a separate, weight-only summary: how
                # many equally-weighted observations this sample behaves like.
                n_eff = float(total**2 / (w**2).sum(dtype=float))
            except (FloatingPointError, OverflowError, ZeroDivisionError, ValueError) as exc:
                raise SurveyEngineError(
                    "SURVEY_INFERENCE_UNAVAILABLE",
                    "design effects are not finite and bounded",
                    reason="nonfinite_design_effect",
                ) from exc

        deff = var_design / var_srs if var_srs != 0 else float("nan")
        standard_error = float(np.sqrt(var_design)) if var_design >= 0 else float("nan")
        outputs = (deff, n_eff, mean, standard_error, var_design, var_srs)
        if (
            not all(np.isfinite(value) for value in outputs)
            or deff < 0
            or n_eff < 0
            or standard_error < 0
        ):
            raise SurveyEngineError(
                "SURVEY_INFERENCE_UNAVAILABLE",
                "design effects are not finite and bounded",
                reason="nonfinite_design_effect",
                n_obs=n_obs,
            )

        return DesignEffects(
            deff=deff,
            kish_n_eff=n_eff,
            n_obs=n_obs,
            mean=mean,
            standard_error=standard_error,
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
