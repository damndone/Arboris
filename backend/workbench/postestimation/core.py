"""Wald, lincom, nlcom and likelihood-ratio tests computed from kernels.

The reference distribution is the kernel's: a kernel that declares ``t`` with
residual degrees of freedom gets F(q, df) and t(df); one that declares ``z``
gets chi2(q) and the normal. That keeps every result consistent with the
p-values the model itself reported.

A refusal names the property that is missing ("this model uses a clustered
covariance") rather than the family, so the same rule covers families added
later.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from scipy import stats

#: Covariance estimators under which the likelihood describes the variance.
#: A likelihood-ratio test is not valid under robust, clustered or design-based
#: variance (Stata's `lrtest` refuses the same cases).
MODEL_BASED_COVARIANCES = frozenset({"nonrobust"})

_NLCOM_FUNCTIONS = {"exp": np.exp, "log": np.log, "sqrt": np.sqrt}
_MAX_EXPRESSION_LENGTH = 500


class PostestimationRefusal(ValueError):
    """An operation that does not apply to this model, with the reason why."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _require_interface(kernel: Mapping[str, Any], interface: str, operation: str) -> None:
    if interface not in (kernel.get("interfaces") or []):
        reason = (kernel.get("unavailable") or {}).get(interface) or "the model does not provide it"
        raise PostestimationRefusal(
            "INTERFACE_UNAVAILABLE",
            f"{operation} needs the model's {interface.replace('_', ' ')}: {reason}",
        )


def _coefficients(kernel: Mapping[str, Any], names: Sequence[str], operation: str) -> tuple[np.ndarray, np.ndarray]:
    """The estimates and covariance block of the named parameters."""
    _require_interface(kernel, "coef_vcov", operation)
    known = list(kernel["param_names"])
    unknown = [name for name in names if name not in known]
    if unknown:
        raise PostestimationRefusal(
            "UNKNOWN_PARAMETER",
            f"{', '.join(map(str, unknown))} is not a parameter of this model; its parameters are "
            f"{', '.join(known)}",
        )
    covered = list(kernel["vcov_param_names"])
    outside = [name for name in names if name not in covered]
    if outside:
        raise PostestimationRefusal(
            "COVARIANCE_NOT_STORED",
            f"the covariance of {', '.join(map(str, outside))} was not stored (only "
            f"{kernel['vcov_scope']} parameters were kept), so a test involving them is not available",
        )
    params = dict(zip(known, kernel["params"]))
    beta = np.array([params[name] for name in names], dtype=float)
    vcov = np.asarray(kernel["vcov"], dtype=float)
    index = [covered.index(name) for name in names]
    return beta, vcov[np.ix_(index, index)]


def _uses_t(kernel: Mapping[str, Any]) -> bool:
    df = kernel.get("df_resid")
    return kernel.get("reference_distribution") == "t" and isinstance(df, (int, float)) and df > 0


def _identity(kernel: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "model_id": kernel["model_id"],
        "model_type": kernel["model_type"],
        "covariance_estimator": kernel.get("covariance_estimator"),
        "nobs": kernel.get("nobs"),
        "df_method": kernel.get("df_method"),
        "n_clusters": kernel.get("n_clusters"),
    }


def _single_inference(kernel: Mapping[str, Any], estimate: float, std_error: float, level: float) -> dict[str, Any]:
    if not 0 < level < 1:
        raise PostestimationRefusal("INVALID_LEVEL", "the confidence level must be between 0 and 1")
    if not math.isfinite(std_error) or std_error <= 0:
        raise PostestimationRefusal(
            "DEGENERATE_VARIANCE", "the combination has no sampling variance, so it cannot be tested"
        )
    statistic = estimate / std_error
    if _uses_t(kernel):
        df = float(kernel["df_resid"])
        p_value = float(2 * stats.t.sf(abs(statistic), df))
        critical = float(stats.t.ppf(0.5 + level / 2, df))
        distribution = "t"
    else:
        df = None
        p_value = float(2 * stats.norm.sf(abs(statistic)))
        critical = float(stats.norm.ppf(0.5 + level / 2))
        distribution = "z"
    return {
        "estimate": float(estimate),
        "std_error": float(std_error),
        "statistic": float(statistic),
        "distribution": distribution,
        "df": df,
        "p_value": p_value,
        "level": level,
        "ci": [float(estimate - critical * std_error), float(estimate + critical * std_error)],
    }


