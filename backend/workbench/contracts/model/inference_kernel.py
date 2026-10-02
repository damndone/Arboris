"""The inference kernel: what post-estimation needs from a fitted model.

A Wald test, a likelihood-ratio test, a linear combination or a marginal effect
needs the parameter vector, its covariance, the reference distribution and,
for LR, the log-likelihood. Until v1.8.10 none of that was persisted -- the
result packet carried one standard error per term -- so the only way to test
two coefficients jointly was to refit, and the refit was written for OLS.

Every run now leaves a kernel beside its result packet. It is extracted from
whatever the model exposes (``params`` and ``cov_params()``), never chosen by
family name, and when a model cannot provide part of it the kernel says which
part and why instead of omitting it.

The kernel lives in ``model_results/inference_kernels/`` rather than next to
the result packets: several readers scan ``model_results/*.json`` and treat
whatever they find as a result.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

INFERENCE_KERNEL_CONTRACT = "workbench.inference_kernel.v1"

#: Above this many parameters the full covariance is not stored. Measured on
#: 2026-10-02: written compactly, 300 parameters take about 1.7 MB and 500 take
#: about 4.8 MB, against a 2 MB budget per result. A fixed-effects model with
#: thousands of dummies keeps only the parameters a reader can ask about, and
#: says that joint tests beyond them are unavailable.
MAX_FULL_VCOV_PARAMS = 300

KERNEL_INTERFACES = ("coef_vcov", "loglik")
REFERENCE_DISTRIBUTIONS = ("t", "z")
VCOV_SCOPES = ("full", "focal", "unavailable")

_FIELDS = frozenset(
    {
        "contract",
        "model_id",
        "model_type",
        "param_names",
        "params",
        "vcov",
        "vcov_param_names",
        "vcov_scope",
        "reference_distribution",
        "df_resid",
        "loglik",
        "nobs",
        "covariance_estimator",
        "estimation_sample_fingerprint",
        "interfaces",
        "unavailable",
    }
)

# Relative tolerance for symmetry: estimators return covariances that are
# symmetric up to floating-point noise, never up to a real asymmetry.
_SYMMETRY_TOLERANCE = 1e-8


class InferenceKernelError(ValueError):
    """A kernel that post-estimation could not safely use."""


def kernel_relative_path(model_id: str) -> str:
    return f"model_results/inference_kernels/{model_id}.json"


def kernel_artifact_id(model_id: str) -> str:
    return f"inference_kernel_{model_id}"


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InferenceKernelError(f"{name} must be a non-empty string")
    return value


def _square_covariance(vcov: Any, size: int) -> np.ndarray:
    matrix = np.asarray(vcov, dtype=float)
    if matrix.ndim != 2 or matrix.shape != (size, size):
        raise InferenceKernelError(f"vcov must be a {size}x{size} matrix")
    if not np.isfinite(matrix).all():
        raise InferenceKernelError("vcov contains a non-finite value")
    scale = max(float(np.max(np.abs(matrix))), 1e-300)
    if float(np.max(np.abs(matrix - matrix.T))) > _SYMMETRY_TOLERANCE * scale:
        raise InferenceKernelError("vcov is not symmetric")
    # A variance of -1e-20 on a coefficient the data pin down exactly is
    # rounding, not a defect; a clearly negative one is.
    if (np.diag(matrix) < -_SYMMETRY_TOLERANCE * scale).any():
        raise InferenceKernelError("vcov has a negative variance")
    return matrix


def build_inference_kernel(
    *,
    model_id: str,
    model_type: str,
    param_names: Sequence[str],
    params: Sequence[float],
    vcov: Any,
    reference_distribution: str,
    df_resid: float | None,
    loglik: float | None,
    nobs: int,
    covariance_estimator: str | None,
    estimation_sample_fingerprint: str | None = None,
    focal_param_names: Sequence[str] | None = None,
    unavailable: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate the pieces and assemble a kernel.

    ``unavailable`` lets a model explain an interface it cannot provide (an
    instrumental-variables fit has no likelihood); the builder adds its own
    reason when it has to drop the covariance.
    """
    _require_text(model_id, "model_id")
    _require_text(model_type, "model_type")
    names = [str(name) for name in param_names]
    if not names:
        raise InferenceKernelError("param_names must not be empty")
    if len(set(names)) != len(names):
        raise InferenceKernelError("param_names must be unique")
    values = [float(value) for value in params]
    if len(values) != len(names):
        raise InferenceKernelError("params and param_names differ in length")
    if not all(math.isfinite(value) for value in values):
        raise InferenceKernelError("params contains a non-finite value")
    if reference_distribution not in REFERENCE_DISTRIBUTIONS:
        raise InferenceKernelError("reference_distribution must be 't' or 'z'")
    if not isinstance(nobs, int) or isinstance(nobs, bool) or nobs < 0:
        raise InferenceKernelError("nobs must be a non-negative integer")

    reasons = {str(key): str(value) for key, value in (unavailable or {}).items() if value}
    matrix = _square_covariance(vcov, len(names)) if vcov is not None else None

    vcov_out: list[list[float]] | None = None
    vcov_names: list[str] | None = None
    scope = "unavailable"
    if matrix is not None:
        if len(names) <= MAX_FULL_VCOV_PARAMS:
            vcov_out, vcov_names, scope = matrix.tolist(), list(names), "full"
        elif focal_param_names:
            focal = [str(name) for name in focal_param_names]
            missing = [name for name in focal if name not in names]
            if missing:
                raise InferenceKernelError(f"focal parameters not in param_names: {missing}")
            if len(focal) > MAX_FULL_VCOV_PARAMS:
                raise InferenceKernelError("too many focal parameters")
            index = [names.index(name) for name in focal]
            vcov_out = matrix[np.ix_(index, index)].tolist()
            vcov_names, scope = focal, "focal"
        else:
            reasons.setdefault(
                "coef_vcov",
                f"The model has {len(names)} parameters, more than the {MAX_FULL_VCOV_PARAMS} "
                "whose full covariance is stored; no parameters were marked as focal.",
            )
    elif "coef_vcov" not in reasons:
        reasons["coef_vcov"] = "The model did not provide a coefficient covariance matrix."

    loglik_value = _finite_or_none(loglik)
    if loglik_value is None:
        reasons.setdefault("loglik", "The model did not provide a log-likelihood.")

    interfaces = []
    if vcov_out is not None:
        interfaces.append("coef_vcov")
        reasons.pop("coef_vcov", None)
    if loglik_value is not None:
        interfaces.append("loglik")
        reasons.pop("loglik", None)

    kernel = {
        "contract": INFERENCE_KERNEL_CONTRACT,
        "model_id": model_id,
        "model_type": model_type,
        "param_names": names,
        "params": values,
        "vcov": vcov_out,
        "vcov_param_names": vcov_names,
        "vcov_scope": scope,
        "reference_distribution": reference_distribution,
        "df_resid": _finite_or_none(df_resid),
        "loglik": loglik_value,
        "nobs": nobs,
        "covariance_estimator": covariance_estimator,
        "estimation_sample_fingerprint": estimation_sample_fingerprint,
        "interfaces": interfaces,
        "unavailable": reasons,
    }
    validate_inference_kernel(kernel)
    return kernel


