"""Real admitted-FD dependency snapshots; disk writes are attack/producer fixtures."""
import copy
import hashlib
import importlib
import json
import os
import tracemalloc

import pytest

from workbench.services.report_evidence_owner_factory import HostBoundProjectFileStoreV1
from workbench.services.results_service import EvidenceProjectionError
from tests.test_v189_evidence_envelope import _ExternalHostAuthority


@pytest.fixture
def api():
    class API:
        def __getattr__(self, name):
            try:
                module = importlib.import_module("workbench.evidence.result_dependencies")
            except ModuleNotFoundError:
                pytest.fail("dependency integrity primitive is missing")
            return getattr(module, name)
    return API()


@pytest.fixture
def host(tmp_path):
    authority = _ExternalHostAuthority("scope:project:deps")
    root = tmp_path / "project"
    run = root / "runs" / "r1"
    run.mkdir(parents=True)
    rows = []
    for name in ("a", "b"):
        raw = ('{"value":"' + name + '"}').encode()
        (run / f"{name}.json").write_bytes(raw)
        rows.append(dict(artifact_id=name, path=f"{name}.json", artifact_type="model_results",
                         step="estimation", inputs=[], sha256=hashlib.sha256(raw).hexdigest()))
    index = {"schema_version": 1, "artifacts": rows}
    (run / "artifacts_index.json").write_text(json.dumps(index))
    store = HostBoundProjectFileStoreV1.from_host(
        root, authority_handle=authority.channel, scope_ref="scope:project:deps")
    yield store, run, index, authority
    store._admission.close()


def capture(api, host, ids=("a", "b")):
    return api.capture_result_dependencies(host[0], project_ref="project:deps", run_id="r1", artifact_ids=ids)


def verify(api, host, manifest, **kwargs):
    return api.verify_result_dependencies(host[0], manifest, project_ref="project:deps", run_id="r1", **kwargs)


def save_index(host):
    (host[1] / "artifacts_index.json").write_text(json.dumps(host[2]))


def test_roundtrip_frozen_and_readmitted_store(api, host):
    manifest = capture(api, host)
    payload = manifest.to_dict()
    assert set(payload) == {"schema_version", "project_ref", "run_id", "records"}
    assert payload["schema_version"] == 1
    assert payload["records"][0] == dict(artifact_id="a", path=["runs", "r1", "a.json"],
        sha256=host[2]["artifacts"][0]["sha256"], index_record=host[2]["artifacts"][0])
    with pytest.raises((TypeError, AttributeError)):
        manifest.records[0]["index_record"]["inputs"] += ("tamper",)
    payload["records"][0]["index_record"]["inputs"].append("tamper")
    assert manifest.to_dict()["records"][0]["index_record"]["inputs"] == []
    assert verify(api, host, manifest) is None
    other = HostBoundProjectFileStoreV1.from_host(host[1].parent.parent,
        authority_handle=host[3].channel, scope_ref="scope:project:deps")
    try:
        api.verify_result_dependencies(other, json.loads(json.dumps(manifest.to_dict())),
                                       project_ref="project:deps", run_id="r1")
    finally:
        other._admission.close()


@pytest.mark.parametrize("attack", ["bytes", "bytes_and_index", "missing_record", "missing_file",
    "symlink", "parent_symlink", "path", "type", "inputs", "duplicate", "index_symlink"])
def test_tamper_fails(api, host, attack):
    manifest = capture(api, host)
    store, run, index, _ = host
    row = index["artifacts"][0]
    if attack in {"bytes", "bytes_and_index"}:
        (run / "a.json").write_bytes(b"changed")
        if attack == "bytes_and_index":
            row["sha256"] = hashlib.sha256(b"changed").hexdigest()
    elif attack == "missing_record":
        index["artifacts"].pop(0)
    elif attack == "missing_file":
        (run / "a.json").unlink()
    elif attack == "symlink":
        (run / "a.json").unlink()
        (run / "a.json").symlink_to(run / "b.json")
    elif attack == "parent_symlink":
        run.rename(run.with_name("moved"))
        run.symlink_to(run.with_name("moved"), target_is_directory=True)
    elif attack == "path":
        row["path"] = "b.json"
    elif attack == "type":
        row["artifact_type"] = "other"
    elif attack == "inputs":
        row["inputs"] = ["foreign"]
    elif attack == "duplicate":
        index["artifacts"].append(copy.deepcopy(row))
    elif attack == "index_symlink":
        (run / "artifacts_index.json").rename(run / "other.json")
        (run / "artifacts_index.json").symlink_to(run / "other.json")
    save_index(host)
    with pytest.raises(EvidenceProjectionError, match="EVIDENCE_DEPENDENCY"):
        verify(api, host, manifest)


