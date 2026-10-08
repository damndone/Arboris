from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from workbench.cli import app


def test_cli_run_passes_imputation_json_to_workflow(tmp_path: Path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_workflow(*_args, **kwargs):
        captured.update(kwargs)
        return {"run_id": _args[1], "status": "completed"}

    import workbench.cli as cli_module
    import workbench.services.run_service as run_service

    # The CLI submits through the run service POST /runs uses (v1.8.12).
    monkeypatch.setattr(run_service, "_run_workflow", fake_run_workflow)
    monkeypatch.setattr(cli_module, "_lineage_url", lambda *_args: "http://example/run")

    CliRunner().invoke(app, ["create", str(tmp_path), "proj"])
    project = tmp_path / "proj"
    data = tmp_path / "data.csv"
    data.write_text("y,x\n1,2\n3,4\n", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "run",
            str(project),
            str(data),
            "y",
            "--x",
            "x",
            "--imputation",
            '{"method":"mice"}',
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["imputation"] == {"method": "mice"}
