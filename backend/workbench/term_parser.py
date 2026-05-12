"""Single source of truth for parsing patsy / statsmodels coefficient term names.

V1.3.2: consolidates the parsing logic previously duplicated across
diagnostic_preview.py, api.py, narrative/claims.py, diagnostic_summary.py,
orchestrator.py, and visualization.py.

Public API: `parse_term(raw, reference_level=None) -> ParsedTerm`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_C_QUOTED_INNER = re.compile(r"""^Q\(['\"](.+?)['\"]\)$""")
_T_LEVEL = re.compile(r"\[T\.(.+?)\]$")
_NP_TRANSFORM = re.compile(r"^np\.(\w+)\((.+)\)$")
_TRANSFORM_DISPLAY = {"log": "log", "sqrt": "sqrt", "exp": "exp"}


@dataclass(frozen=True)
class ParsedTerm:
    raw: str
    display_term: str
    source_id: str
    reference_level: str | None
    is_dummy: bool
    is_interaction: bool
    transformation_op: str | None
    components: list[str] = field(default_factory=list)


def parse_term(raw: str, *, reference_level: str | None = None) -> ParsedTerm:
    """Parse a patsy / statsmodels coefficient term into structured fields.

    Unknown forms degrade gracefully: source_id == raw, display_term == raw,
    transformation_op is None, no exception raised.
    """
    if not raw or raw == "Intercept":
        return _fallback(raw or "")

    # Interactions: split on ':' at top level (patsy never nests parens around ':')
    if ":" in raw and not _is_inside_parens_colon(raw):
        parts = raw.split(":")
        parsed_parts = [parse_term(p) for p in parts]
        components = [p.source_id for p in parsed_parts]
        display = " × ".join(p.display_term for p in parsed_parts)
        is_dummy = any(p.is_dummy for p in parsed_parts)
        return ParsedTerm(
            raw=raw,
            display_term=display,
            source_id=raw,
            reference_level=None,
            is_dummy=is_dummy,
            is_interaction=True,
            transformation_op=None,
            components=components,
        )

    # Categorical: C(...) optionally followed by [T.level]
    if raw.startswith("C(") and "(" in raw:
        return _parse_categorical(raw, reference_level)

    # Transformation: np.log(...), np.sqrt(...), etc.
    transform_match = _NP_TRANSFORM.match(raw)
    if transform_match:
        op = transform_match.group(1)
        inner = transform_match.group(2)
        source = _leading_identifier(inner)
        display_op = _TRANSFORM_DISPLAY.get(op, op)
        return ParsedTerm(
            raw=raw,
            display_term=f"{display_op}({inner})",
            source_id=source,
            reference_level=None,
            is_dummy=False,
            is_interaction=False,
            transformation_op=op,
            components=[source],
        )

    return _fallback(raw)


def _parse_categorical(raw: str, reference_level: str | None) -> ParsedTerm:
    end_of_inner = raw.find(")[T.")
    if end_of_inner != -1:
        inner = raw[2:end_of_inner]
        source = _unwrap_q(inner)
        level_match = _T_LEVEL.search(raw)
        level = level_match.group(1) if level_match else ""
        display = f"{source} = {level}" if level else source
        return ParsedTerm(
            raw=raw,
            display_term=display,
            source_id=source,
            reference_level=reference_level,
            is_dummy=True,
            is_interaction=False,
            transformation_op="C",
            components=[source],
        )
    closing = raw.rfind(")")
    inner = raw[2:closing] if closing > 2 else raw[2:]
    source = _unwrap_q(inner)
    return ParsedTerm(
        raw=raw,
        display_term=source,
        source_id=source,
        reference_level=reference_level,
        is_dummy=False,
        is_interaction=False,
        transformation_op="C",
        components=[source],
    )


def _unwrap_q(inner: str) -> str:
    m = _C_QUOTED_INNER.match(inner)
    return m.group(1) if m else inner


def _leading_identifier(expr: str) -> str:
    """Pull the first identifier out of an inner expression like 'income + 1'."""
    m = re.match(r"^[A-Za-z_][A-Za-z0-9_]*", expr.strip())
    return m.group(0) if m else expr.strip()


def _is_inside_parens_colon(raw: str) -> bool:
    """True only if every ':' lies inside parentheses (defensive; unused by patsy in practice)."""
    depth = 0
    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ":" and depth == 0:
            return False
    return True


def _fallback(raw: str) -> ParsedTerm:
    return ParsedTerm(
        raw=raw,
        display_term=raw,
        source_id=raw,
        reference_level=None,
        is_dummy=False,
        is_interaction=False,
        transformation_op=None,
        components=[raw] if raw else [],
    )
