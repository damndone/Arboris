"""Shared construction helpers for P7 extension result scope metadata."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from workbench.contracts.model.p7_extension import P7ScopeMetadata


def make_p7_scope(
    *,
    estimand: str,
    input_semantics: str,
    assumptions: Sequence[str],
    limitations: Sequence[str],
    not_claimed: Sequence[str],
    unsupported_extensions: Sequence[str],
) -> dict[str, Any]:
    """Build validated scope metadata without accepting raw data or code."""

    return P7ScopeMetadata(
        estimand=estimand,
        input_semantics=input_semantics,
        assumptions=tuple(assumptions),
        limitations=tuple(limitations),
        not_claimed=tuple(not_claimed),
        unsupported_extensions=tuple(unsupported_extensions),
    ).to_dict()


__all__ = ["make_p7_scope"]
