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


# --- Task 3: the surfaces of build_capabilities(), each with a recorded verdict.


def test_every_capability_surface_carries_a_recorded_judgment() -> None:
    """A key of the manifest is either in the inventory or explicitly not.

    This is the invariant Task 3 exists for. Before it, five families were
    absent from the inventory and nothing distinguished "considered and ruled
    out" from "nobody thought of it" -- which is the exact shape of the
    previous version's miss. Asserting set equality against the live manifest
    means the next key added to `build_capabilities()` fails here until someone
    writes down which of the two it is.
    """

    from workbench.agent.capability_contract import CAPABILITY_SURFACES
    from workbench.engine.capabilities import build_capabilities

    declared = {decision.surface for decision in CAPABILITY_SURFACES}

    assert declared == set(build_capabilities())


def test_the_surfaces_ruled_out_say_why_rather_than_being_absent() -> None:
    """Exclusion is a claim with a stated reason, not a silent omission.

    Naming these four here is deliberate: each is a plausible capability that
    was examined and rejected, and a future reader has to be able to see the
    rejection. Asserting only "not in the inventory" would pass equally well if
    the family had never been considered at all.
    """

    from workbench.agent.capability_contract import CAPABILITY_SURFACES

    by_surface = {decision.surface: decision for decision in CAPABILITY_SURFACES}

    for surface in (
        "covariance_options",
        "survey_design",
        "editable_stages",
        "schema_version",
    ):
        decision = by_surface[surface]
        assert not decision.is_capability, surface
        assert decision.produces_kinds == (), surface
        # A one-word "no" is not a reason anybody can act on later.
        assert len(decision.reason.split()) >= 8, surface


def test_every_surface_judged_a_capability_actually_reaches_the_inventory() -> None:
    """`is_capability=True` has to be load-bearing, not a comment.

    A surface can be declared included and still contribute nothing if its
    derivation is never wired into `capability_inventory()`; that would be the
    same silent hole with a nicer label on it.
    """

    from workbench.agent.capability_contract import (
        CAPABILITY_KINDS,
        CAPABILITY_SURFACES,
        capability_inventory,
    )

    listed_kinds = {item.kind for item in capability_inventory()}

    included = [d for d in CAPABILITY_SURFACES if d.is_capability]
    assert included
    for decision in included:
        assert decision.produces_kinds, decision.surface
        for kind in decision.produces_kinds:
            assert kind in CAPABILITY_KINDS, decision.surface
            assert kind in listed_kinds, decision.surface


def test_every_prediction_model_is_in_the_inventory() -> None:
    """A fourth prediction model joins by being published, not by being typed
    into this file."""

    from workbench.agent.capability_contract import capability_inventory
    from workbench.engine.capabilities import build_capabilities

    listed = {
        item.capability_id
        for item in capability_inventory()
        if item.kind == "prediction_model"
    }
    published = {
        f"prediction.{entry['key']}"
        for entry in build_capabilities()["prediction_models"]
    }

    assert published == listed
    assert "prediction.prediction_lasso" in listed


def test_every_imputation_and_resampling_method_is_in_the_inventory() -> None:
    """The two frame-preparation registries land under one kind."""

    from workbench.agent.capability_contract import capability_inventory
    from workbench.engine.capabilities import build_capabilities

    manifest = build_capabilities()
    listed = {
        item.capability_id
        for item in capability_inventory()
        if item.kind == "data_preparation"
    }
    published = {
        f"imputation.{entry['key']}" for entry in manifest["imputation_methods"]
    } | {f"resample.{entry['key']}" for entry in manifest["sampling_methods"]}

    assert published == listed
    assert {"imputation.mice", "resample.smote"} <= listed


def test_prediction_and_preparation_capabilities_can_be_asked_for_by_nobody() -> None:
    """The finding this task exists to surface, asserted rather than narrated.

    `prediction_model_type`, `imputation_method` and `prediction_sampling_method`
    are run-config fields carried only by the HTTP run form and the CLI. No
    registered operation names any of them, so a Lasso prediction, a MICE
    imputation and a SMOTE rebalance are all unreachable from natural language
    today. They are listed as unreachable, not exempt: this is a gap to close,
    not a door deliberately shut.
    """

    from workbench.agent.capability_contract import capability_inventory
    from workbench.engine.capabilities import build_capabilities

    subject = [
        item
        for item in capability_inventory()
        if item.kind in {"prediction_model", "data_preparation"}
    ]

    # Counted off the manifest, not written down: a fourth prediction model has
    # to arrive here as another unreachable entry rather than as a red test
    # somebody deletes.
    manifest = build_capabilities()
    expected = sum(
        len(manifest[surface])
        for surface in ("prediction_models", "imputation_methods", "sampling_methods")
    )
    assert expected
    assert len(subject) == expected

    for item in subject:
        assert not item.is_reachable, item.capability_id
        assert item.reachability_exempt_reason is None, item.capability_id


def test_a_surface_judged_a_capability_must_name_what_it_produces() -> None:
    """The verdict and the kinds it implies cannot disagree.

    A row saying "yes, this is a capability" while naming no kind is a verdict
    that costs nothing and proves nothing, and the inventory-coverage test above
    would have nothing to check it against.
    """

    from workbench.agent.capability_contract import CapabilitySurfaceDecision

    with pytest.raises(ValueError, match=r"must\s+name the kinds it produces"):
        CapabilitySurfaceDecision(
            surface="prediction_models",
            is_capability=True,
            reason="An estimator a user asks for by name rather than a setting.",
        )

    with pytest.raises(ValueError, match=r"must\s+name the kinds it produces"):
        CapabilitySurfaceDecision(
            surface="covariance_options",
            is_capability=False,
            reason="A parameter of an estimator rather than something that runs.",
            produces_kinds=("model_family",),
        )


def test_a_surface_cannot_produce_a_kind_the_inventory_does_not_know() -> None:
    """A typo in a kind fails here, not by quietly matching nothing later."""

    from workbench.agent.capability_contract import CapabilitySurfaceDecision

    with pytest.raises(ValueError, match=r"produces unknown kind"):
        CapabilitySurfaceDecision(
            surface="prediction_models",
            is_capability=True,
            reason="An estimator a user asks for by name rather than a setting.",
            produces_kinds=("prediction-model",),
        )