def test_selected_closure_and_unrelated_export(api, host):
    manifest = capture(api, host)
    host[2]["artifacts"].append(dict(artifact_id="export:new", path="report.xlsx",
        artifact_type="export", step="export", sha256="a" * 64, inputs=[]))
    save_index(host)
    assert verify(api, host, manifest) is None
    (host[1] / "b.json").unlink()
    assert verify(api, host, manifest, dependency_ids=["a"]) is None
    with pytest.raises(EvidenceProjectionError):
        verify(api, host, manifest)
    with pytest.raises(EvidenceProjectionError):
        verify(api, host, manifest, dependency_ids=["unknown"])


@pytest.mark.parametrize("field,value", [("path", "../a.json"), ("path", "/a.json"),
    ("path", "x//a.json"), ("path", "x\\a.json"), ("path", ["a.json"]),
    ("run_id", "r2"), ("project_ref", "project:foreign"), ("sha256", "0" * 64),
    ("artifact_type", "report_evidence"), ("artifact_type", "table_export"),
    ("step", "report"), ("step", "export"),
    ("path", "artifacts_index.json"), ("path", "report_evidence.json")])
def test_capture_rejects_invalid_index(api, host, field, value):
    host[2]["artifacts"][0][field] = value
    save_index(host)
    with pytest.raises(EvidenceProjectionError):
        capture(api, host)


@pytest.mark.parametrize("mutation", ["version", "extra", "record_extra", "duplicate", "path",
    "digest", "index", "foreign_run", "foreign_project"])
def test_manifest_data_validated(api, host, mutation):
    data = capture(api, host).to_dict()
    if mutation == "version": data["schema_version"] = True
    elif mutation == "extra": data["extra"] = 1
    elif mutation == "record_extra": data["records"][0]["extra"] = 1
    elif mutation == "duplicate": data["records"].append(copy.deepcopy(data["records"][0]))
    elif mutation == "path": data["records"][0]["path"] = ["runs", "r2", "a.json"]
    elif mutation == "digest": data["records"][0]["sha256"] = "0" * 64
    elif mutation == "index": data["records"][0]["index_record"]["inputs"] = ["foreign"]
    elif mutation == "foreign_run": data["run_id"] = "r2"
    elif mutation == "foreign_project": data["project_ref"] = "project:foreign"
    with pytest.raises(EvidenceProjectionError):
        verify(api, host, data)


@pytest.mark.parametrize("ids", [["a", "a"], "a", ["missing"], [1]])
def test_bad_selection(api, host, ids):
    with pytest.raises(EvidenceProjectionError):
        capture(api, host, ids)


def test_exact_store_and_closed_admission(api, host):
    with pytest.raises(EvidenceProjectionError):
        api.capture_result_dependencies(object(), project_ref="project:deps", run_id="r1", artifact_ids=[])
    class Subclass(HostBoundProjectFileStoreV1):
        pass
    with pytest.raises(EvidenceProjectionError):
        api.capture_result_dependencies(object.__new__(Subclass), project_ref="project:deps", run_id="r1", artifact_ids=[])
    manifest = capture(api, host)
    host[0]._admission.close()
    with pytest.raises(EvidenceProjectionError):
        verify(api, host, manifest, dependency_ids=[])


def test_duplicate_json_keys_rejected(api, host):
    (host[1] / "artifacts_index.json").write_text('{"schema_version":1,"artifacts":[],"artifacts":[]}')
    with pytest.raises(EvidenceProjectionError):
        capture(api, host, [])


