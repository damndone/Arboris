import json
from pathlib import Path

import pytest

from workbench.config import WorkbenchConfig, load_config
from workbench.domain import (
    ArtifactRecord,
    ColumnMetadata,
    DatasetKind,
    DatasetSchema,
    DecisionRecord,
    GuardrailIssue,
    Severity,
)


def test_default_config_matches_v1_boundaries():
    config = WorkbenchConfig()
    assert config.max_single_file_gb == 2.0
    assert config.max_rows == 5_000_000
    assert config.max_excel_sheets == 20
    assert config.max_upload_files == 20
    assert config.min_join_overlap == 0.7
    assert config.max_missing_rate == 0.4
    assert config.min_model_n == 30
    assert config.max_panel_missing_cells == 0.5
    assert config.min_variable_role_confidence == 0.65
    assert config.random_seed == 20260429


def test_load_config_allows_project_override(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("max_rows: 100\nmin_join_overlap: 0.8\n", encoding="utf-8")
    config = load_config(path)
    assert config.max_rows == 100
    assert config.min_join_overlap == 0.8
    assert config.max_upload_files == 20


def test_load_config_none_returns_defaults():
    assert load_config(None) == WorkbenchConfig()


def test_load_config_missing_path_returns_defaults(tmp_path: Path):
    assert load_config(tmp_path / "missing.yml") == WorkbenchConfig()


def test_load_config_empty_file_returns_defaults(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("", encoding="utf-8")
    assert load_config(path) == WorkbenchConfig()


def test_load_config_ignores_unknown_keys(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text(
        "max_rows: 100\nunknown_threshold: 0.25\n",
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.max_rows == 100
    assert not hasattr(config, "unknown_threshold")


def test_load_config_rejects_non_mapping_yaml(tmp_path: Path):
    path = tmp_path / "config.yml"
    path.write_text("- max_rows\n", encoding="utf-8")
    with pytest.raises(ValueError, match="config.yml.*mapping"):
        load_config(path)


def test_domain_records_are_serializable():
    record = ArtifactRecord(
        artifact_id="raw_file",
        path="data/raw/source.csv",
        artifact_type="raw_data",
        step="ingestion",
        sha256="abc123",
        inputs=[],
    )
    assert record.to_dict() == {
        "artifact_id": "raw_file",
        "path": "data/raw/source.csv",
        "artifact_type": "raw_data",
        "step": "ingestion",
        "sha256": "abc123",
        "inputs": [],
        "config_hash": "",
        "code_version": "0.1.0",
    }
    assert Severity.BLOCKER.value == "BLOCKER"
    assert DatasetKind.PANEL.value == "panel"


def test_guardrail_issue_serializes_enum_value():
    issue = GuardrailIssue(
        severity=Severity.WARNING,
        code="missing_rate",
        message="Column has many missing values.",
        evidence={"column": "wage", "missing_rate": 0.45},
    )
    assert issue.to_dict() == {
        "severity": "WARNING",
        "code": "missing_rate",
        "message": "Column has many missing values.",
        "evidence": {"column": "wage", "missing_rate": 0.45},
        "issue_id": "",
        "affected_stage": "",
        "variables": [],
        "metric": "",
        "value": None,
        "threshold": None,
        "template_key": "",
        "template_params": {},
        "recommended_action_key": "",
        "is_user_action_required": False,
    }


def test_decision_record_is_serializable():
    record = DecisionRecord(
        step="merge",
        suggestion="Use inner join on firm_id.",
        confidence=0.82,
        evidence=["firm_id overlap is high"],
        user_action="accepted",
        final_decision="inner_join",
    )
    assert record.to_dict() == {
        "step": "merge",
        "suggestion": "Use inner join on firm_id.",
        "confidence": 0.82,
        "evidence": ["firm_id overlap is high"],
        "user_action": "accepted",
        "final_decision": "inner_join",
    }


def test_dataset_schema_serializes_nested_column_metadata():
    column = ColumnMetadata(
        name="firm_id",
        dtype="int64",
        semantic_role="entity_id",
        confidence=0.91,
        source_file="panel.csv",
        evidence=["unique within firm-year"],
    )
    schema = DatasetSchema(
        dataset_id="panel_dataset",
        source_files=["panel.csv"],
        columns=[column],
        primary_key_candidates=["firm_id", "year"],
        time_candidates=["year"],
        id_candidates=["firm_id"],
        transformations=[{"operation": "normalize_columns"}],
    )
    data = schema.to_dict()
    assert column.to_dict() == {
        "name": "firm_id",
        "dtype": "int64",
        "semantic_role": "entity_id",
        "confidence": 0.91,
        "source_file": "panel.csv",
        "evidence": ["unique within firm-year"],
    }
    assert data == {
        "dataset_id": "panel_dataset",
        "source_files": ["panel.csv"],
        "columns": [
            {
                "name": "firm_id",
                "dtype": "int64",
                "semantic_role": "entity_id",
                "confidence": 0.91,
                "source_file": "panel.csv",
                "evidence": ["unique within firm-year"],
            }
        ],
        "primary_key_candidates": ["firm_id", "year"],
        "time_candidates": ["year"],
        "id_candidates": ["firm_id"],
        "transformations": [{"operation": "normalize_columns"}],
    }


def test_domain_list_fields_are_not_mutable_through_records():
    record = ArtifactRecord(
        artifact_id="raw_file",
        path="data/raw/source.csv",
        artifact_type="raw_data",
        step="ingestion",
        sha256="abc123",
        inputs=["source.csv"],
    )
    with pytest.raises(AttributeError):
        record.inputs.append("other.csv")
    assert record.to_dict()["inputs"] == ["source.csv"]


def test_domain_mapping_fields_are_not_mutable_through_records():
    issue = GuardrailIssue(
        severity=Severity.BLOCKER,
        code="invalid",
        message="Invalid input.",
        evidence={"rows": 0},
    )
    with pytest.raises(TypeError):
        issue.evidence["rows"] = 1
    assert issue.to_dict()["evidence"] == {"rows": 0}


def test_cli_module_exports_app():
    from workbench.cli import app

    assert app is not None


def _isolate_origin_state(monkeypatch, tmp_path, probe_open=True):
    """Redirect the cache file to a tmp dir and stub the TCP probe so
    `_resolve_ui_origin` is deterministic regardless of whether a real
    dev server is running on the host."""
    from workbench import cli as cli_module

    monkeypatch.delenv("WORKBENCH_UI_ORIGIN", raising=False)
    monkeypatch.setattr(cli_module, "_CACHE_PATH", tmp_path / "ui_origin_cache.json")
    monkeypatch.setattr(cli_module, "_probe_dev_server", lambda: probe_open)


def test_cli_lineage_url_default_origin(tmp_path, monkeypatch):
    """Built URL points at the FE dev origin and lands on the lineage tab."""
    _isolate_origin_state(monkeypatch, tmp_path, probe_open=True)
    from workbench.cli import _lineage_url

    project = tmp_path / "proj"
    project.mkdir()
    url = _lineage_url(project, "run-abc-123")

    assert url.startswith("http://localhost:5173/runs/run-abc-123?")
    assert "tab=lineage" in url
    # project_root is URL-encoded; the absolute path resolves under
    # tmp_path which is itself absolute.
    assert "project_root=" in url
    # Path slashes must be percent-encoded so the query parser doesn't
    # mis-segment the URL.
    assert "%2F" in url or url.count("/runs/") == 1


def test_cli_lineage_url_env_override(tmp_path, monkeypatch):
    """WORKBENCH_UI_ORIGIN overrides the default localhost:5173 origin."""
    from workbench.cli import _lineage_url

    monkeypatch.setenv("WORKBENCH_UI_ORIGIN", "https://my-remote-tunnel.dev/")
    project = tmp_path / "proj"
    project.mkdir()
    url = _lineage_url(project, "r1")
    # Trailing slash on the env value must be stripped.
    assert url.startswith("https://my-remote-tunnel.dev/runs/r1?")


def test_cli_lineage_url_quotes_special_runid(tmp_path, monkeypatch):
    """A run_id containing slashes/spaces must be percent-encoded so
    the URL stays parseable."""
    _isolate_origin_state(monkeypatch, tmp_path, probe_open=True)
    from workbench.cli import _lineage_url

    project = tmp_path / "proj"
    project.mkdir()
    url = _lineage_url(project, "weird run/id")
    # Spaces → %20, slash → %2F. The single legitimate "/runs/" prefix
    # remains intact.
    assert "/runs/weird%20run%2Fid?" in url


def test_resolve_ui_origin_env_var_skips_probe(tmp_path, monkeypatch):
    """T5.3: explicit env var short-circuits the probe and the cache."""
    from workbench import cli as cli_module

    monkeypatch.setenv("WORKBENCH_UI_ORIGIN", "https://tunnel.example/")
    monkeypatch.setattr(cli_module, "_CACHE_PATH", tmp_path / "cache.json")

    def _boom():
        raise AssertionError("probe must not run when env var is set")

    monkeypatch.setattr(cli_module, "_probe_dev_server", _boom)
    assert cli_module._resolve_ui_origin() == "https://tunnel.example"


def test_resolve_ui_origin_probe_open_returns_dev_server(tmp_path, monkeypatch):
    """T5.3: when :5173 accepts a connection, use it and cache the choice."""
    from workbench import cli as cli_module

    cache_path = tmp_path / "cache.json"
    monkeypatch.delenv("WORKBENCH_UI_ORIGIN", raising=False)
    monkeypatch.setattr(cli_module, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(cli_module, "_probe_dev_server", lambda: True)

    assert cli_module._resolve_ui_origin() == "http://localhost:5173"
    # Probe result is persisted so subsequent CLI invocations skip the probe.
    assert cache_path.exists()
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["origin"] == "http://localhost:5173"


def test_resolve_ui_origin_probe_closed_falls_back_to_backend(
    tmp_path, monkeypatch
):
    """T5.3: when :5173 is unreachable, fall back to the backend origin
    so the printed URL still resolves to something a user can open."""
    from workbench import cli as cli_module

    cache_path = tmp_path / "cache.json"
    monkeypatch.delenv("WORKBENCH_UI_ORIGIN", raising=False)
    monkeypatch.setattr(cli_module, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(cli_module, "_probe_dev_server", lambda: False)

    assert cli_module._resolve_ui_origin() == "http://localhost:8000"
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["origin"] == "http://localhost:8000"


def test_cli_run_stdout_is_run_id_only_stderr_carries_url(
    tmp_path, monkeypatch, capsys
):
    """Reviewer P2: stdout must stay machine-readable so
    `RUN_ID=$(workbench run ...)` keeps working. URL goes to stderr.
    """
    from typer.testing import CliRunner

    from workbench import cli as cli_module
    from workbench.cli import app

    # Stub run_workflow so the test doesn't depend on the orchestrator
    # actually executing — we're testing the CLI surface contract,
    # not the run logic.
    monkeypatch.setattr(
        cli_module,
        "_lineage_url",
        lambda project_root, run_id: f"http://example/runs/{run_id}",
    )

    def fake_run_workflow(*_args, **_kwargs):
        return {"run_id": "stub-run-42"}

    # run_workflow is imported lazily inside the command body; patch the
    # source module so the import resolves to our stub.
    import workbench.orchestrator as orch

    monkeypatch.setattr(orch, "run_workflow", fake_run_workflow)

    # Click ≥8.2 separates stdout/stderr by default; the older
    # `mix_stderr=False` kwarg has been removed. We rely on the
    # default (separated) behaviour.
    runner = CliRunner()
    project = tmp_path / "proj"
    project.mkdir()
    data = tmp_path / "data.csv"
    data.write_text("y,x\n1,2\n3,4\n")

    result = runner.invoke(
        app,
        ["run", str(project), str(data), "y", "--x", "x"],
    )
    assert result.exit_code == 0, result.output
    # stdout: only the run_id, with a single trailing newline. This is
    # the contract scripts depend on (e.g. `RUN_ID=$(workbench run ...)`).
    assert result.stdout == "stub-run-42\n"
    # stderr: human-facing URL line, prefixed with "Lineage:".
    assert "Lineage:" in result.stderr
    assert "stub-run-42" in result.stderr
