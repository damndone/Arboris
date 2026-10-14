"""The words of a manual report: a readable first draft, and its values.

A manual report's prose belongs to the person writing it, but its numbers
come from the run's evidence. The draft therefore writes every number as a
value marker, ``[[v:<fact id>]]``: the reading view and every export replace
the marker with the fact's stored value, formatted by one rule, so editing the
prose can never change a number. The evidence snapshot itself is unchanged;
this module only decides how a draft reads (user review 3: the old draft
listed every fact as "metric · aic: 674 [[c:…]]", which nobody could read).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any, Iterable, Mapping

from .operation_presentation import operation_title

VALUE_MARKER = re.compile(r"\[\[v:([A-Za-z0-9._-]+)\]\]")
_MISSING = "—"


def _is_p_value(field: str) -> bool:
    return field.rsplit("/", 1)[-1] in {"p_value", "pvalue", "p_value_corrected"}


def format_number(value: float) -> str:
    """About four significant digits; large numbers keep their integer digits.

    Mirrors frontend/src/format/numbers.ts formatEstimate so a report reads the
    same on screen and in its exports.
    """
    if not math.isfinite(value):
        return _MISSING
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1000:
        return f"{value:,.0f}"
    if magnitude < 1e-4:
        mantissa, exponent = f"{value:.2e}".split("e")
        return f"{float(mantissa):g}e{int(exponent)}"
    return f"{float(f'{value:.4g}'):g}"


def format_p_value(value: float) -> str:
    if not math.isfinite(value):
        return _MISSING
    return "< 0.001" if value < 0.001 else f"{value:.3f}"


def format_fact_value(fact: Mapping[str, Any]) -> str:
    # Same words as frontend/src/manual/ReportEvidence.tsx factValue.
    value = fact.get("value")
    if value is None:
        return "Not reported"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return f"{value:,}" if abs(value) >= 1000 else str(value)
    if isinstance(value, float):
        return format_p_value(value) if _is_p_value(str(fact.get("field", ""))) else format_number(value)
    return str(value)


#: Markers name a fact by a prefix of its id: "f_" and ten hex digits keep
#: the text readable; a prefix must still match exactly one fact.
SHORT_ID = 12
MIN_PREFIX = 8


def short_id(fact_id: str) -> str:
    return fact_id[:SHORT_ID]


def resolve(marker: str, facts: Mapping[str, Mapping[str, Any]]) -> str | None:
    """The one fact id a marker names: exact, or a unique prefix; else None."""
    if marker in facts:
        return marker
    if len(marker) < MIN_PREFIX:
        return None
    matches = [fact_id for fact_id in facts if fact_id.startswith(marker)]
    return matches[0] if len(matches) == 1 else None


def render_values(text: str, facts: Mapping[str, Mapping[str, Any]]) -> str:
    """Replace every value marker with its fact's formatted value."""

    def value(match: re.Match[str]) -> str:
        fact_id = resolve(match.group(1), facts)
        return format_fact_value(facts[fact_id]) if fact_id else match.group(0)

    return VALUE_MARKER.sub(value, text)


def value_ids(text: str) -> list[str]:
    """The markers as written (possibly prefixes)."""
    return [match.group(1) for match in VALUE_MARKER.finditer(text)]


