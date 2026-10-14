"""`workbench analyze` runs any catalog operation through the manual service."""
from __future__ import annotations

import json

import pandas as pd
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
