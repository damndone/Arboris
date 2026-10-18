"""Validate workflow source bindings, visible columns, and dependency order."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ...contracts.common.errors import OperationValidationError
from ...contracts.model.family import family_context_columns, model_family_contract
from .contracts import SUPPORTED_STEP_OUTPUTS, _STEP_ID_PATTERN
from . import registry
from .registry import WORKFLOW_STEP_SPEC_CONTRACTS, workflow_step_operations
from .validation import _validate_step_spec

def _spec_columns(operation_id: str, spec: Mapping[str, Any]) -> set[str]:
    """Every source column a step spec references, for schema checking."""

    columns: set[str] = set()
    extractor_key = (
        WORKFLOW_STEP_SPEC_CONTRACTS[operation_id].column_extractor_key
        if operation_id in WORKFLOW_STEP_SPEC_CONTRACTS
        else None
    )
    if extractor_key == "statistical.explore":
        columns.update(str(item) for item in spec.get("selected_columns", []) or [])
        for item in spec.get("filters", []) or []:
            if isinstance(item, Mapping) and item.get("column"):
                columns.add(str(item["column"]))
        options = spec.get("options") or {}
        if isinstance(options, Mapping) and options.get("group_by"):
            columns.add(str(options["group_by"]))
        for plot in spec.get("plots", []) or []:
            if isinstance(plot, Mapping):
                columns.update(str(plot[key]) for key in ("x_column", "y_column") if plot.get(key))
    elif extractor_key == "statistical.derive_boolean":
        for recipe in spec.get("recipes", []) or []:
            if isinstance(recipe, Mapping) and recipe.get("source_column"):
                columns.add(str(recipe["source_column"]))
    elif extractor_key == "statistical.derive_numeric":
        for recipe in spec.get("recipes", []) or []:
            if isinstance(recipe, Mapping):
                columns.update(
                    str(column) for column in recipe.get("input_columns", []) or []
                )
    elif extractor_key == "statistical.derived_group_summarize":
        columns.update(str(item) for item in spec.get("summarize_columns", []) or [])
        for group in spec.get("groups", []) or []:
            if isinstance(group, Mapping) and group.get("source_column"):
                columns.add(str(group["source_column"]))
    elif extractor_key == "model.genesis":
        columns.update(
            family_context_columns(model_family_contract(spec.get("model_family")), spec)
        )
        if isinstance(spec.get("by_group"), str) and spec["by_group"]:
            columns.add(spec["by_group"])
        for branch in spec.get("branches", []) or []:
            if isinstance(branch, Mapping):
                if branch.get("outcome"):
                    columns.add(str(branch["outcome"]))
                columns.update(str(item) for item in branch.get("predictors", []) or [])
                # Derived-term sources are real source columns too; leaving them
                # out let a typo in a dummy or polynomial column reach execution.
                columns.update(str(item) for item in branch.get("categorical", []) or [])
                for entry in branch.get("polynomials", []) or []:
                    if isinstance(entry, Mapping) and entry.get("column"):
                        columns.add(str(entry["column"]))
    elif extractor_key == "model.post_estimation":
        if spec.get("column"):
            columns.add(str(spec["column"]))
        for selector in spec.get("term_selectors", []) or []:
            if isinstance(selector, Mapping) and selector.get("column"):
                columns.add(str(selector["column"]))
    elif extractor_key and extractor_key.startswith("data."):
        operation = extractor_key.removeprefix("data.")
        from ...data_operation_registry import get_data_operation

        declared = get_data_operation(operation)
        if declared is not None:
            columns.update(declared.referenced_columns(spec))
        elif operation == "feature_recipe":
            columns.update(str(item) for item in spec.get("inputs", []) or [])
    elif extractor_key == "statistical.named_test":
        columns.update(str(item) for item in spec.get("analysis_columns", []) or [])
        if isinstance(spec.get("by_group"), str) and spec["by_group"]:
            columns.add(spec["by_group"])
        for column in (spec.get("reference_means") or {}):
            columns.add(str(column))
        for pair in spec.get("paired_columns", []) or []:
            if isinstance(pair, (list, tuple)):
                columns.update(str(item) for item in pair if item)
    elif extractor_key == "prediction.model":
        if spec.get("y"):
            columns.add(str(spec["y"]))
        columns.update(str(item) for item in spec.get("x", []) or [])
        for field_name in ("entity_column", "group_column", "time_column"):
            if spec.get(field_name):
                columns.add(str(spec[field_name]))
    elif extractor_key == "data_preparation.imputation":
        columns.update(str(item) for item in spec.get("columns", []) or [])
    elif extractor_key == "data_preparation.resampling":
        if spec.get("target_column"):
            columns.add(str(spec["target_column"]))
        columns.update(str(item) for item in spec.get("feature_columns", []) or [])
    elif extractor_key == "model.time_series.recipe":
        options = spec.get("model_options") or {}
        if isinstance(options, Mapping):
            for field_name in ("time_column", "value_column"):
                if options.get(field_name):
                    columns.add(str(options[field_name]))
        for field_name in ("time_column", "value_column"):
            if spec.get(field_name):
                columns.add(str(spec[field_name]))
    elif extractor_key == "model.auto":
        for branch in spec.get("branches", []) or []:
            if isinstance(branch, Mapping):
                if branch.get("outcome"):
                    columns.add(str(branch["outcome"]))
                columns.update(str(item) for item in branch.get("predictors", []) or [])
                columns.update(str(item) for item in branch.get("categorical", []) or [])
                for entry in branch.get("polynomials", []) or []:
                    if isinstance(entry, Mapping) and entry.get("column"):
                        columns.add(str(entry["column"]))
        columns.update(str(item) for item in spec.get("context_columns", []) or [])
    elif extractor_key == "p7.pack":
        from ..p7_pack_registry import p7_pack_registry

        operation = p7_pack_registry.get(operation_id)
        columns.update(
            operation.extract_columns(
                {
                    "operation_id": operation_id,
                    "input_mode": spec.get("input_mode"),
                    "column_bindings": spec.get("column_bindings"),
                    "options": spec.get("options"),
                }
            )
        )
    elif extractor_key == "workflow_capability":
        from ..workflow_capability_registry import workflow_capability_registry

        operation = workflow_capability_registry().require(operation_id)
        request = operation.validate(
            {
                "operation_id": operation_id,
                "input_mode": spec.get("input_mode"),
                "column_bindings": spec.get("column_bindings"),
                "options": spec.get("options"),
            }
        )
        for value in request["column_bindings"].values():
            if isinstance(value, str) and value:
                columns.add(value)
            elif isinstance(value, list):
                columns.update(
                    str(item) for item in value if isinstance(item, str) and item
                )
    return columns


def _data_output_columns(
    operation_id: str, spec: Mapping[str, Any], visible: set[str]
) -> set[str]:
    """Project a data-operation output shape for downstream compile checks."""

    operation = operation_id.removeprefix("data.")
    from ...data_operation_registry import get_data_operation

    declared = get_data_operation(operation)
    if declared is not None:
        return declared.output_columns(spec, set(visible))
    if operation == "feature_recipe":
        return {*visible, str(spec.get("output"))}
    return set(visible)


def validate_workflow_steps(
    steps: Any,
    *,
    available_columns: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Validate an Agent-composed plan: identity, DAG, specs, and schema."""

    if not isinstance(steps, list) or not steps:
        raise OperationValidationError("workflow steps must be a non-empty list")
    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for entry in steps:
        if not isinstance(entry, Mapping):
            raise OperationValidationError("each workflow step must be an object")
        unknown = set(entry) - {"step_id", "operation_id", "spec", "depends_on", "expected_artifacts"}
        if unknown:
            # `source` beside depends_on is the mistake the published vocabulary
            # invites: both are composition-level, but only one lives at the top.
            # "unknown field" would read as "this seam does not exist" and send
            # the author away from a plan that is one move from being correct.
            misplaced = " Did you mean to put it inside `spec`?" if "source" in unknown else ""
            raise OperationValidationError(
                "workflow step contains unknown field(s): "
                + ", ".join(sorted(unknown))
                + misplaced
            )
        step_id = entry.get("step_id")
        if not isinstance(step_id, str) or _STEP_ID_PATTERN.fullmatch(step_id) is None:
            raise OperationValidationError(f"invalid workflow step_id: {step_id!r}")
        if step_id in seen_ids:
            raise OperationValidationError(f"duplicate workflow step_id: {step_id}")
        seen_ids.add(step_id)
        operation_id = entry.get("operation_id")
        if operation_id not in workflow_step_operations():
            raise OperationValidationError(
                f"workflow step {step_id} operation_id is unsupported: {operation_id!r}"
            )
        spec = entry.get("spec")
        if not isinstance(spec, Mapping):
            raise OperationValidationError(f"workflow step {step_id} spec must be an object")
        depends_on = entry.get("depends_on", [])
        if not isinstance(depends_on, list) or any(
            not isinstance(item, str) or not item for item in depends_on
        ):
            raise OperationValidationError(f"workflow step {step_id} depends_on must be step ids")
        # `source` is a composition-level field owned by the workflow, not by
        # any one operation's spec contract, so it is validated here and kept
        # out of the per-operation validator that would reject it as unknown.
        # Keyed on presence, not on truthiness: an explicit `"source": None` is
        # a malformed commitment and must be rejected, never silently dropped.
        declares_source = "source" in spec
        source_commitment = spec.get("source")
        operation_spec = {key: value for key, value in spec.items() if key != "source"}
        if declares_source:
            _validate_source_commitment(step_id, source_commitment)
            # The commitment is only meaningful if the executor is handed the
            # frame it resolves. On an operation that resolves its own data the
            # reference would validate, resolve, pass every integrity check, and
            # then be discarded -- an accepted declaration with no effect, which
            # is the shape this seam exists to eliminate. Close the contract on
            # the consuming side too.
            if operation_id not in registry.STEP_CONSUMES_INPUT_FRAME:
                raise OperationValidationError(
                    f"workflow step {step_id} operation {operation_id} does not read "
                    "a workflow input frame, so it cannot declare a source. Operations "
                    "that can: " + ", ".join(sorted(registry.STEP_CONSUMES_INPUT_FRAME))
                )
        _validate_step_spec(str(operation_id), operation_spec)
        normalized_spec = operation_spec
        if declares_source:
            normalized_spec["source"] = {
                "from_step": source_commitment["from_step"],
                "output": source_commitment["output"],
            }
        normalized.append(
            {
                "step_id": step_id,
                "operation_id": str(operation_id),
                "spec": normalized_spec,
                "depends_on": list(dict.fromkeys(depends_on)),
                "expected_artifacts": [
                    str(item) for item in entry.get("expected_artifacts", []) or []
                ],
            }
        )

    # Resolve source commitments before `_topological_order` runs: until the
    # reference is folded into depends_on, neither the ordering nor the cycle
    # refusal can see that edge at all.
    by_id = {step["step_id"]: step for step in normalized}
    from ..postestimation_steps import bind_model_step_dependencies

    for step in normalized:
        bind_model_step_dependencies(step, by_id, WORKFLOW_STEP_SPEC_CONTRACTS)
    for step in normalized:
        # Keyed on presence for the same reason the spec check above is: an
        # explicit `source: null` was already refused, so a missing key here
        # means the step declared no source rather than a malformed one.
        if "source" not in step["spec"]:
            continue
        source = step["spec"]["source"]
        from_step = source["from_step"]
        if from_step == step["step_id"]:
            raise OperationValidationError(
                f"workflow step {step['step_id']} source refers to itself"
            )
        producer = by_id.get(from_step)
        if producer is None:
            raise OperationValidationError(
                f"workflow step {step['step_id']} source refers to unknown step: {from_step}"
            )
        if producer["operation_id"] not in registry.STEP_PRODUCES_DATASET:
            raise OperationValidationError(
                f"workflow step {step['step_id']} source refers to {from_step}, which "
                f"does not produce a dataset: {producer['operation_id']}. Steps that "
                "produce a dataset: " + ", ".join(sorted(registry.STEP_PRODUCES_DATASET))
            )
        producer_contract = WORKFLOW_STEP_SPEC_CONTRACTS[producer["operation_id"]]
        consumer_contract = WORKFLOW_STEP_SPEC_CONTRACTS[step["operation_id"]]
        accepted_roles = consumer_contract.accepted_dataset_kinds
        produced_role = producer_contract.produced_dataset_kind
        if accepted_roles and produced_role not in accepted_roles:
            raise OperationValidationError(
                f"workflow step {step['step_id']} cannot consume dataset role "
                f"{produced_role!r} from {from_step}; accepted roles: "
                + ", ".join(accepted_roles)
            )
        # Consuming a step's output is an ordering constraint, so the reference
        # becomes a real dependency. Reusing depends_on means the existing
        # topological sort, cycle refusal, fail-closed gating and
        # dependency_fingerprints all cover chained steps with no new machinery.
        if from_step not in step["depends_on"]:
            step["depends_on"] = [*step["depends_on"], from_step]

    known = {step["step_id"] for step in normalized}
    for step in normalized:
        missing = [dep for dep in step["depends_on"] if dep not in known]
        if missing:
            raise OperationValidationError(
                f"workflow step {step['step_id']} depends on unknown step(s): "
                + ", ".join(missing)
            )
        if step["step_id"] in step["depends_on"]:
            raise OperationValidationError(f"workflow step {step['step_id']} depends on itself")

    ordered = _topological_order(normalized)
    # Takes the ordered plan, not the raw one: ancestor resolution depends on it.
    _reject_unreadable_data_sources(ordered)

    if available_columns is not None:
        available = {str(column) for column in available_columns}
        # Each source commitment names a dataset branch, so column visibility
        # is branch-local rather than a mutable global set.  Sibling steps that
        # all consume `first` must see the columns published by `first`, not
        # whichever sibling happened to be validated immediately before them.
        output_columns: dict[str, set[str]] = {}
        ancestors = _step_ancestors(ordered)
        for step in ordered:
            source = step["spec"].get("source")
            if isinstance(source, Mapping):
                input_visible = set(output_columns[source["from_step"]])
            else:
                input_visible = set(available)
                # Preserve the established sourceless replay contract for the
                # two declaration-defined column derivations.  They are not
                # persisted source branches, so their declared output columns
                # are the only ancestor state a sourceless consumer can see.
                for ancestor_id in ancestors[step["step_id"]]:
                    ancestor = next(
                        candidate
                        for candidate in ordered
                        if candidate["step_id"] == ancestor_id
                    )
                    if ancestor["operation_id"] in {
                        "statistical.derive_numeric",
                        "statistical.derive_boolean",
                    }:
                        input_visible.update(output_columns[ancestor_id])
            referenced = _spec_columns(step["operation_id"], step["spec"])
            missing = sorted(referenced - input_visible)
            if missing:
                raise OperationValidationError(
                    f"workflow step {step['step_id']} references missing column(s): "
                    + ", ".join(missing)
                )
            result_visible = set(input_visible)
            if step["operation_id"] == "statistical.derive_boolean":
                result_visible.update(
                    str(recipe["output_name"]) for recipe in step["spec"]["recipes"]
                )
            if step["operation_id"] == "statistical.derive_numeric":
                outputs = {
                    str(recipe["output_name"]) for recipe in step["spec"]["recipes"]
                }
                collisions = sorted(outputs & input_visible)
                if collisions:
                    raise OperationValidationError(
                        "derive_numeric output column already exists: " + ", ".join(collisions)
                    )
                result_visible.update(outputs)
            if step["operation_id"].startswith("data."):
                result_visible = _data_output_columns(
                    step["operation_id"], step["spec"], input_visible
                )
            output_columns[step["step_id"]] = result_visible
    return ordered


