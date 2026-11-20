"""Missing extension and incompatible present binary are distinct outcomes."""
import importlib
from types import SimpleNamespace

import pytest


@pytest.fixture
def isolated_loader(tmp_path, monkeypatch):
    from workbench import native_kendall
    original_import = importlib.import_module
    def absent(name, *args, **kwargs):
        if name == '_kendall_counts':
            raise ModuleNotFoundError("No module named '_kendall_counts'", name=name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(native_kendall.importlib, 'import_module', absent)
    monkeypatch.setattr(native_kendall, '__file__', str(tmp_path / 'backend/workbench/native_kendall.py'))
    directory = tmp_path / 'local/native-kendall'
    directory.mkdir(parents=True)
    native_kendall._load_native.cache_clear()
    yield native_kendall, directory
    native_kendall._load_native.cache_clear()


def test_absent_native_artifact_is_explicitly_unavailable(isolated_loader):
    kernel, _ = isolated_loader
    assert kernel._load_native() is None


@pytest.mark.parametrize('name', ['_kendall_counts.cpython-000-other.so', '_kendall_counts.pyd'])
def test_foreign_abi_artifact_cannot_silently_select_reference(isolated_loader, name):
    kernel, directory = isolated_loader
    (directory / name).write_bytes(b'foreign ABI artifact, never execute')
    with pytest.raises(RuntimeError, match='ABI mismatch'):
        kernel._load_native()


def test_api_version_float_equality_cannot_pass_integer_metadata_contract(isolated_loader, monkeypatch):
    kernel, _ = isolated_loader
    monkeypatch.setattr(kernel.importlib, 'import_module', lambda _: SimpleNamespace(API_VERSION=4.0))
    with pytest.raises(RuntimeError, match='API_VERSION mismatch'):
        kernel._load_native()
