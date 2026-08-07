"""P0 composition seam: a step declaring its input as another step's output.

This slice covers the declaration itself, which belongs to the composition
rather than to any one operation's spec contract: a well-formed `source` is
accepted and preserved, and every malformed shape is refused by name. It also
covers the other half of the seam: what a dataset-producing step publishes for
such a reference to resolve against.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.agent.operations import OperationValidationError
from workbench.agent.workflow import (
    WorkflowExecutionError,
    WorkflowExecutor,
    WorkflowStepResult,
    compile_workflow,
)
from workbench.agent import workflow_contracts
from workbench.agent.workflow_contracts import validate_workflow_steps
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
            "outcome": [100.0 + index * 2.5 for index in range(48)],
            "rate_a": [float(index % 17) for index in range(48)],
            "rate_b": [float((index * 7) % 13) for index in range(48)],
            "size": [200.0 + index * 7 for index in range(48)],
        }
    )


def _sourced(step: dict, from_step: str = "first") -> dict:
    step["spec"]["source"] = {"from_step": from_step, "output": "produced_dataset"}
    return step


def _meta_plan() -> list[dict]:
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
        steps=_meta_plan(),
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


_LINEAGE_META_READERS = {
    "statistical.derive_numeric": _numeric_recipe_claims,
    "statistical.explore": _exploration_claims,
    "statistical.derive_boolean": _exploration_claims,
    "statistical.derived_group_summarize": _exploration_claims,
    "model.genesis": _genesis_claims,
    "model.joint_f_test": _post_estimation_claims,
    "model.white_test": _post_estimation_claims,
    "model.quadratic_stationary_point": _post_estimation_claims,
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
