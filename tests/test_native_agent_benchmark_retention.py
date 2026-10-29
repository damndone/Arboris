"""Retention correction refuses unknown or changed benchmark product trees."""
from importlib.util import module_from_spec, spec_from_file_location
import hashlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[1] / "native/canonical_numbers/migrate_retention.py"
    spec = spec_from_file_location("native_agent_retention",path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(out):
    out.mkdir()
    manifest = out / "source-manifest.json"
    manifest.write_text(json.dumps({"original_source":True,"fixture_manifest_sha256":"f"*64})+"\n")
    checksum = hashlib.sha256(manifest.read_bytes()).hexdigest()
    roots, rows = [], []
    for ordinal in range(15):
        role = "baseline" if ordinal % 2 == 0 else "candidate"
        root = out / f"{ordinal:02d}-{role}"
        root.mkdir()
        (root / "state.json").write_text(json.dumps({"ordinal":ordinal})+"\n")
        roots.append(root)
        rows.append({"engine_role":role,"work_dir":str(root),"manifest_sha256":"f"*64})
    (out / "runs.jsonl").write_text("".join(json.dumps(row)+"\n" for row in rows))
    (out / "report.json").write_text(json.dumps({"manifest_sha256":checksum,"accepted_local_replay":True}))
    return roots, rows


def test_journals_all_files_and_archives_before_removing_only_products(tmp_path,migration):
    out = tmp_path / "comparison"
    roots, _ = fixture(out)
    frozen = tmp_path / "frozen-input-source"
    frozen.mkdir()
    (frozen / "untouched.txt").write_text("keep this source")
    original = {name:(out / name).read_bytes() for name in ("runs.jsonl","report.json","source-manifest.json")}
    result = migration.migrate(out)
    assert result["migration_state"] == "completed"
    assert result["original_full_protocol_accepted"] is False
    assert result["retained_product_directories"] == 0
    assert all(not root.exists() for root in roots)
    assert (frozen / "untouched.txt").read_text() == "keep this source"
    assert all((out / name).read_bytes() == raw for name,raw in original.items())
    records = migration.evidence.read_records(out / "retention-migration.jsonl")
    assert len(records) == 15 and all(record["file_count"] == 1 for record in records)
    assert len(result["representatives"]) == 2
    assert all(Path(archive["path"]).is_file() for archive in result["representatives"].values())


def test_changed_file_after_snapshot_refuses_all_removal(tmp_path,migration,monkeypatch):
    out = tmp_path / "comparison"
    roots, _ = fixture(out)
    snapshot = migration.evidence.snapshot
    def changed(tree,**kwargs):
        record = snapshot(tree,**kwargs)
        (tree / "state.json").write_text("changed after inventory")
        return record
    monkeypatch.setattr(migration.evidence,"snapshot",changed)
    with pytest.raises(ValueError,match="files changed"):
        migration.migrate(out)
    assert all(root.exists() for root in roots)


def test_work_dir_cannot_name_a_frozen_input_outside_comparison(tmp_path,migration):
    out = tmp_path / "comparison"
    roots, rows = fixture(out)
    frozen = tmp_path / "00-baseline"
    frozen.mkdir()
    (frozen / "source.txt").write_text("fixed input")
    rows[0]["work_dir"] = str(frozen)
    (out / "runs.jsonl").write_text("".join(json.dumps(row)+"\n" for row in rows))
    with pytest.raises(ValueError,match="outside the exact"):
        migration.migrate(out)
    assert all(root.exists() for root in roots)
    assert (frozen / "source.txt").read_text() == "fixed input"


def test_future_driver_keeps_one_active_tree_and_retires_every_observation(tmp_path,monkeypatch):
    """Synthetic worker outputs verify retention only, never performance."""
    from types import SimpleNamespace
    path = Path(__file__).resolve().parents[1] / "native/canonical_numbers/agent_benchmark.py"
    spec = spec_from_file_location("native_agent_benchmark",path)
    benchmark = module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    trees = []
    for role in ("baseline","candidate"):
        tree = tmp_path / role
        files = []
        for name in benchmark.MODULES:
            source = tree / "backend/workbench" / name
            source.parent.mkdir(parents=True,exist_ok=True)
            source.write_text("# synthetic source fixture\n")
            files.append({"path":str(source.relative_to(tree)),"sha256":hashlib.sha256(source.read_bytes()).hexdigest()})
        (tree / "source-manifest.json").write_text(json.dumps({"files":files}))
        trees.append(tree)
    source_fixture = tmp_path / "fixture"
    source_fixture.mkdir()
    (source_fixture / "manifest.json").write_text("{}\n")
    checksum = hashlib.sha256((source_fixture / "manifest.json").read_bytes()).hexdigest()
    out = tmp_path / "retention-only"
    launches = []
    def worker(command,**unused):
        work = Path(command[command.index("--work-dir")+1])
        assert work == out / "active/work"
        assert not work.exists()
        assert [p.name for p in out.iterdir() if p.is_dir() and p.name != "representatives"] == ["active"]
        work.mkdir()
        (work / "state.json").write_text('{"result":"stable"}\n')
        launches.append(str(work))
        return SimpleNamespace(returncode=0,stdout=json.dumps({
            "seconds":.1,"local_pipeline_seconds":.05,"rss_bytes":1000,
            "manifest_sha256":checksum,"result_sha256":"1"*64,"stage_seconds":{"context_build":.03}}),stderr="")
    monkeypatch.setattr(benchmark.subprocess,"run",worker)
    monkeypatch.setattr(benchmark,"host_idle_snapshot",lambda:{"processes_checked":1,"competing":[]})
    monkeypatch.setattr(benchmark,"require_space",lambda *args,**kwargs:10_000_000_000)
    monkeypatch.setattr(benchmark.sys,"argv",[str(path),"--baseline-source",str(trees[0]),
        "--candidate-source",str(trees[1]),"--fixture",str(source_fixture),"--sha256",checksum,"--out",str(out)])
    benchmark.main()
    assert len(launches) == 15
    assert not (out / "active").exists()
    from perf_evidence import read_records
    assert len(read_records(out / "retention.jsonl")) == 15
    assert len(list((out / "representatives").glob("*.tar.gz"))) == 2
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
    report = json.loads((out / "report.json").read_text())
    assert all(row["manifest_sha256"] == checksum for row in rows)
    assert all(row["benchmark_manifest_sha256"] == report["manifest_sha256"] for row in rows)
    assert checksum != report["manifest_sha256"]


@pytest.fixture
def benchmark_module():
    path = Path(__file__).resolve().parents[1] / "native/canonical_numbers/agent_benchmark.py"
    spec = spec_from_file_location("native_agent_benchmark_host_probe",path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_host_probe_rejects_a_competing_test_process(benchmark_module,monkeypatch):
    owner = benchmark_module
    pid = owner.os.getpid() + 1_000_000
    monkeypatch.setattr(owner.subprocess,"check_output",lambda *args,**kwargs:
                        f"{pid} 1 python -m pytest tests/test_something.py\n")
    with pytest.raises(RuntimeError,match="not test/evaluation-idle"):
        owner.host_idle_snapshot()


def test_host_probe_permission_error_is_never_reported_as_idle(benchmark_module,monkeypatch):
    def denied(*args,**kwargs):
        raise PermissionError("host process probe denied")
    monkeypatch.setattr(benchmark_module.subprocess,"check_output",denied)
    with pytest.raises(PermissionError,match="denied"):
        benchmark_module.host_idle_snapshot()


def test_source_registration_detects_changed_lazy_dependency(tmp_path,benchmark_module):
    source = tmp_path / "backend/workbench/agent/context_compiler.py"
    source.parent.mkdir(parents=True)
    source.write_text("# original lazy dependency\n")
    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(json.dumps({"files":[{"path":str(source.relative_to(tmp_path)),
        "sha256":hashlib.sha256(source.read_bytes()).hexdigest()}]}))
    pinned = hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert benchmark_module.verify_source_snapshot(tmp_path,pinned)["files"] == 1
    source.write_text("# changed lazy dependency\n")
    with pytest.raises(ValueError,match="source file digest changed"):
        benchmark_module.verify_source_snapshot(tmp_path,pinned)


def test_source_registration_detects_added_source_and_changed_manifest(tmp_path,benchmark_module):
    source = tmp_path / "backend/workbench/agent/context.py"
    source.parent.mkdir(parents=True)
    source.write_text("# fixed source\n")
    manifest = tmp_path / "source-manifest.json"
    manifest.write_text(json.dumps({"files":[{"path":str(source.relative_to(tmp_path)),
        "sha256":hashlib.sha256(source.read_bytes()).hexdigest()}]}))
    pinned = hashlib.sha256(manifest.read_bytes()).hexdigest()
    extra = source.with_name("unregistered.py")
    extra.write_text("# new unregistered source\n")
    with pytest.raises(ValueError,match="source file set changed"):
        benchmark_module.verify_source_snapshot(tmp_path,pinned)
    extra.unlink()
    manifest.write_text(manifest.read_text()+"\n")
    with pytest.raises(ValueError,match="source manifest digest changed"):
        benchmark_module.verify_source_snapshot(tmp_path,pinned)
