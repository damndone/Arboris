"""P0 composition seam: a step declaring its input as another step's output.

This slice covers the declaration itself, which belongs to the composition
rather than to any one operation's spec contract: a well-formed `source` is
accepted and preserved, and every malformed shape is refused by name. It also
covers the other half of the seam: what a dataset-producing step publishes for
such a reference to resolve against.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.agent.operations import OperationValidationError
from workbench.agent.workflow import (
    PERSISTED_STEP_OUTPUT,
    WorkflowExecutionError,
    WorkflowExecutor,
    WorkflowStepResult,
    WorkflowStepState,
    compile_workflow,
)
from workbench.agent import workflow_contracts
from workbench.agent.workflow_contracts import (
    validate_workflow_steps,
    workflow_step_vocabulary,
)
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.artifacts import read_json, sha256_file, write_json
from workbench.graph_store import GraphStore
from workbench.statistical_exploration import resolve_statistical_source


def _numeric_step(step_id: str, output_name: str) -> dict:
    return {
        "step_id": step_id,
        "operation_id": "statistical.derive_numeric",
        "spec": {
            "recipes": [
                {
                    "operator": "multiply",
                    "input_columns": ["size", "weight"],
                    "output_name": output_name,
                }
            ]
        },
    }


def test_step_spec_accepts_a_source_commitment() -> None:
    """A step may declare that its input is another step's output."""

    downstream = _numeric_step("second", "doubled_again")
    downstream["spec"]["source"] = {"from_step": "first", "output": "produced_dataset"}
    steps = [_numeric_step("first", "doubled"), downstream]

    ordered = validate_workflow_steps(steps)

    assert [item["step_id"] for item in ordered] == ["first", "second"]
    assert ordered[1]["spec"]["source"] == {
        "from_step": "first",
        "output": "produced_dataset",
    }


def _step_with_source(source: object) -> list[dict]:
    """One otherwise-valid plan whose single step carries the given source."""

    step = _numeric_step("only", "doubled")
    step["spec"]["source"] = source
    return [step]


def test_explicit_null_source_is_rejected_rather_than_dropped() -> None:
    """A written-out `source: null` is a malformed commitment, not an absent one."""

    with pytest.raises(
        OperationValidationError, match=r"step only source must be an object"
    ):
        validate_workflow_steps(_step_with_source(None))


def test_non_object_source_is_rejected() -> None:
    """A bare step id is not a source commitment."""

    with pytest.raises(
        OperationValidationError, match=r"step only source must be an object"
    ):
        validate_workflow_steps(_step_with_source("first"))


def test_source_with_unknown_field_is_rejected() -> None:
    """Naming the unknown field is what lets the author correct it."""

    with pytest.raises(
        OperationValidationError,
        match=r"step only source contains unknown field\(s\): column",
    ):
        validate_workflow_steps(
            _step_with_source(
                {"from_step": "first", "output": "produced_dataset", "column": "size"}
            )
        )


@pytest.mark.parametrize("from_step", ["", 7, None])
def test_source_without_a_usable_from_step_is_rejected(from_step: object) -> None:
    """from_step must actually name a step."""

    with pytest.raises(
        OperationValidationError,
        match=r"step only source\.from_step must name another step in this plan",
    ):
        validate_workflow_steps(
            _step_with_source({"from_step": from_step, "output": "produced_dataset"})
        )


def test_source_output_outside_the_supported_set_is_rejected() -> None:
    """The output key is a closed set, so a near-miss fails loudly."""

    with pytest.raises(
        OperationValidationError,
        match=r"step only source\.output must be one of: produced_dataset",
    ):
        validate_workflow_steps(
            _step_with_source({"from_step": "first", "output": "produced_data"})
        )


def test_malformed_from_step_is_a_format_error_not_an_unknown_step() -> None:
    """A from_step that cannot be a step id must be named as malformed.

    Reporting it as an unresolvable reference would send the author looking for
    a missing step instead of at the id they mistyped.
    """

    with pytest.raises(
        OperationValidationError,
        match=r"step only source\.from_step must name another step in this plan",
    ):
        validate_workflow_steps(
            _step_with_source({"from_step": "not an id!!", "output": "produced_dataset"})
        )


def test_source_commitment_to_an_unknown_step_is_rejected() -> None:
    """A dangling reference is a compile error, not a runtime surprise."""

    downstream = _numeric_step("second", "doubled_again")
    downstream["spec"]["source"] = {"from_step": "absent", "output": "produced_dataset"}

    with pytest.raises(OperationValidationError, match="unknown step"):
        validate_workflow_steps([_numeric_step("first", "doubled"), downstream])


def test_source_commitment_to_itself_is_rejected() -> None:
    """A step cannot be its own input; that is a plan with no starting point."""

    step = _numeric_step("only", "doubled")
    step["spec"]["source"] = {"from_step": "only", "output": "produced_dataset"}

    with pytest.raises(OperationValidationError, match="refers to itself"):
        validate_workflow_steps([step])


def test_source_commitment_to_a_step_that_produces_no_dataset_is_rejected() -> None:
    """Only steps that persist a dataset can be consumed as an input."""

    downstream = _numeric_step("second", "doubled_again")
    downstream["spec"]["source"] = {"from_step": "explored", "output": "produced_dataset"}
    steps = [
        {
            "step_id": "explored",
            "operation_id": "statistical.explore",
            "spec": {"operation": "corr", "selected_columns": ["size", "outcome"]},
        },
        downstream,
    ]

    with pytest.raises(OperationValidationError, match="does not produce a dataset"):
        validate_workflow_steps(steps)


def test_source_commitment_implies_a_dependency() -> None:
    """Declaring an input is declaring an ordering; the DAG must reflect it."""

    downstream = _numeric_step("second", "doubled_again")
    downstream["spec"]["source"] = {"from_step": "first", "output": "produced_dataset"}

    ordered = validate_workflow_steps([downstream, _numeric_step("first", "doubled")])

    assert [item["step_id"] for item in ordered] == ["first", "second"]
    assert ordered[1]["depends_on"] == ["first"]


def test_source_commitment_cannot_form_a_cycle() -> None:
    """A reference is a dependency, so the existing cycle refusal covers it."""

    first = _numeric_step("first", "doubled")
    first["spec"]["source"] = {"from_step": "second", "output": "produced_dataset"}
    second = _numeric_step("second", "doubled_again")
    second["spec"]["source"] = {"from_step": "first", "output": "produced_dataset"}

    with pytest.raises(OperationValidationError, match="cycle"):
        validate_workflow_steps([first, second])


def _chain_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            # weight is 3.0 so that size * weight is unique in this frame: with
            # a weight of 2.0 the product equals `outcome` column for column,
            # and a derivation that merely copied outcome would still pass.
            "size": [1.0, 2.0, 3.0, 4.0],
            "weight": [3.0, 3.0, 3.0, 3.0],
            "outcome": [2.0, 4.0, 6.0, 8.0],
            "wave": ["a", "a", "b", "b"],
        }
    )


def _compiled_chain(tmp_path: Path, steps: list[dict]):
    frame = _chain_frame()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = compile_workflow(
        workflow_id="wf_seam",
        target={
            "run_id": run_id,
            "node_ref": "stage:source",
            "artifact_id": artifact_id,
        },
        preconditions={"context_fingerprint": "sha256:fixture"},
        steps=steps,
        available_columns=list(frame.columns),
    )
    return project, draft


def test_a_dataset_producing_step_publishes_a_resolvable_binding(tmp_path: Path) -> None:
    """The output block carries everything a downstream step needs to resolve."""

    project, draft = _compiled_chain(tmp_path, [_numeric_step("first", "doubled")])
    executor = build_workflow_step_executor(project, draft)

    result = executor(draft.steps[0], {})

    produced = result.payload["produced_dataset"]
    assert set(produced) == {
        "schema_version",
        "run_id",
        "node_ref",
        "artifact_id",
        "content_sha256",
        "result_fingerprint",
    }
    assert produced["schema_version"] == "workflow-produced-dataset.v1"
    assert produced["run_id"] == draft.target["run_id"]
    assert produced["result_fingerprint"] == result.result_fingerprint

    # Resolve the binding through the resolver a consuming step will use, rather
    # than re-reading the index by hand: that is what "resolvable" has to mean,
    # and it also enforces that node_ref and artifact_id name the same dataset.
    context, published = resolve_statistical_source(
        project,
        source_run_id=produced["run_id"],
        source_node_id=produced["node_ref"],
        source_artifact_id=produced["artifact_id"],
    )

    # The published hash must match the bytes the resolver actually read. This
    # is the check a consumer can fail; result_fingerprint cannot serve here,
    # since re-deriving it from the same step record compares it to itself.
    assert produced["content_sha256"] == context["source_sha256"]
    assert list(published["doubled"]) == [3.0, 6.0, 9.0, 12.0]