def unavailable_inference_kernel(
    *, model_id: str, model_type: str, nobs: int | None, reason: str
) -> dict[str, Any]:
    """A kernel that records why nothing could be extracted."""
    _require_text(reason, "reason")
    kernel = {
        "contract": INFERENCE_KERNEL_CONTRACT,
        "model_id": _require_text(model_id, "model_id"),
        "model_type": _require_text(model_type, "model_type"),
        "param_names": [],
        "params": [],
        "vcov": None,
        "vcov_param_names": None,
        "vcov_scope": "unavailable",
        "reference_distribution": None,
        "df_resid": None,
        "loglik": None,
        "nobs": nobs if isinstance(nobs, int) and not isinstance(nobs, bool) and nobs >= 0 else None,
        "covariance_estimator": None,
        "estimation_sample_fingerprint": None,
        "interfaces": [],
        "unavailable": {interface: reason for interface in KERNEL_INTERFACES},
    }
    validate_inference_kernel(kernel)
    return kernel


def validate_inference_kernel(kernel: Any) -> None:
    """Check a persisted kernel before anyone computes with it."""
    if not isinstance(kernel, Mapping):
        raise InferenceKernelError("inference kernel must be an object")
    if set(kernel) != _FIELDS:
        raise InferenceKernelError(
            f"inference kernel fields differ: missing {sorted(_FIELDS - set(kernel))}, "
            f"unexpected {sorted(set(kernel) - _FIELDS)}"
        )
    if kernel["contract"] != INFERENCE_KERNEL_CONTRACT:
        raise InferenceKernelError("inference kernel contract is not recognised")
    interfaces = kernel["interfaces"]
    if not isinstance(interfaces, list) or any(item not in KERNEL_INTERFACES for item in interfaces):
        raise InferenceKernelError("interfaces must list known kernel interfaces")
    unavailable = kernel["unavailable"]
    if not isinstance(unavailable, Mapping):
        raise InferenceKernelError("unavailable must be an object")
    for interface in KERNEL_INTERFACES:
        if (interface in interfaces) == bool(unavailable.get(interface)):
            raise InferenceKernelError(
                f"{interface} must be either provided or explained, not both or neither"
            )
    if kernel["vcov_scope"] not in VCOV_SCOPES:
        raise InferenceKernelError("vcov_scope is not recognised")
    names = kernel["param_names"]
    if not isinstance(names, list) or len(names) != len(kernel["params"]):
        raise InferenceKernelError("param_names and params differ in length")
    if "coef_vcov" in interfaces:
        vcov_names = kernel["vcov_param_names"]
        if not isinstance(vcov_names, list) or not set(vcov_names) <= set(names):
            raise InferenceKernelError("vcov_param_names must name kernel parameters")
        _square_covariance(kernel["vcov"], len(vcov_names))
        if kernel["reference_distribution"] not in REFERENCE_DISTRIBUTIONS:
            raise InferenceKernelError("reference_distribution must be 't' or 'z'")
    elif kernel["vcov"] is not None:
        raise InferenceKernelError("vcov is present but coef_vcov is not offered")
    if "loglik" in interfaces and _finite_or_none(kernel["loglik"]) is None:
        raise InferenceKernelError("loglik is offered but not finite")


