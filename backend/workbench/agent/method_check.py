"""A reply's estimate must come from a model family that serves the outcome it estimates.

The check library flags a fit whose family is not declared for its outcome's type
(``outcome.type_served``), and the result summary carries that record. A reply is
withdrawn once, before the person sees it, when its numbers rest on such a fit and
nothing the Agent read in this conversation came from a family that does serve that
outcome. The correction names the serving families and the permitted way to refit.

Prompt text alone did not move the model: on the recorded binary_logit.goal turn,
18 of 18 NVIDIA Nemotron probe samples (2026-11-07/08) planned the answer from the
imported OLS whatever the focus line, the scope rule or the check's remedy said, while
the same model refitted a Logit as soon as it was told the analysis was not done.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from ..checks.fit_checks import OUTCOME_TYPE_SERVED
from . import numeric_grounding

MESSAGE_NAME = "method_check"
MAX_REPAIRS = 1


def _payloads(messages: Sequence[Mapping[str, Any]]):
    for index, message in enumerate(messages):
        if message.get("role") != "tool":
            continue
        content = message.get("content")
        try:
            yield index, json.loads(content) if isinstance(content, str) else content
        except ValueError:
            continue


def _dicts(value: Any):
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def unserved_reads(messages: Sequence[Mapping[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """Tool results that carry a fit's record that its family does not serve its outcome."""
    return [(index, dict(item.get("evidence") or {})) for index, payload in _payloads(messages)
            for item in _dicts(payload)
            if item.get("check_id") == OUTCOME_TYPE_SERVED.check_id and item.get("status") == "caution"]


def served_fit_read(messages: Sequence[Mapping[str, Any]], serving: set[str]) -> bool:
    return any(item.get(key) in serving for _, payload in _payloads(messages) for item in _dicts(payload)
               for key in ("model_family", "model_type") if isinstance(item.get(key), str))


def finding(reply: str, messages: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """The unserved fit's record when the reply's numbers rest on it alone, else None."""
    reads = unserved_reads(messages)
    if not reads or not reply.strip():
        return None
    serving = {name for _, evidence in reads for name in evidence.get("families_serving_outcome_type") or ()}
    if serving and served_fit_read(messages, serving):
        return None
    flagged = {index for index, _ in reads}
    without = [message for index, message in enumerate(messages) if index not in flagged]
    if len(numeric_grounding.check(reply, without)) <= len(numeric_grounding.check(reply, messages)):
        return None
    return reads[-1][1]


def correction_message(evidence: Mapping[str, Any], *, new_specification_denied: bool) -> str:
    serving = list(evidence.get("families_serving_outcome_type") or ())
    default = evidence.get("default_family_for_outcome_type") or (serving[0] if serving else None)
    refused = ("; a new model specification (model.genesis) is refused by this project's permissions"
               if new_specification_denied else "")
    refit = (f"model.rerun on the same model node with model_type {default} keeps its data, outcome and "
             f"predictors (a change of estimator, not a new specification){refused}. " if default else "")
    return ("[Workbench -- an automatic check, not from the user] This draft was not shown. Its estimate rests on "
            f"{evidence.get('family') or 'a fit'}, which is not declared for {evidence.get('outcome_type') or 'this'} "
            f"outcomes; families declared for them: {', '.join(serving) or 'none registered'}. Refit with one of "
            f"them before answering: {refit}Answer from that fit; the earlier fit may appear only as a comparison. "
            "If none can be fitted here, say so and why instead of presenting the earlier fit as the answer.")
