"""`code.execute` operation tests.

These exercise the real sandbox (no mocks): every preview here actually runs
Python in an isolated subprocess. Tests are skipped only where the host has no
isolation backend at all, which is itself asserted to be fail-closed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json, sha256_file
from workbench.code_execution import (
    CodeExecuteSpecV1,
    CodeExecuteValidationError,
    NondeterministicCodeError,
    apply_code_execute,
    code_execute_execution_key,
    preview_code_execute,
)
from workbench.sandbox import isolation_backend

from tests.test_data_column_cast import _source_project
from tests.test_data_columns_cast import _model_project

pytestmark = pytest.mark.skipif(
    isolation_backend() is None,
    reason="no OS sandbox backend on this host; code.execute is fail-closed here",
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"age": [10, 11, 12], "income": [100.0, 200.0, 300.0]})


def _spec(run_id: str, artifact_id: str, code: str, **kwargs) -> CodeExecuteSpecV1:
    return CodeExecuteSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        code=code,
        **kwargs,
    )


def test_spec_rejects_empty_code_bad_language_and_oversized_code() -> None:
    with pytest.raises(ValueError, match="code must be a non-empty string"):
        _spec("r", "a", "   ")
    with pytest.raises(ValueError, match="language"):
        _spec("r", "a", "result = df", language="ruby")
    with pytest.raises(ValueError, match="at most"):
        _spec("r", "a", "x" * 20_001)
    with pytest.raises(ValueError, match="output_format"):
        _spec("r", "a", "result = df", output_format="parquet")


def test_preview_really_runs_the_code_and_reports_the_schema_diff(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    spec = _spec(run_id, artifact_id, "result = df.assign(doubled=df['age'] * 2)")

    preview = preview_code_execute(project, spec)

    assert preview.status == "ready"
    assert preview.error is None
    assert preview.row_count_before == 3
    assert preview.row_count_after == 3
    assert preview.columns_added == ("doubled",)
    assert preview.columns_removed == ()
    assert [row["doubled"] for row in preview.result_preview_rows] == [20, 22, 24]
    assert preview.schema_fingerprint_before != preview.schema_fingerprint_after
    assert preview.result_fingerprint


def test_preview_writes_nothing_into_the_project(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    before = {p: sha256_file(p) for p in sorted((project / "runs").rglob("*")) if p.is_file()}

    preview = preview_code_execute(
        project, _spec(run_id, artifact_id, "result = df.assign(x=1)")
    )
    assert preview.status == "ready"

    after = {p: sha256_file(p) for p in sorted((project / "runs").rglob("*")) if p.is_file()}
    assert after == before, "preview must be a disposable trial run, not a write"
    assert not (project / "runs" / run_id / "derived" / "code_execute").exists()


def test_preview_reports_user_code_errors_as_blocked_not_exceptions(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())

    preview = preview_code_execute(
        project, _spec(run_id, artifact_id, "result = df['nope'] + 1")
    )

    assert preview.status == "blocked"
    assert preview.fingerprint == ""
    assert preview.error is not None
    assert "KeyError" in preview.error


def test_preview_blocks_when_result_is_missing_or_not_a_dataframe(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())

    missing = preview_code_execute(project, _spec(run_id, artifact_id, "x = df.shape"))
    assert missing.status == "blocked"
    assert "did not define `result`" in (missing.error or "")

    wrong_type = preview_code_execute(project, _spec(run_id, artifact_id, "result = 42"))
    assert wrong_type.status == "blocked"
    assert "must be a pandas DataFrame" in (wrong_type.error or "")
    assert "int" in (wrong_type.error or "")


def test_preview_captures_stdout_so_the_terminal_can_show_it(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())

    preview = preview_code_execute(
        project, _spec(run_id, artifact_id, "print('hello from the sandbox')\nresult = df")
    )

    assert preview.status == "ready"
    assert "hello from the sandbox" in preview.stdout


def test_code_cannot_reach_the_network(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    code = (
        "import socket\n"
        "socket.create_connection(('1.1.1.1', 80), timeout=5)\n"
        "result = df\n"
    )

    preview = preview_code_execute(project, _spec(run_id, artifact_id, code))

    assert preview.status == "blocked"
    assert preview.error


def test_code_cannot_overwrite_the_source_artifact(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    index = read_json(project / "runs" / run_id / "artifacts_index.json")
    source_rel = next(
        item["path"] for item in index["artifacts"] if item["artifact_id"] == artifact_id
    )
    source_path = project / "runs" / run_id / source_rel
    original = source_path.read_bytes()

    code = f"open({str(source_path)!r}, 'w').write('destroyed')\nresult = df\n"
    preview = preview_code_execute(project, _spec(run_id, artifact_id, code))

    assert preview.status == "blocked"
    assert source_path.read_bytes() == original, "source artifact must be physically unwritable"


def test_apply_materializes_a_child_node_recipe_and_node_index(tmp_path: Path) -> None:
    from workbench.artifacts import write_json
    from workbench.lineage.node_index import NODE_INDEX_FILENAME

    project, run_id, artifact_id = _model_project(tmp_path, _frame())
    write_json(
        project / "runs" / run_id / NODE_INDEX_FILENAME,
        {
            "stage:source": {
                "node_hash": "a" * 64,
                "producing_stage": "cleaning",
                "cas_ref": {"node_hash": "a" * 64, "artifact": "data.csv"},
            }
        },
    )
    spec = _spec(run_id, artifact_id, "result = df.assign(doubled=df['age'] * 2)")
    preview = preview_code_execute(project, spec)

    effect = apply_code_execute(project, spec, preview)

    run_root = project / "runs" / run_id
    artifact_path = run_root / effect.artifact_path
    assert artifact_path.is_file()
    written = pd.read_csv(artifact_path)
    assert list(written["doubled"]) == [20, 22, 24]

    recipe = read_json(run_root / effect.recipe_path)
    assert recipe["schema_version"] == "code-execute.v1"
    assert recipe["spec"]["code"] == spec.code
    assert recipe["result"]["result_fingerprint"] == preview.result_fingerprint

    from workbench.graph_store import GraphStore

    graph = GraphStore(project / "runs").read(run_id)
    child = graph.nodes[effect.child_node_id]
    assert child.parent_stage_id == "stage:source"
    assert child.payload_ref == effect.artifact_path
    annotation = child.annotations[0]
    assert annotation["operation_id"] == "code.execute"
    assert annotation["code_sha256"] == spec.code_sha256

    from workbench.lineage.node_index import NODE_INDEX_FILENAME

    index = read_json(run_root / NODE_INDEX_FILENAME)
    entry = index[effect.child_node_id]
    assert entry["node_hash"] == sha256_file(artifact_path)
    assert entry["producing_stage"] == "code.execute"


def test_apply_marks_downstream_models_for_rerun(tmp_path: Path) -> None:
    project, run_id, artifact_id = _model_project(tmp_path, _frame())
    spec = _spec(run_id, artifact_id, "result = df.assign(x=1)")
    preview = preview_code_execute(project, spec)

    apply_code_execute(project, spec, preview)

    from workbench.graph_store import GraphStore

    graph = GraphStore(project / "runs").read(run_id)
    model = graph.nodes["model:ols"]
    invalidation = [a for a in model.annotations if a.get("type") == "downstream_invalidation"]
    assert len(invalidation) == 1
    assert invalidation[0]["reason"] == "code_execute"
    assert invalidation[0]["rerun_required"] is True


def test_apply_is_idempotent_for_one_execution_key(tmp_path: Path) -> None:
    project, run_id, artifact_id = _model_project(tmp_path, _frame())
    spec = _spec(run_id, artifact_id, "result = df.assign(x=1)")
    preview = preview_code_execute(project, spec)

    first = apply_code_execute(project, spec, preview)
    second = apply_code_execute(project, spec, preview)

    assert first == second
    from workbench.graph_store import GraphStore

    graph = GraphStore(project / "runs").read(run_id)
    children = [n for n in graph.nodes if n.startswith("code-exec:")]
    assert children == [first.child_node_id]
    index = read_json(project / "runs" / run_id / "artifacts_index.json")
    ids = [item["artifact_id"] for item in index["artifacts"]]
    assert ids.count(first.artifact_id) == 1


def test_execution_key_is_deterministic_for_the_same_code_and_source(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    spec = _spec(run_id, artifact_id, "result = df.assign(x=1)")

    first = preview_code_execute(project, spec)
    second = preview_code_execute(project, spec)

    assert first.fingerprint == second.fingerprint
    assert code_execute_execution_key(spec, first) == code_execute_execution_key(spec, second)


def test_nondeterministic_code_is_refused_at_execution_and_writes_nothing(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    code = "import random\nresult = df.assign(noise=[random.random() for _ in range(len(df))])\n"
    spec = _spec(run_id, artifact_id, code)
    preview = preview_code_execute(project, spec)
    assert preview.status == "ready"

    with pytest.raises(NondeterministicCodeError):
        apply_code_execute(project, spec, preview)

    derived = project / "runs" / run_id / "derived" / "code_execute"
    written = [p for p in derived.rglob("data.csv")] if derived.exists() else []
    assert written == [], "a result the user never confirmed must not be materialized"


def test_apply_rejects_a_blocked_preview(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    spec = _spec(run_id, artifact_id, "result = df['nope']")
    preview = preview_code_execute(project, spec)

    with pytest.raises(CodeExecuteValidationError, match="blocked"):
        apply_code_execute(project, spec, preview)


def test_apply_rejects_a_preview_from_a_different_spec(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    preview = preview_code_execute(project, _spec(run_id, artifact_id, "result = df.assign(x=1)"))
    other = _spec(run_id, artifact_id, "result = df.assign(y=2)")

    with pytest.raises(CodeExecuteValidationError, match="does not match"):
        apply_code_execute(project, other, preview)


def test_xlsx_output_round_trips_through_the_schema_sidecar(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(tmp_path, _frame())
    spec = _spec(
        run_id,
        artifact_id,
        "result = df.assign(code=df['age'].astype(str))",
        output_format="xlsx",
    )
    preview = preview_code_execute(project, spec)
    assert preview.status == "ready"

    effect = apply_code_execute(project, spec, preview)

    assert effect.artifact_path.endswith("data.xlsx")
    from workbench.data_operations import _read_frame

    frame = _read_frame(project / "runs" / run_id / effect.artifact_path)
    assert str(frame["code"].dtype) in {"string", "object", "str"}
    assert list(frame["code"]) == ["10", "11", "12"]
