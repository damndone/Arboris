"""Model-results reading + issue-stream normalization.

Reads the ``model_results/*.json`` a run produced and reconciles the stored
guardrail issues with the final preprocessing state (e.g. surfacing
auto-dummy-coding as an INFO issue). Pure functions over a run directory and
plain dicts — no HTTP, no filesystem writes.

Extracted verbatim from ``api.py`` in v1.6.10 (D1 decomposition, Phase 2).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from ..artifacts import read_json
from ..domain import GuardrailIssue, Severity
from ..term_parser import is_q_quoted_dummy, parse_term


_OLS_RESULT_CONTRACT_RE = re.compile(r"^ols_result_contract_v(\d+)$")


def validate_result_contract(result: Mapping[str, object]) -> dict[str, object]:
    """Read and validate the additive OLS contract without label inference."""
    if not isinstance(result, Mapping):
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: result must be an object")
    version = result.get("contract_version")
    match = _OLS_RESULT_CONTRACT_RE.fullmatch(version) if isinstance(version, str) else None
    if match is None or int(match.group(1)) < 1:
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: missing or unsupported OLS contract")
    if result.get("model") != "ols" or result.get("model_type") not in {
        "ols",
        "ols_robust",
        "ols_clustered",
    }:
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: result is not an OLS result")
    stable_ids = result.get("stable_result_ids")
    candidates = result.get("candidate_result_ids")
    coefficients = result.get("coefficients")
    if (
        not isinstance(stable_ids, list)
        or not stable_ids
        or any(not isinstance(item, str) or not item for item in stable_ids)
        or len(set(stable_ids)) != len(stable_ids)
        or candidates != stable_ids
        or not isinstance(coefficients, Mapping)
    ):
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: unstable OLS result IDs")
    coefficient_ids = {
        coefficient.get("result_id")
        for coefficient in coefficients.values()
        if isinstance(coefficient, Mapping)
    }
    if coefficient_ids != set(stable_ids):
        raise ValueError("SOURCE_CONTRACT_UNSUPPORTED: coefficient IDs do not match result IDs")
    return dict(result)


def read_coefficient_by_result_id(
    result: Mapping[str, object], result_id: str
) -> dict[str, object] | None:
    """Resolve an OLS coefficient by its stored stable ID, never by display label."""
    validated = validate_result_contract(result)
    coefficients = validated["coefficients"]
    if not isinstance(coefficients, Mapping) or not isinstance(result_id, str):
        return None
    for coefficient in coefficients.values():
        if isinstance(coefficient, Mapping) and coefficient.get("result_id") == result_id:
            return dict(coefficient)
    return None


def read_model_results(run_root: Path) -> list[dict]:
    model_dir = run_root / "model_results"
    if not model_dir.is_dir():
        return []
    results: list[dict] = []
    for path in sorted(model_dir.glob("*.json")):
        data = read_json(path)
        if isinstance(data, dict) and isinstance(data.get("coefficients"), dict):
            results.append(data)
    return results


def _model_results(run_root: Path) -> list[dict]:
    """Compatibility wrapper for the existing HTTP route import."""

    return read_model_results(run_root)


def _normalize_issue_stream(errors: dict, model_results: list[dict]) -> dict:
    """Align legacy/stored issues with the final model preprocessing state."""
    issues = errors.get("issues", [])
    if not isinstance(issues, list):
        return {"issues": []}
    dummy_coded = _dummy_coded_columns(model_results)
    if not dummy_coded:
        return {"issues": issues}

    normalized: list[dict] = []
    emitted_auto: set[str] = set()
    for issue in issues:
        if not isinstance(issue, dict):
            normalized.append(issue)
            continue
        evidence = issue.get("evidence", {})
        column = evidence.get("column") if isinstance(evidence, dict) else None
        if issue.get("code") == "CATEGORICAL_CANDIDATE" and column in dummy_coded:
            if column not in emitted_auto:
                normalized.append(_auto_dummy_coded_issue(column))
                emitted_auto.add(column)
            continue
        normalized.append(issue)

    existing_auto = {
        issue.get("evidence", {}).get("column")
        for issue in normalized
        if isinstance(issue, dict)
        and issue.get("code") == "CATEGORICAL_AUTO_DUMMY_CODED"
        and isinstance(issue.get("evidence"), dict)
    }
    for column in sorted(dummy_coded - existing_auto - emitted_auto):
        normalized.append(_auto_dummy_coded_issue(column))
    return {"issues": normalized}


def _dummy_coded_columns(model_results: list[dict]) -> set[str]:
    columns: set[str] = set()
    for result in model_results:
        coefficients = result.get("coefficients", {})
        if not isinstance(coefficients, dict):
            continue
        for term in coefficients:
            if not isinstance(term, str):
                continue
            if is_q_quoted_dummy(term):
                columns.add(parse_term(term).source_id)
    return columns


def _auto_dummy_coded_issue(column: str) -> dict:
    return GuardrailIssue(
        Severity.INFO,
        "CATEGORICAL_AUTO_DUMMY_CODED",
        f"Column '{column}' was detected as categorical and automatically dummy-coded.",
        evidence={"column": column, "preprocessing": "dummy_coded"},
        affected_stage="data_cleaning",
        variables=[column],
        template_key="categorical_auto_dummy",
    ).to_dict()
