"""P1 统一能力清单：让「有哪些能力」成为可枚举的对象。

这些不变量属于清单本身：每个能力声明自己怎样被够到，有意关闭的必须写明理由，
而不是靠缺席来表达。
"""

from __future__ import annotations

import pytest

from workbench.agent.capability_contract import CapabilityContract


def test_a_capability_declares_how_it_can_be_reached() -> None:
    """A capability names a live operation that can propose it directly."""

    contract = CapabilityContract(
        capability_id="data.columns.cast",
        kind="data_operation",
        summary="Cast several columns in the current dataset node.",
        proposed_by=("data.columns.cast",),
    )

    assert contract.directly_reachable_by == ("data.columns.cast",)
    assert contract.composition_reachable_by == ()
    assert contract.is_reachable
    assert contract.reachability_exempt_reason is None


def test_a_capability_distinguishes_composition_from_direct_proposal() -> None:
    """A disabled top-level operation can still be a multi-step capability."""

    contract = CapabilityContract(
        capability_id="model.ols",
        kind="model_family",
        summary="Estimate an ordinary least squares model.",
        proposed_by=("model.genesis",),
        composable_as=("model.genesis",),
    )

    assert contract.directly_reachable_by == ()
    assert contract.composition_reachable_by == ("model.genesis",)
    assert contract.is_reachable


def test_a_nonexistent_declared_path_is_not_reachable() -> None:
    """A non-empty path declaration is not evidence that a consumer exists."""

    contract = CapabilityContract(
        capability_id="pack.missing",
        kind="pack",
        summary="A deliberately fake capability for the reachability guard.",
        proposed_by=("model.genesis",),
        composable_as=("workflow.not_registered",),
    )

    assert contract.directly_reachable_by == ()
    assert contract.composition_reachable_by == ()
    assert not contract.is_reachable


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


def test_a_pack_capability_can_be_composable_without_model_genesis_admission() -> None:
    """A pack's generic workflow adapter is distinct from model.genesis.

    The two time-series packs are not regression families and therefore remain
    outside `MODEL_FAMILY_CONTRACTS`. Their own generic workflow operations are
    still real composition routes and must not be mistaken for model.genesis
    branches.
    """

    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS

    by_id = {item.capability_id: item for item in capability_inventory()}

    for key in ("time_series.arma_garch", "time_series.ets"):
        assert key not in MODEL_FAMILY_CONTRACTS
        item = by_id[f"model.{key}"]
        assert item.kind == "model_family"
        assert item.proposed_by == ()
        assert item.composable_as == (f"model.{key}",)
        assert item.top_level_exposure_note
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
    assert auto.proposed_by == ()
    assert auto.composable_as == ("model.auto",)
    assert auto.top_level_exposure_note
    assert auto.is_reachable


def test_the_standalone_operation_surfaces_are_in_the_inventory() -> None:
    """Standalone operations expose only their live proposal paths."""

    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    by_id = {item.capability_id: item for item in capability_inventory()}
    standalone = set(OperationRegistry().operation_ids()) - set(
        WORKFLOW_STEP_SPEC_CONTRACTS
    )
    definitions = {
        item["operation_id"]: item for item in OperationRegistry().capabilities()
    }

    assert standalone
    for operation_id in standalone:
        item = by_id[operation_id]
        assert item.kind == "data_operation"
        if definitions[operation_id]["natural_language_enabled"]:
            assert item.proposed_by == (operation_id,)
            assert item.reachability_exempt_reason is None
        else:
            assert item.proposed_by == ()
            assert item.reachability_exempt_reason is not None
        # Not a workflow step, so it cannot appear inside a multi-step plan.
        assert item.composable_as == ()


