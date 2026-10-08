"""V1812-CLI-FROM-CATALOG: the command line is generated, not hand-written.

`workbench run` takes the same fields as POST /runs (one field table builds
both) and submits through the same service; `workbench postestimation <op>`
has one subcommand per registered post-estimation operation, with options
from its step contract; `workbench export-script` uses the HTTP export
service; `workbench models` lists the capability catalog.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from workbench.app import app as http_app
from workbench.cli import app as cli_app
from workbench.run_request import RUN_REQUEST_FIELDS

REPO = Path(__file__).resolve().parents[1]
# Help is rendered by rich, which truncates to the terminal width.
WIDE = {"COLUMNS": "400"}


def _form_schema() -> dict:
    document = http_app.openapi()
    body = document["paths"]["/runs"]["post"]["requestBody"]["content"]["multipart/form-data"]["schema"]
    name = body["$ref"].rsplit("/", 1)[-1]
    return document["components"]["schemas"][name]


def test_the_field_table_is_the_run_form() -> None:
    schema = _form_schema()
    declared = {field.name for field in RUN_REQUEST_FIELDS}
    assert set(schema["properties"]) == declared | {"project_root", "file"}
    for field in RUN_REQUEST_FIELDS:
        prop = schema["properties"][field.name]
        assert (field.name in schema.get("required", [])) == field.required, field.name
        if not field.required:
            assert prop.get("default") == field.default, field.name


def test_every_run_field_is_a_cli_option() -> None:
    result = CliRunner().invoke(cli_app, ["run", "--help"], env=WIDE)
    assert result.exit_code == 0, result.output
    for field in RUN_REQUEST_FIELDS:
        if field.name == "y":
            continue  # positional, as before
        assert f"--{field.name.replace('_', '-')}" in result.output, field.name


SAMPLE = "y,x1,x2,w,g\n" + "\n".join(f"{i % 7},{i * 0.5},{(i * 3) % 11},{1 + i % 2},{i % 4}" for i in range(60)) + "\n"


def _captured_workflow_kwargs(submit) -> dict:
    with patch(
        "workbench.services.run_service._run_workflow",
        return_value={"run_id": "r", "status": "completed"},
    ) as workflow:
        submit()
        for _ in range(200):
            if workflow.call_args is not None:
                break
            time.sleep(0.05)
    kwargs = dict(workflow.call_args.kwargs)
    for volatile in ("on_step", "stop_reason", "lmm_execution_admission"):
        kwargs.pop(volatile, None)
    return kwargs


def test_cli_and_http_submit_identical_workflow_arguments(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    data = tmp_path / "data.csv"
    data.write_text(SAMPLE, encoding="utf-8")
    CliRunner().invoke(cli_app, ["create", str(tmp_path), "proj"])

    fields = {
        "model_type": "negative_binomial",
        "y": "y",
        "x": json.dumps(["x1", "x2"]),
        "model_options": json.dumps({"dispersion": "constant"}),
        "frequency_weight": "w",
        "covariance": "clustered",
        "entity_col": "g",
        "statistical_tests": json.dumps({}),
    }

    def via_http() -> None:
        response = TestClient(http_app).post(
            "/runs",
            data={"project_root": str(project), **fields},
            files={"file": ("data.csv", io.BytesIO(SAMPLE.encode()), "text/csv")},
        )
        assert response.status_code == 200, response.text

    def via_cli() -> None:
        result = CliRunner().invoke(
            cli_app,
            [
                "run", str(project), str(data), "y",
                "--x", "x1", "--x", "x2",
                "--model-type", "negative_binomial",
                "--model-options", '{"dispersion": "constant"}',
                "--frequency-weight", "w",
                "--covariance", "clustered",
                "--entity-col", "g",
            ],
        )
        assert result.exit_code == 0, result.output

    http_kwargs = _captured_workflow_kwargs(via_http)
    cli_kwargs = _captured_workflow_kwargs(via_cli)
    assert cli_kwargs == http_kwargs
    assert cli_kwargs["model_options"] == {"dispersion": "constant"}
    assert cli_kwargs["frequency_weight"] == "w"


def test_postestimation_has_one_subcommand_per_registered_operation() -> None:
    from workbench.postestimation.registry import OPERATIONS
    from workbench.contracts.model.postestimation_steps import STEP_SHAPES

    result = CliRunner().invoke(cli_app, ["postestimation", "--help"], env=WIDE)
    assert result.exit_code == 0, result.output
    assert set(STEP_SHAPES) == set(OPERATIONS)
    for operation, (_summary, fields, _required, _types) in STEP_SHAPES.items():
        assert operation in result.output
        detail = CliRunner().invoke(cli_app, ["postestimation", operation, "--help"], env=WIDE)
        assert detail.exit_code == 0, detail.output
        for name in fields:
            assert f"--{name.replace('_', '-')}" in detail.output, (operation, name)


def test_the_cli_starts_without_loading_statistics_or_web_libraries() -> None:
    probe = (
        "import sys, time; t = time.perf_counter(); import workbench.cli; "
        "elapsed = time.perf_counter() - t; "
        "heavy = [m for m in ('pandas', 'numpy', 'scipy', 'statsmodels', 'fastapi') if m in sys.modules]; "
        "print(heavy, elapsed)"
    )
    output = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO, env={"PYTHONPATH": str(REPO / "backend"), "PATH": ""},
        capture_output=True, text=True, check=True,
    ).stdout.split(maxsplit=1)
    assert output[0] == "[]", output
    assert float(output[1]) < 0.5


def test_models_lists_the_capability_catalog() -> None:
    result = CliRunner().invoke(cli_app, ["models"], env=WIDE)
    assert result.exit_code == 0, result.output
    assert "negative_binomial" in result.output
    detail = CliRunner().invoke(cli_app, ["models", "negative_binomial"], env=WIDE)
    assert detail.exit_code == 0, detail.output
    assert "dispersion" in detail.output


def test_an_unknown_model_type_is_refused_before_a_run_is_created(tmp_path: Path) -> None:
    CliRunner().invoke(cli_app, ["create", str(tmp_path), "proj"])
    data = tmp_path / "data.csv"
    data.write_text(SAMPLE, encoding="utf-8")
    result = CliRunner().invoke(
        cli_app, ["run", str(tmp_path / "proj"), str(data), "y", "--x", "x1", "--model-type", "not_a_model"]
    )
    assert result.exit_code != 0
    assert "not_a_model" in result.output
    assert not any((tmp_path / "proj" / "runs").glob("*/run_manifest.json"))


def _nb1_counts(path: Path) -> None:
    import numpy as np

    rng = np.random.default_rng(20261008)
    n = 400
    x1 = rng.normal(size=n)
    x2 = rng.binomial(1, 0.4, size=n)
    mu = np.exp(0.4 + 0.5 * x1 - 0.3 * x2)
    # NB1: Var = mu * (1 + delta), a gamma-Poisson mixture with shape mu / delta.
    y = rng.poisson(rng.gamma(shape=mu / 1.5, scale=1.5))
    lines = ["y,x1,x2", *(f"{a},{b:.6f},{c}" for a, b, c in zip(y, x1, x2))]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_nb1_wald_and_a_native_stata_script_from_the_command_line(tmp_path: Path) -> None:
    """Objective step 5 acceptance, as a regression: NB1 -> Wald -> Stata, run by Stata itself."""
    import zipfile

    from native_runner import STATA

    runner = CliRunner()
    runner.invoke(cli_app, ["create", str(tmp_path), "proj"])
    project = tmp_path / "proj"
    data = tmp_path / "counts.csv"
    _nb1_counts(data)

    fitted = runner.invoke(cli_app, [
        "run", str(project), str(data), "y", "--x", "x1", "--x", "x2",
        "--model-type", "negative_binomial", "--model-options", '{"dispersion": "constant"}',
    ])
    assert fitted.exit_code == 0, fitted.output
    run_id = fitted.stdout.strip()

    wald = runner.invoke(cli_app, [
        "postestimation", "wald", str(project), run_id, "--model-ref", "model:negative_binomial_1",
        "--constraints", '[{"terms": {"x1": 1}, "value": 0}, {"terms": {"x2": 1}, "value": 0}]',
    ])
    assert wald.exit_code == 0, wald.output
    tested = json.loads(wald.stdout)
    [result] = tested["results"]
    assert (result["distribution"], result["df_num"], result["model_type"]) == ("chi2", 2, "negative_binomial")

    exported = runner.invoke(cli_app, [
        "export-script", str(project), run_id, "--target", "artifact:" + tested["artifact_ids"][0],
        "--language", "stata", "--require-native", "--output", str(tmp_path),
    ])
    assert exported.exit_code == 0, exported.output
    bundle = json.loads(exported.stdout)
    assert bundle["fully_native"] is True
    assert [step["operation"] for step in bundle["coverage"]][-2:] == ["model.negative_binomial", "postestimation.wald"]

    # Stata itself, cold, as a user would run the downloaded bundle.
    assert STATA.is_file(), "Required Stata binary is missing"
    unpacked = tmp_path / "bundle"
    with zipfile.ZipFile(bundle["output_path"]) as archive:
        archive.extractall(unpacked)
    completed = subprocess.run([str(STATA), "-b", "do", "analysis.do"], cwd=unpacked, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    log = (unpacked / "analysis.log").read_text(encoding="utf-8", errors="replace")
    script_part = log.split(". do analysis.do", 1)[1]
    assert "dispersion(constant)" in script_part
    assert "\nr(" not in script_part, script_part[-2000:]
    assert script_part.rstrip().endswith("end of do-file")


from tests.test_script_export_lineage_builder import data_path, model_path  # noqa: E402,F401 (fixtures)


def test_postestimation_on_a_model_fitted_from_a_data_operation_node(model_path) -> None:
    """The source is the dataset the lineage graph draws into the model, in the model's own run."""
    project, model_run, _ = model_path
    result = CliRunner().invoke(cli_app, [
        "postestimation", "wald", str(project), model_run, "--model-ref", "model:ols_1",
        "--constraints", '[{"terms": {"x": 1}, "value": 0}]',
    ])
    assert result.exit_code == 0, result.output
    tested = json.loads(result.stdout)
    [outcome] = tested["results"]
    # Clustered OLS on 40 clusters: F with the cluster df, as the API reports it.
    assert (outcome["distribution"], outcome["df_den"], outcome["n_clusters"]) == ("F", 39, 40)
    run_root = project / "runs" / model_run
    assert json.loads((run_root / "run_inputs.json").read_text(encoding="utf-8"))["dataset_source"]
    registered = json.loads((run_root / "artifacts_index.json").read_text(encoding="utf-8"))["artifacts"]
    assert set(tested["artifact_ids"]) <= {item["artifact_id"] for item in registered}