def _parameter_names(
    fitted: Any,
    params: Any,
    param_names: Sequence[str] | None,
    public_name: Callable[[str], str] | None,
) -> list[str] | None:
    if param_names is not None:
        return [str(name) for name in param_names]
    if getattr(params, "columns", None) is not None:
        return None  # multi-equation: the runtime must name the parameters
    index = getattr(params, "index", None)
    if index is None:
        # A robust-covariance result carries a bare array; the names stay on the
        # model it was fitted from.
        index = getattr(getattr(fitted, "model", None), "exog_names", None)
    if index is None:
        return None
    rename = public_name or str
    return [rename(str(name)) for name in index]


def _flatten(values: Any) -> np.ndarray:
    """Parameters in equation-major order for multi-equation models.

    A multinomial logit's ``params`` is terms x equations; its covariance is
    ordered by equation, then term, so the parameter vector must be too.
    """
    array = np.asarray(values, dtype=float)
    return array.T.reshape(-1) if array.ndim == 2 else array.reshape(-1)


def estimation_rows_fingerprint(row_labels: Sequence[Any]) -> str:
    """Identify the rows a model was estimated on, in order.

    Two models can only be compared by a likelihood-ratio test when they were
    fitted to the same observations. This identifies the rows, not the data
    set, so a caller comparing two models must also check that both read the
    same data node.
    """
    payload = json.dumps([str(label) for label in row_labels], ensure_ascii=False, separators=(",", ":"))
    return "rows-sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fitted_rows_fingerprint(fitted: Any) -> str | None:
    labels = getattr(getattr(getattr(fitted, "model", None), "data", None), "row_labels", None)
    if labels is None:
        return None
    try:
        return estimation_rows_fingerprint(list(labels))
    except TypeError:
        return None