def _step_ancestors(steps: list[dict[str, Any]]) -> dict[str, frozenset[str]]:
    """Transitive dependencies per step, from an already topologically ordered plan.

    The ordering is a real precondition, so it is enforced structurally rather
    than by a comment: every dependency is resolved before the step that names
    it, and an unordered input raises KeyError on the spot instead of recursing.
    """

    ancestors: dict[str, frozenset[str]] = {}
    for step in steps:
        collected: set[str] = set()
        for dependency in step["depends_on"]:
            collected.add(dependency)
            collected |= ancestors[dependency]
        ancestors[step["step_id"]] = frozenset(collected)
    return ancestors


def _reject_unreadable_data_sources(steps: list[dict[str, Any]]) -> None:
    """Refuse plans whose declared transforms could not all reach the step reading them.

    Two shapes, one failure: a step estimating on data that is not what the plan
    reads as its input, with nothing going red.

    First, a step that commits to `source` reads exactly that dataset at
    execution time, so any *other* dataset-producing ancestor it declares is
    computed and then dropped without a word -- the author reads the plan as
    "both transforms applied" and gets one of them. Ancestors of the declared
    source are exempt: they are how that dataset was built, so they are already
    inside the frame the step reads.

    Second, a step that declares *no* source is served by the runtime's replay
    path, which reconstructs its ancestors by re-applying their specs to the
    workflow target. That path only knows how to replay
    STEP_REPLAYABLE_BY_RECIPE. Any other dataset producer upstream of it would
    simply be skipped, and the step would run against the original table while
    the plan says otherwise. Today the two sets are equal so this cannot happen;
    the rule exists so that the day P3 adds a transform without wiring it up,
    the plan fails to compile rather than quietly reporting the wrong number.
    """

    by_id = {step["step_id"]: step for step in steps}
    ancestors = _step_ancestors(steps)

    for step in steps:
        # Ordering/model dependencies do not imply data consumption. A kernel
        # consumer reads its explicit model reference; only frame consumers
        # can silently lose an upstream dataset through the replay path.
        if step["operation_id"] not in registry.STEP_CONSUMES_INPUT_FRAME:
            continue
        step_id = step["step_id"]
        if "source" not in step["spec"]:
            unreplayable = sorted(
                candidate
                for candidate in ancestors[step_id]
                if by_id[candidate]["operation_id"] in registry.STEP_PRODUCES_DATASET
                and by_id[candidate]["operation_id"] not in registry.STEP_REPLAYABLE_BY_RECIPE
            )
            if unreplayable:
                raise OperationValidationError(
                    f"workflow step {step_id} does not declare a source, so it reads "
                    "the original table; the dataset(s) produced by "
                    + ", ".join(unreplayable)
                    + " would be ignored. Declare source.from_step to read them."
                )
            continue
        from_step = str(step["spec"]["source"]["from_step"])
        declared_lineage = {from_step} | ancestors[from_step]
        discarded = sorted(
            candidate
            for candidate in ancestors[step_id] - declared_lineage
            if by_id[candidate]["operation_id"] in registry.STEP_PRODUCES_DATASET
        )
        if discarded:
            raise OperationValidationError(
                f"workflow step {step_id} declares more than one data source: "
                f"it reads {from_step}, so the dataset(s) produced by "
                + ", ".join(discarded)
                + " would be silently discarded. A step can only have one data "
                "source; route the other transform through it."
            )