def test_a_stream_that_ends_without_a_terminal_event_reads_the_manifest(tmp_path: Path, monkeypatch) -> None:
    import queue

    from workbench import cli_commands

    class Events:
        subscribers = 0

        def subscribe(self, run_id):
            Events.subscribers += 1
            stream = queue.Queue()
            stream.put({"event": "step_start", "step": "ingestion"})
            stream.put(None)  # cleanup closed the stream before any workflow_* event
            return stream, []

        def unsubscribe(self, run_id, subscriber):
            Events.subscribers -= 1

    run_root = tmp_path / "runs" / "r1"
    run_root.mkdir(parents=True)
    (run_root / "run_manifest.json").write_text(json.dumps({"run_id": "r1", "status": "failed"}), encoding="utf-8")
    monkeypatch.setattr("workbench.events.get_event_manager", lambda: Events())

    assert cli_commands._wait_for_terminal(tmp_path, "r1", lambda _event: None) == "failed"
    assert Events.subscribers == 0  # nothing left subscribed


def test_an_export_whose_bundle_is_not_registered_is_refused(tmp_path: Path, monkeypatch) -> None:
    from workbench import cli_commands

    CliRunner().invoke(cli_app, ["create", str(tmp_path), "proj"])
    project = tmp_path / "proj"
    run_root = project / "runs" / "r1"
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")
    monkeypatch.setattr(
        "workbench.services.script_export.export_analysis_script",
        lambda *_a, **_k: {"artifact_id": "missing", "language": "stata", "filename": "analysis-stata.zip"},
    )
    monkeypatch.setattr("workbench.analysis_ledger.record_ui_action", lambda *_a, **_k: None)

    with pytest.raises(cli_commands.CommandError, match="missing"):
        cli_commands.export_script(project, "r1", "model:ols_1", "stata", require_native=False, output=None)