def _covariance(fitted: Any) -> Any:
    cov_params = getattr(fitted, "cov_params", None)
    if callable(cov_params):
        return cov_params()
    return getattr(fitted, "cov", None)  # linearmodels exposes it as an attribute


def kernel_from_fitted(
    fitted: Any,
    *,
    model_id: str,
    model_type: str,
    nobs: int,
    param_names: Sequence[str] | None = None,
    public_name: Callable[[str], str] | None = None,
    estimation_sample_fingerprint: str | None = None,
    unavailable: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    """Extract a kernel from any fitted object exposing params and a covariance.

    ``public_name`` maps an estimator's term label to the name the result
    packet reports (formula quoting removed), so a post-estimation request
    naming a coefficient finds it in both.

    Returns ``None`` when the object does not expose those interfaces, so the
    caller can record why rather than guess.
    """
    if fitted is None:
        return None
    params = getattr(fitted, "params", None)
    if params is None:
        return None
    try:
        covariance = _covariance(fitted)
    except Exception as error:  # the model has the interface but it failed
        return unavailable_inference_kernel(
            model_id=model_id,
            model_type=model_type,
            nobs=nobs if nobs else None,
            reason=f"The model failed to produce a covariance matrix: {type(error).__name__}.",
        )
    if covariance is None:
        return None
    names = _parameter_names(fitted, params, param_names, public_name)
    flat = _flatten(params)
    if names is None or len(names) != len(flat):
        return None
    if not nobs:
        fitted_nobs = _finite_or_none(getattr(fitted, "nobs", None))
        nobs = int(fitted_nobs) if fitted_nobs is not None else 0

    use_t = getattr(fitted, "use_t", None)
    if use_t is None:
        use_t = bool(getattr(fitted, "debiased", False))
    loglik = getattr(fitted, "llf", None)
    if loglik is None:
        loglik = getattr(fitted, "loglikelihood", None)
    reasons = dict(unavailable or {})
    try:
        return build_inference_kernel(
            model_id=model_id,
            model_type=model_type,
            param_names=names,
            params=flat.tolist(),
            vcov=np.asarray(covariance, dtype=float),
            reference_distribution="t" if use_t else "z",
            df_resid=_finite_or_none(getattr(fitted, "df_resid", None)),
            loglik=loglik,
            nobs=nobs,
            covariance_estimator=str(getattr(fitted, "cov_type", "") or "") or None,
            estimation_sample_fingerprint=estimation_sample_fingerprint or _fitted_rows_fingerprint(fitted),
            unavailable=reasons,
        )
    except (InferenceKernelError, TypeError, ValueError) as error:
        # A separated logit or a perfectly collinear design can leave a
        # covariance that is not usable. The fit itself still stands, so the
        # run continues and post-estimation is refused with the reason.
        return unavailable_inference_kernel(
            model_id=model_id,
            model_type=model_type,
            nobs=nobs,
            reason=f"The fitted covariance matrix could not be used: {error}.",
        )


def resolve_inference_kernel(
    *,
    model_id: str,
    model_type: str,
    primary: Mapping[str, Any],
    fitted: Any,
    recorded: Mapping[str, Any] | None,
    public_name: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """The one rule every run follows.

    A kernel a runtime recorded wins (it knows names the fitted object lost);
    otherwise it is extracted from the fitted object; otherwise the run says why
    there is none.
    """
    nobs = primary.get("nobs")
    nobs = nobs if isinstance(nobs, int) and not isinstance(nobs, bool) else None
    if recorded is not None:
        validate_inference_kernel(recorded)
        return dict(recorded)
    extracted = kernel_from_fitted(
        fitted,
        model_id=model_id,
        model_type=model_type,
        nobs=nobs if nobs is not None else 0,
        public_name=public_name,
    )
    if extracted is not None:
        return extracted
    return unavailable_inference_kernel(
        model_id=model_id,
        model_type=model_type,
        nobs=nobs,
        reason=(
            f"The {model_type} runtime does not expose a coefficient covariance matrix or a "
            "log-likelihood yet, so post-estimation on this result is not available."
        ),
    )
