from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.artifacts import read_json, write_json
from workbench.graph_store import GraphStore
from workbench.lineage.node_index import NODE_INDEX_FILENAME
from workbench.sandbox import isolation_backend

pytestmark = pytest.mark.skipif(
    isolation_backend() is None,
    reason="no OS sandbox backend on this host; code.execute is fail-closed here",
)


def test_code_execute_replay_repairs_state_after_registration_failpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash after materialization must not turn replay into an orphan success."""

    import workbench.code_execution as code_execution
    from workbench.agent.execution import InjectedOperationCrash

    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"age": [1, 2], "name": ["a", "b"]}),
    )
    run_calls = 0

    def fake_run(source_path, _spec):
        nonlocal run_calls
        run_calls += 1
        frame = code_execution._read_frame(source_path).assign(x=1)
        return code_execution._CodeRunOutcome(
            ok=True,
            frame=frame,
            stdout="",
            error=None,
        )

    monkeypatch.setattr(code_execution, "_run_code", fake_run)
    spec = code_execution.CodeExecuteSpecV1(
        source_run_id=run_id,
        source_node_id="stage:source",
        source_artifact_id=artifact_id,
        code="result = df.assign(x=1)",
    )
    preview = code_execution.preview_code_execute(project, spec)
    execution = code_execution.code_execute_execution_key(spec, preview)
    key = execution.removeprefix("exec_")
    effect, artifact_rel, recipe_rel = code_execution._effect_for(key, spec.output_format)
    run_root = project / "runs" / run_id
    write_json(
        run_root / NODE_INDEX_FILENAME,
        {
            "stage:source": {
                "node_hash": "source-hash",
                "producing_stage": "source",
                "cas_ref": {"node_hash": "source-hash", "artifact": "data.csv"},
            }
        },
    )

    original_register = code_execution._ensure_registered_artifact
    crashed = False

    def crash_before_registration(*args, **kwargs):
        nonlocal crashed
        if not crashed:
            crashed = True
            raise InjectedOperationCrash("after_materialization_before_registration")
        return original_register(*args, **kwargs)

    monkeypatch.setattr(
        code_execution,
        "_ensure_registered_artifact",
        crash_before_registration,
    )
    with pytest.raises(InjectedOperationCrash):
        code_execution.apply_code_execute(project, spec, preview)

    assert (run_root / artifact_rel).is_file()
    assert (run_root / recipe_rel).is_file()
    monkeypatch.setattr(code_execution, "_ensure_registered_artifact", original_register)

    replayed = code_execution.apply_code_execute(project, spec, preview)

    registered = read_json(run_root / "artifacts_index.json")["artifacts"]
    graph = GraphStore(project / "runs").read(run_id)
    node_index = read_json(run_root / NODE_INDEX_FILENAME)
    assert replayed == effect
    assert any(item["artifact_id"] == effect.artifact_id for item in registered)
    assert any(item["artifact_id"] == effect.recipe_artifact_id for item in registered)
    assert effect.child_node_id in graph.nodes
    assert effect.child_node_id in node_index
    # One preview run, one failed materialization run, and one replay run.
    assert run_calls == 3
