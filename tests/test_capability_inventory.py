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


def test_every_model_family_appears_in_the_inventory() -> None:
    """The twenty-first family joins the inventory by being registered, not by
    someone remembering to add it here."""

    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS

    families = {
        item.capability_id
        for item in capability_inventory()
        if item.kind == "model_family"
    }

    assert {f"model.{name}" for name in MODEL_FAMILY_CONTRACTS} <= families


def test_a_selectable_family_without_an_admission_contract_is_not_composable() -> None:
    """The asymmetry this inventory exists to expose, stated as an invariant.

    `time_series.arma_garch` and `time_series.ets` can be picked in the model
    selector and run by hand, but neither has a `ModelFamilyContract`, so
    `model_family_contract()` refuses them inside a workflow step. That is a
    real partial-reach state: proposable, not composable. Flattening it to
    either "reachable" or "absent" is the silent-exclusion failure this whole
    task is a response to.
    """

    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS

    by_id = {item.capability_id: item for item in capability_inventory()}

    for key in ("time_series.arma_garch", "time_series.ets"):
        assert key not in MODEL_FAMILY_CONTRACTS
        item = by_id[f"model.{key}"]
        assert item.kind == "model_family"
        assert "model.genesis" in item.proposed_by
        assert item.composable_as == ()
        assert item.is_reachable


def test_every_selectable_model_type_is_accounted_for() -> None:
    """No model type may drop out of the inventory on its way in.

    The inventory is only worth trusting if the set it enumerates is provably
    the set the product exposes; a key that is quietly skipped is exactly the
    hole the previous version shipped.
    """

    from workbench.agent.capability_contract import capability_inventory
    from workbench.engine.capabilities import build_capabilities

    listed = {item.capability_id for item in capability_inventory()}
    exposed = {
        f"model.{entry['key']}" for entry in build_capabilities()["model_types"]
    }

    assert exposed <= listed


def test_the_auto_selector_is_listed_as_a_selector_not_a_family() -> None:
    """`auto` is offered next to the families but is not one of them.

    It picks a family from y's type, so calling it a model family would make
    the inventory claim a twenty-first estimator exists. It is listed under its
    own kind instead of being skipped, because "not a family" is not a reason
    to make a user-selectable capability invisible.
    """

    from workbench.agent.capability_contract import capability_inventory

    by_id = {item.capability_id: item for item in capability_inventory()}
    auto = by_id["model.auto"]

    assert auto.kind == "selector"
    assert "model.genesis" in auto.proposed_by
    assert auto.composable_as == ()


def test_the_standalone_operation_surfaces_are_in_the_inventory() -> None:
    """The six operations that are not workflow steps propose themselves."""

    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    by_id = {item.capability_id: item for item in capability_inventory()}
    standalone = set(OperationRegistry().operation_ids()) - set(
        WORKFLOW_STEP_SPEC_CONTRACTS
    )

    assert standalone
    for operation_id in standalone:
        item = by_id[operation_id]
        assert item.kind == "data_operation"
        assert operation_id in item.proposed_by
        # Not a workflow step, so it cannot appear inside a multi-step plan.
        assert item.composable_as == ()


def test_a_step_identity_is_one_capability_carrying_two_paths() -> None:
    """An operation that is also a step is not two capabilities.

    Ten operation ids appear both as a top-level proposal surface and as a
    workflow step. Counting them twice would inflate the denominator of any
    "how much is reachable" claim; that is what `proposed_by` and
    `composable_as` are two tuples for.
    """

    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    operations = [
        item for item in capability_inventory() if item.kind == "data_operation"
    ]
    operation_ids = set(OperationRegistry().operation_ids())

    assert len(operations) == len(operation_ids)
    assert {item.capability_id for item in operations} == operation_ids

    for item in operations:
        if item.capability_id in WORKFLOW_STEP_SPEC_CONTRACTS:
            assert item.composable_as == (item.capability_id,)


def test_every_statistical_test_family_is_in_the_inventory() -> None:
    """A ninth test family joins by being registered, like a model family."""

    from workbench.agent.capability_contract import capability_inventory
    from workbench.statistical_tests import TEST_FAMILIES

    listed = {
        item.capability_id
        for item in capability_inventory()
        if item.kind == "statistical_test"
    }

    assert listed == {f"test.{name}" for name in TEST_FAMILIES}


def test_the_inventory_has_no_duplicate_capability_ids() -> None:
    """Two entries for one id would let a guard pass on the wrong one."""

    from workbench.agent.capability_contract import capability_inventory

    ids = [item.capability_id for item in capability_inventory()]

    assert len(ids) == len(set(ids))


def test_no_summary_is_the_capability_name_echoed_back() -> None:
    """The non-empty check only bites if a name cannot be used to satisfy it.

    Two of the three source registries had no description field before this
    inventory existed, so the cheap way to make them enumerable was to pass the
    key or the artifact filename through as the summary. That passes Task 1's
    validation and tells a planning agent nothing about when to reach for the
    capability, which is indistinguishable from not publishing it.
    """

    from workbench.agent.capability_contract import capability_inventory

    for item in capability_inventory():
        summary = item.summary.strip()
        collapsed = summary.strip(".").lower().replace(" ", "_")
        tail = item.capability_id.split(".", 1)[-1].lower()

        assert collapsed != tail, item.capability_id
        assert collapsed != item.capability_id.lower(), item.capability_id
        assert not summary.endswith(".json"), item.capability_id
        # A real description of when to use something does not fit in three
        # words; a name pasted into the field always does.
        assert len(summary.split()) >= 4, f"{item.capability_id}: {summary!r}"
