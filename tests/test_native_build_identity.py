"""Build admission must prove the current sources and the actual binary, offline."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np
import pytest

from workbench import native_build
from workbench.estimation_engine import native

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_native_identity_test", ROOT / "scripts/build_native.py")
aggregate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aggregate)
MODULES = [path.parent.name for path in (ROOT / "native").glob("*/build.py")]


@pytest.fixture
def synthetic_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(aggregate, "ROOT", tmp_path)
    return tmp_path


def old_build(root, name):
    module = root / "native" / name
    module.mkdir(parents=True)
    # Preserve each real module's default output location.
    (module / "build.py").write_text((ROOT / "native" / name / "build.py").read_text())
    source = module / "source.cpp"
    source.write_text("// compiled source\n")
    out = aggregate.output_directory(module)
    out.mkdir(parents=True)
    binary = out / "old-binary.so"
    binary.write_bytes(b"compiled bytes")
    manifest = {"sources": {"source.cpp": hashlib.sha256(source.read_bytes()).hexdigest()},
                "binary": str(binary), "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest()}
    return module, out, binary, manifest


@pytest.mark.parametrize("name", MODULES)
@pytest.mark.parametrize("damage", ["missing-manifest", "incomplete-manifest", "added-source", "replaced-binary"])
def test_every_module_rejects_unproven_build(synthetic_tree, name, damage):
    module, out, binary, manifest = old_build(synthetic_tree, name)
    if damage == "incomplete-manifest":
        manifest = {"sources": {}}
    elif damage == "added-source":
        (module / "added.cpp").write_text("// newly added source\n")
    elif damage == "replaced-binary":
        binary.write_bytes(b"replacement")
    if damage != "missing-manifest":
        (out / "build-manifest.json").write_text(json.dumps(manifest))
    state = aggregate.status(module)
    assert state != "current" and not state.startswith("built"), state


def test_aggregate_check_returns_nonzero_for_missing_manifests(synthetic_tree, monkeypatch, capsys):
    for name in MODULES:
        old_build(synthetic_tree, name)
    monkeypatch.setattr(sys, "argv", ["build_native.py", "--check"])
    assert aggregate.main() != 0
    assert "no source manifest to compare" not in capsys.readouterr().out


@pytest.fixture
def isolated_loader(tmp_path, monkeypatch):
    native._load_once.cache_clear()
    monkeypatch.setattr(native, "library_directory", lambda: tmp_path)
    opened = []
    monkeypatch.setattr(native, "_open", lambda path: opened.append(path) or object())
    yield tmp_path, opened
    native._load_once.cache_clear()


@pytest.mark.parametrize("body", [None, "{}", "{broken json"])
def test_fast_loader_rejects_bad_manifest_before_opening_binary(isolated_loader, body):
    directory, opened = isolated_loader
    (directory / native._NAME).write_bytes(b"untrusted binary")
    if body is not None:
        (directory / "build-manifest.json").write_text(body)
    with pytest.raises((RuntimeError, ValueError)):
        native.available()
    assert opened == []


def test_foreign_binary_is_an_error_not_an_absent_optional_build(isolated_loader):
    directory, opened = isolated_loader
    (directory / "libarboris_engine.foreign-abi").write_bytes(b"foreign")
    with pytest.raises(RuntimeError, match="ABI|binary"):
        native.available()
    assert opened == []


def test_absent_optional_engine_remains_available_to_reference(isolated_loader):
    assert native.available() is False


def test_present_broken_build_record_does_not_look_like_an_unbuilt_engine(isolated_loader):
    directory, opened = isolated_loader
    (directory / "build-manifest.json").write_text("{}")
    with pytest.raises(RuntimeError, match="manifest|build"):
        native.available()
    assert opened == []


def test_normal_binary_read_during_load_may_change_access_time(isolated_loader, monkeypatch):
    directory, _ = isolated_loader
    binary = directory / native._NAME
    binary.write_bytes(b"verified binary")
    os.utime(binary, ns=(0, binary.stat().st_mtime_ns))
    monkeypatch.setattr(native, "verify_build", lambda *args: {"binary_sha256": "verified"})
    monkeypatch.setattr(native, "_open", lambda path: path.read_bytes())
    assert native.available() is True


def test_loaded_binary_verification_is_cached_and_build_records_are_isolated(isolated_loader, monkeypatch):
    directory, opened = isolated_loader
    (directory / native._NAME).write_bytes(b"verified binary")
    verified = []
    monkeypatch.setattr(native, "verify_build", lambda *args: verified.append(True) or {"sources": {"lib.rs": "verified"}})
    assert native.available() is True
    for _ in range(3):
        record = native.build_record()
        record["sources"]["lib.rs"] = "mutated caller copy"
    assert native.build_record()["sources"] == {"lib.rs": "verified"}
    assert len(verified) == len(opened) == 1


def test_binary_replaced_at_end_of_verification_is_rejected_before_loading(isolated_loader, monkeypatch):
    directory, opened = isolated_loader
    binary = directory / native._NAME
    binary.write_bytes(b"verified bytes")

    def replace_after_verification(*args):
        replacement = directory / "replacement"
        replacement.write_bytes(b"unverified bytes")
        replacement.replace(binary)
        return {"binary_sha256": "digest of old binary"}

    monkeypatch.setattr(native, "verify_build", replace_after_verification)
    with pytest.raises(RuntimeError, match="binary changed"):
        native.available()
    assert opened == []


def test_concurrent_first_load_cannot_reattribute_a_sticky_image(isolated_loader, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading

    directory, _ = isolated_loader
    binary = directory / native._NAME
    binary.write_bytes(b"A")
    replacement = directory / "replacement"
    replacement.write_bytes(b"B")
    first_opened, finish_first = threading.Event(), threading.Event()
    second_started, finish_second = threading.Event(), threading.Event()
    opened = []

    def library_directory():
        if threading.current_thread().name.startswith("second-loader"):
            assert finish_second.wait(5)
        return directory

    def open_sticky(path):
        opened.append(path.read_bytes())
        if len(opened) == 1:
            first_opened.set()
            assert finish_first.wait(5)
        return b"A"  # the already-mapped image on a repeated path load

    def second_call():
        second_started.set()
        return native.build_record()

    monkeypatch.setattr(native, "library_directory", library_directory)
    monkeypatch.setattr(native, "verify_build", lambda *args: {"binary_sha256": binary.read_text()})
    monkeypatch.setattr(native, "_open", open_sticky)
    with ThreadPoolExecutor(1, thread_name_prefix="first-loader") as first_pool, \
         ThreadPoolExecutor(1, thread_name_prefix="second-loader") as second_pool:
        first = first_pool.submit(native.build_record)
        assert first_opened.wait(5)
        second = second_pool.submit(second_call)
        assert second_started.wait(5)
        # Old lru_cache allows this second call into its uncached body.
        # Give that caller time to reach the library_directory barrier.
        threading.Event().wait(.05)
        finish_first.set()
        try:
            assert first.result(timeout=5)["binary_sha256"] == "A"
            replacement.replace(binary)
        finally:
            finish_second.set()
        assert second.result(timeout=5)["binary_sha256"] == "A"
    assert opened == [b"A"]


def test_binary_changed_after_open_requires_restart_before_retry(isolated_loader, monkeypatch):
    directory, _ = isolated_loader
    binary = directory / native._NAME
    binary.write_bytes(b"A")
    opened = []

    def open_sticky(path):
        opened.append(path.read_bytes())
        if len(opened) == 1:
            replacement = directory / "replacement"
            replacement.write_bytes(b"B")
            replacement.replace(binary)
        return b"A"

    monkeypatch.setattr(native, "verify_build", lambda *args: {"binary_sha256": binary.read_text()})
    monkeypatch.setattr(native, "_open", open_sticky)
    with pytest.raises(RuntimeError, match="binary changed"):
        native.build_record()
    with pytest.raises(RuntimeError, match="restart"):
        native.build_record()
    assert opened == [b"A"]


@pytest.fixture
def recorded_build(tmp_path, monkeypatch):
    module = tmp_path / "native/engine"
    (module / "src").mkdir(parents=True)
    (module / "build.py").write_text("# builder\n")
    (module / "src/lib.rs").write_text("// source\n")
    (module / "Cargo.toml").write_text("# crate\n")
    helper = tmp_path / "backend/workbench/native_build.py"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(Path(native_build.__file__).read_bytes())
    out = tmp_path / "local/native-engine"
    out.mkdir(parents=True)
    compiler = {name: {"executable": "/offline/" + name, "binary_sha256": "a" * 64, "version": "test tool"}
                for name in ("cargo", "rustc")}
    monkeypatch.setattr(native_build, "_compiler", lambda *args: compiler)
    for name in native_build.artifact_names(module):
        path = out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"compiled output")
    record = native_build._inputs(module, out, "row-exact") | {"compiler": compiler,
        "artifacts": {name: native_build.digest(out / name) for name in native_build.artifact_names(module)},
        "binary": str(out / native_build.artifact_names(module)[0]),
        "binary_sha256": native_build.digest(out / native_build.artifact_names(module)[0])}
    record["build_identity_sha256"] = native_build._json_digest(record)
    (out / "build-manifest.json").write_text(json.dumps(record))
    return module, out, record


@pytest.mark.parametrize("damage", ["none", "source-added", "source-edited", "source-removed", "binary-replaced",
                                  "cli-replaced", "configuration", "platform", "compiler", "manifest-truncated"])
def test_current_manifest_admits_only_complete_unchanged_build(recorded_build, damage):
    module, out, record = recorded_build
    if damage == "source-added":
        (module / "src/added.rs").write_text("// new source\n")
    elif damage == "source-edited":
        (module / "src/lib.rs").write_text("// changed source\n")
    elif damage == "source-removed":
        (module / "src/lib.rs").unlink()
    elif damage == "binary-replaced":
        Path(record["binary"]).write_bytes(b"replacement")
    elif damage == "cli-replaced":
        (out / "target/release/arboris-engine").write_bytes(b"replacement CLI")
    elif damage in {"configuration", "platform", "compiler", "manifest-truncated"}:
        if damage == "configuration":
            record["configuration"]["command"].append("--other")
        elif damage == "platform":
            record["platform_abi"]["machine"] = "another architecture"
        elif damage == "compiler":
            record["compiler"]["rustc"]["version"] = "different compiler"
        else:
            record.pop("artifacts")
        (out / "build-manifest.json").write_text(json.dumps(record))
    if damage == "none":
        assert native_build.verify_build(module, out, check_toolchain=True) == record
    else:
        with pytest.raises(native_build.NativeBuildError):
            native_build.verify_build(module, out, check_toolchain=True)


def test_rebuild_cannot_adopt_a_cargo_cached_binary(recorded_build, monkeypatch):
    module, out, _ = recorded_build
    cached_library = out / "target/release" / native_build.artifact_names(module)[0]
    cached_library.write_bytes(b"unproven cached binary")
    clean = []

    def cargo(command, **kwargs):
        if "clean" in command:
            clean.append(True)
        elif clean:
            cached_library.write_bytes(b"freshly compiled binary")
    monkeypatch.setattr(native_build.subprocess, "run", cargo)
    # A consumer can retain an already mapped image across an explicit rebuild.
    with (out / native_build.artifact_names(module)[0]).open("rb") as old_image:
        record = native_build.build(module, out)
        assert old_image.read() == b"compiled output"
    assert Path(record["binary"]).read_bytes() == b"freshly compiled binary"


def test_successful_noop_cpp_compiler_cannot_adopt_an_old_output(tmp_path, monkeypatch):
    module = tmp_path / "native/canonical_numbers"
    module.mkdir(parents=True)
    (module / "canonical_numbers.cpp").write_text("// current source\n")
    (module / "build.py").write_text("// current builder\n")
    helper = tmp_path / "backend/workbench/native_build.py"
    helper.parent.mkdir(parents=True)
    helper.write_bytes(Path(native_build.__file__).read_bytes())
    out = tmp_path / "local/native-canonical"
    out.mkdir(parents=True)
    binary = out / native_build.artifact_names(module)[0]
    binary.write_bytes(b"unknown old output")
    compiler = {"cxx": {"executable": "/offline/cxx", "binary_sha256": "a" * 64, "version": "test tool"}}
    monkeypatch.setattr(native_build, "_compiler", lambda *args: compiler)
    monkeypatch.setattr(native_build.subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises((native_build.NativeBuildError, OSError)):
        native_build.build(module, out)
    assert not (out / "build-manifest.json").exists()


def call_fake_engine(monkeypatch, *, covariance="unadjusted", instruments=2, corrupt=None, status=0):
    k, cursor, endogenous = 3, 12, 1
    output = np.ones(cursor + endogenous + 7)
    output[k:cursor] = np.eye(k).ravel()
    output[cursor + 2 + endogenous] = 96  # first-stage residual degrees of freedom
    if instruments == endogenous:
        output[cursor + 4 + endogenous:cursor + 6 + endogenous] = np.nan
    if covariance != "unadjusted":
        output[-2:] = np.nan
    if corrupt:
        index, value = corrupt
        output[index] = value

    class Library:
        def arboris_iv_2sls_output_len(self, *args):
            return len(output)

        def arboris_iv_2sls(self, *args):
            np.ctypeslib.as_array(args[-2], shape=(args[-1],))[:] = output
            return status

    monkeypatch.setattr(native, "_loaded", lambda: (Library(), {}))
    column = np.ones(100)
    return native.iv_2sls(column, [column, column], [column], [column] * instruments, covariance)


@pytest.mark.parametrize("index,value", [(0, np.nan), (4, np.inf), (3, -1), (12, -1), (13, -1),
                                       (14, np.nan), (15, np.nan), (16, np.inf), (17, np.nan),
                                       (18, np.nan), (19, np.nan)])
def test_success_status_cannot_publish_invalid_defined_outputs(monkeypatch, index, value):
    with pytest.raises(RuntimeError, match="native engine.*output"):
        call_fake_engine(monkeypatch, corrupt=(index, value))


@pytest.mark.parametrize("covariance,instruments", [("unadjusted", 1), ("robust", 1), ("robust", 2)])
def test_undefined_iv_statistics_keep_their_nan_values(monkeypatch, covariance, instruments):
    out = call_fake_engine(monkeypatch, covariance=covariance, instruments=instruments)
    assert np.isfinite(out[:17]).all()
    assert np.isnan(out[-1]) == (covariance == "robust")


def test_native_numerical_error_status_is_not_a_reference_fallback(monkeypatch):
    with pytest.raises(RuntimeError, match="status 4"):
        call_fake_engine(monkeypatch, status=4)


@pytest.fixture
def recorded_ar_variants(synthetic_tree, monkeypatch):
    module = synthetic_tree / 'native/ar_exact'
    module.mkdir(parents=True)
    (module / 'build.py').write_text((ROOT / 'native/ar_exact/build.py').read_text())
    (module / 'ar_exact.cpp').write_text('// exact source\n')
    (module / 'ar_moments.cpp').write_text('// moments source\n')
    helper = synthetic_tree / 'backend/workbench/native_build.py'
    helper.parent.mkdir(parents=True)
    helper.write_bytes(Path(native_build.__file__).read_bytes())
    out = native_build.default_output(module)
    out.mkdir(parents=True)
    compiler = {'cxx': {'executable': '/offline/c++', 'binary_sha256': 'a' * 64, 'version': 'offline c++'}}
    monkeypatch.setattr(native_build, '_compiler', lambda *args: compiler)
    for variant in ('row-exact', 'moments'):
        names = native_build.artifact_names(module, variant)
        for name in names:
            (out / name).write_bytes(('fresh ' + variant).encode())
        record = native_build._inputs(module, out, variant) | {'compiler': compiler,
            'artifacts': {name: native_build.digest(out / name) for name in names},
            'binary': str(out / names[0]), 'binary_sha256': native_build.digest(out / names[0])}
        record['build_identity_sha256'] = native_build._json_digest(record)
        native_build.manifest_path(out, variant).write_text(json.dumps(record))
    return module, out


@pytest.mark.parametrize('damage', ['missing_manifest', 'missing_binary', 'stale_manifest', 'damaged_binary', 'none'])
def test_aggregate_check_accounts_for_both_ar_production_variants(recorded_ar_variants, monkeypatch, capsys, damage):
    module, out = recorded_ar_variants
    manifest = native_build.manifest_path(out, 'moments')
    binary = out / native_build.artifact_names(module, 'moments')[0]
    if damage == 'missing_manifest':
        manifest.unlink()
    elif damage == 'missing_binary':
        binary.unlink()
    elif damage == 'stale_manifest':
        record = json.loads(manifest.read_text())
        record['configuration']['environment'] = {'STALE_TOOLCHAIN_INPUT': 'yes'}
        manifest.write_text(json.dumps(record))
    elif damage == 'damaged_binary':
        binary.write_bytes(b'replaced moments output')
    assert aggregate.status(module) == 'current'  # the row-exact variant alone cannot certify this component
    monkeypatch.setattr(sys, 'argv', ['build_native.py', '--check'])
    assert aggregate.main() == (0 if damage == 'none' else 1)
    output = capsys.readouterr().out
    assert 'ar_exact:row-exact' in output and 'ar_exact:moments' in output


def test_aggregate_build_dispatches_each_declared_ar_variant(recorded_ar_variants, monkeypatch):
    commands = []
    monkeypatch.setattr(aggregate, 'status', lambda *args, **kwargs: 'current')
    class Result:
        returncode, stderr = 0, ''
    def build(command, **kwargs):
        commands.append(command)
        return Result()
    monkeypatch.setattr(aggregate.subprocess, 'run', build)
    monkeypatch.setattr(sys, 'argv', ['build_native.py'])
    assert aggregate.main() == 0
    assert len(commands) == 2
    assert commands[0][-2:] == ['--engine', 'row-exact']
    assert commands[1][-2:] == ['--engine', 'moments']


def test_shared_variant_declaration_rejects_unsupported_single_module_variant(tmp_path):
    assert native_build.variants(tmp_path / 'native/ar_exact') == ('row-exact', 'moments')
    assert native_build.variants(tmp_path / 'native/canonical_numbers') == ('row-exact',)
    with pytest.raises(native_build.NativeBuildError, match='moments variant is only supported'):
        native_build.artifact_names(tmp_path / 'native/canonical_numbers', 'moments')
