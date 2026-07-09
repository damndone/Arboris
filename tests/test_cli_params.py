from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from workbench.cli import app


def _invoke(monkeypatch, tmp_path: Path, extra_args: list[str]) -> dict[str, object]:
    captured: dict[str, object] = {}

    def fake_run_workflow(*_args, **kwargs):
        captured.update(kwargs)
        return {"run_id": "stub-run"}

    import workbench.cli as cli_module
    import workbench.orchestrator as orch

    monkeypatch.setattr(orch, "run_workflow", fake_run_workflow)
    monkeypatch.setattr(cli_module, "_lineage_url", lambda *_a: "http://example/run")

    project = tmp_path / "proj"
    project.mkdir()
    data = tmp_path / "data.csv"
    data.write_text("y,x\n1,2\n3,4\n", encoding="utf-8")

    result = CliRunner().invoke(
        app, ["run", str(project), str(data), "y", "--x", "x", *extra_args]
    )
    assert result.exit_code == 0, result.output
    return captured


def test_cli_passes_panel_params(tmp_path: Path, monkeypatch):
    captured = _invoke(
        monkeypatch, tmp_path,
        ["--model-type", "panel_ols", "--entity-col", "firm", "--time-col", "year"],
    )
    assert captured["entity_col"] == "firm"
    assert captured["time_col"] == "year"


def test_cli_passes_iv_params(tmp_path: Path, monkeypatch):
    captured = _invoke(
        monkeypatch, tmp_path,
        ["--iv-endog", "educ", "--iv-instruments", "nearc4", "--iv-instruments", "age"],
    )
    assert captured["iv_endog"] == ["educ"]
    assert captured["iv_instruments"] == ["nearc4", "age"]


def test_cli_passes_did_params(tmp_path: Path, monkeypatch):
    captured = _invoke(
        monkeypatch, tmp_path,
        ["--model-type", "did", "--did-mode", "twfe",
         "--did-cohort-col", "g", "--did-treat-col", "d", "--did-post-col", "post"],
    )
    assert captured["did_mode"] == "twfe"
    assert captured["did_cohort_col"] == "g"
    assert captured["did_treat_col"] == "d"
    assert captured["did_post_col"] == "post"


def test_cli_passes_cs_and_honest_params(tmp_path: Path, monkeypatch):
    captured = _invoke(
        monkeypatch, tmp_path,
        ["--model-type", "did", "--did-mode", "cs",
         "--cs-control-group", "notyettreated", "--cs-est-method", "dr",
         "--cs-base-period", "universal", "--cs-cluster-var", "state",
         "--cs-anticipation", "1", "--honest-did"],
    )
    assert captured["cs_control_group"] == "notyettreated"
    assert captured["cs_est_method"] == "dr"
    assert captured["cs_base_period"] == "universal"
    assert captured["cs_cluster_var"] == "state"
    assert captured["cs_anticipation"] == 1
    assert captured["honest_did"] is True


def test_cli_defaults_pin_back_compat(tmp_path: Path, monkeypatch):
    """No new flags → engine defaults, so old invocations don't accidentally
    enter panel/IV/DID paths."""
    captured = _invoke(monkeypatch, tmp_path, [])
    assert captured["entity_col"] == ""
    assert captured["time_col"] == ""
    assert captured["covariance"] == ""
    assert not captured["iv_endog"]
    assert not captured["iv_instruments"]
    assert captured["did_mode"] == ""
    assert captured["did_cohort_col"] == ""
    assert captured["cs_anticipation"] == 0
    assert captured["honest_did"] is False