def test_unstable_fd_read_rejected(api, host, monkeypatch):
    original = os.read
    attacked = []
    target = (host[1] / "a.json").stat().st_ino
    def mutate(fd, count):
        raw = original(fd, count)
        if raw and os.fstat(fd).st_ino == target and not attacked:
            attacked.append(True)
            (host[1] / "a.json").write_bytes(b"changed during read")
        return raw
    monkeypatch.setattr(os, "read", mutate)
    with pytest.raises(EvidenceProjectionError):
        capture(api, host)
    assert attacked == [True]


@pytest.mark.parametrize("target", ["source", "index"])
@pytest.mark.parametrize("kind", ["fifo", "directory"])
def test_non_regular_files_rejected_without_blocking(api, host, target, kind):
    path = host[1] / ("a.json" if target == "source" else "artifacts_index.json")
    path.unlink()
    if kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    with pytest.raises(EvidenceProjectionError) as error:
        capture(api, host)
    assert error.value.code == "EVIDENCE_DEPENDENCY_UNAVAILABLE"


@pytest.mark.parametrize("stage", ["capture", "verify"])
@pytest.mark.parametrize("attack", ["replace", "index_record"])
def test_mid_read_replacement_or_index_change(api, host, monkeypatch, stage, attack):
    manifest = capture(api, host)
    original = os.read
    target = (host[1] / "a.json").stat().st_ino
    attacked = []
    def mutate(fd, count):
        raw = original(fd, count)
        if raw and os.fstat(fd).st_ino == target and not attacked:
            attacked.append(True)
            if attack == "replace":
                replacement = host[1] / "replacement.json"
                replacement.write_bytes(raw)
                replacement.replace(host[1] / "a.json")
            else:
                host[2]["artifacts"][0]["inputs"] = ["changed-during-read"]
                save_index(host)
        return raw
    monkeypatch.setattr(os, "read", mutate)
    with pytest.raises(EvidenceProjectionError) as error:
        capture(api, host) if stage == "capture" else verify(api, host, manifest)
    assert error.value.code in {"EVIDENCE_DEPENDENCY_UNSTABLE", "EVIDENCE_DEPENDENCY_MISMATCH"}
    assert attacked == [True]


def test_unselected_record_change_does_not_break_selected_closure(api, host):
    manifest = capture(api, host)
    host[2]["artifacts"][1]["inputs"] = ["changed"]
    save_index(host)
    assert verify(api, host, manifest, dependency_ids=["a"]) is None
    with pytest.raises(EvidenceProjectionError) as error:
        verify(api, host, manifest)
    assert error.value.code == "EVIDENCE_DEPENDENCY_MISMATCH"


def test_manifest_is_not_authority(api, host):
    original = capture(api, host)
    (host[1] / "a.json").write_bytes(b"new producer result")
    host[2]["artifacts"][0]["sha256"] = hashlib.sha256(b"new producer result").hexdigest()
    save_index(host)
    with pytest.raises(EvidenceProjectionError):
        verify(api, host, original)
    # New self-consistent data can pass: owner must use C0's original sealed data.
    replacement = capture(api, host)
    assert verify(api, host, replacement.to_dict()) is None


@pytest.mark.parametrize("mutation", ["duplicate_path", "foreign_unrelated", "unsafe_unrelated", "missing_index"])
def test_invalid_index_structure(api, host, mutation):
    if mutation == "missing_index":
        (host[1] / "artifacts_index.json").unlink()
    else:
        row = host[2]["artifacts"][1]
        if mutation == "duplicate_path": row["path"] = "a.json"
        elif mutation == "foreign_unrelated": row["run_id"] = "other"
        else: row["path"] = "../other.json"
        save_index(host)
    with pytest.raises(EvidenceProjectionError):
        capture(api, host, ["a"])


def test_index_limit_is_explicit(api):
    assert api.MAX_ARTIFACT_INDEX_BYTES == 8 * 1024 * 1024


