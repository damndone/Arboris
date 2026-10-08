"""Column references in model formulas: ``Q(<Python string literal>)``.

Formulas name every column through patsy's ``Q()``, so any column name is
safe in a formula. The literal is ``repr(column)``: ``Q('x')``, ``Q("o'brien")``
when the name holds a single quote, and backslash escapes when it holds both
quotes or a backslash. Every reader turns a term back into the user's column
through this module, which evaluates the literal rather than stripping quote
characters (V1811-PUBLIC-TERM-QUOTE).

Standard library only.
"""

from __future__ import annotations

import ast
import re

#: A Python string literal in either quote style, with backslash escapes, as
#: ``repr`` writes one (never a raw newline). For readers that search longer
#: text; the match is decoded with ``literal_value``.
STRING_LITERAL = r"""(?:'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")"""

#: ``Q(<literal>)``, the literal captured as ``literal``.
QUOTED_COLUMN = rf"Q\((?P<literal>{STRING_LITERAL})\)"

_QUOTED_COLUMN = re.compile(rf"^{QUOTED_COLUMN}$")

#: A treatment-coded level of a categorical column: ``C(Q('g'))[T.b]``, with an
#: optional contrast (``C(Q('g'), Sum)``) and the bare ``C(g)[T.b]`` form.
_CATEGORICAL_LEVEL = re.compile(
    rf"^C\((?:{QUOTED_COLUMN}|(?P<bare>[^,()]+?))(?:\s*,[^\[]*)?\)\[T\.(?P<level>.+)\]$"
)


def quote_column(column: str) -> str:
    """The formula reference to ``column``."""
    return f"Q({column!r})"


def literal_value(literal: str) -> str:
    """The string a matched ``STRING_LITERAL`` denotes.

    Raises ValueError for text the pattern matches but Python cannot decode
    (``'\\N'`` without a name, a truncated ``'\\x4'``): such a term was not
    written by ``quote_column`` and names no column.
    """
    try:
        value = ast.literal_eval(literal)
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"not a decodable string literal: {literal!r}") from exc
    if not isinstance(value, str):
        raise ValueError(f"not a string literal: {literal!r}")
    return value


def _decoded(literal: str) -> str | None:
    try:
        return literal_value(literal)
    except ValueError:
        return None


def unquote_column(term: str) -> str | None:
    """The column a whole ``Q(...)`` term names, or None for any other term."""
    match = _QUOTED_COLUMN.match(term)
    return None if match is None else _decoded(match.group("literal"))


def public_term(term: object) -> str:
    """The user's column for a ``Q(...)`` term; any other term unchanged."""
    text = str(term)
    column = unquote_column(text)
    return text if column is None else column


def categorical_level(term: str) -> tuple[str, str] | None:
    """``(column, level)`` for a treatment-coded categorical term, else None."""
    match = _CATEGORICAL_LEVEL.match(term)
    if match is None:
        return None
    literal = match.group("literal")
    column = _decoded(literal) if literal is not None else match.group("bare").strip()
    return None if column is None else (column, match.group("level"))
