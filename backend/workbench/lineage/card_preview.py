"""Local graph card presentation for persisted, run-owned evidence."""

from __future__ import annotations

import json
import math
import re
import stat
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ..estimation_engine import engine_provenance
from ..formula_terms import public_term

_SMALL_JSON_LIMIT = 256 * 1024
_MODEL_JSON_LIMIT = 2 * 1024 * 1024
_MODEL_ID = re.compile(r"[\w.-]{1,128}")
_FAMILY_TITLES = {
    "iv_2sls": "IV (2SLS)",
    "ols": "OLS",
    "panel_ols": "Panel OLS",
    "did": "Difference-in-differences",
    "cox_ph": "Cox proportional hazards",
}
_INTERCEPTS = {"intercept", "(intercept)", "const", "constant"}


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _read_object(run_root: Path, relative: str, limit: int = _SMALL_JSON_LIMIT) -> dict:
    """Read at most one small regular file at its canonical run-owned path."""
    try:
        path = run_root.resolve(strict=True) / relative
        if path.resolve(strict=True) != path:
            return {}
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return {}
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
        if len(payload) <= limit:
            return _object(json.loads(payload.decode("utf-8")))
    except (OSError, ValueError, RecursionError):
        pass
    return {}


def _source_columns(run_root: Path, filename: str, inputs: dict) -> list[tuple[str, str]]:
    metadata = _read_object(run_root, "staged/metadata_registry.json")
    form = _object(inputs.get("form"))
    labels = _object(_object(form.get("labels")).get("variable_labels"))
    columns = {
        name: _text(labels.get(name), 80) for column in _list(metadata.get("columns"))
        if isinstance(column, dict) and column.get("source_file") == filename
        and isinstance(name := column.get("name"), str) and name.strip()
    }
    return sorted(columns.items(), key=lambda item: not item[1])[:3]


def _raw_card(run_root: Path, node: dict, manifest: dict, inputs: dict) -> dict:
    recorded = {
        path for entry in _list(manifest.get("lineage"))
        if isinstance(entry, dict) and isinstance(source := entry.get("source"), str)
        and (path := Path(source)).is_absolute() and entry.get("artifact_id") == f"raw_{path.name}"
    }
    snapshots = set()
    index = _read_object(run_root, "artifacts_index.json")
    for item in _list(index.get("artifacts")):
        artifact = _object(item)
        artifact_id = artifact.get("artifact_id")
        if artifact.get("artifact_type") == "raw_data" and isinstance(artifact_id, str) and artifact_id.startswith("raw_"):
            name = artifact_id.removeprefix("raw_")
            if artifact.get("path") == f"raw_snapshot/{name}":
                snapshots.add(name)
    filename = _object(inputs.get("upload")).get("filename")
    if filename is None:
        candidates = {path.name for path in recorded} | snapshots
        if len(candidates) == 1:
            filename = next(iter(candidates))
    if not isinstance(filename, str) or filename in {"", ".", ".."} or Path(filename).name != filename:
        filename = ""

    path_line = ""
    detail = ["Original local path not recorded"]
    paths = [path for path in recorded if path.name == filename]
    if len(paths) == 1:
        source = paths[0]
        if source.parent == run_root.absolute() / "_uploads":
            detail.append(f"Recorded upload staging path: {source}")
        else:
            folder = str(source.parent)
            if len(folder) > 34:
                folder = f"…/{_text(source.parent.name, 32)}"
            path_line = f"Folder: {folder}"
            detail = [f"Recorded input path: {source}"]
    if filename in snapshots:
        relative = f"raw_snapshot/{filename}"
        try:
            snapshot = run_root.resolve(strict=True) / relative
            if snapshot.resolve(strict=True) == snapshot and snapshot.is_file():
                detail.append(f"Run snapshot: {snapshot}")
                if not path_line:
                    path_line = f"Snapshot: {_text(relative, 100)}"
        except (OSError, ValueError):
            pass

    summary = _text(node.get("summary"), 80).removeprefix("Raw: ")
    lines = [path_line or "Original folder not recorded"]
    if summary:
        lines.append(summary)
    if filename and (columns := _source_columns(run_root, filename, inputs)):
        lines.append("Columns: " + ", ".join(_text(label or name, 28) for name, label in columns))
        detail.append("Example columns: " + ", ".join(
            f"{_text(name, 80)} ({label})" if label else _text(name, 80) for name, label in columns
        ))
    return {
        "title": _text(filename, 100) or "Raw data",
        "lines": lines,
        "detail": "\n".join(detail),
    }


