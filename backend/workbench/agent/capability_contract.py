"""One capability's identity and the paths by which it can be asked for.

A capability is not an operation. `model.genesis` is a single operation that
carries twenty-three model families, so a guard written over operations stays
green when the twenty-fourth family is unreachable -- which is exactly how the
previous version's reachability check missed the data-operation family. This
contract is the layer that makes "every capability" enumerable, and reach a
property each capability states about itself rather than one a human re-checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


CAPABILITY_KINDS = frozenset(
    {
        "model_family",
        # "selector" is not an estimator or a transform: it is a user-selectable
        # entry that resolves to one of the others. `auto` is one, and it needs
        # a kind of its own -- calling it a model family would have the
        # inventory assert an estimator exists that does not, and leaving it out
        # would hide a capability the product visibly offers.
        "selector",
        # "data_operation" means specifically a registered `OperationRegistry`
        # entry, which is why the frame-preparation methods below could not
        # borrow it: they are named methods on the run config, not operations.
        "data_operation",
        "statistical_test",
        # A prediction model is never a legal `model_type`. It travels the
        # separate `prediction_model_type` config field, is dispatched by the
        # diagnostics stage, and returns out-of-sample metrics instead of
        # coefficients -- passing one as `model_type` does not run it, it falls
        # through to the y-type default. Filing these under "model_family"
        # would make that silent passthrough look like a supported path, and
        # would make their absence from MODEL_FAMILY_CONTRACTS read as an
        # oversight rather than a category difference.
        "prediction_model",
        # One kind for both frame-preparation registries (imputation and
        # class-imbalance resampling) rather than one each: they share a shape
        # -- a named method chosen on the run config that transforms the frame
        # before a model is fit and produces no result of its own.
        "data_preparation",
        "pack",
    }
)

#: model_types keys that resolve to a family rather than being one. Declared
#: here so a future selector is a one-line addition instead of a family the
#: inventory misdescribes.
MODEL_TYPE_SELECTORS = frozenset({"auto"})


@dataclass(frozen=True)
class CapabilityContract:
    capability_id: str
    kind: str
    summary: str
    #: operation_ids that can propose this capability at the top level.
    #: A tuple rather than a flag: a guard has to be able to say *through what*
    #: a capability is reachable, and a family wired to an operation that does
    #: not exist is invisible to a boolean.
    proposed_by: tuple[str, ...] = ()
    #: workflow step operation_ids that can compose this capability in a plan.
    composable_as: tuple[str, ...] = ()
    #: Deliberately closed capabilities say so here. Absence from the inventory
    #: and presence with a stated reason are different claims, and only the
    #: second one survives someone asking "was this an oversight?".
    reachability_exempt_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ValueError("capability_id must be a non-empty string")
        if self.kind not in CAPABILITY_KINDS:
            raise ValueError(
                f"capability {self.capability_id} kind must be one of: "
                + ", ".join(sorted(CAPABILITY_KINDS))
            )
        if not self.summary.strip():
            raise ValueError(
                f"capability {self.capability_id} needs a summary: it is what a "
                "reader and a model both see first"
            )
        if self.reachability_exempt_reason is not None:
            if not self.reachability_exempt_reason.strip():
                # An empty reason passes `is not None` and answers "was this an
                # oversight?" with silence while counting as an answer.
                raise ValueError(
                    f"capability {self.capability_id} is marked exempt and must "
                    "state a reason: a blank one records a closure nobody can "
                    "check"
                )
            if self.is_reachable:
                raise ValueError(
                    f"reachable capability {self.capability_id} cannot also be "
                    "exempt from reachability: it is wired up, so an exemption "
                    "reason on it records a closure that did not happen"
                )

    @property
    def is_reachable(self) -> bool:
        return bool(self.proposed_by or self.composable_as)


@dataclass(frozen=True)
class CapabilitySurfaceDecision:
    """One key of `build_capabilities()`, and the verdict passed on it.

    The test for "is this a capability?" is whether a user would say *do this
    for me*. "Run a Lasso prediction" is a request; "do robust" is not a
    sentence. But the verdict matters less than the fact that one was recorded:
    an excluded family that is simply missing from the inventory is
    indistinguishable from a family nobody thought about, and that is precisely
    how the previous version came to publish a reach claim over a denominator
    with an entire operation family missing from it. Every key gets a row here,
    including the ones that are obviously not capabilities.
    """

    #: The `build_capabilities()` key this verdict is about.
    surface: str
    is_capability: bool
    reason: str
    #: The inventory kinds this surface contributes, empty when excluded. Stated
    #: so the "included" verdict can be checked against the inventory instead of
    #: being taken on faith.
    produces_kinds: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.surface.strip():
            raise ValueError("surface must be a non-empty string")
        if not self.reason.strip():
            raise ValueError(f"surface {self.surface} needs a reason")
        if self.is_capability != bool(self.produces_kinds):
            raise ValueError(
                f"surface {self.surface}: a surface judged a capability must "
                "name the kinds it produces, and one judged otherwise must "
                "name none"
            )
        unknown = set(self.produces_kinds) - CAPABILITY_KINDS
        if unknown:
            raise ValueError(
                f"surface {self.surface} produces unknown kind(s): "
                + ", ".join(sorted(unknown))
            )


#: Every key `build_capabilities()` publishes, with the judgment passed on it.
#: A test asserts this covers the live manifest exactly, so a new key cannot be
#: added to the product without someone deciding which of the two it is.
CAPABILITY_SURFACES: tuple[CapabilitySurfaceDecision, ...] = (
    CapabilitySurfaceDecision(
        surface="model_types",
        is_capability=True,
        reason=(
            "Each entry is an estimator a user asks for by name -- 'fit a "
            "Cox model' -- plus the `auto` router that resolves to one."
        ),
        produces_kinds=("model_family", "selector"),
    ),
    CapabilitySurfaceDecision(
        surface="prediction_models",
        is_capability=True,
        reason=(
            "'Predict this with a random forest' is a request for a specific "
            "estimator, not a setting on some other request."
        ),
        produces_kinds=("prediction_model",),
    ),
    CapabilitySurfaceDecision(
        surface="imputation_methods",
        is_capability=True,
        reason=(
            "'Impute the missing values with MICE' is a thing a user asks to "
            "have done; it changes which rows the model sees at all."
        ),
        produces_kinds=("data_preparation",),
    ),
    CapabilitySurfaceDecision(
        surface="sampling_methods",
        is_capability=True,
        reason=(
            "'Rebalance the classes with SMOTE' is a request. It only applies "
            "on the prediction path, but that is a composition constraint, "
            "not a demotion to being somebody else's parameter."
        ),
        produces_kinds=("data_preparation",),
    ),
    CapabilitySurfaceDecision(
        surface="covariance_options",
        is_capability=False,
        reason=(
            "A parameter of an estimator, not something that runs. 'Do robust "
            "for me' is not a sentence; 'fit OLS with robust standard errors' "
            "is one request with an argument. It is already published as the "
            "`covariance` param on every family that takes it, so its reach "
            "is that family's reach and needs no second denominator entry."
        ),
    ),
    CapabilitySurfaceDecision(
        surface="survey_design",
        is_capability=False,
        reason=(
            "A cross-cutting attribute of a run, like Stata's `svyset`: "
            "nothing executes 'a survey design'. It changes the variance "
            "channel of whichever estimator is already being asked for, and "
            "`_attach_survey_design_params` publishes it as params on the "
            "families that accept it -- the product itself already treats it "
            "as arguments. Counting it as a capability would create an entry "
            "with no result and no id a user could name, while its real reach "
            "question ('can family F's design be set through an operation?') "
            "is per-family and already carried by that family's entry."
        ),
    ),
    CapabilitySurfaceDecision(
        surface="editable_stages",
        is_capability=False,
        reason=(
            "An editing surface: which stage of an existing run the editor may "
            "reopen. 'Do model for me' is not a request, and the thing that "
            "gets edited is already in the inventory as the model family."
        ),
    ),
    CapabilitySurfaceDecision(
        surface="schema_version",
        is_capability=False,
        reason=(
            "The wire version of the manifest itself. Listed only so this "
            "table can be asserted equal to the live manifest's key set, which "
            "is what stops a future key from being added unexamined."
        ),
    ),
)


def _model_capabilities() -> list[CapabilityContract]:
    """Every model type, from the two registries that between them define one.

    Neither registry alone is the answer, and the gap between them is the point:

    * `build_capabilities()["model_types"]` is what a user can pick and run, and
      is the only place a family's human description lives.
    * `MODEL_FAMILY_CONTRACTS` is what `model_family_contract()` admits into a
      workflow step, and therefore what `operation.multi_step` can compose.

    Taking the union means a family registered in either one shows up without
    anybody editing this function; splitting the two paths across `proposed_by`
    and `composable_as` means a family present in only one is reported as the
    partial-reach state it really is instead of being rounded to reachable or
    dropped.
    """

    # Imported here: workbench.engine.capabilities pulls in the pack loader and
    # the whole stage pipeline, and importing that at module scope makes this
    # module a participant in the engine/orchestrator import cycle.
    from workbench.engine.capabilities import build_capabilities

    from .workflow_contracts import MODEL_FAMILY_CONTRACTS

    selectable = {
        str(entry["key"]): entry for entry in build_capabilities()["model_types"]
    }

    capabilities: list[CapabilityContract] = []
    for key in sorted({*selectable, *MODEL_FAMILY_CONTRACTS}):
        entry = selectable.get(key)
        admitted = key in MODEL_FAMILY_CONTRACTS
        if entry is not None:
            summary = str(entry.get("description") or "")
        else:
            # A family the workflow admits but the selector never offers. It has
            # no description anywhere, so say what is actually known about it
            # and that the description is missing -- echoing the id back would
            # satisfy the summary check while telling a planner nothing.
            contract = MODEL_FAMILY_CONTRACTS[key]
            summary = (
                "Workflow-executable model family returning a "
                f"{contract.result_shape} result. No selector description is "
                "registered for it."
            )
        capabilities.append(
            CapabilityContract(
                capability_id=f"model.{key}",
                kind="selector" if key in MODEL_TYPE_SELECTORS else "model_family",
                summary=summary,
                # Top-level model.genesis does not restrict model_type to the
                # admission table, so anything the selector offers can be
                # proposed directly.
                proposed_by=("model.genesis",) if entry is not None else (),
                # ...but a model.genesis *step* inside a plan calls
                # model_family_contract(), which refuses anything not admitted.
                composable_as=("model.genesis",) if admitted else (),
            )
        )
    return capabilities


def _operation_capabilities() -> list[CapabilityContract]:
    """Every registered operation, once, carrying the paths it can be asked on.

    An operation that is also a workflow step is one capability with two paths,
    not two capabilities: counting it twice would inflate the denominator of any
    "how much of the product is reachable" claim.
    """

    from .operations import OperationRegistry
    from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    registry = OperationRegistry()
    summaries: dict[str, str] = {}
    for entry in registry.capabilities():
        # capabilities() is keyed by (id, version); the capability is the id, so
        # the first registered version supplies the description.
        summaries.setdefault(str(entry["operation_id"]), str(entry["ui_description"]))

    return [
        CapabilityContract(
            capability_id=operation_id,
            kind="data_operation",
            summary=summaries[operation_id],
            proposed_by=(operation_id,),
            composable_as=(
                (operation_id,) if operation_id in WORKFLOW_STEP_SPEC_CONTRACTS else ()
            ),
        )
        for operation_id in sorted(summaries)
    ]


def _statistical_test_capabilities() -> list[CapabilityContract]:
    """Every statistical test family, with the reach it actually has: none.

    These run as a pipeline stage inside every model run and are selected by
    column types, so no operation can name one. They are listed as unreachable
    rather than omitted, because "cannot be asked for by name" is a finding the
    inventory exists to make visible, not a reason to leave them out.
    """

    from ..statistical_tests import TEST_FAMILIES

    return [
        CapabilityContract(
            capability_id=f"test.{family}",
            kind="statistical_test",
            summary=contract.summary,
        )
        for family, contract in sorted(TEST_FAMILIES.items())
    ]


def _prediction_capabilities() -> list[CapabilityContract]:
    """Every prediction model, with the reach it actually has: none.

    A prediction run is requested through the `prediction_model_type` field of
    the run config, which only the HTTP run form and the CLI populate. No
    registered operation carries that field -- `model.rerun`'s override set is
    derived from a family's published params, and `prediction_model_type` is
    not one of them -- so no Agent can ask for a Lasso prediction at all. That
    is a finding, so these are listed as unreachable rather than left out.
    """

    from workbench.engine.capabilities import build_capabilities

    return [
        CapabilityContract(
            # Prefix plus the registry key verbatim, so the wire value a caller
            # must send is recoverable from the capability id. Trimming the
            # redundant-looking `prediction_` would break that.
            capability_id=f"prediction.{entry['key']}",
            kind="prediction_model",
            # PREDICTION_UI registers a three-word description ("L1-regularized
            # linear prediction."), which says what the estimator is but not
            # the thing a planner most needs: that asking for it is a different
            # kind of request than asking for a model family. The channel is
            # appended rather than the description being rewritten, because
            # rewriting it would change what the run form shows a human.
            summary=(
                f"{str(entry['description']).rstrip('.')}. Fit and scored out "
                "of sample by the prediction protocol (hold-out split with "
                "cross-validation), not by the estimation stage."
            ),
        )
        for entry in build_capabilities()["prediction_models"]
    ]


def _data_preparation_capabilities() -> list[CapabilityContract]:
    """Imputation and class-imbalance resampling, both equally out of reach.

    `imputation_method` and `prediction_sampling_method` are run-config fields
    on the same footing as `prediction_model_type`: reachable from the run form
    and the CLI, named by no operation. MICE is the sharper case of the two --
    it decides whether rows with missing values are dropped or filled, so an
    Agent driving an analysis cannot influence the sample it estimates on.
    """

    from workbench.engine.capabilities import build_capabilities

    manifest = build_capabilities()
    capabilities = [
        CapabilityContract(
            capability_id=f"imputation.{entry['key']}",
            kind="data_preparation",
            summary=str(entry["description"]),
        )
        for entry in manifest["imputation_methods"]
    ]
    capabilities.extend(
        CapabilityContract(
            capability_id=f"resample.{entry['key']}",
            kind="data_preparation",
            # SAMPLING_UI registers a label and nothing else, so state what is
            # actually known about the method and say the description is
            # missing. Passing the label through as the summary would satisfy
            # Task 1's non-empty check while telling a planner nothing.
            summary=(
                f"Class-imbalance resampling offered as {entry['label']!r}, "
                "applied to the training split before a prediction model is "
                "fit. No description is registered for it."
            ),
        )
        for entry in manifest["sampling_methods"]
    )
    return capabilities


def capability_inventory() -> tuple[CapabilityContract, ...]:
    """The enumerable set of things this product can be asked to do.

    Derived from the live registries on every call. A hand-kept copy would be a
    second place to remember, and the one that gets forgotten -- which is how
    the previous version came to claim full natural-language reach while an
    entire operation family was unreachable.
    """

    return (
        *_model_capabilities(),
        *_operation_capabilities(),
        *_statistical_test_capabilities(),
        *_prediction_capabilities(),
        *_data_preparation_capabilities(),
    )


class UnreachableCapabilities(NamedTuple):
    """The two ways a capability can be out of reach, kept apart.

    A tuple so `exempt, gaps = unreachable_capabilities()` reads naturally, and
    named so it does not have to. Both sides are lists of the same type, which
    means a caller who writes `gaps, exempt = ...` gets a guard that waves gaps
    through and rejects stated closures, with nothing in the types to object.
    """

    #: Capabilities the product deliberately does not expose, each carrying the
    #: reason. A guard should accept these.
    exempt: tuple[CapabilityContract, ...]
    #: Capabilities nobody wired up. A guard should fail on these -- they are
    #: the amount by which "natural language reaches everything" overstates.
    gaps: tuple[CapabilityContract, ...]


def unreachable_capabilities() -> UnreachableCapabilities:
    """Split what cannot be reached into what was closed and what was missed.

    Collapsing the two hides whichever one matters. Treating every gap as an
    exemption dresses up the shortfall this inventory exists to expose; treating
    every exemption as a gap makes a decision look like an oversight. The
    partition is over `capability_inventory()`, so a capability cannot fall out
    of both sides by being forgotten here.
    """

    exempt: list[CapabilityContract] = []
    gaps: list[CapabilityContract] = []
    for item in capability_inventory():
        if item.is_reachable:
            continue
        # __post_init__ has already refused a blank reason and refused a reason
        # on a reachable entry, so this is the whole space of what is left.
        if item.reachability_exempt_reason is None:
            gaps.append(item)
        else:
            exempt.append(item)
    return UnreachableCapabilities(exempt=tuple(exempt), gaps=tuple(gaps))


__all__ = [
    "CAPABILITY_KINDS",
    "CAPABILITY_SURFACES",
    "MODEL_TYPE_SELECTORS",
    "CapabilityContract",
    "CapabilitySurfaceDecision",
    "UnreachableCapabilities",
    "capability_inventory",
    "unreachable_capabilities",
]
