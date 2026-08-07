"""Typed failures for the design-variance engine.

Every refusal here carries a machine-decidable code and, where a composition is
at fault, the exact capabilities that were missing.  An agent that receives a
sentence cannot reason about it; one that receives a code and a missing-capability
list can pick another variance channel and continue.
"""

from __future__ import annotations


class SurveyEngineError(RuntimeError):
    """A design or execution failure the caller must see rather than absorb."""

    def __init__(self, code: str, detail: str = "", **context: object) -> None:
        self.code = code
        self.detail = detail
        self.context = dict(context)
        super().__init__(f"{code}: {detail}" if detail else code)


class SurveyCompositionError(SurveyEngineError):
    """A Design x Estimator x Variance combination that cannot be formed.

    Raised only for combinations that are *derivably* impossible -- an estimator
    lacking the capability a channel needs -- never from a hand-written table of
    which family supports which design.
    """

    def __init__(
        self,
        code: str,
        detail: str = "",
        missing_capabilities: list[str] | None = None,
        **context: object,
    ) -> None:
        self.missing_capabilities = list(missing_capabilities or [])
        super().__init__(code, detail, missing_capabilities=self.missing_capabilities, **context)