def _clean_card(run_root: Path, node: dict) -> dict:
    actions = _read_object(run_root, "processed/cleaning_actions.json").get("actions")
    summary = _text(node.get("summary"), 80).removeprefix("Cleaned: ")
    lines = [summary] if summary else []
    if not isinstance(actions, list):
        return {"title": "Cleaned data", "lines": [*lines, "Cleaning log unavailable"]}

    normalized: set[tuple[str, str]] = set()
    disambiguated: set[tuple[str, str]] = set()
    numeric: list[str] = []
    dates: list[str] = []
    kept_duplicates = 0
    removed_duplicates = 0
    other = 0
    for action in actions:
        record = _object(action)
        kind = record.get("action")
        if kind == "normalize_column_names":
            normalized.update(
                (before, after) for before, after in _object(record.get("details")).items()
                if isinstance(after, str) and before != after
            )
        elif kind == "deduplicate_column_names":
            for change in _list(record.get("details")):
                before, after = _object(change).get("from"), _object(change).get("to")
                if isinstance(before, str) and isinstance(after, str) and before != after:
                    disambiguated.add((before, after))
        elif kind == "coerce_to_numeric":
            column = _text(record.get("column"), 44)
            dtype = _text(record.get("original_dtype"), 32)
            rate = record.get("conversion_rate")
            conversion = [f"from {dtype}"] if dtype else []
            if type(rate) in (int, float) and 0 <= rate <= 1:
                conversion.append(f"{rate:.2%} convertible")
            if column:
                numeric.append(f"{column} ({', '.join(conversion)})" if conversion else column)
            else:
                other += 1
        elif kind == "parse_date_candidate":
            if column := _text(record.get("column"), 44):
                dates.append(column)
            else:
                other += 1
        elif kind == "duplicate_rows_found" and record.get("kept") is True and type(record.get("rows")) is int:
            kept_duplicates += max(record["rows"], 0)
        elif kind == "drop_duplicate_rows" and type(record.get("rows_dropped")) is int:
            removed_duplicates += max(record["rows_dropped"], 0)
        else:
            other += 1

    changes = [
        f"{count} {label}" for count, label in (
            (len(normalized | disambiguated), "renamed"),
            (len(numeric), "converted to numeric"), (len(dates), "parsed as dates"),
            (other, "other log entries"),
        ) if count
    ]
    if changes or not removed_duplicates:
        lines.append(" · ".join(changes) if changes else "No recorded changes")
    row_evidence = [f"{count} duplicate rows {action}" for count, action in (
        (kept_duplicates, "kept"), (removed_duplicates, "removed"),
    ) if count]
    if row_evidence:
        lines.append(" · ".join(row_evidence))
    detail = [*lines]
    for label, pairs in (("Normalized", normalized - disambiguated), ("Disambiguated", disambiguated)):
        if pairs:
            examples = [f"{_text(before, 32)} → {_text(after, 32)}" for before, after in sorted(pairs)[:3]]
            detail.append(f"{label}: " + ", ".join(examples))
    for label, columns in (("Converted to numeric", numeric), ("Parsed as dates", dates)):
        if columns:
            detail.append(f"{label}: " + ", ".join(columns[:3]))
    return {"title": "Cleaned data", "lines": lines, "detail": "\n".join(detail)}