def _chained_step(step_id: str, from_step: str, output_name: str, on_column: str) -> dict:
    """A step that reads another step's output and derives from a column in it."""

    step = _numeric_step(step_id, output_name)
    step["spec"]["source"] = {"from_step": from_step, "output": "produced_dataset"}
    step["spec"]["recipes"] = [
        {
            "operator": "multiply",
            "input_columns": [on_column, "size"],
            "output_name": output_name,
        }
    ]
    return step


def test_a_chained_plan_runs_end_to_end_with_the_right_numbers(tmp_path: Path) -> None:
    """A two-step chain completes and the arithmetic is right.

    Values are asserted, not just status: "the run finished" and "the run
    computed the right thing" are different claims, and only the second one is
    worth anything to whoever reads the result.

    What this does NOT prove is *where* `second` got its input. It passed before
    the executor learned to resolve a declared `source` at all, because replaying
    `first`'s recipes onto the original target happens to produce the same
    numbers -- see the next test for why that is currently unavoidable, and
    treat `test_a_chained_step_reads_the_bytes_the_upstream_step_published` as
    the only evidence covering the seam itself.
    """

    project, draft = _compiled_chain(
        tmp_path,
        [
            _numeric_step("first", "doubled"),
            _chained_step("second", "first", "scaled", "doubled"),
        ],
    )

    state = WorkflowExecutor(project).execute(
        draft, build_workflow_step_executor(project, draft)
    )

    assert state.steps["second"].status == "completed", state.steps["second"].error
    frame = pd.read_csv(
        _artifact_path(
            project,
            str(draft.target["run_id"]),
            state.steps["second"].artifact_ids[0],
        )
    )
    # doubled = size * weight = size * 3; scaled = doubled * size = 3 * size**2.
    assert list(frame["doubled"]) == [3.0, 6.0, 9.0, 12.0]
    assert list(frame["scaled"]) == [3.0, 12.0, 27.0, 48.0]


def test_a_chained_step_reads_the_bytes_the_upstream_step_published(
    tmp_path: Path,
) -> None:
    """Proves *where* the input came from, not merely that the values are right.

    Why this has to go the long way round: no value assertion can currently tell
    "read the dataset the upstream step persisted" apart from "replay the
    upstream step's recipes onto the original target". `statistical.derive_numeric`
    is today's only operation with `produces_dataset=True`, and it can only add
    columns -- it never changes row count, drops a column, or alters a dtype.
    So the two mechanisms are provably identical column for column on every
    chain that can be written right now, and a passing value test says nothing
    about which one ran.

    Rewriting the persisted dataset is what separates them: a step that resolves
    its declared source reads those bytes and refuses them as no longer the ones
    the completed step published, while a step replaying recipes never looks at
    the file and sails past.

    When P3's data transforms land this stops being the only available lever --
    a reshape changes row count and a subset drops columns, so the mechanisms
    become distinguishable by value. This test stays valid either way; it is
    just no longer carrying the seam alone.

    The run's own artifact index is rewritten to match, which is the whole point
    -- that is the state a run directory rebuilt between resumes would be in, so
    the resolver's index check passes and the binding's content hash is the only
    thing standing between the plan and a frame nobody's step produced.
    """

    project, draft = _compiled_chain(
        tmp_path,
        [
            _numeric_step("first", "doubled"),
            _chained_step("second", "first", "scaled", "doubled"),
        ],
    )
    executor = build_workflow_step_executor(project, draft)
    upstream = executor(draft.steps[0], {})

    produced = upstream.payload["produced_dataset"]
    persisted = _artifact_path(project, produced["run_id"], produced["artifact_id"])
    tampered = pd.read_csv(persisted)
    tampered["doubled"] = [30.0, 60.0, 90.0, 120.0]
    persisted.write_text(tampered.to_csv(index=False), encoding="utf-8")
    _reindex_artifact(project, produced["run_id"], produced["artifact_id"], persisted)

    with pytest.raises(WorkflowExecutionError, match="different content"):
        executor(draft.steps[1], {"first": upstream})


def test_an_unresolved_source_refuses_rather_than_falling_back(tmp_path: Path) -> None:
    """No upstream result means no input -- not the original table instead.

    Returning the workflow's own target here would be the exact defect this
    seam exists to remove: the step would estimate on untransformed data, report
    `completed`, and carry provenance saying it consumed the transform.
    """

    project, draft = _compiled_chain(
        tmp_path,
        [
            _numeric_step("first", "doubled"),
            _chained_step("second", "first", "scaled", "doubled"),
        ],
    )
    executor = build_workflow_step_executor(project, draft)

    with pytest.raises(
        WorkflowExecutionError,
        match=r"workflow step second source first has not completed",
    ):
        executor(draft.steps[1], {})


def test_an_upstream_without_the_declared_binding_refuses(tmp_path: Path) -> None:
    """A completed upstream that published nothing is still an unresolved input.

    Distinguished from the unresolved case on purpose: "the step never ran" and
    "the step ran but did not publish what you committed to reading" send an
    author to different places. Neither may quietly become the original table.
    """

    project, draft = _compiled_chain(
        tmp_path,
        [
            _numeric_step("first", "doubled"),
            _chained_step("second", "first", "scaled", "doubled"),
        ],
    )
    executor = build_workflow_step_executor(project, draft)
    upstream = executor(draft.steps[0], {})
    without_binding = WorkflowStepResult(
        artifact_ids=list(upstream.artifact_ids),
        row_counts=dict(upstream.row_counts),
        result_fingerprint=upstream.result_fingerprint,
        payload={
            key: value
            for key, value in upstream.payload.items()
            if key != "produced_dataset"
        },
    )

    with pytest.raises(
        WorkflowExecutionError,
        match=r"workflow step second source first published no 'produced_dataset' binding",
    ):
        executor(draft.steps[1], {"first": without_binding})


def _reindex_artifact(
    project: Path, run_id: str, artifact_id: str, path: Path
) -> None:
    """Re-record an artifact's digest so the run index agrees with its file."""

    index_path = project / "runs" / run_id / "artifacts_index.json"
    index = read_json(index_path)
    for record in index["artifacts"]:
        if record["artifact_id"] == artifact_id:
            record["sha256"] = sha256_file(path)
            write_json(index_path, index)
            return
    raise AssertionError(f"unregistered artifact: {artifact_id}")


def _artifact_path(project: Path, run_id: str, artifact_id: str) -> Path:
    """Locate a registered artifact's file through the run's own index."""

    run_root = project / "runs" / run_id
    index = read_json(run_root / "artifacts_index.json")
    for record in index["artifacts"]:
        if record["artifact_id"] == artifact_id:
            return run_root / record["path"]
    raise AssertionError(f"unregistered artifact: {artifact_id}")


def test_a_second_dataset_producer_alongside_a_source_is_rejected() -> None:
    """Two upstream datasets, one read: refuse rather than discard one silently."""

    downstream = _chained_step("second", "first", "scaled", "doubled")
    downstream["depends_on"] = ["unrelated"]

    with pytest.raises(
        OperationValidationError,
        match=r"step second declares more than one data source",
    ):
        validate_workflow_steps(
            [
                _numeric_step("first", "doubled"),
                _numeric_step("unrelated", "sidelined"),
                downstream,
            ]
        )


def test_the_declared_source_own_ancestors_are_not_a_second_source() -> None:
    """A chain is one source, not three: only strays outside the lineage fail."""

    ordered = validate_workflow_steps(
        [
            _numeric_step("base", "doubled"),
            _chained_step("middle", "base", "scaled", "doubled"),
            _chained_step("last", "middle", "rescaled", "scaled"),
        ]
    )

    assert [item["step_id"] for item in ordered] == ["base", "middle", "last"]


