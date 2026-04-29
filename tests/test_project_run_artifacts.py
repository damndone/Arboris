import json
from pathlib import Path

from workbench.artifacts import read_json, register_artifact, sha256_file, write_json
from workbench.projects import create_project, create_run


def test_create_project_and_run_directories(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    assert (project.root / "project.yaml").exists()
    assert (project.root / "config.yml").exists()
    assert (project.root / "data" / "raw").is_dir()
    assert (project.root / "runs").is_dir()
    assert (project.root / "backups").is_dir()

    run = create_run(project.root, mode="auto")
    assert run.run_id
    for dirname in [
        "raw_snapshot",
        "staged",
        "processed",
        "model_results",
        "figures",
        "tables",
        "reports",
        "exports",
    ]:
        assert (run.root / dirname).is_dir()
    assert (run.root / "workflow_log.jsonl").read_text(encoding="utf-8") == ""
    assert read_json(run.root / "run_manifest.json") == {
        "run_id": run.run_id,
        "mode": "auto",
        "status": "created",
        "lineage": [],
    }
    environment = read_json(run.root / "environment.json")
    assert environment["app_version"] == "0.1.0"
    assert environment["python_version"]
    assert environment["os"]
    assert environment["random_seed"] == 20260429
    assert read_json(run.root / "artifacts_index.json") == {"artifacts": []}
    assert read_json(run.root / "decisions.json") == {"decisions": []}
    assert read_json(run.root / "errors.json") == {"issues": []}


def test_create_run_generates_unique_run_roots(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    first = create_run(project.root, mode="auto")
    second = create_run(project.root, mode="auto")
    assert first.run_id != second.run_id
    assert first.root != second.root
    assert first.root.exists()
    assert second.root.exists()


def test_json_helpers_round_trip_payload(tmp_path: Path):
    path = tmp_path / "nested" / "payload.json"
    payload = {"name": "demo", "values": [1, 2, 3]}
    write_json(path, payload)
    assert read_json(path) == payload


def test_register_artifact_writes_index_and_hash(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    run = create_run(project.root, mode="auto")
    source = run.root / "staged" / "sample.txt"
    source.write_text("abc", encoding="utf-8")
    record = register_artifact(run.root, "sample", source, "text", "unit", [])
    index = json.loads((run.root / "artifacts_index.json").read_text(encoding="utf-8"))
    assert index["artifacts"][0]["artifact_id"] == "sample"
    assert index["artifacts"][0]["sha256"] == sha256_file(source)
    assert record.path.endswith("sample.txt")
