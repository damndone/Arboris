"""Fit a model family once per group (combinators/by_group.py).

Each group is fitted by the family's own handler, exactly as a single run
would fit it, under its own result id (``ols_1_g01``...), so each group keeps
its own result, inference kernel, stable ids and post-estimation. A group below
the check library's sample threshold, or whose fit fails, is recorded as not
estimable with the reason; nothing is dropped silently. The collection
envelope lists every group and lives under ``model_results/collections/``,
outside the directory readers scan for results.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ...artifacts import register_artifact, write_json
from ...combinators.by_group import (
    ByGroupRefusal,
    capability_for,
    group_member,
    plan_groups,
    semantics_for,
    too_small,
)
from ...contracts.model.result_collection import build_result_collection
from ..context import DataHandle

COLLECTION_PATH = "model_results/collections/by_group.json"
COLLECTION_ARTIFACT = "by_group_collection"
#: The group-difference tests on the pooled interacted model.
DIFFERENCES_PATH = "model_results/collections/by_group_differences.json"


def _python(value: Any) -> Any:
    return value.item() if isinstance(value, np.generic) else value


#: The indicator a domain fit uses to mark its group as the subpopulation.
_DOMAIN_INDICATOR = "__wb_by_group__"


def _group_rows(ctx: Any, frame: Any, mask: np.ndarray, semantics: str) -> tuple[Any, Any]:
    """The rows one group's fit sees, and the subpop declaration to restore.

    ``subset`` keeps the group's rows only. ``domain`` keeps every row and
    declares the group a subpopulation of the design, combined with any
    subpopulation the run already declared.
    """
    if semantics != "domain":
        return frame.loc[mask].copy(), None
    rows = frame.copy()
    rows[_DOMAIN_INDICATOR] = mask.astype(int)
    saved = ctx.artifacts.get("_survey_subpop")
    existing = str(saved or "").strip()
    ctx.artifacts["_survey_subpop"] = (
        f"({existing}) and {_DOMAIN_INDICATOR} == 1" if existing else f"{_DOMAIN_INDICATOR} == 1"
    )
    return rows, saved


def _binary_outcome(primary: dict[str, Any], family: str) -> bool:
    """Whether the family declares a binary outcome (its minimum also counts events)."""
    from ...contracts.model.result_envelope_registry import declaration_for

    try:
        declaration = declaration_for(str(primary.get("model_type") or family))
    except (KeyError, ValueError):
        return False
    return "outcome.binary" in getattr(declaration, "traits", frozenset())


def _events(fitted: Any) -> int | None:
    endog = getattr(getattr(fitted, "model", None), "endog", None)
    if endog is None:
        return None
    values = np.asarray(endog, dtype=float)
    ones = int((values == 1).sum())
    return min(ones, int(values.size) - ones)


def fit_by_group(
    handler: Any, ctx: Any, env: Any, request: dict[str, Any], *, design_declared: bool, kernel_for: Any = None,
) -> list[tuple[str, dict, Any]]:
    """Fit every group; return the estimated ones as (model_id, packet, fitted)."""
    from ...cleaning import normalize_column_name

    raw_column = str(request.get("column") or "").strip()
    if not raw_column:
        raise ByGroupRefusal("COLUMN_MISSING", "by-group execution needs the grouping column")
    column = normalize_column_name(raw_column)
    outcome, predictors = ctx.artifacts["_normalized_y"], list(ctx.artifacts["_normalized_x"])
    if column == outcome or column in predictors:
        raise ByGroupRefusal(
            "COLUMN_IN_MODEL",
            f"{raw_column} is in the model; a grouping column cannot also be the outcome or a predictor.",
        )
    family = capability_for(handler.model_type)
    semantics = semantics_for(family, design_declared=design_declared)
    frame = ctx.data.frame
    groups = plan_groups(frame, column)

    fits: list[tuple[str, dict, Any]] = []
    members: list[dict[str, Any]] = []
    estimated_groups = []
    for group in groups:
        group_id = f"{handler.model_id}_{group.slug}"
        rows, saved_subpop = _group_rows(ctx, frame, group.mask, semantics)
        ctx.artifacts["_model_id_override"] = group_id
        try:
            model_id, primary, fitted = handler.fit(
                ctx.with_data(DataHandle.of(rows, artifact_id=ctx.data.artifact_id,
                                            provenance=ctx.data.provenance)),
                env,
            )
        except (ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
            members.append(group_member(group, status="not_estimable", reason=f"the fit failed: {error}"))
            continue
        finally:
            ctx.artifacts.pop("_model_id_override", None)
            if semantics == "domain":
                ctx.artifacts["_survey_subpop"] = saved_subpop
        if semantics == "domain" and "survey_design" not in primary:
            raise ByGroupRefusal(
                "DESIGN_NOT_SUPPORTED",
                f"{family} does not compute a design-based variance, so it cannot be estimated by "
                "group as a domain of the sampling design.",
            )
        nobs = (primary.get("nobs_subpopulation") if semantics == "domain"
                else primary.get("nobs") if isinstance(primary.get("nobs"), int) else group.nobs)
        parameters = len(primary.get("coefficients") or {})
        reason = too_small(nobs, parameters, events=_events(fitted) if _binary_outcome(primary, family) else None)
        if reason is not None:
            recorded = ctx.artifacts.get("_inference_kernels")
            if isinstance(recorded, dict):
                recorded.pop(model_id, None)
            members.append(group_member(group, status="not_estimable", reason=reason, nobs=nobs))
            continue
        primary["by_group"] = {
            "column": raw_column,
            "key": group.key,
            "value": _python(group.value),
            "index": group.index,
            "n_groups": len(groups),
            "semantics": semantics,
            "collection": COLLECTION_PATH,
        }
        fits.append((model_id, primary, fitted))
        estimated_groups.append(group)
        members.append(group_member(group, status="estimated", result_ref=f"model_results/{model_id}.json",
                                    nobs=nobs))

    # Every group's result names the groups that could not be estimated, so no
    # reader of one group can miss that the comparison is incomplete.
    not_estimable = [
        {"key": m["key"], "nobs": m["nobs"], "reason": m["reason"]}
        for m in members if m["status"] == "not_estimable"
    ]
    differences = (
        _group_differences(handler, ctx, env, frame, estimated_groups, kernel_for, semantics)
        if kernel_for is not None and len(estimated_groups) >= 2
        else {"status": "not_available", "reason": "fewer than two groups were estimated"}
    )
    for _, primary, _ in fits:
        primary["by_group"]["not_estimable"] = not_estimable
        primary["by_group"]["difference_tests"] = differences
    collection = build_result_collection(
        combinator="by_group",
        capability=family,
        parameters={"column": raw_column, "semantics": semantics, "n_groups": len(groups)},
        members=members,
        pooled={"method": "group_differences", "result_ref": DIFFERENCES_PATH},
    )
    run_root = Path(env.run_root)
    write_json(run_root / DIFFERENCES_PATH, differences)
    path = run_root / COLLECTION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, collection)
    register_artifact(run_root, COLLECTION_ARTIFACT, path, "metadata", "econometrics",
                      [model_id for model_id, _, _ in fits] or [ctx.data.artifact_id])
    ctx.artifacts["_by_group"] = {"column": raw_column, "collection": COLLECTION_PATH,
                                  "estimated": len(fits), "n_groups": len(groups)}
    if not fits:
        raise ByGroupRefusal(
            "NO_GROUP_ESTIMABLE",
            "no group could be estimated: " + "; ".join(f"{m['key']}: {m['reason']}" for m in members),
        )
    return fits


def _group_differences(
    handler: Any, ctx: Any, env: Any, frame: Any, estimated: list[Any], kernel_for: Any, semantics: str = "subset",
) -> dict[str, Any]:
    """Wald tests of group differences on the fully interacted pooled model.

    The pooled sample of the estimated groups is fitted with an indicator for
    every group but the first and its product with every regressor, by the same
    family, covariance and handler as the groups themselves; the tests read its
    inference kernel (post-estimation, step 2). "all" asks whether the groups'
    coefficients are the same (a Chow test); one test per regressor asks whether
    that regressor's effect is the same in every group.
    """
    from ...postestimation import PostestimationRefusal
    from ...postestimation.registry import run_operation

    # The regressors the groups were fitted on: the model's own, less an exposure
    # offset, which enters with a fixed coefficient and is not compared.
    predictors = [name for name in ctx.artifacts["_normalized_x"] if name != getattr(ctx, "exposure_col", None)]
    categorical = sorted(set(ctx.artifacts.get("_categorical_vars") or ()) & set(predictors))
    if categorical:
        return {"status": "not_available",
                "reason": f"the model has categorical predictors ({', '.join(categorical)}); the "
                          "group-difference test is offered for numeric predictors only so far"}
    in_pooled = np.zeros(len(frame), dtype=bool)
    for group in estimated:
        in_pooled |= group.mask
    # Under a design the pooled groups are one domain of the full sample.
    pooled, saved_subpop = _group_rows(ctx, frame, in_pooled, semantics)
    terms: dict[str, list[str]] = {"all": [], **{name: [] for name in predictors}}
    for group in estimated[1:]:
        indicator = f"by_{group.slug}"
        while indicator in pooled.columns:
            indicator = f"_{indicator}"
        pooled[indicator] = (group.mask[in_pooled] if semantics != "domain" else group.mask).astype(float)
        terms["all"].append(indicator)
        for name in predictors:
            product = f"{indicator}_x_{name}"
            pooled[product] = pooled[indicator] * pooled[name]
            terms["all"].append(product)
            terms[name].append(product)
    added = terms["all"]
    model_id = f"{handler.model_id}_groups"
    saved = {key: ctx.artifacts.get(key) for key in ("_normalized_x", "_poisson_x", "_model_id_override")}
    try:
        ctx.artifacts["_normalized_x"] = list(ctx.artifacts["_normalized_x"]) + added
        if saved["_poisson_x"] is not None:
            ctx.artifacts["_poisson_x"] = list(saved["_poisson_x"]) + added
        ctx.artifacts["_model_id_override"] = model_id
        fitted_id, packet, fitted = handler.fit(
            ctx.with_data(DataHandle.of(pooled, artifact_id=ctx.data.artifact_id, provenance=ctx.data.provenance)),
            env,
        )
        kernel = kernel_for(fitted_id, packet, fitted)
    except (ValueError, ArithmeticError, np.linalg.LinAlgError) as error:
        return {"status": "not_available", "reason": f"the pooled interaction model could not be fitted: {error}"}
    finally:
        for key, value in saved.items():
            if value is None:
                ctx.artifacts.pop(key, None)
            else:
                ctx.artifacts[key] = value
        if semantics == "domain":
            ctx.artifacts["_survey_subpop"] = saved_subpop
    from ...orchestrator import _write_inference_kernel

    _write_inference_kernel(Path(env.run_root), kernel, inputs=[ctx.data.artifact_id])
    tests = []
    for name, names in terms.items():
        label = ("all coefficients equal across groups" if name == "all"
                 else f"effect of {name} equal across groups")
        try:
            result = run_operation("wald", [kernel], {"constraints": [{"terms": {t: 1}, "value": 0} for t in names]})
        except PostestimationRefusal as refusal:
            tests.append({"name": name, "label": label, "status": "not_available", "reason": refusal.message})
            continue
        tests.append({
            "name": name, "label": label, "status": "estimated", "terms": names,
            "statistic": result["statistic"], "df_num": result["df_num"], "df_den": result.get("df_den"),
            "p_value": result["p_value"], "distribution": result.get("distribution"),
            **({"adjustment": result["adjustment"]} if result.get("adjustment") else {}),
        })
    return {
        "status": "estimated",
        "method": "Wald test on the pooled model with the group fully interacted with every regressor",
        "reference_group": estimated[0].key,
        "model": model_id,
        "nobs": packet.get("nobs"),
        "covariance_estimator": kernel.get("covariance_estimator"),
        "tests": tests,
    }
