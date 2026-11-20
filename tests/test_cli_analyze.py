"""`workbench analyze` runs any catalog operation through the manual service."""
from __future__ import annotations

import json

import pandas as pd
import pytest
from typer.testing import CliRunner

from tests.test_cli_data_operations import source
from workbench.cli import app

WIDE = {"COLUMNS": "400"}


def invoke(*args):
    return CliRunner().invoke(app, list(map(str, args)), env=WIDE)


def target(tmp_path):
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "y": [2.0, 1.0, 4.0, 3.0, 6.0, 5.0]})
    return source(tmp_path, frame)


def spearman_args(root, run_id, node, artifact, options=None):
    spec = {"input_mode": "typed", "column_bindings": {"x": "x", "y": "y"}, "options": options or {}}
    return ["analyze", "run", "nonparametric.spearman", root, "--run", run_id, "--node", node,
            "--artifact", artifact, "--spec", json.dumps(spec)]


def test_list_and_describe_read_the_catalog():
    listing = invoke("analyze", "list", "--json")
    assert listing.exit_code == 0, listing.output
    operations = {item["id"]: item for item in json.loads(listing.stdout)}
    assert operations["nonparametric.spearman"]["name"] == "Spearman correlation"
    assert operations["data.import"]["runs_here"] is False
    described = json.loads(invoke("analyze", "describe", "nonparametric.spearman").stdout)
    options = described["spec_schema"]["properties"]["options"]["properties"]
    assert options["missing_policy"]["enum"] == ["complete_case_v1", "reject"]


def test_run_previews_and_confirm_executes_the_pinned_plan(tmp_path):
    root, run_id, node, artifact = target(tmp_path)
    preview = invoke(*spearman_args(root, run_id, node, artifact))
    assert preview.exit_code == 0, preview.output
    plan = json.loads(preview.stdout)
    assert plan["status"] == "awaiting_confirmation"
    done = invoke("analyze", "confirm", root, "--request-id", plan["request_id"],
                  "--preview-id", plan["preview_id"], "--fingerprint", plan["fingerprint"])
    assert done.exit_code == 0, done.output
    result = json.loads(done.stdout)
    assert result["status"] == "completed"
    assert result["steps"][0]["operation_id"] == "nonparametric.spearman" and result["steps"][0]["artifact_refs"]


def test_refusals_are_specific_and_nonzero(tmp_path):
    root, run_id, node, artifact = target(tmp_path)
    unknown = invoke("analyze", "run", "no.such", root, "--run", run_id, "--node", node, "--artifact", artifact)
    assert unknown.exit_code != 0 and "unknown operation" in unknown.output
    dedicated = invoke("analyze", "run", "data.import", root, "--run", run_id, "--node", node, "--artifact", artifact)
    assert dedicated.exit_code != 0 and "its own entry" in dedicated.output
    outside = invoke(*spearman_args(root, run_id, node, artifact, {"missing_policy": "drop"}))
    assert outside.exit_code != 0 and "missing_policy" in outside.output
    bad = invoke("analyze", "run", "nonparametric.spearman", root, "--run", run_id, "--node", node,
                 "--artifact", artifact, "--spec", "[1]")
    assert bad.exit_code != 0 and "JSON object" in bad.output


def test_native_preview_rejects_a_window_larger_than_the_selected_dataset(tmp_path):
    root, run_id, node, artifact = target(tmp_path)
    spec = {"input_mode": "frame", "column_bindings": {"time_col": "x", "return_columns": ["y"]},
            "options": {"window": 7}}
    result = invoke("analyze", "run", "quant.rolling_risk", root, "--run", run_id, "--node", node,
                    "--artifact", artifact, "--spec", json.dumps(spec))
    assert result.exit_code == 2, result.output
    assert "OPERATION_INVALID" in result.stderr and "window must be an integer from 2 to 6" in result.stderr


def confirm(root, plan):
    return invoke("analyze", "confirm", root, "--request-id", plan["request_id"],
                  "--preview-id", plan["preview_id"], "--fingerprint", plan["fingerprint"])