@pytest.mark.parametrize("stage", ["capture", "verify"])
@pytest.mark.parametrize("size", [8 * 1024 * 1024 + 1, 1024 * 1024 * 1024])
def test_huge_index_rejected_before_content_read(api, host, monkeypatch, stage, size):
    manifest = capture(api, host)
    path = host[1] / "artifacts_index.json"
    # Sparse fixture: never allocate the oversized index in the test either.
    with path.open("r+b") as handle:
        handle.truncate(size)
    target = path.stat().st_ino
    original = os.read
    def guarded_read(fd, count):
        assert os.fstat(fd).st_ino != target, "oversized index reached content allocation"
        return original(fd, count)
    monkeypatch.setattr(os, "read", guarded_read)
    with pytest.raises(EvidenceProjectionError) as error:
        capture(api, host) if stage == "capture" else verify(api, host, manifest)
    assert error.value.code == "EVIDENCE_DEPENDENCY_INVALID"


@pytest.mark.parametrize("stage", ["capture", "verify"])
def test_growing_source_never_reads_past_initial_size(api, host, monkeypatch, stage):
    path = host[1] / "a.json"
    initial = b"x" * (1024 * 1024 + 17)
    path.write_bytes(initial)
    host[2]["artifacts"][0]["sha256"] = hashlib.sha256(initial).hexdigest()
    save_index(host)
    manifest = capture(api, host)
    original = os.read
    target = path.stat().st_ino
    consumed = 0
    calls = []
    def growing_read(fd, count):
        nonlocal consumed
        if os.fstat(fd).st_ino != target:
            return original(fd, count)
        remaining = len(initial) - consumed
        assert 0 < count <= min(1024 * 1024, remaining), "read exceeded initial-size budget"
        raw = original(fd, count)
        consumed += len(raw)
        calls.append(count)
        # Growth on every read would keep an EOF-driven loop alive indefinitely.
        with path.open("ab") as handle:
            handle.write(b"growth")
        return raw
    monkeypatch.setattr(os, "read", growing_read)
    with pytest.raises(EvidenceProjectionError) as error:
        capture(api, host) if stage == "capture" else verify(api, host, manifest)
    assert error.value.code == "EVIDENCE_DEPENDENCY_UNSTABLE"
    assert consumed == len(initial)
    assert calls == [1024 * 1024, 17]
    assert path.stat().st_size > len(initial)


@pytest.mark.parametrize("size_mib", [8, 24])
@pytest.mark.parametrize("stage", ["capture", "verify"])
def test_multimib_source_has_bounded_memory(api, host, size_mib, stage):
    capture(api, host)  # Import/bootstrap outside the measured read operation.
    path = host[1] / "a.json"
    block = b"0123456789abcdef" * (1024 * 1024 // 16)
    digest = hashlib.sha256()
    with path.open("wb") as handle:
        for _ in range(size_mib):
            handle.write(block)
            digest.update(block)
    expected = digest.hexdigest()
    host[2]["artifacts"][0]["sha256"] = expected
    save_index(host)
    manifest = capture(api, host)
    tracemalloc.start()
    try:
        if stage == "capture":
            result = capture(api, host)
            assert result.to_dict()["records"][0]["sha256"] == expected
        else:
            assert verify(api, host, manifest) is None
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024, f"source read peak {peak} bytes is not bounded"


@pytest.mark.parametrize("version", [0, -1, 2, 999])
def test_unknown_integer_manifest_version_has_distinct_code(api, host, version):
    manifest = capture(api, host).to_dict()
    manifest["schema_version"] = version
    with pytest.raises(EvidenceProjectionError) as error:
        verify(api, host, manifest)
    assert error.value.code == "UNSUPPORTED_VERSION"


@pytest.mark.parametrize("version", [True, False, 1.0, 2.0, "1", "2", None])
def test_malformed_manifest_version_remains_invalid(api, host, version):
    manifest = capture(api, host).to_dict()
    manifest["schema_version"] = version
    with pytest.raises(EvidenceProjectionError) as error:
        verify(api, host, manifest)
    assert error.value.code == "EVIDENCE_DEPENDENCY_INVALID"
