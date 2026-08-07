"""The registry that replaced `result_shape`'s closed enum.

Until v1.8.7 a model family's output had to be one of three shapes, checked
against a literal set.  Anything whose result was not coefficients, an effect
estimate or an event study simply could not be registered -- factor loadings,
reliability coefficients, cluster assignments and discriminant functions were
blocked by a three-element tuple rather than by any real constraint.

Opening the point without also declaring payloads would have re-opened the
artifact-schema debt, where consumers guess a packet's contents from its
`artifact_type`.  v1.8.6 settled that with a minimal payload gate, and the same
gate applies here: a shape declares a minimal schema and a version, so Table,
Report, Compare and the Agent negotiate rather than guess.

This registry deliberately does not validate payloads against their schemas --
that is the consumer's job at read time.  It guarantees only that a declared
shape *has* a schema to negotiate against.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from threading import RLock


class ResultShapeError(ValueError):
    """A shape declaration that cannot be admitted."""


@dataclass(frozen=True)
class ResultShapeDeclaration:
    name: str
    payload_schema: Mapping[str, object]
    payload_version: str
    description: str = ""


_LOCK = RLock()
_REGISTRY: dict[str, ResultShapeDeclaration] = {}


def register_result_shape(
    name: str,
    *,
    payload_schema: Mapping[str, object] | None,
    payload_version: str,
    description: str = "",
) -> ResultShapeDeclaration:
    """Declare a result shape and the minimal schema its payload satisfies."""
    if not name or not isinstance(name, str):
        raise ResultShapeError("result shape name must be a non-empty string")
    if payload_schema is None or not isinstance(payload_schema, Mapping) or not payload_schema:
        raise ResultShapeError(
            f"result shape {name!r} must declare a non-empty payload schema; "
            "without one consumers are back to guessing from artifact_type"
        )
    if not payload_version or not isinstance(payload_version, str):
        raise ResultShapeError(f"result shape {name!r} must declare a payload version")

    declaration = ResultShapeDeclaration(
        name=name,
        payload_schema=dict(payload_schema),
        payload_version=payload_version,
        description=description,
    )
    with _LOCK:
        existing = _REGISTRY.get(name)
        if existing is not None and existing != declaration:
            raise ResultShapeError(
                f"result shape {name!r} is already declared with different terms"
            )
        _REGISTRY[name] = declaration
    return declaration


def is_registered(name: str) -> bool:
    with _LOCK:
        return name in _REGISTRY


def get_result_shape(name: str) -> ResultShapeDeclaration:
    with _LOCK:
        try:
            return _REGISTRY[name]
        except KeyError as exc:
            raise ResultShapeError(f"result shape {name!r} is not declared") from exc


def registered_result_shapes() -> dict[str, ResultShapeDeclaration]:
    with _LOCK:
        return dict(_REGISTRY)


# The three shapes that used to be the whole enum.  They are declarations now,
# on exactly the same footing as anything registered later -- which is what makes
# "one declaration per family" true rather than aspirational.
register_result_shape(
    "coefficient_intervals",
    payload_schema={
        "type": "object",
        "required": ["coefficients"],
        "properties": {"coefficients": {"type": "object"}},
    },
    payload_version="1.0",
    description="Point estimates with standard errors and confidence intervals.",
)
register_result_shape(
    "effect_estimate_bundle",
    payload_schema={
        "type": "object",
        "required": ["effects"],
        "properties": {"effects": {"type": "object"}},
    },
    payload_version="1.0",
    description="Grouped causal effect estimates with their aggregation.",
)
register_result_shape(
    "event_study_bundle",
    payload_schema={
        "type": "object",
        "required": ["event_study"],
        "properties": {"event_study": {"type": "object"}},
    },
    payload_version="1.0",
    description="Event-time effect paths with pre-trend evidence.",
)

register_result_shape(
    "anova_table",
    payload_schema={
        "type": "object",
        "required": ["anova_table", "sums_of_squares_type"],
        "properties": {
            "anova_table": {"type": "array"},
            "sums_of_squares_type": {"type": "integer"},
            "effect_sizes": {"type": "object"},
            "posthoc": {"type": "object"},
        },
    },
    payload_version="1.0",
    description=(
        "Variance decomposition with its declared sums-of-squares type, effect "
        "sizes and optional post-hoc comparisons."
    ),
)