def resolved_ids(text: str, facts: Mapping[str, Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    """(fact ids the text shows, markers that name no single fact)."""
    shown, unknown = [], []
    for marker in value_ids(text):
        fact_id = resolve(marker, facts)
        (shown if fact_id else unknown).append(fact_id or marker)
    return list(dict.fromkeys(shown)), unknown


# ---------------------------------------------------------------------------
# Draft


class _Index:
    """Facts by the node they describe and their field."""

    def __init__(self, facts: Iterable[Mapping[str, Any]]):
        self.by_node: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
        for fact in facts:
            self.by_node[str(fact["source"]["node_key"])][str(fact["field"])] = fact

    def node(self, key: str) -> dict[str, Mapping[str, Any]]:
        return self.by_node.get(key, {})

    def graph_node(self, suffix: str) -> dict[str, Mapping[str, Any]]:
        """Graph facts are keyed '<head hash>::model:<id>'; merge every head's."""
        merged: dict[str, Mapping[str, Any]] = {}
        for key, fields in self.by_node.items():
            if key == suffix or key.endswith(f"::{suffix}"):
                merged.update(fields)
        return merged


def _v(fact: Mapping[str, Any] | None) -> str | None:
    return f"[[v:{short_id(str(fact['id']))}]]" if fact else None


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _roles(graph: Mapping[str, Mapping[str, Any]]) -> tuple[str | None, list[str]]:
    outcome, regressors = None, []
    for field, fact in sorted(graph.items()):
        match = re.fullmatch(r"param/e:role:(.+):([a-z_]+)/role", field)
        if not match:
            continue
        dropped = graph.get(field.removesuffix("/role") + "/dropped")
        if dropped and dropped.get("value") is True:
            continue
        if fact.get("value") == "outcome":
            outcome = match.group(1)
        elif match.group(1) not in regressors:
            regressors.append(match.group(1))
    return outcome, regressors


def _coefficient_lines(model: Mapping[str, Mapping[str, Any]]) -> list[str]:
    terms: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for field, fact in model.items():
        match = re.fullmatch(r"coefficient/(.+)/([a-z_]+)", field)
        if match:
            terms[match.group(1)][match.group(2)] = fact
    lines = []
    # Intercept last: the slopes are what a reader looks for first.
    for term in sorted(terms, key=lambda name: (name.lower() in {"intercept", "const", "_cons"}, list(terms).index(name))):
        stats = terms[term]
        if "estimate" not in stats:
            continue
        details = []
        if "std_error" in stats:
            details.append(f"SE {_v(stats['std_error'])}")
        if "ci_lower" in stats and "ci_upper" in stats:
            details.append(f"CI {_v(stats['ci_lower'])} to {_v(stats['ci_upper'])}")
        if "p_value" in stats:
            details.append(f"p {_v(stats['p_value'])}")
        suffix = f" ({'; '.join(details)})" if details else ""
        lines.append(f"- **{term}**: {_v(stats['estimate'])}{suffix}")
    return lines


_FIT = (
    ("metric/n_observations", "model/nobs", "Observations"),
    ("metric/r_squared", "model/r_squared", "R²"),
    ("metric/adjusted_r_squared", "model/adjusted_r_squared", "Adjusted R²"),
    ("metric/aic", None, "AIC"),
    ("metric/bic", None, "BIC"),
    ("metric/llf", None, "Log-likelihood"),
)


def _fit_line(graph: Mapping[str, Mapping[str, Any]], model: Mapping[str, Mapping[str, Any]]) -> str | None:
    parts = []
    for graph_field, model_field, label in _FIT:
        fact = graph.get(graph_field) or (model.get(model_field) if model_field else None)
        if fact is not None and fact.get("value") is not None:
            parts.append(f"{label} {_v(fact)}")
    return "Fit: " + " · ".join(parts) + "." if parts else None


def _test_line(fields: Mapping[str, Mapping[str, Any]]) -> str | None:
    operation = fields.get("post_estimation/operation")
    if operation is None:
        return None
    title = operation_title(f"postestimation.{operation['value']}") or str(operation["value"])
    statistic = fields.get("post_estimation/statistic")
    p_value = fields.get("post_estimation/p_value")
    distribution = fields.get("post_estimation/distribution")
    df_num, df_den = fields.get("post_estimation/df_num"), fields.get("post_estimation/df_den")
    terms = sorted({match.group(1) for field in fields if (match := re.fullmatch(r"post_estimation/constraints/\d+/terms/(.+)", field))})
    subject = f" of {_join(terms)}" if terms else ""
    parts = []
    if statistic is not None:
        name = str(distribution["value"]) if distribution and distribution.get("value") else "Statistic"
        if df_num is not None and df_den is not None:
            name = f"{name}({_v(df_num)}, {_v(df_den)})"
        elif df_num is not None:
            name = f"{name}({_v(df_num)})"
        parts.append(f"{name} = {_v(statistic)}")
    if p_value is not None:
        parts.append(f"p {_v(p_value)}")
    return f"- **{title}**{subject}: " + ", ".join(parts) + "." if parts else f"- **{title}**{subject}."


def draft_text(facts: list[Mapping[str, Any]], limitations: list[str]) -> str:
    """A first draft that reads like a results section, every number a marker."""
    index = _Index(facts)
    models = sorted(
        {key.removeprefix("model:") for key in index.by_node if key.startswith("model:")},
    )
    tests: dict[str, list[str]] = defaultdict(list)
    for key, fields in index.by_node.items():
        if key.startswith("workflow:") and "post_estimation/operation" in fields:
            owner = fields.get("post_estimation/model_id")
            line = _test_line(fields)
            if line:
                tests[str(owner["value"]) if owner else ""].append(line)

    # The report's title is its own field; the text starts with the models.
    lines: list[str] = []
    if not models:
        lines += ["No fitted model is recorded for this run. Add your notes here.", ""]
    for model_id in models:
        model = index.node(f"model:{model_id}")
        graph = index.graph_node(f"model:{model_id}")
        inference = model
        label = model.get("model/label")
        model_type = model.get("model/model_type")
        outcome, regressors = _roles(graph)
        heading = str(label["value"]) if label and label.get("value") else model_id
        lines += [f"## {heading}", ""]

        sentences = [f"Estimator: {_v(model_type) or model_id}."]
        if outcome:
            predictors = f"; predictors {_join([f'**{name}**' for name in regressors])}" if regressors else ""
            sentences.append(f"Outcome **{outcome}**{predictors}.")
        nobs = graph.get("metric/n_observations") or model.get("model/nobs")
        covariance = inference.get("inference/covariance_estimator")
        estimated = []
        if nobs is not None:
            estimated.append(f"on {_v(nobs)} observations")
        if covariance is not None:
            estimated.append(f"with {_v(covariance)} standard errors")
        if estimated:
            sentences.append("Estimated " + " ".join(estimated) + ".")
        sentence = " ".join(sentences)[:-1]
        lines += [sentence + ".", ""]

        coefficients = _coefficient_lines(model)
        if coefficients:
            level = model.get("inference/confidence_level")
            lines += [f"### Estimates{f' (CI at {_v(level)})' if level else ''}", "", *coefficients, ""]
        fit = _fit_line(graph, model)
        if fit:
            lines += [fit, ""]
        if tests.get(model_id):
            lines += ["### Tests", "", *tests.pop(model_id), ""]
    remaining = [line for group in tests.values() for line in group]
    if remaining:
        lines += ["## Other tests", "", *remaining, ""]
    # Limits are kept with the record and printed by the panel and exports.
    del limitations
    return "\n".join(lines).rstrip() + "\n"
