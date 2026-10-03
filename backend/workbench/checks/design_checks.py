"""Design-level checks: they read the regressors and roles, never the outcome."""

from __future__ import annotations

import math

import numpy as np

from .context import CheckContext, public_column
from .contracts import CheckOutcome, CheckSpec, Threshold


def rows_per_parameter(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    design = context.design
    if design is None:
        return CheckOutcome("not_checked", "The estimator does not expose its design matrix.")
    rows, parameters = design.matrix.shape
    ratio = rows / parameters if parameters else math.inf
    evidence = {"rows": rows, "parameters": parameters, "rows_per_parameter": round(ratio, 2)}
    limit = spec.threshold("caution_below")
    if ratio < limit:
        return CheckOutcome(
            "caution",
            f"{rows} rows for {parameters} parameters ({ratio:.1f} per parameter); estimates this "
            f"thin are unstable and overfit.",
            evidence,
            "Collect more data, or reduce the number of parameters.",
        )
    return CheckOutcome("holds", f"{ratio:.1f} rows per parameter.", evidence)


def _correlation(matrix: np.ndarray) -> np.ndarray | None:
    centered = matrix - matrix.mean(axis=0)
    scale = np.sqrt((centered**2).sum(axis=0))
    if np.any(scale == 0):
        return None
    normalized = centered / scale
    return normalized.T @ normalized


def collinearity_gvif(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    """Generalized VIF on the design matrix (Fox & Monette, 1992).

    For a term of df columns, GVIF = det(R_term) det(R_rest) / det(R) on the
    correlation matrix of the non-intercept columns; GVIF^(1/(2 df)) puts terms
    of different size on the scale of sqrt(VIF). With one column per term it is
    the ordinary VIF.
    """
    design = context.design
    if design is None:
        return CheckOutcome("not_checked", "The estimator does not expose its design matrix.")
    if len(design.terms) < 2:
        return CheckOutcome("not_applicable", "Collinearity needs at least two regressors.")
    columns = design.regressor_columns
    position = {column: index for index, column in enumerate(columns)}
    matrix = design.matrix[:, columns]
    constant = [public_column(design.column_names[column]) for column in columns if np.ptp(design.matrix[:, column]) == 0]
    if constant:
        return CheckOutcome(
            "fails",
            f"{', '.join(constant)} does not vary in the estimation sample, so it cannot be "
            "separated from the intercept.",
            {"constant_columns": constant},
            "Remove the constant regressor.",
        )
    correlation = _correlation(matrix)
    eigenvalues, eigenvectors = np.linalg.eigh(correlation)
    if eigenvalues[0] < 1e-10 * len(columns):
        # The null direction names the columns that combine exactly.
        loading = np.abs(eigenvectors[:, 0])
        involved = sorted(
            {label for label, positions in design.terms.items() if any(loading[position[c]] > 1e-6 for c in positions)}
        )
        return CheckOutcome(
            "fails",
            f"The regressors {', '.join(involved)} are perfectly collinear: one is an exact combination "
            "of the others, so their separate effects are not identified.",
            {"perfectly_collinear_terms": involved},
            "Remove one of the collinear regressors.",
        )
    determinant = float(np.prod(eigenvalues))
    limit = spec.threshold("caution_above")
    terms = {}
    worst = None
    for label, positions in design.terms.items():
        inside = [position[column] for column in positions]
        outside = [index for index in range(len(columns)) if index not in inside]
        df = len(inside)
        rest = float(np.linalg.det(correlation[np.ix_(outside, outside)])) if outside else 1.0
        gvif = float(np.linalg.det(correlation[np.ix_(inside, inside)])) * rest / determinant
        adjusted = gvif ** (1 / (2 * df))
        terms[label] = {"gvif": round(gvif, 2), "df": df, "gvif_adjusted": round(adjusted, 3)}
        if worst is None or adjusted > worst[1]:
            worst = (label, adjusted, gvif)
    evidence = {"terms": terms, "threshold_gvif_adjusted": round(limit, 3)}
    label, adjusted, gvif = worst
    if adjusted > limit:
        named = "VIF" if terms[label]["df"] == 1 else "GVIF"
        return CheckOutcome(
            "caution",
            f"{label} is strongly collinear with the other regressors ({named} {gvif:.1f}); its "
            "coefficient is imprecise and sensitive to small changes in the data.",
            evidence,
            "Consider dropping or combining the collinear regressors, or report them jointly.",
        )
    return CheckOutcome("holds", f"Largest {('VIF' if terms[label]['df'] == 1 else 'GVIF')} {gvif:.1f} ({label}).", evidence)


ROWS_PER_PARAMETER = CheckSpec(
    check_id="design.rows_per_parameter",
    title="Rows per parameter",
    requires=frozenset({"design.linear_predictor"}),
    blinding="design",
    thresholds=(
        Threshold("caution_below", 10.0, "fewer than 10 rows per estimated parameter",
                  "Harrell (2015), Regression Modeling Strategies, 2nd ed., section 4.4"),
    ),
    run=rows_per_parameter,
)

COLLINEARITY = CheckSpec(
    check_id="collinearity.gvif",
    title="Collinearity (GVIF)",
    requires=frozenset({"design.linear_predictor"}),
    blinding="design",
    thresholds=(
        Threshold("caution_above", math.sqrt(10.0), "GVIF^(1/(2 df)) above sqrt(10), i.e. VIF above 10 for a one-column term",
                  "Fox & Monette (1992), JASA 87(417); VIF > 10 convention"),
    ),
    run=collinearity_gvif,
    max_cells=50_000_000,
)