def _validate_source_commitment(step_id: str, source: Any) -> None:
    """Validate one step's declared upstream input reference."""

    if not isinstance(source, Mapping):
        raise OperationValidationError(f"workflow step {step_id} source must be an object")
    unknown = set(source) - {"from_step", "output"}
    if unknown:
        raise OperationValidationError(
            f"workflow step {step_id} source contains unknown field(s): "
            + ", ".join(sorted(unknown))
        )
    # Held to the same pattern as step_id itself: an id that could never name a
    # step is a format error, and reporting it later as an unresolvable
    # reference would point the author at a missing step rather than the typo.
    from_step = source.get("from_step")
    if not isinstance(from_step, str) or _STEP_ID_PATTERN.fullmatch(from_step) is None:
        raise OperationValidationError(
            f"workflow step {step_id} source.from_step must name another step in this plan"
        )
    output = source.get("output")
    if output not in SUPPORTED_STEP_OUTPUTS:
        raise OperationValidationError(
            f"workflow step {step_id} source.output must be one of: "
            + ", ".join(sorted(SUPPORTED_STEP_OUTPUTS))
        )


def _topological_order(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order the plan by dependency, refusing a cycle rather than looping."""

    by_id = {step["step_id"]: step for step in steps}
    state: dict[str, int] = {}
    ordered: list[dict[str, Any]] = []

    def visit(step_id: str, trail: tuple[str, ...]) -> None:
        mark = state.get(step_id, 0)
        if mark == 2:
            return
        if mark == 1:
            raise OperationValidationError(
                "workflow steps contain a dependency cycle: "
                + " -> ".join((*trail, step_id))
            )
        state[step_id] = 1
        for dependency in by_id[step_id]["depends_on"]:
            visit(dependency, (*trail, step_id))
        state[step_id] = 2
        ordered.append(by_id[step_id])

    for step in steps:
        visit(step["step_id"], ())
    return ordered