@pytest.fixture
def failed_local_level(tmp_path, monkeypatch):
    from workbench import native_time_series

    def forbid_provider(*args, **kwargs):
        pytest.fail("CLI analysis must not construct a model provider")

    monkeypatch.setattr("workbench.agent.model.OpenAICompatibleModelAdapter.__init__", forbid_provider)
    root, run_id, node, artifact = source(tmp_path, pd.DataFrame({"t": [1, 2, 3, 4], "y": [2.0, 3.5, 1.5, 4.0]}))
    spec = {"input_mode": "frame", "column_bindings": {"time_col": "t", "outcome": "y"},
            "options": {"process_variance": 0.2, "observation_variance": 0.5,
                        "initial_mean": 0.0, "initial_variance": 1.0}}
    args = ("analyze", "run", "time_series.local_level", root, "--run", run_id, "--node", node,
            "--artifact", artifact, "--spec", json.dumps(spec))
    preview = invoke(*args)
    assert preview.exit_code == 0, preview.output
    plan = json.loads(preview.stdout)
    assert plan["status"] == "awaiting_confirmation"
    with monkeypatch.context() as unavailable:
        # Exercise the real missing-build check without altering the shared build or its loader cache.
        unavailable.setattr(native_time_series, "default_output", lambda _: tmp_path / "missing-build")
        unavailable.setattr(native_time_series, "_load_once", native_time_series._load_once.__wrapped__)
        failed = confirm(root, plan)
    assert failed.exit_code == 1, failed.output
    result = json.loads(failed.stdout)
    assert result["status"] == "failed" and result["request_id"] == plan["request_id"]
    assert "TIME_SERIES_NATIVE_BUILD_MISSING" in result["steps"][0]["error"]
    return root, args, failed


def test_failed_run_replay_preserves_json_and_reports_how_to_retry(failed_local_level):
    root, args, failed = failed_local_level
    result = json.loads(failed.stdout)
    events = root / "workbench" / "workflows" / f"{result['workflow_id']}.jsonl"
    previous_events = events.read_bytes()
    replay = invoke(*args)
    assert replay.exit_code == 1, replay.output
    assert json.loads(replay.stdout) == result
    assert events.read_bytes() == previous_events
    for response in (failed, replay):
        assert f"error: operation failed: {result['steps'][0]['error']}" in response.stderr
        assert "new --request-id" in response.stderr


def test_new_request_executes_verified_native_fixture_and_completed_replays(failed_local_level):
    from workbench import native_time_series
    from workbench.graph_store import GraphStore
    from workbench.native_build import default_output, manifest_path

    receipt = manifest_path(default_output(native_time_series._MODULE))
    if not receipt.is_file():
        pytest.skip("Explicit native build required for time_series")
    root, args, failed = failed_local_level
    retry_args = (*args, "--request-id", "retry-local-level")
    preview = invoke(*retry_args)
    assert preview.exit_code == 0, preview.output
    plan = json.loads(preview.stdout)
    assert plan["status"] == "awaiting_confirmation" and plan["request_id"] == "retry-local-level"
    done = confirm(root, plan)
    assert done.exit_code == 0, done.output
    result = json.loads(done.stdout)
    assert result["status"] == "completed"
    assert result["operation_record_id"] != json.loads(failed.stdout)["operation_record_id"]
    ref = result["steps"][0]["node_refs"][0]
    graph = GraphStore(root / "runs").read(ref["run_id"])
    saved = json.loads((root / "runs" / ref["run_id"] / graph.nodes[ref["node_id"]].payload_ref).read_text())
    assert saved["result"]["engine"]["build_identity_sha256"] == json.loads(receipt.read_text())["build_identity_sha256"]
    assert saved["result"]["forecast"]["steps"] == 1
    for replay in (invoke(*retry_args), confirm(root, plan)):
        assert replay.exit_code == 0 and replay.stdout == done.stdout and not replay.stderr