def test_a_step_that_never_receives_the_frame_cannot_declare_a_source() -> None:
    """Closing the contract on the consuming side, not only the producing one.

    `report.compose` resolves nothing from the data -- the runtime never hands
    it an input frame. A `source` on it would validate, resolve, pass every
    integrity check, and then be dropped, leaving a plan that reads as though a
    transform were applied to a step that never opened the data at all.
    """

    report = {
        "step_id": "report",
        "operation_id": "report.compose",
        "depends_on": ["first"],
        "spec": {
            "sections": ["descriptives"],
            "source": {"from_step": "first", "output": "produced_dataset"},
        },
    }

    with pytest.raises(
        OperationValidationError,
        match=r"step report operation report\.compose does not read a workflow input frame",
    ):
        validate_workflow_steps([_numeric_step("first", "doubled"), report])


def test_an_unreplayable_producer_upstream_of_a_sourceless_step_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule that is deliberately inert today, and must not be inert in P3.

    A step declaring no `source` is served by the recipe-replay path, which can
    only reconstruct the operations in STEP_REPLAYABLE_BY_RECIPE. Any other
    dataset producer upstream of it is skipped in silence and the step runs
    against the original table while the plan says otherwise.

    Today every producer happens to be replayable, so the rule can never fire on
    a real plan -- which is exactly why it needs a test that removes that
    coincidence. Emptying the whitelist is the same condition P3 creates the
    moment it registers a reshape without wiring it into the replay path.
    """

    monkeypatch.setattr(workflow_contracts, "STEP_REPLAYABLE_BY_RECIPE", frozenset())

    downstream = _numeric_step("second", "scaled")
    downstream["depends_on"] = ["first"]

    with pytest.raises(
        OperationValidationError,
        match=r"step second does not declare a source, so it reads the original table",
    ):
        validate_workflow_steps([_numeric_step("first", "doubled"), downstream])


def test_the_replay_path_and_the_compile_rule_read_the_same_declaration() -> None:
    """One declaration, two consumers -- so they cannot drift into disagreement.

    The runtime decides what to replay and the compiler decides what must be
    read through `source`. If those were two hand-maintained lists, P3 could
    satisfy one and not the other, which is the silent-wrong-number case this
    rule exists to prevent.
    """

    declared = {
        operation_id
        for operation_id, contract in workflow_contracts.WORKFLOW_STEP_SPEC_CONTRACTS.items()
        if contract.replayable_by_recipe
    }

    assert workflow_contracts.STEP_REPLAYABLE_BY_RECIPE == declared
    assert declared <= workflow_contracts.STEP_PRODUCES_DATASET


def _binding_but(tmp_path: Path, **overrides: object):
    """A completed upstream whose published binding has been tampered with."""

    project, draft = _compiled_chain(
        tmp_path,
        [_numeric_step("first", "doubled"), _chained_step("second", "first", "scaled", "doubled")],
    )
    executor = build_workflow_step_executor(project, draft)
    upstream = executor(draft.steps[0], {})
    binding = {**upstream.payload["produced_dataset"], **overrides}
    for key, value in overrides.items():
        if value is None:
            binding.pop(key, None)
    tampered = dataclasses.replace(
        upstream, payload={**upstream.payload, "produced_dataset": binding}
    )
    return draft, executor, {"first": tampered}


def test_a_binding_from_an_unknown_schema_version_is_refused(tmp_path: Path) -> None:
    """The version is compared, not merely written.

    A binding read back on resume can outlive the code that wrote it, so an
    unrecognised version has to stop the step rather than be read optimistically
    with whatever fields happen to still line up.
    """

    draft, executor, previous = _binding_but(tmp_path, schema_version="workflow-produced-dataset.v2")

    with pytest.raises(WorkflowExecutionError, match=r"published a .* binding, but this runtime reads"):
        executor(draft.steps[1], previous)


def test_a_binding_missing_a_required_field_names_the_field(tmp_path: Path) -> None:
    """A bare KeyError here becomes error="'node_ref'" and tells the reader nothing."""

    draft, executor, previous = _binding_but(tmp_path, node_ref=None)

    with pytest.raises(WorkflowExecutionError, match=r"incomplete binding, missing: node_ref"):
        executor(draft.steps[1], previous)


def test_a_binding_from_another_run_is_refused_rather_than_dangling(
    tmp_path: Path,
) -> None:
    """A cross-run binding would put a parent on the graph that this run lacks.

    The derived dataset is persisted on the workflow's own target run, and the
    graph mutated is that run's graph. Pointing `parent_stage_id` at a node
    living in a different run would write an edge whose source does not exist
    here -- a lineage claim no reader can follow, and no error anywhere.

    No plan can produce this today, because the only dataset producer publishes
    the target run's id. That is a property of today's operations, not a
    guarantee of the contract, so it is checked rather than assumed.
    """

    draft, executor, previous = _binding_but(tmp_path, run_id="run_elsewhere")

    with pytest.raises(
        WorkflowExecutionError,
        match=r"published a binding on run run_elsewhere, but this workflow runs on run",
    ):
        executor(draft.steps[1], previous)


def _run_chain(tmp_path: Path) -> tuple[Path, object, dict]:
    """Run `first -> second` where `second` declares `first` as its source."""

    project, draft = _compiled_chain(
        tmp_path,
        [
            _numeric_step("first", "doubled"),
            _chained_step("second", "first", "scaled", "doubled"),
        ],
    )
    executor = build_workflow_step_executor(project, draft)
    upstream = executor(draft.steps[0], {})
    downstream = executor(draft.steps[1], {"first": upstream})
    return project, draft, {"first": upstream, "second": downstream}


def _derived_node_id(result: WorkflowStepResult) -> str:
    return str(result.payload["produced_dataset"]["node_ref"])


def test_a_chained_step_claims_its_upstream_as_its_graph_parent(tmp_path: Path) -> None:
    """The graph must name the dataset the step actually consumed.

    A node whose parent is `stage:source` says the original table produced it.
    That claim is read by rerun (which would believe editing the source affects
    this node), by comparison, by AI explanation and by the report -- and it is
    false the moment the step declared a `source`. Nothing errors; the graph
    simply lies.
    """

    project, draft, results = _run_chain(tmp_path)

    graph = GraphStore(project / "runs").read(str(draft.target["run_id"]))
    upstream_node = _derived_node_id(results["first"])
    child_node = _derived_node_id(results["second"])

    assert graph.nodes[child_node].parent_stage_id == upstream_node
    assert graph.nodes[upstream_node].parent_stage_id == "stage:source"
    assert graph.edges[f"edge:{child_node}"].source_id == upstream_node
    assert graph.branches[
        graph.nodes[child_node].branch_id
    ].forked_from_node_id == upstream_node


def test_a_chained_step_records_its_upstream_dataset_in_the_recipe(
    tmp_path: Path,
) -> None:
    """recipe.json is the replayable record; its source must be the real one.

    Naming the original artifact here would make the recipe unreplayable in the
    precise way that is hardest to notice: replaying it reproduces different
    numbers while every hash in the file checks out.
    """

    project, draft, results = _run_chain(tmp_path)

    upstream = results["first"].payload["produced_dataset"]
    recipe_path = _artifact_path(
        project,
        str(draft.target["run_id"]),
        results["second"].artifact_ids[1],
    )
    recipe = read_json(recipe_path)

    assert recipe["source"]["artifact_id"] == upstream["artifact_id"]
    assert recipe["source"]["sha256"] == upstream["content_sha256"]


def test_a_chained_step_registers_its_upstream_artifact_as_its_input(
    tmp_path: Path,
) -> None:
    """The artifacts index is the other lineage record, and must agree."""

    project, draft, results = _run_chain(tmp_path)

    upstream_artifact = results["first"].payload["produced_dataset"]["artifact_id"]
    data_artifact_id, recipe_artifact_id = results["second"].artifact_ids[:2]
    index = read_json(
        project / "runs" / str(draft.target["run_id"]) / "artifacts_index.json"
    )
    records = {item["artifact_id"]: item for item in index["artifacts"]}

    assert records[data_artifact_id]["inputs"] == [upstream_artifact]
    assert records[recipe_artifact_id]["inputs"] == [
        upstream_artifact,
        data_artifact_id,
    ]


def test_a_sourceless_step_still_claims_the_original_table(tmp_path: Path) -> None:
    """The unchanged half of the contract, asserted rather than assumed.

    A step that declares no source really is derived from the workflow target,
    so its lineage must keep naming it -- correcting the chained case must not
    quietly re-point the ordinary one.
    """

    project, draft = _compiled_chain(tmp_path, [_numeric_step("first", "doubled")])
    executor = build_workflow_step_executor(project, draft)

    result = executor(draft.steps[0], {})

    run_id = str(draft.target["run_id"])
    node_id = _derived_node_id(result)
    graph = GraphStore(project / "runs").read(run_id)
    assert graph.nodes[node_id].parent_stage_id == str(draft.target["node_ref"])
    assert graph.edges[f"edge:{node_id}"].source_id == str(draft.target["node_ref"])

    data_artifact_id, recipe_artifact_id = result.artifact_ids[:2]
    recipe = read_json(_artifact_path(project, run_id, recipe_artifact_id))
    assert recipe["source"]["artifact_id"] == str(draft.target["artifact_id"])
    context, _frame = resolve_statistical_source(
        project,
        source_run_id=run_id,
        source_node_id=str(draft.target["node_ref"]),
        source_artifact_id=str(draft.target["artifact_id"]),
    )
    assert recipe["source"]["sha256"] == context["source_sha256"]

    index = read_json(project / "runs" / run_id / "artifacts_index.json")
    records = {item["artifact_id"]: item for item in index["artifacts"]}
    assert records[data_artifact_id]["inputs"] == [str(draft.target["artifact_id"])]
    assert records[recipe_artifact_id]["inputs"] == [
        str(draft.target["artifact_id"]),
        data_artifact_id,
    ]


# --- The lineage meta-guard -------------------------------------------------
#
# Every operation the runtime hands a resolved input frame to may declare a
# `source`, and every one of them writes down where its output came from. Those
# two facts have to stay joined: a step that computes from an upstream dataset
# and then records `draft.target` produces no error, no red test and a graph
# that says the original table produced numbers it never touched.
#
# Nothing about the code makes that joining automatic -- `_lineage_source` is
# reusable, but forgetting to call it costs nothing. So the guard is derived
# from the contract instead: the case registry below must cover
# STEP_CONSUMES_INPUT_FRAME exactly, and each case runs a real chain and reads
# the reference actually written to disk. Registering a new consuming operation
# without wiring its lineage turns this file red twice over -- once because the
# registry is incomplete, and once because the claim it writes is the target.


def _meta_frame() -> pd.DataFrame:
    """A frame big enough to estimate on, with a column worth deriving."""

    return pd.DataFrame(
        {
            "wave": [1, 2, 3, 4] * 12,
            "time": pd.date_range("2020-01-01", periods=48, freq="D"),
            "outcome": [100.0 + index * 2.5 for index in range(48)],
            "rate_a": [float(index % 17) for index in range(48)],
            "rate_b": [float((index * 7) % 13) for index in range(48)],
            "size": [200.0 + index * 7 for index in range(48)],
        }
    )


def _sourced(step: dict, from_step: str = "first") -> dict:
    step["spec"]["source"] = {"from_step": from_step, "output": "produced_dataset"}
    return step


def _meta_plan(*, secondary_run_id: str, secondary_artifact_id: str) -> list[dict]:
    """One plan whose every consuming step reads `first`'s output.

    `first` is the only step without a `source`: it is the upstream whose
    published binding every other step here must end up naming.
    """

    return [
        {
            "step_id": "first",
            "operation_id": "statistical.derive_numeric",
            "spec": {
                "recipes": [
                    {
                        "operator": "multiply",
                        "input_columns": ["size", "rate_a"],
                        "output_name": "scaled",
                    }
                ]
            },
        },
        _sourced(
            {
                "step_id": "detail",
                "operation_id": "statistical.explore",
                "spec": {
                    "operation": "summarize_detail",
                    "selected_columns": ["size", "scaled"],
                },
            }
        ),
        _sourced(
            {
                "step_id": "scatter",
                "operation_id": "statistical.explore",
                "spec": {
                    "operation": "scatter",
                    "plots": [{"x_column": "scaled", "y_column": "outcome"}],
                },
            }
        ),
        _sourced(
            {
                "step_id": "chained",
                "operation_id": "statistical.derive_numeric",
                "spec": {
                    "recipes": [
                        {
                            "operator": "multiply",
                            "input_columns": ["scaled", "size"],
                            "output_name": "rescaled",
                        }
                    ]
                },
            }
        ),
        _sourced(
            {
                "step_id": "split",
                "operation_id": "statistical.derive_boolean",
                "depends_on": ["detail"],
                "spec": {
                    "recipes": [
                        {
                            "source_column": "size",
                            "percentile": 25,
                            "comparison": "lte",
                            "output_name": "small_unit",
                        }
                    ]
                },
            }
        ),
        _sourced(
            {
                "step_id": "compare",
                "operation_id": "statistical.derived_group_summarize",
                "depends_on": ["split"],
                "spec": {
                    "groups": [
                        {
                            "source_column": "size",
                            "percentile": 25,
                            "comparison": "lte",
                            "output_name": "small_unit",
                        }
                    ],
                    "summarize_columns": ["outcome"],
                },
            }
        ),
        _sourced(
            {
                "step_id": "models",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "ols",
                    "covariance": "unadjusted",
                    "branches": [
                        {
                            "branch_id": "curved",
                            "outcome": "outcome",
                            "predictors": ["scaled", "rate_b"],
                            "polynomials": [{"column": "scaled", "degree": 2}],
                        }
                    ],
                },
            }
        ),
        _sourced(
            {
                "step_id": "joint",
                "operation_id": "model.joint_f_test",
                "depends_on": ["models"],
                "spec": {
                    "branch_id": "curved",
                    "term_selectors": [{"kind": "linear", "column": "rate_b"}],
                },
            }
        ),
        _sourced(
            {
                "step_id": "white",
                "operation_id": "model.white_test",
                "depends_on": ["models"],
                "spec": {"branch_id": "curved"},
            }
        ),
        _sourced(
            {
                "step_id": "stationary",
                "operation_id": "model.quadratic_stationary_point",
                "depends_on": ["models"],
                "spec": {"branch_id": "curved", "column": "scaled"},
            }
        ),
        _sourced(
            {
                "step_id": "data_merge",
                "operation_id": "data.merge",
                "spec": {
                    "secondary_run_id": secondary_run_id,
                    "secondary_node_id": "stage:source",
                    "secondary_artifact_id": secondary_artifact_id,
                    "keys": ["outcome"],
                    "how": "left",
                    "indicator": "merge_status",
                },
            }
        ),
        _sourced(
            {
                "step_id": "data_append",
                "operation_id": "data.append",
                "spec": {
                    "secondary_run_id": secondary_run_id,
                    "secondary_node_id": "stage:source",
                    "secondary_artifact_id": secondary_artifact_id,
                    "schema_policy": "union",
                },
            }
        ),
        _sourced(
            {
                "step_id": "data_reshape",
                "operation_id": "data.reshape",
                "spec": {
                    "direction": "wide_to_long",
                    "id_columns": ["wave", "outcome"],
                    "value_columns": ["rate_a", "rate_b"],
                    "var_name": "metric",
                    "value_name": "metric_value",
                },
            }
        ),
        _sourced(
            {
                "step_id": "data_subset",
                "operation_id": "data.subset",
                "spec": {
                    "columns": ["wave", "scaled"],
                    "filters": [{"column": "wave", "op": "ge", "value": 1}],
                },
            }
        ),
        _sourced(
            {
                "step_id": "data_feature_recipe",
                "operation_id": "data.feature_recipe",
                "spec": {
                    "recipe_id": "meta_interaction",
                    "recipe_operation_id": "interaction",
                    "inputs": ["rate_a", "rate_b"],
                    "output": "rate_interaction",
                    "parameters": {"left": "rate_a", "right": "rate_b"},
                },
            }
        ),
        _sourced(
            {
                "step_id": "data_dedupe",
                "operation_id": "data.dedupe",
                "spec": {"columns": ["wave", "outcome"], "keep": "first"},
            }
        ),
        _sourced(
            {
                "step_id": "data_rename",
                "operation_id": "data.rename",
                "spec": {"mapping": {"scaled": "scaled_renamed"}},
            }
        ),
        _sourced(
            {
                "step_id": "data_aggregate",
                "operation_id": "data.aggregate",
                "spec": {
                    "group_by": ["wave"],
                    "aggregations": [
                        {"column": "outcome", "func": "mean", "output": "outcome_mean"}
                    ],
                },
            }
        ),
        _sourced(
            {
                "step_id": "data_fill_missing",
                "operation_id": "data.fill_missing",
                "spec": {
                    "strategies": [{"column": "rate_a", "strategy": "mean"}],
                },
            }
        ),
        _sourced(
            {
                "step_id": "data_tsset",
                "operation_id": "data.tsset",
                "spec": {"time_column": "time", "frequency": "D"},
            }
        ),
        _sourced(
            {
                "step_id": "data_lag",
                "operation_id": "data.lag",
                "spec": {"columns": ["outcome"], "lags": [1]},
            }
        ),
    ]


# Which step in the plan above exercises which operation. Several operations
# reach the persist layer by more than one route -- `statistical.explore` alone
# has a plain branch and a plots branch that call it from different places --
# so this maps to a list rather than a single step.
_LINEAGE_META_STEPS: dict[str, tuple[str, ...]] = {
    "statistical.derive_numeric": ("chained",),
    "statistical.explore": ("detail", "scatter"),
    "statistical.derive_boolean": ("split",),
    "statistical.derived_group_summarize": ("compare",),
    "model.genesis": ("models",),
    "model.joint_f_test": ("joint",),
    "model.white_test": ("white",),
    "model.quadratic_stationary_point": ("stationary",),
    "data.merge": ("data_merge",),
    "data.append": ("data_append",),
    "data.reshape": ("data_reshape",),
    "data.subset": ("data_subset",),
    "data.feature_recipe": ("data_feature_recipe",),
    "data.dedupe": ("data_dedupe",),
    "data.rename": ("data_rename",),
    "data.aggregate": ("data_aggregate",),
    "data.fill_missing": ("data_fill_missing",),
    "data.tsset": ("data_tsset",),
    "data.lag": ("data_lag",),
}

# Operations that write no source reference at all, and so cannot be checked
# by reading one back. Empty today, and deliberately explicit: a silent skip
# here would turn this guard into a test that passes because it looked at
# nothing. Adding an entry requires stating why the operation records no
# provenance, which is a claim worth having to write down.
_LINEAGE_META_UNRECORDED: dict[str, str] = {}


def _meta_project(tmp_path: Path):
    """A project whose source run carries the upload model.genesis re-estimates from."""

    from workbench.lineage.run_inputs import write_run_inputs
    from workbench.lineage.upload_store import store_upload_bytes

    frame = _meta_frame()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    upload_sha = store_upload_bytes(
        project, frame.to_csv(index=False).encode("utf-8"), filename="fixture.csv"
    )
    write_run_inputs(
        project / "runs" / run_id,
        form={"model_type": "auto", "y": "", "x": ""},
        upload={"sha256": upload_sha, "filename": "fixture.csv"},
        rerun_of=None,
        from_node=None,
        rerun_reason="initial",
        override_hash=None,
        dag_hash="fixture-dag",
    )
    draft = compile_workflow(
        workflow_id="wf_lineage_meta",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "sha256:fixture"},
        steps=_meta_plan(
            secondary_run_id=run_id,
            secondary_artifact_id=artifact_id,
        ),
        available_columns=list(frame.columns),
    )
    return project, draft


def _exploration_claims(project: Path, draft, step_id: str, result) -> dict[str, dict[str, str]]:
    """Every persisted exploration record this step wrote, and its named source."""

    run_id = str(draft.target["run_id"])
    claims: dict[str, dict[str, str]] = {}
    for artifact_id in result.artifact_ids:
        path = _artifact_path(project, run_id, artifact_id)
        if path.suffix == ".json":
            payload = read_json(path)
            if not isinstance(payload, dict) or "source_artifact_id" not in payload:
                continue
            claims[f"{step_id}:{artifact_id}"] = {
                "artifact_id": str(payload["source_artifact_id"]),
                "sha256": str(payload["source_sha256"]),
            }
            continue
        if path.suffix != ".txt":
            # Exports (CSV, PDF) carry the numbers, not a provenance header.
            continue
        # The human-readable transcript states the same provenance in prose,
        # and is the copy a person is most likely to believe. It is checked
        # here rather than trusted to follow the JSON.
        lines = dict(
            line.split(": ", 1)
            for line in path.read_text(encoding="utf-8").splitlines()
            if ": " in line
        )
        if "source_artifact_id" not in lines:
            continue
        claims[f"{step_id}:{artifact_id}"] = {
            "artifact_id": lines["source_artifact_id"],
            "sha256": lines["source_sha256"],
        }
    return claims


def _numeric_recipe_claims(project: Path, draft, step_id: str, result) -> dict[str, dict[str, str]]:
    """The replayable recipe plus the graph edge the derived dataset hangs from."""

    run_id = str(draft.target["run_id"])
    recipe = read_json(_artifact_path(project, run_id, result.artifact_ids[1]))
    node_id = str(result.payload["produced_dataset"]["node_ref"])
    graph = GraphStore(project / "runs").read(run_id)
    return {
        f"{step_id}:recipe": {
            "artifact_id": str(recipe["source"]["artifact_id"]),
            "sha256": str(recipe["source"]["sha256"]),
        },
        f"{step_id}:graph": {"node_ref": str(graph.nodes[node_id].parent_stage_id)},
    }


def _post_estimation_claims(project: Path, draft, step_id: str, result) -> dict[str, dict[str, str]]:
    """The `source` block of the persisted test/post-estimation artifact."""

    run_id = str(draft.target["run_id"])
    payload = read_json(_artifact_path(project, run_id, result.artifact_ids[0]))
    source = payload["source"]
    return {
        f"{step_id}:artifact": {
            "artifact_id": str(source["artifact_id"]),
            "node_ref": str(source["node_ref"]),
            "sha256": str(source["sha256"]),
        }
    }


def _genesis_claims(project: Path, draft, step_id: str, result) -> dict[str, dict[str, str]]:
    """The exploration context stored on every Genesis draft this step created."""

    from workbench.lineage.pipeline_drafts import PipelineDraftStore

    store = PipelineDraftStore(project)
    claims: dict[str, dict[str, str]] = {}
    for summary in store.list():
        stored = store.get(summary["draft_id"])
        context = stored.draft.get("exploration_context") or {}
        if context.get("workflow_step_id") != step_id:
            continue
        claims[f"{step_id}:{summary['draft_id']}"] = {
            "artifact_id": str(context["source_artifact_id"]),
            "node_ref": str(context["source_node_id"]),
            "sha256": str(context["source_sha256"]),
        }
    return claims


def _data_management_claims(
    project: Path, draft, step_id: str, result
) -> dict[str, dict[str, str]]:
    """Read data-operation provenance from all three durable records."""

    run_id = str(draft.target["run_id"])
    binding = result.payload["produced_dataset"]
    data_artifact_id = str(binding["artifact_id"])
    recipe_artifact_id = str(result.artifact_ids[1])
    index = read_json(project / "runs" / run_id / "artifacts_index.json")
    records = {item["artifact_id"]: item for item in index["artifacts"]}
    data_record = records[data_artifact_id]
    recipe = read_json(_artifact_path(project, run_id, recipe_artifact_id))
    source_sha = (
        recipe.get("preview", {}).get("source_sha256")
        if isinstance(recipe.get("preview"), dict)
        else recipe.get("source_sha256")
    )
    graph = GraphStore(project / "runs").read(run_id)
    child = graph.nodes[str(binding["node_ref"])]
    return {
        f"{step_id}:artifact-input": {
            "artifact_id": str(data_record["inputs"][0]),
        },
        f"{step_id}:recipe": {
            "sha256": str(source_sha),
        },
        f"{step_id}:graph": {
            "node_ref": str(child.parent_stage_id),
        },
    }


_LINEAGE_META_READERS = {
    "statistical.derive_numeric": _numeric_recipe_claims,
    "statistical.explore": _exploration_claims,
    "statistical.derive_boolean": _exploration_claims,
    "statistical.derived_group_summarize": _exploration_claims,
    "model.genesis": _genesis_claims,
    "model.joint_f_test": _post_estimation_claims,
    "model.white_test": _post_estimation_claims,
    "model.quadratic_stationary_point": _post_estimation_claims,
    "data.merge": _data_management_claims,
    "data.append": _data_management_claims,
    "data.reshape": _data_management_claims,
    "data.subset": _data_management_claims,
    "data.feature_recipe": _data_management_claims,
    "data.dedupe": _data_management_claims,
    "data.rename": _data_management_claims,
    "data.aggregate": _data_management_claims,
    "data.fill_missing": _data_management_claims,
    "data.tsset": _data_management_claims,
    "data.lag": _data_management_claims,
}


def test_the_lineage_case_registry_covers_every_consuming_operation() -> None:
    """Registering a consuming operation must force a lineage decision.

    The registry is the half of the guard that cannot be satisfied by accident:
    a new entry in STEP_CONSUMES_INPUT_FRAME with no case here fails before any
    chain runs, and the only way past it is to either exercise the operation or
    write down why it records no source at all.
    """

    covered = set(_LINEAGE_META_STEPS) | set(_LINEAGE_META_UNRECORDED)

    assert covered == set(workflow_contracts.STEP_CONSUMES_INPUT_FRAME)
    assert not (set(_LINEAGE_META_STEPS) & set(_LINEAGE_META_UNRECORDED))
    assert set(_LINEAGE_META_READERS) == set(_LINEAGE_META_STEPS)


def test_every_consuming_operation_records_the_dataset_it_actually_read(
    tmp_path: Path,
) -> None:
    """One chain per consuming operation, checked against what reached the disk.

    Each step here computes from `first`'s derived dataset. Recording
    `draft.target` instead is invisible from the numbers -- they are right --
    and visible only here: the artifact, the recipe, the graph edge and the
    Genesis context all have to name the binding that was actually read.
    """

    project, draft = _meta_project(tmp_path)
    executor = build_workflow_step_executor(project, draft)
    by_id = {step.step_id: step for step in draft.steps}

    results: dict[str, WorkflowStepResult] = {}
    for step in draft.steps:
        results[step.step_id] = executor(step, results)

    binding = results["first"].payload["produced_dataset"]
    expected = {
        "artifact_id": str(binding["artifact_id"]),
        "node_ref": str(binding["node_ref"]),
        "sha256": str(binding["content_sha256"]),
    }
    # The whole guard rests on the two being distinguishable: if the derived
    # dataset happened to share the target's identity, every assertion below
    # would pass no matter what the runtime wrote.
    assert expected["artifact_id"] != str(draft.target["artifact_id"])
    assert expected["node_ref"] != str(draft.target["node_ref"])

    checked: dict[str, dict[str, str]] = {}
    for operation_id, step_ids in _LINEAGE_META_STEPS.items():
        reader = _LINEAGE_META_READERS[operation_id]
        for step_id in step_ids:
            assert by_id[step_id].operation_id == operation_id
            claims = reader(project, draft, step_id, results[step_id])
            assert claims, f"{operation_id} wrote no source reference to read back"
            checked.update(claims)

    assert checked
    # Collected rather than asserted one at a time: when several paths lie, the
    # reader needs the whole list, not whichever one sorts first.
    lies = [
        f"{where} records {field}={value!r}, but the step read {expected[field]!r}"
        for where, claim in sorted(checked.items())
        for field, value in sorted(claim.items())
        if value != expected[field]
    ]
    assert not lies, "lineage records name a dataset the step never read:\n" + "\n".join(lies)


# --- Resume: the binding has to survive the gap between two passes ----------
#
# `WorkflowExecutor.execute` rebuilds `completed_results` for already-completed
# steps out of persisted `WorkflowStepState`, not out of the results the
# executor returned in the earlier pass. Anything a step published that is not
# in that state is gone by the time a resumed downstream step asks for it.


def _state_path(project: Path, workflow_id: str = "wf_seam") -> Path:
    return project / "workbench" / "workflows" / f"{workflow_id}.jsonl"


def _state_records(project: Path, workflow_id: str = "wf_seam") -> list[dict]:
    return [
        json.loads(line)
        for line in _state_path(project, workflow_id).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _interrupted_chain(tmp_path: Path):
    """Run `first -> second` through the executor, failing on `second`.

    Uses the real step executor for `first`, so the state left behind is the
    state a genuine interruption leaves behind, not a hand-built approximation.
    """

    project, draft = _compiled_chain(
        tmp_path,
        [
            _numeric_step("first", "doubled"),
            _chained_step("second", "first", "scaled", "doubled"),
        ],
    )
    real = build_workflow_step_executor(project, draft)

    def interrupted(step, previous):
        if step.step_id == "second":
            raise WorkflowExecutionError("simulated interruption")
        return real(step, previous)

    first_pass = WorkflowExecutor(project).execute(draft, interrupted)
    assert first_pass.status == "failed"
    assert first_pass.steps["first"].status == "completed"
    assert first_pass.steps["second"].status == "failed"
    return project, draft, real


def test_a_resumed_chain_can_still_resolve_the_upstream_binding(tmp_path: Path) -> None:
    """Resume rebuilds completed results from state, so the binding must persist.

    Without persistence this is not a wrong number, it is a chain that can never
    be resumed at all: `second` asks `first` for the dataset it published, and
    the rebuilt result carries an empty payload.
    """

    project, draft, real = _interrupted_chain(tmp_path)

    resumed = WorkflowExecutor(project).execute(draft, real)

    assert resumed.steps["second"].status == "completed", resumed.steps["second"].error
    assert resumed.status == "completed"


def test_the_published_binding_reaches_the_persisted_state_file(tmp_path: Path) -> None:
    """Assert on the bytes on disk, not only that a resume happened to work.

    A resume can pass for reasons that have nothing to do with persistence --
    an in-process cache, a step that re-derives its own input. What the next
    process gets is whatever is in this file.
    """

    project, draft, _ = _interrupted_chain(tmp_path)

    completed = [
        record
        for record in _state_records(project)
        if record["steps"]["first"]["status"] == "completed"
    ]
    assert completed, "the first step never reached a completed state record"
    binding = completed[-1]["steps"]["first"]["produced_dataset"]

    assert binding["schema_version"] == "workflow-produced-dataset.v1"
    assert binding["run_id"] == draft.target["run_id"]
    # The persisted binding must name the derived dataset, not the workflow's
    # own target: a binding that pointed back at the target would resume
    # cleanly and feed the untransformed table to every downstream step.
    assert binding["artifact_id"] != str(draft.target["artifact_id"])
    assert binding["node_ref"] != str(draft.target["node_ref"])
    _, published = resolve_statistical_source(
        project,
        source_run_id=str(binding["run_id"]),
        source_node_id=str(binding["node_ref"]),
        source_artifact_id=str(binding["artifact_id"]),
    )
    assert list(published["doubled"]) == [3.0, 6.0, 9.0, 12.0]


def test_only_the_declared_output_binding_is_persisted(tmp_path: Path) -> None:
    """The resume surface is the declared contract, not the whole payload.

    `produced_dataset` is the one block another step may commit to consuming.
    Persisting the entire payload would widen the coupling between steps from
    that contract to "whatever the upstream happened to put there", which is
    the exact seam this slice exists to narrow.
    """

    project, _, _ = _interrupted_chain(tmp_path)

    completed = [
        record
        for record in _state_records(project)
        if record["steps"]["first"]["status"] == "completed"
    ][-1]["steps"]["first"]

    # `output_columns` is the other half of this producer's live payload.
    assert "output_columns" not in completed
    assert "payload" not in completed


def test_the_persisted_output_key_is_the_whole_supported_set() -> None:
    """If a second consumable output is declared, resume has to carry it too.

    The state field is named for one binding. Growing SUPPORTED_STEP_OUTPUTS
    without growing the state would reintroduce exactly this bug for the new
    output, silently, so the growth has to fail here first.
    """

    assert workflow_contracts.SUPPORTED_STEP_OUTPUTS == {PERSISTED_STEP_OUTPUT}


def test_a_state_record_without_a_binding_still_loads(tmp_path: Path) -> None:
    """State written before binding persistence must not break on read."""

    legacy = WorkflowStepState.from_dict(
        {
            "step_id": "first",
            "fingerprint": "sha256:legacy",
            "status": "completed",
            "artifact_ids": ["workflow_derived_numeric_legacy"],
            "row_counts": {"doubled": 4},
            "error": None,
            "result_fingerprint": "sha256:legacy",
        }
    )

    assert legacy.produced_dataset is None
    assert legacy.status == "completed"


def test_a_non_object_persisted_binding_is_refused_rather_than_read(tmp_path: Path) -> None:
    """A corrupt binding in the state file is not a binding with missing keys."""

    with pytest.raises(WorkflowExecutionError, match=r"produced_dataset.*must be an object"):
        WorkflowStepState.from_dict(
            {
                "step_id": "first",
                "fingerprint": "sha256:legacy",
                "status": "completed",
                "produced_dataset": "workflow_derived_numeric_legacy",
            }
        )


def test_a_binding_lost_across_resume_names_the_persistence_gap(tmp_path: Path) -> None:
    """The two ways a binding can be absent send a reader to different places.

    "the upstream published nothing" points at the producing step's output;
    "the binding did not survive resume" points at the round trip through the
    state file. Reporting the first for the second sends whoever hits it to
    audit a step whose output is intact.

    What the branch may NOT do is pick one cause of the loss and assert it. A
    stale state record and a producer that never published are both reachable
    here, and they need opposite responses -- re-run, or fix the producer. A
    message naming only the first tells whoever hit the second to re-run into an
    identical failure.
    """

    project, draft, real = _interrupted_chain(tmp_path)

    # Rewrite the state the way a pre-persistence version of this executor
    # would have written it, then resume against it.
    stripped = []
    for record in _state_records(project):
        for step_state in record["steps"].values():
            step_state.pop(PERSISTED_STEP_OUTPUT, None)
        stripped.append(json.dumps(record, ensure_ascii=False))
    _state_path(project).write_text("\n".join(stripped) + "\n", encoding="utf-8")

    resumed = WorkflowExecutor(project).execute(draft, real)

    assert resumed.steps["second"].status == "failed"
    error = resumed.steps["second"].error or ""
    assert "did not survive" in error, error
    assert "persisted workflow state" in error, error
    # Must not be reported as an upstream that published nothing.
    assert "published no" not in error, error
    # Both causes have to be on offer, with what to do about each.
    assert "re-running the plan from the start" in error, error
    assert "without publishing the binding" in error, error


def test_a_step_publishing_an_unstorable_binding_fails_rather_than_losing_it(
    tmp_path: Path,
) -> None:
    """A non-Mapping binding is dropped in silence if it is merely coerced away.

    Nothing downstream would see the loss on this pass -- the consuming step
    reads the live payload. It surfaces one resume later, as a state record with
    no binding, and the resume path then reports it as a persistence gap: the
    state file blamed for a value the producer handed over and the executor
    threw away. Refusing at the point of loss is what keeps the later diagnosis
    honest.
    """

    project, draft = _compiled_chain(
        tmp_path,
        [
            _numeric_step("first", "doubled"),
            _chained_step("second", "first", "scaled", "doubled"),
        ],
    )
    real = build_workflow_step_executor(project, draft)

    def publishes_a_list(step, previous):
        result = real(step, previous)
        if step.step_id != "first":
            return result
        return dataclasses.replace(
            result,
            payload={**result.payload, "produced_dataset": ["not", "an", "object"]},
        )

    state = WorkflowExecutor(project).execute(draft, publishes_a_list)

    assert state.steps["first"].status == "failed"
    error = state.steps["first"].error or ""
    assert "produced_dataset that must be an object, got list" in error, error
    # The step must not be recorded as completed-with-nothing-published, which
    # is the shape a later resume would misdiagnose.
    assert state.steps["first"].produced_dataset is None
    assert state.steps["second"].status == "blocked"


# --- The three guarantees the composition seam rests on -----------------------
#
# Task 1-5 built the mechanism; what follows pins the three properties that make
# it safe to cache, resume and compose. Each one is written so that the defect it
# names would otherwise pass silently.


def _head_variant(input_columns: list[str]) -> list[dict]:
    """`first -> second`, varying only what `first` multiplies.

    `second` is deliberately untouched between variants: it always derives
    `scaled` from `doubled`, the column `first` publishes under both. That is
    what makes the fingerprint claim below mean something -- the downstream spec
    really is byte-identical across the two plans.
    """

    first = _numeric_step("first", "doubled")
    first["spec"]["recipes"][0]["input_columns"] = input_columns
    return [first, _chained_step("second", "first", "scaled", "doubled")]


def _two_plans_on_one_project(tmp_path: Path, plan_a: list[dict], plan_b: list[dict]):
    """Compile two plans against the same target, so only the steps differ.

    Compiling against two projects would give the drafts different run ids, and
    every fingerprint would then differ for a reason that has nothing to do with
    the property under test.
    """

    frame = _chain_frame()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    target = {"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id}

    def build(steps: list[dict]):
        return compile_workflow(
            workflow_id="wf_seam",
            target=dict(target),
            preconditions={"context_fingerprint": "sha256:fixture"},
            steps=steps,
            available_columns=list(frame.columns),
        )

    return build(plan_a), build(plan_b)


def test_changing_the_chain_head_reidentifies_every_step_below_it(
    tmp_path: Path,
) -> None:
    """Guarantee 1: a step's identity covers what it consumes, not just its spec.

    `_make_step` folds `dependency_fingerprints` into each step's identity, and
    Task 2 put `from_step` into `depends_on` -- so a chained step inherits that
    coverage. This asserts the consequence: edit the head of a chain and the step
    below it is a different step, *even though its own spec is unchanged*.

    Without it, a cache or a resume keyed on the downstream fingerprint would
    hand back a result computed from the previous version of the upstream table.
    Nothing about that result looks wrong; it is simply an answer to the old
    question.
    """

    baseline, altered = _two_plans_on_one_project(
        tmp_path,
        _head_variant(["size", "weight"]),
        _head_variant(["size", "outcome"]),
    )

    # The premise, asserted rather than assumed: the downstream steps are the
    # same declaration in both plans. If this ever stops holding, the test below
    # is proving nothing.
    assert baseline.steps[1].spec == altered.steps[1].spec
    assert baseline.steps[1].step_id == altered.steps[1].step_id
    assert baseline.steps[1].depends_on == altered.steps[1].depends_on
    assert baseline.target == altered.target

    assert baseline.steps[0].fingerprint != altered.steps[0].fingerprint
    assert baseline.steps[1].fingerprint != altered.steps[1].fingerprint
    assert baseline.plan_fingerprint != altered.plan_fingerprint


def test_a_failed_chain_head_blocks_the_step_below_it(tmp_path: Path) -> None:
    """Guarantee 2: no upstream output means no run -- never the original table.

    `second` here is written so that it *could* run on the workflow target: it
    multiplies `weight` by `size`, both of which exist in the untransformed
    frame. Do not "simplify" it to derive from `doubled` like the other chained
    steps in this file.

    The reason is not that a `doubled` downstream would let the guard pass --
    it would not. The assertion is `== "blocked"`, so the `failed` that a
    missing column produces is caught too. The reason is that a fallback can be
    written two ways, and only this one pins both:

      * fall back to a branch that replays the upstream recipes: a `doubled`
        downstream and a `weight` downstream both reach `completed`;
      * fall back to the bare `source_frame` with no replay: a `weight`
        downstream still reaches `completed`, while a `doubled` downstream dies
        on the missing column and goes red for the wrong reason.

    So `weight` is the only shape that reproduces the production accident under
    *either* implementation of the defect, instead of sometimes catching it as
    a KeyError. A guard that goes red for the wrong reason still passes review
    and stops protecting the moment the fallback is written the other way.

    The failure mode being excluded is the expensive one this repository has
    already shipped once: a step quietly reading the pre-transform data, the run
    reporting success, the report reading normally, and every number in it being
    an answer about the wrong dataset.
    """

    project, draft = _compiled_chain(
        tmp_path,
        [
            _numeric_step("first", "doubled"),
            _chained_step("second", "first", "scaled", "weight"),
        ],
    )
    real = build_workflow_step_executor(project, draft)

    def head_fails(step, previous):
        if step.step_id == "first":
            raise WorkflowExecutionError("simulated head failure")
        return real(step, previous)

    state = WorkflowExecutor(project).execute(draft, head_fails)

    assert state.steps["first"].status == "failed"
    # blocked, specifically: not `failed` (which would say `second` was tried
    # and broke) and not `completed` (which would say it produced something).
    assert state.steps["second"].status == "blocked", state.steps["second"].error
    assert state.steps["second"].artifact_ids == ()
    assert state.steps["second"].produced_dataset is None
    assert state.status == "failed"

    # And nothing was computed behind the status: `scaled` is the column only
    # `second` writes, so its absence from every table in the run is the
    # evidence that no fallback result reached disk.
    run_root = project / "runs" / str(draft.target["run_id"])
    for path in sorted(run_root.rglob("*.csv")):
        assert "scaled" not in pd.read_csv(path).columns, path


def _explore_step(step_id: str) -> dict:
    """One exploration declaration, reused verbatim on both sides."""

    return {
        "step_id": step_id,
        "operation_id": "statistical.explore",
        "spec": {
            "operation": "summarize_detail",
            # Columns that exist in the target and in the derived table alike,
            # so the two steps really are the same exploration.
            "selected_columns": ["size", "weight"],
        },
    }


def test_the_same_exploration_on_a_derived_table_is_a_different_identity(
    tmp_path: Path,
) -> None:
    """Guarantee 3: the fingerprint follows the data actually read.

    Two steps, the same `ExplorationSpec`, the same workflow target. One reads
    the target; the other reads a derived table published by `first`. They must
    not land on the same identity.

    That identity is a path -- `artifacts/statistical_exploration/{fp}.json`.
    A collision has two outcomes, both bad: the second exploration silently
    returns the first one's stored numbers, or the store refuses a perfectly
    legal plan as ambiguous. Today `derive_numeric` only appends columns, so a
    collision would return numbers that happen to agree; once P3's subset and
    reshape change rows and values, the same collision returns numbers that do
    not.
    """

    from workbench.agent.workflow_runtime import _exploration_spec, _lineage_source

    project, draft = _compiled_chain(
        tmp_path,
        [
            _numeric_step("first", "doubled"),
            _explore_step("direct"),
            _sourced(_explore_step("derived"), "first"),
        ],
    )
    by_id = {step.step_id: step for step in draft.steps}

    # The premise: one and the same exploration on both sides. The `source`
    # commitment is a routing instruction, not part of the exploration, so it
    # does not reach the spec the fingerprint is computed from -- which is
    # exactly why the digest has to carry the difference.
    assert _exploration_spec(by_id["direct"].spec) == _exploration_spec(
        by_id["derived"].spec
    )

    executor = build_workflow_step_executor(project, draft)
    upstream = executor(by_id["first"], {})
    direct = executor(by_id["direct"], {})

    # Check the digest each step's identity is keyed on BEFORE the derived step
    # runs, because the exploration store refuses a colliding artifact binding
    # on its own. Waiting for that would make this guard red for a reason it
    # does not own -- it would be leaning on another layer's determinism check,
    # and would go quiet the moment that check moved or relaxed.
    source_context, _ = resolve_statistical_source(
        project,
        source_run_id=str(draft.target["run_id"]),
        source_node_id=str(draft.target["node_ref"]),
        source_artifact_id=str(draft.target["artifact_id"]),
    )
    published = str(upstream.payload["produced_dataset"]["content_sha256"])
    direct_sha = _lineage_source(draft, by_id["direct"], source_context, {})["sha256"]
    derived_sha = _lineage_source(
        draft, by_id["derived"], source_context, {"first": upstream}
    )["sha256"]

    assert direct_sha == str(source_context["source_sha256"])
    # The derived step keys on the table it read, not the workflow's target.
    assert derived_sha == published, derived_sha
    assert derived_sha != direct_sha

    derived = executor(by_id["derived"], {"first": upstream})

    assert direct.result_fingerprint != derived.result_fingerprint
    # The identity is a location, so state the consequence directly: the two
    # records must not share an artifact.
    assert set(direct.artifact_ids).isdisjoint(derived.artifact_ids)


# --- The seam's only reader that is not a test -------------------------------
#
# Everything above verifies that a declared `source` is validated, resolved,
# executed and recovered correctly. None of it puts the field within reach of
# the planning agent, which learns real field names from exactly one place:
# workflow_step_vocabulary(). A seam the agent cannot name is a seam only the
# test suite uses.


def test_the_vocabulary_publishes_the_source_field() -> None:
    """The planning agent's only route to the composition seam."""

    source = workflow_step_vocabulary()["source"]

    assert set(source["shape"]) == {"from_step", "output"}
    assert source["purpose"]
    assert source["semantics"]


