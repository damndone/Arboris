"""Which Agent workflows run without asking the user first.

A workflow whose every step only reads data -- descriptive statistics and
inferential tests -- changes no dataset, no model and no report, so waiting
for a click protects nothing. It runs at once, and it is recorded in the
analysis ledger and disclosed like everything else.

What stays behind a confirmation: anything that changes data or metadata,
fits or refits a model, composes a report, or runs code; and read-only work
past the budget below. Running many tests is where p-hacking lives, so after
``SESSION_INFERENTIAL_BUDGET`` inferential steps in one Agent session every
further test needs the user's confirmation, and the Agent is told why.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..analysis_ledger import step_category

READ_ONLY_CATEGORIES = frozenset({"descriptive", "inferential"})
MAX_AUTO_STEPS = 12
SESSION_INFERENTIAL_BUDGET = 30
ACTOR = "read_only_policy"


@dataclass(frozen=True)
class AutoRunDecision:
    allowed: bool
    reason: str
    inferential_steps: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason, "inferential_steps": self.inferential_steps}


def decide(operation_id: str, changes: Mapping[str, Any], *, prior_inferential_steps: int) -> AutoRunDecision:
    if operation_id != "operation.multi_step":
        return AutoRunDecision(False, "only composed read-only workflows run without confirmation")
    steps: Sequence[Any] = changes.get("steps") or ()
    if not steps:
        return AutoRunDecision(False, "the workflow has no steps")
    categories = [step_category(str(step.get("operation_id", ""))) for step in steps if isinstance(step, Mapping)]
    if len(categories) != len(steps):
        return AutoRunDecision(False, "a step is malformed")
    changing = sorted({category for category in categories if category not in READ_ONLY_CATEGORIES})
    if changing:
        return AutoRunDecision(False, f"the workflow includes {', '.join(changing)} steps, which need the user's confirmation")
    inferential = categories.count("inferential")
    if len(steps) > MAX_AUTO_STEPS:
        return AutoRunDecision(
            False, f"{len(steps)} steps exceed the {MAX_AUTO_STEPS}-step limit for running without confirmation", inferential
        )
    if prior_inferential_steps + inferential > SESSION_INFERENTIAL_BUDGET:
        return AutoRunDecision(
            False,
            f"this session has already run {prior_inferential_steps} inferential tests; past "
            f"{SESSION_INFERENTIAL_BUDGET}, more tests need the user's confirmation because the chance "
            "of a false positive grows with every test",
            inferential,
        )
    return AutoRunDecision(True, "every step only reads data", inferential)