def _model_id(node_id: str, node: dict) -> str | None:
    model_id = node_id.removeprefix("model:")
    if (
        node.get("kind") == "model"
        and model_id != node_id
        and _MODEL_ID.fullmatch(model_id)
        and node.get("payload_ref") == f"model_results/{model_id}.json"
    ):
        return model_id
    return None


def _family_title(model: dict, fallback: str) -> str:
    family = _text(model.get("model_type"), 80)
    return _FAMILY_TITLES.get(family, family.replace("_", " ").capitalize() or fallback)


def _imputation_detail(run_root: Path, model_id: str) -> list[str]:
    summary = _read_object(run_root, "imputation_summary.json")
    output_ids = _list(summary.get("output_artifacts"))
    if summary.get("status") != "completed" or summary.get("method") != "mice" or not output_ids:
        return []
    index = _read_object(run_root, "artifacts_index.json")
    records = [
        item for item in _list(index.get("artifacts"))
        if isinstance(item, dict) and item.get("artifact_id") == model_id
        and item.get("path") == f"model_results/{model_id}.json"
    ]
    if len(records) != 1 or not all(item in _list(records[0].get("inputs")) for item in output_ids):
        return []
    detail = [f"Imputation before fitting: MICE ({len(output_ids)} completed "
              f"{'dataset' if len(output_ids) == 1 else 'datasets'})"]
    columns = [_text(column, 48) for column in _list(summary.get("imputed_columns"))[:8]]
    if columns:
        detail.append("Imputed columns: " + ", ".join(columns))
    return detail


def _model_card(run_root: Path, node: dict, manifest: dict, model_id: str | None, model: dict) -> dict:
    title = _family_title(model, _text(node.get("display_label"), 80) or "Model")
    if not model_id or not model:
        summary = _text(node.get("summary"), 80)
        return {"title": title, "lines": [line for line in (summary, "Model evidence unavailable") if line]}
    nobs = model.get("nobs")
    sample = f"n={nobs:,}" if type(nobs) is int and 0 < nobs < 10**15 else "n unavailable"
    outcome = _text(model.get("y_column"), 28)
    routing = _object(manifest.get("model_routing"))
    if not outcome and model_id and routing.get("effective_model_id") == model_id:
        outcome = _text(routing.get("current_y") or manifest.get("y"), 28)
    covariance = _text(model.get("covariance_estimator"), 42)
    if not covariance:
        kernel = _read_object(run_root, f"model_results/inference_kernels/{model_id}.json", _MODEL_JSON_LIMIT)
        if kernel.get("model_id") == model_id:
            covariance = _text(kernel.get("covariance_estimator"), 42)
    receipt = engine_provenance(model) or {}
    engine = _text(model.get("engine") or receipt.get("used"), 32)
    fallback = receipt.get("requested") == "fast" and receipt.get("used") == "reference"
    lines = [
        f"{sample} · y={outcome}" if outcome else f"{sample} · outcome unavailable",
        f"Covariance: {covariance}" if covariance else "Covariance unavailable",
        (engine + (" · fallback" if fallback else "")) if engine else "Engine unavailable",
    ]
    detail = [*lines, *_imputation_detail(run_root, model_id)]
    if fallback:
        detail.append("Fast requested; reference used.")
        if reason := _text(receipt.get("reason"), 340):
            detail.append(reason)
    return {"title": title, "lines": lines, "detail": "\n".join(detail)}


def _number(value: Any) -> float | None:
    if type(value) not in (float, int):
        return None
    try:
        return float(value) if math.isfinite(value) else None
    except OverflowError:
        return None


_REPORT_LEVELS = (0.90, 0.95, 0.99)
_REPORT_MAX_TERMS = 300


