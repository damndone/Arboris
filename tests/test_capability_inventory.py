"""P1 统一能力清单：让「有哪些能力」成为可枚举的对象。

这些不变量属于清单本身：每个能力声明自己怎样被够到，有意关闭的必须写明理由，
而不是靠缺席来表达。
"""

from __future__ import annotations

import pytest

from workbench.agent.capability_contract import CapabilityContract


def test_a_capability_declares_how_it_can_be_reached() -> None:
    """A capability that names no path to itself is one nobody can ask for."""

    contract = CapabilityContract(
        capability_id="model.ols",
        kind="model_family",
        summary="Ordinary least squares.",
        proposed_by=("model.genesis",),
        composable_as=("model.genesis",),
    )

    assert contract.is_reachable
    assert contract.reachability_exempt_reason is None


def test_a_capability_with_no_path_is_not_reachable() -> None:
    """Unreachable is a state the inventory can report, not one it hides."""

    contract = CapabilityContract(
        capability_id="multivariate.pca",
        kind="pack",
        summary="Principal component analysis.",
    )

    assert not contract.is_reachable


def test_a_capability_without_an_id_is_refused() -> None:
    """An unnamed capability cannot be named in a guard's failure message."""

    with pytest.raises(ValueError, match=r"capability_id must be a non-empty string"):
        CapabilityContract(capability_id="   ", kind="pack", summary="Something.")


def test_a_capability_of_an_unknown_kind_is_refused() -> None:
    """The kinds are a closed set so a typo fails here, not at enumeration."""

    with pytest.raises(ValueError, match=r"kind must be one of"):
        CapabilityContract(
            capability_id="model.ols", kind="model-family", summary="OLS."
        )


def test_a_capability_without_a_summary_is_refused() -> None:
    """The summary is the first thing a reader and a model both see.

    An inventory entry that only carries an id tells a planning agent a name
    exists and nothing about when to reach for it, which is indistinguishable
    from not publishing it at all.
    """

    with pytest.raises(ValueError, match=r"needs a summary"):
        CapabilityContract(capability_id="model.ols", kind="model_family", summary=" ")
