"""What to write instead: help appended to a refusal of the Agent's own input.

Contract errors name what was wrong. The Agent also needs what is right, or it
guesses again: in the v1.9.1 smoke it wrote ``event_col`` for the Cox model's
``event_column`` and learned only that ``event_col`` was refused. The help is
read from the declarations the check used, so it cannot drift from them.
"""

from __future__ import annotations

import difflib
import re

_UNKNOWN_OPTIONS = re.compile(r"model\.genesis (\S+) model_options does not accept field\(s\): (.+)$")
_MISSING_OPTIONS = re.compile(r"model\.genesis (\S+) model_options requires: ")


def _family_fields(family: str) -> tuple[tuple[str, ...], tuple[str, ...]] | None:
    from ..contracts.model.family import MODEL_FAMILY_CONTRACTS

    contract = MODEL_FAMILY_CONTRACTS.get(family)
    if contract is None:
        return None
    return tuple(contract.model_options_fields), tuple(contract.model_options_required_fields)


_OLS_CLUSTER = (
    " To cluster an OLS fit's standard errors by a column, fit OLS without it, then propose model.rerun "
    "on that model with changes {\"covariance\": \"clustered\", \"entity_col\": \"<column>\"}. For "
    "within-entity (fixed-effects) estimates use model_family panel_ols with entity_col."
)


def help_for(message: str) -> str:
    """A sentence to append to ``message``, or ''."""

    first_line = message.splitlines()[0] if message else ""
    if first_line.startswith("model.genesis ols does not accept panel entity_col or time_col") or (
            first_line.startswith("model.genesis ols model_options does not accept") and "cluster" in first_line):
        # Asked twice in one task by a weaker model (free-route no-thinking round, panel_fe).
        return (_help_for_options(first_line) + _OLS_CLUSTER) if "model_options" in first_line else _OLS_CLUSTER
    return _help_for_options(first_line)


def _help_for_options(first_line: str) -> str:
    unknown = _UNKNOWN_OPTIONS.search(first_line)
    family = unknown.group(1) if unknown else (m.group(1) if (m := _MISSING_OPTIONS.search(first_line)) else None)
    fields = _family_fields(family) if family else None
    if not fields:
        return ""
    accepted, required = fields
    parts = [f"{family} model_options accepts: {', '.join(accepted) or 'no fields'}"
             + (f" (required: {', '.join(required)})" if required else "") + "."]
    if unknown:
        guesses = []
        for name in (item.strip() for item in unknown.group(2).split(",")):
            match = difflib.get_close_matches(name, accepted, n=1, cutoff=0.5)
            if match:
                guesses.append(f"{name} -> {match[0]}")
        if guesses:
            parts.append("Did you mean " + "; ".join(guesses) + "?")
    return " " + " ".join(parts)
