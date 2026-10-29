"""Product-path native canonical selection and failure boundaries."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from workbench import canonical


def bridge():
    return importlib.import_module("workbench.native_canonical")


def test_bridge_is_a_product_module():
    assert importlib.util.find_spec("workbench.native_canonical") is not None


def test_canonical_numeric_product_path_uses_native(monkeypatch):
    native = bridge()
    calls = []
    values = [1] * 100_000
    encoded = "[" + ",".join(["1"] * len(values)) + "]"
    monkeypatch.setattr(native, "_load", lambda: (SimpleNamespace(
        encode_numbers=lambda values: calls.append(list(values)) or encoded
    ), "native", "extension_loaded"))
    assert canonical.canonical_json_v1({"evidence": values}) == '{"evidence":' + encoded + '}'
    assert calls == [values]


def test_missing_binary_explicit_reference_audit(monkeypatch, tmp_path):
    native = bridge()
    monkeypatch.setattr(native, "_extension_directory", lambda: tmp_path)
    native._load.cache_clear()
    try:
        assert canonical.canonical_json_v1([10**21, 1e21]) == "[1000000000000000000000,1000000000000000000000]"
        assert native.backend_info() == {"engine": "reference", "reason": "extension_not_built",
                                         "measured_min_items": 100_000, "small_sequence_engine": "reference"}
    finally:
        native._load.cache_clear()


@pytest.mark.parametrize("failure", [ImportError("broken extension"), RuntimeError("ABI mismatch")])
def test_loader_errors_propagate(monkeypatch, tmp_path, failure):
    native = bridge()
    monkeypatch.setattr(native, "_extension_directory", lambda: tmp_path)
    (tmp_path / ("_canonical_numbers" + native.EXT_SUFFIX)).touch()
    monkeypatch.setattr(native, "_load_extension", lambda path: (_ for _ in ()).throw(failure))
    native._load.cache_clear()
    try:
        with pytest.raises(type(failure), match=str(failure)):
            native.backend_info()
    finally:
        native._load.cache_clear()


def test_wrong_interpreter_binary_is_not_missing(monkeypatch, tmp_path):
    native = bridge()
    monkeypatch.setattr(native, "_extension_directory", lambda: tmp_path)
    (tmp_path / "_canonical_numbers.cpython-000-other.so").touch()
    native._load.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="interpreter ABI"):
            native.backend_info()
    finally:
        native._load.cache_clear()



@pytest.mark.parametrize("version", [0, None, True, "1"])
def test_extension_abi_is_verified(monkeypatch, tmp_path, version):
    native = bridge()
    monkeypatch.setattr(native.importlib.util, "spec_from_file_location", lambda *args:
        SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None)))
    monkeypatch.setattr(native.importlib.util, "module_from_spec", lambda spec:
        SimpleNamespace(ABI_VERSION=version))
    with pytest.raises(RuntimeError, match="ABI mismatch"):
        native._load_extension(tmp_path / "_canonical_numbers.so")


def test_backend_audit_is_structured_and_contains_no_input(monkeypatch, tmp_path, caplog):
    native = bridge()
    monkeypatch.setattr(native, "_extension_directory", lambda: tmp_path)
    native._load.cache_clear()
    try:
        native.small_sequence_reference.cache_clear()
        with caplog.at_level("INFO", logger="workbench.native_canonical"):
            canonical.canonical_json_v1([12345.6789])
        record = caplog.records[-1]
        assert record.canonical_engine == "reference"
        assert record.canonical_reason == "below_measured_minimum"
        assert "12345" not in record.getMessage()
    finally:
        native._load.cache_clear()


def test_bounded_agent_context_hashes_preserve_bytes_on_reference_path(monkeypatch):
    import hashlib
    from workbench.agent.context_compiler import (
        NotebookPlanningContextV1, generation_context_hash, freshness_dependency_fingerprint,
        FRESHNESS_DEPENDENCY_FIELDS,
    )
    native = bridge()
    module, engine, reason = native._load()
    if module is None:
        pytest.skip("build the product canonical numeric kernel first")
    context = NotebookPlanningContextV1(
        context_id="test", notebook_id="notebook", run_family_id="family",
        active_head_run_id="run", analysis_contract={"lags": [1, 2, 3]},
        dataset_profile={"quantiles": [0, -0.0, 1e-6, 1e21, 10**21]},
        active_run_summary={"coefficients": [1e21, 10**21, 2.5]},
        bounded_lineage=[], diagnostics=[], artifact_summaries=[], artifact_type_counts={},
        available_capabilities=[], existing_option_summaries=[], user_focus={},
        source_manifest=[], omissions=[], budget_report={}, compiled_at="incidental",
    )
    payload = context.hashable_payload()
    # This oracle explicitly disables the native boundary only within a unit
    # test, never in performance workers or application configuration.
    with monkeypatch.context() as reference:
        reference.setattr(canonical, "_native_encode_numbers", lambda values: None)
        expected = "sha256:" + hashlib.sha256(canonical.canonical_json_v1(payload).encode()).hexdigest()
        expected_fresh = "fresh1:" + hashlib.sha256(canonical.canonical_json_v1(
            {field: payload[field] for field in FRESHNESS_DEPENDENCY_FIELDS}
        ).encode()).hexdigest()
    calls = []
    def tracked(values):
        calls.append(tuple(values))
        return module.encode_numbers(values)
    monkeypatch.setattr(native, "_load", lambda: (SimpleNamespace(encode_numbers=tracked), engine, reason))
    assert generation_context_hash(context) == expected
    assert freshness_dependency_fingerprint(context) == expected_fresh
    assert calls == []  # Bounded contexts are below the measured native cutover.


def test_small_numeric_sequences_do_not_load_native(monkeypatch):
    native = bridge()
    def forbidden():
        pytest.fail("small sequences must use the reference encoder")
    monkeypatch.setattr(native, "_load", forbidden)
    assert canonical.canonical_json_v1([1, 2.5]) == "[1,2.5]"
    assert canonical.canonical_json_v1([1] * 99_999).count(",") == 99_998


def test_large_actual_product_encoding_keeps_reference_bytes(monkeypatch):
    native = bridge()
    module, engine, reason = native._load()
    if module is None:
        pytest.skip("build the product canonical numeric kernel first")
    values = [1e21, 10**21, -0.0, 0, 2.5] * 20_000
    expected = "[" + ",".join(canonical._encode_numbers(values)) + "]"
    calls = []
    def tracked(sequence):
        calls.append(len(sequence))
        return module.encode_numbers(sequence)
    monkeypatch.setattr(native, "_load", lambda: (SimpleNamespace(encode_numbers=tracked), engine, reason))
    assert canonical.canonical_json_v1(values) == expected
    assert calls == [100_000]