def _report_default_term(model: dict, coefficients: dict, model_key: str, nodes: dict, edges: list) -> tuple[str | None, str]:
    primary = _object(model.get("primary_estimand"))
    if primary:
        result_id, term = primary.get("result_id"), primary.get("term")
        if isinstance(result_id, str) and result_id:
            matches = [key for key, value in coefficients.items() if _object(value).get("result_id") == result_id]
            if len(matches) == 1 and (term is None or term == matches[0]):
                return matches[0], "Recorded primary coefficient"
        elif "result_id" not in primary and isinstance(term, str) and term in coefficients:
            return term, "Recorded primary coefficient"
        return None, "The recorded primary coefficient is unavailable. Choose a saved coefficient."

    iv = model.get("model_type") == "iv_2sls"
    focal = {
        source.removeprefix("var:").removesuffix(":cleaned")
        for edge in edges if edge.get("target_id") == model_key and edge.get("op") == "enters_as_focal"
        and isinstance(source := edge.get("source_id"), str)
        and source.startswith("var:") and source.endswith(":cleaned")
        and _object(nodes.get(source)).get("kind") == "variable"
        and _object(edge.get("params")).get("source") == ("_iv_endog" if iv else "focal_x")
        and _object(edge.get("params")).get("dropped") is not True
    }
    preferred = next((term for term in coefficients if public_term(term) in focal), None)
    if preferred is not None:
        return preferred, "First saved endogenous coefficient" if iv else "First saved focal coefficient"
    term = next((term for term in coefficients if term.casefold() not in _INTERCEPTS), None)
    return (term, "First saved non-intercept coefficient") if term is not None else (
        next(iter(coefficients)), "First saved coefficient",
    )


def _report_saved_interval(model: dict, row: dict) -> dict | None:
    lower, upper = _number(row.get("ci_lower")), _number(row.get("ci_upper"))
    if lower is None or upper is None or lower > upper:
        return None
    evidence = _object(model.get("covariance_evidence"))
    level = row.get("confidence_level", model.get("confidence_level", evidence.get("confidence_level")))
    if level is None and model.get("model_type") == "iv_2sls" and model.get("engine") in ("linearmodels", "arboris-engine"):
        level = 0.95  # Both IV producers persist conf_int() at its default level.
    level = _number(level)
    return {"level": level if level is not None and 0 < level < 1 else None, "lower": lower, "upper": upper}


def _report_inference(run_root: Path, model_id: str, model: dict) -> tuple[dict, str]:
    """Admit only known saved Wald producers and their matching v1 kernel."""
    from ..contracts.model.inference_kernel import declared_weights, validate_inference_kernel

    family = model.get("model_type")
    iv = family == "iv_2sls" and model.get("engine") in ("linearmodels", "arboris-engine")
    ols = model.get("contract_version") == "ols_result_contract_v1" and family in ("ols", "ols_robust", "ols_clustered", "ols_hac")
    if type(model.get("schema_version")) is not int or model["schema_version"] != 1 or not (iv or ols):
        return {}, "This saved model does not declare a supported coefficient interval method."
    kernel = _read_object(run_root, f"model_results/inference_kernels/{model_id}.json", _MODEL_JSON_LIMIT)
    if (kernel.get("model_id") != model_id or kernel.get("nobs") != model.get("nobs")
        or (kernel.get("model_type") != family and not (ols and kernel.get("model_type") == "ols"))):
        return {}, "A matching saved inference kernel is unavailable."
    try:
        validate_inference_kernel(kernel)
    except (ValueError, TypeError, OverflowError):
        return {}, "The saved inference kernel is invalid."
    if kernel["weights"] != "none" or declared_weights(model) != "none":
        return {}, "Alternate confidence levels for weighted fits are unavailable in this preview."
    if "coef_vcov" not in kernel["interfaces"]:
        return {}, "The saved kernel does not contain coefficient covariance."

    distribution = kernel["reference_distribution"]
    df = _number(kernel["df_resid"]) if distribution == "t" else None
    df_method = kernel["df_method"]
    if distribution == "t" and (df is None or df <= 0 or df_method not in {"residual", "clusters_minus_one"}
                               or (df_method == "clusters_minus_one" and df != (kernel["n_clusters"] or 0) - 1)):
        return {}, "The saved t reference lacks verified degrees of freedom."
    if distribution == "z" and df_method != "asymptotic":
        return {}, "The saved normal reference does not have an asymptotic inference declaration."
    if ols:
        evidence = _object(model.get("covariance_evidence"))
        if evidence.get("confidence_interval_method") != ("t" if distribution == "t" else "normal_z") or (
            distribution == "t" and _number(evidence.get("effective_df")) != df
        ):
            return {}, "The saved coefficient interval method differs from the inference kernel."
    covariance = model.get("covariance_estimator")
    if isinstance(covariance, str) and covariance.casefold() != _text(kernel["covariance_estimator"], 128).casefold():
        return {}, "The saved covariance estimator differs from the inference kernel."

    names, covariance_names = kernel["param_names"], kernel["vcov_param_names"]
    if len(set(names)) != len(names) or len(set(covariance_names)) != len(covariance_names):
        return {}, "The saved inference kernel has ambiguous coefficient names."
    from scipy import stats

    reference = stats.t(df) if df is not None else stats.norm
    return {
        "distribution": distribution, **({"df": df} if df is not None else {}),
        "params": dict(zip(names, kernel["params"])),
        "variances": {name: kernel["vcov"][i][i] for i, name in enumerate(covariance_names)},
        "critical": {level: float(reference.ppf(0.5 + level / 2)) for level in _REPORT_LEVELS},
    }, ""


