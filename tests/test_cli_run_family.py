"""Gate 1 closeout — the migration must be reachable from outside the test suite.

Without an entry point the strict regime can never engage on a real project, so
`RUN_FAMILY_REQUIRED` would only ever fire in tests. These tests drive the CLI
the way a user would.
"""
import json
from pathlib import Path

from typer.testing import CliRunner

from workbench.cli import app
from workbench.lineage.run_family import bind_run_to_family, resolve_run_family

runner = CliRunner()


def _make_run(runs_dir: Path, run_id: str, *, rerun_of: str | None = None) -> Path:
    run_root = runs_dir / run_id
    run_root.mkdir(parents=True)
    (run_root / "run_inputs.json").write_text(
        json.dumps({"run_input_schema_version": 1, "rerun_of": rerun_of, "form": {}})
    )
    (run_root / "node_index.json").write_text(json.dumps({}))
    return run_root


def test_migrate_binds_every_run_and_reports_counts(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    runs = project / "runs"
    _make_run(runs, "run_001")
    _make_run(runs, "run_002", rerun_of="run_001")

    result = runner.invoke(app, ["run-family", "migrate", str(project)])

    assert result.exit_code == 0, result.output
    assert "2 run" in result.output
    assert "legacy-family:run_001" in result.output
    for run_id in ("run_001", "run_002"):
        resolved = resolve_run_family(project, run_id)
        assert resolved.source == "persisted"
        assert resolved.run_family_id == "legacy-family:run_001"


def test_migrate_is_idempotent_from_the_cli(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    _make_run(project / "runs", "run_001")

    first = runner.invoke(app, ["run-family", "migrate", str(project)])
    second = runner.invoke(app, ["run-family", "migrate", str(project)])

    assert first.exit_code == 0 and second.exit_code == 0
    assert "0 new" in second.output


def test_verify_reports_a_divergence_and_exits_nonzero(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    runs = project / "runs"
    _make_run(runs, "run_001")
    child = _make_run(runs, "run_002", rerun_of="run_001")
    runner.invoke(app, ["run-family", "migrate", str(project)])
    # Force a divergence: rewrite the child's membership to another family.
    (child / "run_family.json").unlink()
    bind_run_to_family(child, run_family_id="legacy-family:run_777", bound_by="tamper")

    result = runner.invoke(app, ["run-family", "verify", str(project)])

    assert result.exit_code == 1
    assert "run_002" in result.output
    assert "legacy-family:run_777" in result.output


def test_verify_is_clean_after_a_plain_migration(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    _make_run(project / "runs", "run_001")
    runner.invoke(app, ["run-family", "migrate", str(project)])

    result = runner.invoke(app, ["run-family", "verify", str(project)])

    assert result.exit_code == 0
    assert "1 run" in result.output