def test_inventory_records_only_live_natural_language_proposers() -> None:
    """The inventory must not promote registry membership into NL reach."""

    from workbench.agent.capability_contract import capability_inventory

    by_id = {item.capability_id: item for item in capability_inventory()}
    direct_ids = {
        item.capability_id for item in by_id.values() if item.directly_reachable_by
    }

    assert direct_ids == {
        "data.columns.cast",
        "graph.fork",
        "model.rerun",
        "operation.multi_step",
    }
    assert by_id["model.ols"].proposed_by == ()
    assert by_id["model.ols"].composition_reachable_by == ("model.genesis",)


def test_the_two_closed_operations_are_explicitly_exempt() -> None:
    """The two product decisions are visible as reasons, not omissions."""

    from workbench.agent.capability_contract import unreachable_capabilities

    result = unreachable_capabilities()

    assert {item.capability_id for item in result.exempt} == {
        "code.execute",
        "data.column.cast",
    }
    assert all(item.reachability_exempt_reason for item in result.exempt)


def test_natural_language_reachability_guard_pins_current_truth() -> None:
    """Pin today's reachability facts as an intentional change record.

        This test is expected to go red when P5 or P7 wires a currently missing
        route. P7's declaration-driven adoption deliberately changed the pinned
        truth from ``(54, 4, 30, 34, 2, 18)`` to
        ``(118, 4, 112, 116, 2, 0)``. That is not a stale test: the counts and
        gap IDs must be updated in the same deliberate change that closes a gap,
        rather than silently weakening this record.
    """

    from workbench.agent.capability_contract import capability_reachability_guard

    report = capability_reachability_guard()

    assert (
        len(report.inventory),
        len(report.directly_reachable),
        len(report.composition_reachable),
        len(report.reachable),
        len(report.exempt),
        len(report.gaps),
    ) == (118, 4, 112, 116, 2, 0)
    assert {item.capability_id for item in report.gaps} == set()
    assert {item.capability_id for item in report.exempt} == {
        "code.execute",
        "data.column.cast",
    }


def test_reachability_guard_derives_its_denominator_from_the_supplied_inventory() -> None:
    from workbench.agent.capability_contract import (
        CapabilityContract,
        capability_inventory,
        capability_reachability_guard,
    )

    fake = CapabilityContract(
        capability_id="pack.injected_for_guard",
        kind="pack",
        summary="An injected capability used to test the denominator.",
    )
    inventory = (*capability_inventory(), fake)
    report = capability_reachability_guard(inventory)

    assert (
        len(report.inventory),
        {item.capability_id for item in report.gaps},
    ) == (
        len(inventory),
        {"pack.injected_for_guard"},
    )


def test_time_series_and_auto_capabilities_have_generic_workflow_routes() -> None:
    """Selectable capabilities are reachable through their typed workflow steps."""

    from workbench.agent.capability_contract import unreachable_capabilities

    _exempt, gaps = unreachable_capabilities()

    assert not {"model.time_series.arma_garch", "model.time_series.ets", "model.auto"} & {
        item.capability_id for item in gaps
    }


def test_a_step_identity_is_one_capability_carrying_two_paths() -> None:
    """An operation that is also a step is not two capabilities.

        Operation ids appear both as a top-level proposal surface and as a
        workflow step. Counting them twice would inflate the denominator of any
    "how much is reachable" claim; that is what `proposed_by` and
    `composable_as` are two tuples for.
    """

    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    operation_ids = set(OperationRegistry().operation_ids())
    operations = [
        item for item in capability_inventory() if item.capability_id in operation_ids
    ]

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