def test_the_published_source_sets_are_the_declared_ones() -> None:
    """Published from the same constants the validator refuses against.

    A hand-written list here would be a second place to remember, and the one
    that goes stale: the agent would be taught an operation the compiler
    rejects, or -- worse -- never told about one it would have accepted.
    """

    source = workflow_step_vocabulary()["source"]

    assert set(source["outputs"]) == set(workflow_contracts.SUPPORTED_STEP_OUTPUTS)
    assert set(source["produced_by"]) == set(workflow_contracts.STEP_PRODUCES_DATASET)
    assert set(source["declarable_by"]) == set(workflow_contracts.STEP_CONSUMES_INPUT_FRAME)


def test_the_published_sets_track_the_declarations_they_are_read_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drift guard: a newly declared capability must publish itself.

    This is the live half of the derivation chain. The other half --
    ``constant == comprehension over WORKFLOW_STEP_SPEC_CONTRACTS`` -- is
    asserted in the contract tests below; together they say that registering a
    step operation with ``produces_dataset=True`` reaches the agent with no
    second edit. Standing in for that future registration by extending the
    constants is what makes the guard fail against a hard-coded list, which is
    the failure mode it exists to catch.
    """

    monkeypatch.setattr(
        workflow_contracts,
        "STEP_PRODUCES_DATASET",
        frozenset({*workflow_contracts.STEP_PRODUCES_DATASET, "data.future_reshape"}),
    )
    monkeypatch.setattr(
        workflow_contracts,
        "STEP_CONSUMES_INPUT_FRAME",
        frozenset({*workflow_contracts.STEP_CONSUMES_INPUT_FRAME, "data.future_reshape"}),
    )
    monkeypatch.setattr(
        workflow_contracts,
        "SUPPORTED_STEP_OUTPUTS",
        frozenset({*workflow_contracts.SUPPORTED_STEP_OUTPUTS, "produced_summary"}),
    )

    source = workflow_step_vocabulary()["source"]

    assert "data.future_reshape" in source["produced_by"]
    assert "data.future_reshape" in source["declarable_by"]
    assert "produced_summary" in source["outputs"]


def test_the_source_sets_are_derived_from_the_step_contracts() -> None:
    """The other half of the chain: constants are never hand-kept lists."""

    contracts = workflow_contracts.WORKFLOW_STEP_SPEC_CONTRACTS

    assert workflow_contracts.STEP_PRODUCES_DATASET == {
        operation_id
        for operation_id, contract in contracts.items()
        if contract.produces_dataset
    }
    assert workflow_contracts.STEP_CONSUMES_INPUT_FRAME == {
        operation_id
        for operation_id, contract in contracts.items()
        if contract.consumes_input_frame
    }


def test_the_agent_protocol_text_carries_the_source_field() -> None:
    """The vocabulary dict is not the prompt; the rendered lines are.

    The chain protocol renders selected vocabulary keys into text, so a key
    added to the dict and not to the renderer is published to nobody. That is
    the same out-of-reach failure this whole version exists to fix, and it
    would be invisible to a dict-level assertion.
    """

    from workbench.http.agent_routes import _step_vocabulary_lines

    rendered = _step_vocabulary_lines()

    assert "source" in rendered
    assert "from_step" in rendered
    for operation_id in workflow_contracts.STEP_PRODUCES_DATASET:
        assert operation_id in rendered


def test_a_source_beside_depends_on_is_told_where_it_belongs() -> None:
    """The likeliest mistake gets the least useful message unless we help.

    The vocabulary says `source` lives inside `spec`, but it sits alongside
    `depends_on` conceptually, so an author placing it beside `depends_on` is
    one move from a correct plan. A bare "unknown field" reads as "this seam
    does not exist" and sends them to look for another way to express it.
    """

    misplaced = _numeric_step("second", "scaled")
    misplaced["source"] = {"from_step": "first", "output": "produced_dataset"}

    with pytest.raises(OperationValidationError, match=r"inside `spec`"):
        validate_workflow_steps([_numeric_step("first", "doubled"), misplaced])
