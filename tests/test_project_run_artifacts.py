import json
from pathlib import Path

from workbench.artifacts import register_artifact, sha256_file
from workbench.projects import create_project, create_run


def test_create_project_and_run_directories(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    assert (project.root / "project.yaml").exists()
    assert (project.root / "config.yml").exists()
    assert (project.root / "data" / "raw").is_dir()

    run = create_run(project.root, mode="auto")
    assert run.run_id
    assert (run.root / "run_manifest.json").exists()
    assert (run.root / "environment.json").exists()
    assert (run.root / "artifacts_index.json").exists()
    assert (run.root / "decisions.json").exists()
    assert (run.root / "errors.json").exists()
    assert (run.root / "staged").is_dir()
    assert (run.root / "processed").is_dir()


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