def _report_coefficient(model: dict, term: str, row: dict, inference: dict, reason: str) -> dict:
    estimate, pvalue = _number(row.get("estimate")), _number(row.get("p_value"))
    saved = _report_saved_interval(model, row)
    intervals = []
    if inference:
        beta = _number(inference["params"].get(term))
        variance = _number(inference["variances"].get(term))
        se = math.sqrt(variance) if variance is not None and variance > 0 else None
        saved_se = _number(row.get("std_error"))
        if (beta is None or estimate != beta or se is None or saved_se is None
            or not math.isclose(se, saved_se, rel_tol=1e-12, abs_tol=0)):
            reason = "No matching estimate and positive coefficient variance are recorded for this term."
        else:
            for level, critical in inference["critical"].items():
                lower, upper = beta - critical * se, beta + critical * se
                if math.isfinite(lower) and math.isfinite(upper):
                    intervals.append({"level": level, "lower": lower, "upper": upper})
            if saved is not None:
                # Check the declared method against the saved interval, which stays authoritative.
                matching = next((item for item in intervals if item["level"] == saved["level"]), None)
                if not matching or not all(math.isclose(matching[key], saved[key], rel_tol=1e-12, abs_tol=0)
                                           for key in ("lower", "upper")):
                    intervals = []
                    reason = "The saved interval cannot be verified against the recorded reference distribution."
            if not intervals and not reason:
                reason = "The recorded inference does not yield a finite interval."
    return {
        "term": term, "label": public_term(term), "estimate": estimate,
        "p_value": pvalue if pvalue is not None and 0 <= pvalue <= 1 else None,
        "saved_interval": saved, "intervals": intervals,
        **({"interval_unavailable": reason} if reason else {}),
    }