def test_prediction_and_preparation_capabilities_have_typed_workflow_routes() -> None:
    """Prediction and preparation methods are reachable without run-form guessing.

    The generic operation declarations now own these bindings and their
    execution contracts. The live manifest still owns the denominator.
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
        assert item.is_reachable, item.capability_id
        assert item.reachability_exempt_reason is None, item.capability_id


def test_the_inventory_separates_a_closed_door_from_a_missing_one() -> None:
    """Two different facts, and collapsing them hides whichever one matters.

    A capability nobody wired up and a capability deliberately withheld are not
    the same claim. P2's guard has to fail on the first and accept the second,
    so P1 has to be able to tell them apart before P2 can assert anything.
    """

    from workbench.agent.capability_contract import unreachable_capabilities

    exempt, gaps = unreachable_capabilities()

    for item in exempt:
        assert item.reachability_exempt_reason, item.capability_id
    for item in gaps:
        assert item.reachability_exempt_reason is None, item.capability_id
    assert not (set(exempt) & set(gaps))


def test_todays_unreachable_capabilities_are_all_gaps() -> None:
    """Recording the number is the point: it is the size of the promise
    'natural language reaches every capability' currently overstates by.

    This test pins today's facts on purpose, so it is *expected* to go red the
    day someone closes one of these gaps or shuts a door deliberately. That is
    not the test breaking: it is the record of the shortfall asking to be
    updated in the same change that alters it, instead of the number quietly
    getting smaller with nobody noticing it moved.
    """

    from workbench.agent.capability_contract import unreachable_capabilities

    exempt, gaps = unreachable_capabilities()

    assert {item.capability_id for item in exempt} == {
        "code.execute",
        "data.column.cast",
    }
    assert {item.kind for item in gaps} == set()
    assert len(gaps) == 0


def test_the_partition_covers_every_unreachable_capability_and_nothing_else() -> None:
    """Two lists that agree with each other can still both be wrong.

    The partition tests above are satisfied by returning nothing at all on the
    exempt side, and by dropping a capability from both sides. Neither would be
    caught by asking each list about itself, so the partition is checked against
    the inventory it partitions: every unreachable entry lands on exactly one
    side, and no reachable entry lands on either.
    """

    from workbench.agent.capability_contract import (
        capability_inventory,
        unreachable_capabilities,
    )

    inventory = capability_inventory()
    unreachable = {item for item in inventory if not item.is_reachable}
    assert unreachable

    exempt, gaps = unreachable_capabilities()

    assert set(exempt) | set(gaps) == unreachable
    assert len(exempt) + len(gaps) == len(unreachable)
    reachable = {item for item in inventory if item.is_reachable}
    assert reachable
    assert not (reachable & (set(exempt) | set(gaps)))


def test_the_two_sides_of_the_partition_are_reachable_by_name() -> None:
    """Positional unpacking of two same-typed lists is one typo from a lie.

    A caller that writes `gaps, exempt = ...` gets a guard that passes on gaps
    and fails on stated exemptions, with nothing in the types to object. The
    result names its sides so the mix-up has to be spelled out to happen.
    """

    from workbench.agent.capability_contract import unreachable_capabilities

    result = unreachable_capabilities()

    assert result.exempt == result[0]
    assert result.gaps == result[1]
    assert all(item.reachability_exempt_reason is None for item in result.gaps)


def test_a_capability_cannot_be_reachable_and_exempt_at_once() -> None:
    """An exemption reason on a reachable capability is a contradiction.

    It reads as "deliberately withheld" while the capability is in fact wired
    up, which would let a real closure be recorded on the wrong entry and never
    show up on either side of the partition.
    """

    from workbench.agent.capability_contract import CapabilityContract

    with pytest.raises(ValueError, match=r"reachable capability .* cannot"):
        CapabilityContract(
            capability_id="data.columns.cast",
            kind="data_operation",
            summary="Cast several columns in the current dataset node.",
            proposed_by=("data.columns.cast",),
            reachability_exempt_reason="Withheld pending review.",
        )


def test_an_exemption_reason_must_say_something() -> None:
    """A whitespace reason satisfies `is not None` and explains nothing.

    The exempt side exists so a closure survives someone asking "was this an
    oversight?"; a blank string answers that question with silence while
    counting as an answer.
    """

    from workbench.agent.capability_contract import CapabilityContract

    with pytest.raises(ValueError, match=r"exempt.*reason"):
        CapabilityContract(
            capability_id="prediction.lasso",
            kind="prediction_model",
            summary="L1-regularized linear prediction.",
            reachability_exempt_reason="   ",
        )


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
