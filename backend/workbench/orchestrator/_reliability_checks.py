"""Reliability / correlation checks extracted from orchestrator
(V1.5.4.5, behavior-frozen).

Verbatim move. Consumed by diagnostics/reliability/exposure stages via the
workbench.orchestrator.* namespace. 阈值常量（0.7/0.5）随其函数留在本文件。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..artifacts import write_json
from ..domain import GuardrailIssue, Severity


_BINARY_CORRELATION_WARN = 0.7  # |r| > 0.7 > Severity.WARNING
_BINARY_CORRELATION_INFO = 0.5  # 0.5 < |r| <= 0.7 > Severity.INFO
_TREATMENT_PROXY_CORRELATION_WARN = 0.7


def _diagnostic_family(model_result: dict[str, Any]) -> str:
    model_type = model_result.get("model_type", "ols")
    if model_type == "glm":
        family = model_result.get("glm_family")
        return str(family) if family else "glm"
    if model_type == "poisson_rate":
        return "poisson"
    if model_type in ("ols", "ols_robust", "fixed_effects", "panel_ols"):
        return "ols"
    return str(model_type)


def _check_model_validity(
    diag: dict[str, Any],
    model_id: str,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    cd = diag.get("cooks_distance", {})
    if isinstance(cd, dict):
        if cd.get("max") is None and cd.get("leverage_max") is not None:
            issue = GuardrailIssue(
                Severity.WARNING,
                "MODEL_DIAGNOSTIC_ANOMALY",
                f"Model {model_id}: Cook's distance could not be computed. "
                f"Derived results (influence diagnostics) may be unreliable.",
                {"model_id": model_id, "leverage_max": cd.get("leverage_max")},
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
        if cd.get("leverage_max") is not None and float(cd["leverage_max"]) >= 1.0:
            issue = GuardrailIssue(
                Severity.WARNING,
                "MODEL_OVERPARAMETERIZED",
                f"Model {model_id}: max leverage is {cd['leverage_max']:.4f}. "
                f"Model may be over-parameterized or contain near-singular design matrix.",
                {"model_id": model_id, "leverage_max": cd["leverage_max"]},
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _check_overdispersion_issue(
    diag: dict[str, Any],
    model_id: str,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    od = diag.get("overdispersion", {})
    if not isinstance(od, dict):
        return
    od_ratio = od.get("overdispersion_ratio")
    if od_ratio is not None and float(od_ratio) > 2.0:
        warning = od.get(
            "warning",
            f"Severe overdispersion detected (ratio={float(od_ratio):.2f}). "
            f"Poisson model is unreliable.",
        )
        issue_dicts.append(GuardrailIssue(
            Severity.WARNING,
            "OVERDISPERSION_DETECTED",
            warning,
            {
                "model_id": model_id,
                "overdispersion_ratio": float(od_ratio),
                "recommended_action": (
                    "Switch to Negative Binomial regression or use "
                    "robust standard errors."
                ),
            },
        ).to_dict())
        write_json(run_root / "errors.json", {"issues": issue_dicts})
    zero_rate = od.get("zero_rate")
    if zero_rate is not None and float(zero_rate) > 0.5:
        od["zero_inflation_hint"] = (
            f"Outcome has {float(zero_rate):.0%} zeros. Consider comparing with "
            f"zero-inflated Poisson or hurdle model if zeros may arise from a separate process."
        )


_EXPOSURE_NAME_PATTERNS = (
    "exposure", "exposure_months", "policy_months", "person_years",
    "risk_time", "offset", "time_at_risk", "months", "years_at_risk",
)


def _detect_exposure_candidates(x_vars: list[str]) -> list[str]:
    """Detect column names that look like exposure/offset variables."""
    detected: list[str] = []
    for var in x_vars:
        var_lower = var.lower()
        if any(pat == var_lower or var_lower.endswith(f"_{pat}") or var_lower.startswith(f"{pat}_")
               for pat in _EXPOSURE_NAME_PATTERNS):
            detected.append(var)
    return detected


def _select_valid_exposure_col(
    frame: pd.DataFrame,
    exposure_candidates: list[str],
) -> str | None:
    """Return the first candidate that can validly be used as a GLM exposure."""
    for candidate in exposure_candidates:
        if candidate not in frame.columns:
            continue
        values = pd.to_numeric(frame[candidate], errors="coerce").dropna()
        if values.empty:
            continue
        if (values > 0).all():
            return candidate
    return None


def _check_rare_event(
    frame: pd.DataFrame,
    y: str,
    model_type: str,
    n_predictors: int,
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> dict[str, Any] | None:
    if model_type not in ("logit",):
        return None
    if y not in frame.columns:
        return None
    series = frame[y].dropna()
    if len(series) == 0:
        return None
    positive_rate = float(series.astype(float).mean())
    n_positive = int(positive_rate * len(series))
    epv = n_positive / max(n_predictors, 1)
    if positive_rate >= 0.05 and epv >= 5:
        return None
    reliability = "Low / exploratory only" if (positive_rate < 0.05 or epv < 5) else "Caution advised"
    issue_dicts.append(GuardrailIssue(
        Severity.WARNING if reliability.startswith("Low") else Severity.INFO,
        "RARE_EVENT_WARNING",
        f"The positive class for '{y}' accounts for {positive_rate:.1%} ({n_positive} of {len(series)}). "
        f"Events per predictor: {epv:.1f}. "
        f"Standard MLE Logit reliability is reduced. "
        f"Consider Firth penalized likelihood or exact logistic regression (not yet available in this MVP).",
        {"positive_rate": positive_rate, "n_positive": n_positive, "n_total": int(len(series)), "events_per_predictor": round(epv, 1)},
    ).to_dict())
    write_json(run_root / "errors.json", {"issues": issue_dicts})
    return {"reliability": reliability, "events_per_predictor": round(epv, 1), "positive_rate": positive_rate}


def _detect_binary_vars(frame: pd.DataFrame, x_vars: list[str]) -> set[str]:
    binary: set[str] = set()
    for var in x_vars:
        if var not in frame.columns:
            continue
        unique = sorted(frame[var].dropna().unique())
        if len(unique) == 2:
            try:
                if set(unique) <= {0, 1, 0.0, 1.0, True, False}:
                    binary.add(var)
            except Exception:
                pass
    return binary


def _check_binary_correlations(
    frame: pd.DataFrame,
    binary_vars: set[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    """Check for highly correlated binary X variables and add INFO/WARNING issues."""
    binary_list = sorted(binary_vars)
    for i in range(len(binary_list)):
        for j in range(i + 1, len(binary_list)):
            var1, var2 = binary_list[i], binary_list[j]
            if var1 not in frame.columns or var2 not in frame.columns:
                continue
            col1 = frame[var1].astype(float)
            col2 = frame[var2].astype(float)
            r = col1.corr(col2)
            abs_r = abs(r)
            if pd.isna(r):
                continue
            evidence: dict[str, Any] = {
                "var1": var1, "var2": var2, "correlation": round(float(r), 4),
            }
            if abs_r > _BINARY_CORRELATION_WARN:
                severity = Severity.WARNING
                message = (
                    f"{var1} and {var2} are strongly correlated (r={r:.2f}). "
                    f"This may inflate standard errors. "
                    f"Consider removing or combining one."
                )
                evidence["action_suggestions"] = [
                    "Keep both if they represent distinct concepts in your domain.",
                    "Compare models with each variable individually vs. both together.",
                    "If redundant, consider combining into a single indicator.",
                ]
            elif abs_r > _BINARY_CORRELATION_INFO:
                severity = Severity.INFO
                message = (
                    f"{var1} and {var2} are moderately correlated (r={r:.2f}). "
                    f"The model can still be used, but be cautious when interpreting "
                    f"individual binary coefficients."
                )
                evidence["action_suggestions"] = [
                    "Keep both if they represent distinct concepts in your domain.",
                    "Compare models with each variable individually vs. both together.",
                    "If redundant, consider combining into a single indicator.",
                ]
            else:
                continue
            issue = GuardrailIssue(severity, "BINARY_CORRELATION", message, evidence)
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})


def _check_treatment_proxy_correlations(
    frame: pd.DataFrame,
    x_vars: list[str],
    issue_dicts: list[dict[str, Any]],
    run_root: Path,
) -> None:
    treatment_vars = [
        var for var in x_vars
        if var in frame.columns and "treatment" in var.lower()
    ]
    proxy_vars = [
        var for var in x_vars
        if var in frame.columns
        and any(token in var.lower() for token in ("proxy", "interaction"))
    ]
    for treatment in treatment_vars:
        for proxy in proxy_vars:
            if treatment == proxy:
                continue
            pair = frame[[treatment, proxy]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(pair) < 3:
                continue
            r = pair[treatment].corr(pair[proxy])
            if pd.isna(r) or abs(r) <= _TREATMENT_PROXY_CORRELATION_WARN:
                continue
            issue = GuardrailIssue(
                Severity.WARNING,
                "TREATMENT_PROXY_CORRELATION",
                f"{treatment} and {proxy} are highly correlated (r={r:.3f}). "
                "Interpret their coefficients jointly; individual treatment-effect "
                "interpretation may be unstable.",
                {
                    "treatment": treatment,
                    "proxy": proxy,
                    "correlation": round(float(r), 4),
                    "action_suggestions": [
                        "Compare models with and without the proxy term.",
                        "Interpret treatment and proxy coefficients jointly.",
                    ],
                },
            )
            issue_dicts.append(issue.to_dict())
            write_json(run_root / "errors.json", {"issues": issue_dicts})