def _report_card(
    run_root: Path, report_id: str, nodes: dict, edges: list, load_model: Callable[[str], tuple[str | None, dict]],
) -> dict:
    unavailable = {"title": "Report", "lines": ["Effect evidence unavailable"]}
    bindings = [edge.get("source_id") for edge in edges
                if edge.get("target_id") == report_id and edge.get("op") == "render_report"]
    if len(bindings) != 1 or not isinstance(bindings[0], str):
        return {**unavailable, "detail": "No unique model is linked to this report in this run."}
    model_key = bindings[0]
    model_id, model = load_model(model_key)
    if not model_id or not model:
        return {**unavailable, "detail": "The linked model result is unavailable in this run."}
    title = f"{_family_title(model, 'Model')} results"
    coefficients = _object(model.get("coefficients"))
    if not coefficients:
        return {**unavailable, "title": title, "detail": "The linked model has no saved coefficient."}
    term, selection = _report_default_term(model, coefficients, model_key, nodes, edges)
    inference, reason = _report_inference(run_root, model_id, model) if len(coefficients) <= _REPORT_MAX_TERMS else ({}, "")
    report = None
    if len(coefficients) <= _REPORT_MAX_TERMS:
        report = {
            "model_id": model_id, "default_term": term,
            "coefficients": [_report_coefficient(model, key, _object(row), inference, reason) for key, row in coefficients.items()],
            **{key: inference[key] for key in ("distribution", "df") if key in inference},
        }
        if len(json.dumps(report, ensure_ascii=True, allow_nan=False).encode("ascii")) > _SMALL_JSON_LIMIT:
            report = None
    size_note = "" if report else " The full coefficient list exceeds the preview limit. Open the linked model result table."
    extra = {"report": report} if report else {}
    if term is None:
        line = "Choose a coefficient in the report details" if report else "Coefficient list exceeds the preview limit"
        return {"title": title, "lines": [line], "detail": selection + size_note, **extra}

    value = _object(coefficients[term])
    estimate = _number(value.get("estimate"))
    pvalue = _number(value.get("p_value"))
    # Common regression serializers store p to six decimals.
    near_threshold = pvalue is not None and abs(pvalue - 0.05) <= 0.0000005
    if pvalue is None or not 0 <= pvalue <= 1:
        significance = "p unavailable"
    elif near_threshold:
        significance = "p≈.05"
    else:
        significance = "Significant" if pvalue < 0.05 else "Not significant"
    label = _text(public_term(term), 12)
    effect = f"{estimate:.4g}" if estimate is not None else "unavailable"
    saved = _report_saved_interval(model, value)
    interval = "CI unavailable"
    if saved:
        ci_label = f"{saved['level']:.0%} CI" if saved["level"] is not None else "CI"
        interval = f"{ci_label} [{saved['lower']:.4g}, {saved['upper']:.4g}]"
    detail = (
        f"{selection}: {_text(public_term(term), 96)}. "
        f"Showing one of {len(coefficients)} saved coefficients. Significance uses the saved p at the 5% level for this coefficient only."
    )
    if near_threshold:
        detail += " Saved p is at the threshold and may be rounded."
    elif significance == "Not significant":
        detail += " This does not establish that the association is zero."
    return {"title": title, "lines": [f"{label} {effect} · {significance}", interval], "detail": detail + size_note, **extra}


def build_card_previews(
    run_root: Path, graph: dict, manifest: dict, inputs: dict, node_ids: Iterable[str],
) -> dict[str, dict]:
    """Build presentation-only summaries for the requested run-local graph nodes."""
    nodes = _object(graph.get("nodes"))
    edges = [edge for edge in _object(graph.get("edges")).values() if isinstance(edge, dict)]
    models: dict[str, tuple[str | None, dict]] = {}

    def load_model(node_id: str) -> tuple[str | None, dict]:
        if node_id not in models:
            model_id = _model_id(node_id, _object(nodes.get(node_id)))
            result = _read_object(run_root, f"model_results/{model_id}.json", _MODEL_JSON_LIMIT) if model_id else {}
            models[node_id] = model_id, result if result.get("model_id") == model_id else {}
        return models[node_id]

    previews = {}
    for node_id in dict.fromkeys(node_ids):
        node = _object(nodes.get(node_id))
        kind = node.get("kind")
        if kind == "dataset_stage" and node_id in {"stage:raw", "stage:source"}:
            previews[node_id] = _raw_card(run_root, node, manifest, inputs)
        elif kind == "dataset_stage" and node_id == "stage:cleaned":
            previews[node_id] = _clean_card(run_root, node)
        elif kind == "model":
            previews[node_id] = _model_card(run_root, node, manifest, *load_model(node_id))
        elif kind == "report":
            previews[node_id] = _report_card(run_root, node_id, nodes, edges, load_model)
    return previews
