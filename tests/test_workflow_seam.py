"""P0 composition seam: a step declaring its input as another step's output.

This slice covers the declaration itself, which belongs to the composition
rather than to any one operation's spec contract: a well-formed `source` is
accepted and preserved, and every malformed shape is refused by name. It also
covers the other half of the seam: what a dataset-producing step publishes for
such a reference to resolve against.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.agent.operations import OperationValidationError
from workbench.agent.workflow import (
    WorkflowExecutionError,
    WorkflowExecutor,
    compile_workflow,
)
from workbench.agent.workflow_contracts import validate_workflow_steps
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.artifacts import read_json, sha256_file, write_json
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