def _terms(terms: Any, operation: str) -> dict[str, float]:
    if not isinstance(terms, Mapping) or not terms:
        raise PostestimationRefusal("INVALID_SPEC", f"{operation} needs at least one parameter with a weight")
    out: dict[str, float] = {}
    for name, weight in terms.items():
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight):
            raise PostestimationRefusal("INVALID_SPEC", f"the weight of {name} must be a finite number")
        out[str(name)] = float(weight)
    return out


def wald_test(kernel: Mapping[str, Any], constraints: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Test the linear restrictions ``sum(terms[j] * b_j) = value``, jointly."""
    if not isinstance(constraints, Sequence) or isinstance(constraints, (str, bytes)) or not constraints:
        raise PostestimationRefusal("INVALID_SPEC", "a Wald test needs at least one constraint")
    parsed = []
    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            raise PostestimationRefusal("INVALID_SPEC", "each constraint must be an object")
        value = constraint.get("value", 0.0)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise PostestimationRefusal("INVALID_SPEC", "a constraint's value must be a finite number")
        parsed.append((_terms(constraint.get("terms"), "a Wald constraint"), float(value)))
    names = list(dict.fromkeys(name for terms, _ in parsed for name in terms))
    beta, vcov = _coefficients(kernel, names, "a Wald test")
    restriction = np.array([[terms.get(name, 0.0) for name in names] for terms, _ in parsed])
    target = np.array([value for _, value in parsed])
    q = len(parsed)
    # numpy's default tolerance is relative to the largest singular value, so
    # the check does not depend on the units the coefficients are measured in.
    if np.linalg.matrix_rank(restriction) < q:
        raise PostestimationRefusal(
            "DEPENDENT_CONSTRAINTS",
            "the constraints are not linearly independent; remove the redundant ones",
        )
    middle = restriction @ vcov @ restriction.T
    if np.linalg.matrix_rank(middle) < q:
        raise PostestimationRefusal(
            "SINGULAR_COVARIANCE",
            "the covariance of the restricted combinations is singular, so the joint test is not defined",
        )
    gap = restriction @ beta - target
    chi2 = float(gap @ np.linalg.solve(middle, gap))
    adjustment = None
    if _uses_t(kernel) and kernel.get("df_method") == "design" and q > 1:
        # Under a sampling design the Wald statistic is referred to the
        # Korn-Graubard (1990) adjusted F: (d - q + 1) / (d q) W on
        # (q, d - q + 1) -- Stata's default after svy. For q = 1 it equals the
        # unadjusted F.
        design_df = float(kernel["df_resid"])
        df_den = design_df - q + 1
        if df_den <= 0:
            raise PostestimationRefusal(
                "TOO_FEW_DESIGN_DF",
                f"{q} constraints need more than {design_df:g} design degrees of freedom for the "
                "adjusted F test",
            )
        statistic = chi2 * df_den / (design_df * q)
        p_value = float(stats.f.sf(statistic, q, df_den))
        distribution = "F"
        adjustment = "korn_graubard_adjusted_f"
    elif _uses_t(kernel):
        df_den = float(kernel["df_resid"])
        statistic = chi2 / q
        p_value = float(stats.f.sf(statistic, q, df_den))
        distribution = "F"
    else:
        df_den = None
        statistic = chi2
        p_value = float(stats.chi2.sf(chi2, q))
        distribution = "chi2"
    return {
        "operation": "wald",
        **_identity(kernel),
        "constraints": [{"terms": terms, "value": value} for terms, value in parsed],
        "distribution": distribution,
        "statistic": statistic,
        "df_num": q,
        "df_den": df_den,
        "p_value": p_value,
        **({"adjustment": adjustment} if adjustment else {}),
    }


def lincom(
    kernel: Mapping[str, Any], terms: Mapping[str, Any], *, constant: float = 0.0, level: float = 0.95
) -> dict[str, Any]:
    """A linear combination ``sum(terms[j] * b_j) + constant`` with its inference."""
    weights = _terms(terms, "lincom")
    if isinstance(constant, bool) or not isinstance(constant, (int, float)) or not math.isfinite(constant):
        raise PostestimationRefusal("INVALID_SPEC", "the constant must be a finite number")
    names = list(weights)
    beta, vcov = _coefficients(kernel, names, "lincom")
    vector = np.array([weights[name] for name in names])
    estimate = float(vector @ beta + constant)
    std_error = float(math.sqrt(max(float(vector @ vcov @ vector), 0.0)))
    return {
        "operation": "lincom",
        **_identity(kernel),
        "terms": weights,
        "constant": float(constant),
        **_single_inference(kernel, estimate, std_error, level),
    }


class _Expression:
    """A restricted arithmetic expression over parameter names.

    Accepted: numbers, parameter names written bare when they are identifiers
    or as ``b["any name"]``, + - * / **, unary minus, and exp/log/sqrt. Anything
    else is refused before evaluation, so the expression can never reach code.
    """

    def __init__(self, text: str, parameters: Sequence[str]) -> None:
        if not isinstance(text, str) or not text.strip():
            raise PostestimationRefusal("INVALID_SPEC", "nlcom needs an expression")
        if len(text) > _MAX_EXPRESSION_LENGTH:
            raise PostestimationRefusal("INVALID_SPEC", "the expression is too long")
        try:
            self.tree = ast.parse(text.strip(), mode="eval")
        except SyntaxError as exc:
            raise PostestimationRefusal("INVALID_EXPRESSION", f"the expression is not valid: {exc.msg}") from exc
        self.parameters = list(parameters)
        self.used: list[str] = []
        self._check(self.tree.body)

    def _parameter(self, name: str) -> str:
        if name not in self.parameters:
            raise PostestimationRefusal(
                "UNKNOWN_PARAMETER",
                f"{name} is not a parameter of this model; its parameters are {', '.join(self.parameters)}",
            )
        if name not in self.used:
            self.used.append(name)
        return name

    def _check(self, node: ast.AST) -> None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
            self._check(node.left)
            self._check(node.right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            self._check(node.operand)
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return
        elif isinstance(node, ast.Name):
            self._parameter(node.id)
        elif (
            isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "b"
            and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)
        ):
            self._parameter(node.slice.value)
        elif (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _NLCOM_FUNCTIONS and len(node.args) == 1 and not node.keywords
        ):
            self._check(node.args[0])
        else:
            raise PostestimationRefusal(
                "INVALID_EXPRESSION",
                "only numbers, parameter names, + - * / **, and exp, log, sqrt are allowed",
            )

    def evaluate(self, values: Mapping[str, float]) -> float:
        def walk(node: ast.AST) -> float:
            if isinstance(node, ast.BinOp):
                left, right = walk(node.left), walk(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return left / right if right != 0 else math.nan
                return left ** right if left > 0 or float(right).is_integer() else math.nan
            if isinstance(node, ast.UnaryOp):
                value = walk(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.Constant):
                return float(node.value)
            if isinstance(node, ast.Name):
                return values[node.id]
            if isinstance(node, ast.Subscript):
                return values[node.slice.value]
            argument = walk(node.args[0])
            with np.errstate(all="ignore"):
                return float(_NLCOM_FUNCTIONS[node.func.id](argument))

        try:
            return float(walk(self.tree.body))
        except (OverflowError, ValueError, ZeroDivisionError):
            return math.nan


def nlcom(kernel: Mapping[str, Any], expression: str, *, level: float = 0.95) -> dict[str, Any]:
    """A smooth function of the parameters, by the delta method."""
    parsed = _Expression(expression, list(kernel.get("param_names") or []))
    if not parsed.used:
        raise PostestimationRefusal("INVALID_EXPRESSION", "the expression does not use any parameter")
    beta, vcov = _coefficients(kernel, parsed.used, "nlcom")
    point = dict(zip(parsed.used, beta))
    estimate = parsed.evaluate(point)
    if not math.isfinite(estimate):
        raise PostestimationRefusal("UNDEFINED_AT_ESTIMATE", "the expression is not defined at the estimates")
    gradient = np.empty(len(beta))
    for index, name in enumerate(parsed.used):
        # Central differences with a step scaled to the parameter: the error
        # is O(h^2), about 1e-10 relative at this step.
        step = 6e-6 * max(1.0, abs(point[name]))
        upper = parsed.evaluate({**point, name: point[name] + step})
        lower = parsed.evaluate({**point, name: point[name] - step})
        if not (math.isfinite(upper) and math.isfinite(lower)):
            raise PostestimationRefusal(
                "UNDEFINED_AT_ESTIMATE", "the expression is not differentiable at the estimates"
            )
        gradient[index] = (upper - lower) / (2 * step)
    std_error = float(math.sqrt(max(float(gradient @ vcov @ gradient), 0.0)))
    result = {
        "operation": "nlcom",
        **_identity(kernel),
        "expression": expression.strip(),
        **_single_inference(kernel, estimate, std_error, level),
        "warnings": [],
    }
    # The delta method is a linearisation. Where one standard error away the
    # function departs from its tangent by more than a tenth of the standard
    # error, the interval it gives is unreliable, and the reader is told so.
    shift = np.sqrt(np.clip(np.diag(vcov), 0.0, None))
    for sign in (-1.0, 1.0):
        moved = {name: point[name] + sign * shift[index] for index, name in enumerate(parsed.used)}
        exact = parsed.evaluate(moved)
        linear = estimate + float(gradient @ (sign * shift))
        if not math.isfinite(exact) or abs(exact - linear) > 0.1 * std_error:
            result["warnings"].append(
                "The expression is strongly non-linear near the estimates; the delta-method "
                "interval may be inaccurate."
            )
            break
    return result


def lr_test(full: Mapping[str, Any], restricted: Mapping[str, Any]) -> dict[str, Any]:
    """Likelihood-ratio test of a restricted model nested in a fuller one."""
    for label, kernel in (("the fuller model", full), ("the restricted model", restricted)):
        _require_interface(kernel, "loglik", f"a likelihood-ratio test of {label}")
        estimator = kernel.get("covariance_estimator")
        if estimator not in MODEL_BASED_COVARIANCES:
            raise PostestimationRefusal(
                "NOT_MODEL_BASED_VARIANCE",
                f"{label} uses a {estimator or 'non-model-based'} covariance; a likelihood-ratio test "
                "assumes the likelihood describes the variance, so use a Wald test instead",
            )
        if kernel.get("weights") == "sampling":
            raise PostestimationRefusal(
                "SAMPLING_WEIGHTS",
                f"{label} uses sampling weights; its likelihood is a pseudo-likelihood, so a "
                "likelihood-ratio test is not valid. Use a Wald test instead",
            )
    if full["model_type"] != restricted["model_type"]:
        raise PostestimationRefusal(
            "DIFFERENT_MODELS",
            f"the two models are of different kinds ({full['model_type']} and "
            f"{restricted['model_type']}), so their likelihoods are not comparable",
        )
    if full.get("weights") != restricted.get("weights"):
        raise PostestimationRefusal("DIFFERENT_WEIGHTS", "the two models weight their samples differently")
    full_sample = full.get("estimation_sample_fingerprint")
    restricted_sample = restricted.get("estimation_sample_fingerprint")
    if not full_sample or not restricted_sample:
        raise PostestimationRefusal(
            "SAMPLE_UNVERIFIED",
            "one of the models does not record its estimation sample, so it cannot be "
            "verified that both used the same observations",
        )
    if full_sample != restricted_sample:
        raise PostestimationRefusal(
            "DIFFERENT_SAMPLES",
            "the two models were estimated on different observations (for example because of "
            "missing values in the extra variables); refit both on the same sample first",
        )
    full_names = list(full["param_names"])
    restricted_names = list(restricted["param_names"])
    if not set(restricted_names) < set(full_names):
        raise PostestimationRefusal(
            "NOT_NESTED",
            "the restricted model's parameters must be a strict subset of the fuller model's",
        )
    difference = len(full_names) - len(restricted_names)
    statistic = 2.0 * (float(full["loglik"]) - float(restricted["loglik"]))
    tolerance = 1e-8 * max(1.0, abs(float(full["loglik"])))
    if statistic < -tolerance:
        raise PostestimationRefusal(
            "NOT_NESTED",
            "the restricted model fits better than the fuller one, which nested models cannot do",
        )
    statistic = max(statistic, 0.0)
    return {
        "operation": "lr",
        "full": _identity(full),
        "restricted": _identity(restricted),
        "dropped_parameters": [name for name in full_names if name not in restricted_names],
        "distribution": "chi2",
        "statistic": statistic,
        "df": difference,
        "p_value": float(stats.chi2.sf(statistic, difference)),
        "loglik_full": float(full["loglik"]),
        "loglik_restricted": float(restricted["loglik"]),
    }
