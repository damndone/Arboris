"""native/io_writers against the Python references it replaces, byte for byte."""
from __future__ import annotations

import decimal
import hashlib
import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from workbench import canonical, native_io
from workbench.analysis_loop import fingerprints
from workbench.artifacts import write_json
from workbench.engine.packs.v186_model_families import runtime

pytestmark = pytest.mark.skipif(native_io.module() is None, reason="native/io_writers/build.py has not been run")


def without_native(monkeypatch):
    monkeypatch.setattr(native_io, "module", lambda: None)


# ------------------------------------------------------------------------------------- loader

def test_an_absent_build_selects_the_references(monkeypatch, tmp_path):
    monkeypatch.setattr(native_io, "_directory", lambda: tmp_path)
    native_io.module.cache_clear()
    try:
        assert native_io.module() is None
        assert native_io.json_bytes({"a": 1}) is None
        assert native_io.dumps({"a": [1]}, indent=2) == json.dumps({"a": [1]}, indent=2)
    finally:
        native_io.module.cache_clear()


def test_a_build_for_another_interpreter_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(native_io, "_directory", lambda: tmp_path)
    (tmp_path / "_arboris_io.cpython-000-other.so").touch()
    native_io.module.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="interpreter ABI"):
            native_io.module()
    finally:
        native_io.module.cache_clear()


@pytest.mark.parametrize("version", [0, 2, None, "1", True])
def test_another_abi_fails(monkeypatch, tmp_path, version):
    monkeypatch.setattr(native_io.importlib.util, "spec_from_file_location", lambda *args:
                        SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module: None)))
    monkeypatch.setattr(native_io.importlib.util, "module_from_spec", lambda spec: SimpleNamespace(ABI_VERSION=version))
    with pytest.raises(RuntimeError, match="ABI mismatch"):
        native_io._open(tmp_path / "_arboris_io.so")


def test_a_build_that_disagrees_with_its_reference_stands_aside(monkeypatch, caplog):
    monkeypatch.setattr(native_io, "_first_disagreement", lambda loaded: "csv_rows")
    native_io.module.cache_clear()
    try:
        assert native_io.module() is None
        assert "csv_rows differs from its Python reference" in caplog.text
    finally:
        native_io.module.cache_clear()


def test_the_self_check_catches_a_one_ulp_float_repr(monkeypatch):
    loaded = native_io.module()

    class OffByOne:
        def __getattr__(self, name):
            return getattr(loaded, name)

        def csv_rows(self, columns, *args):
            columns = [(kind, np.nextafter(values, np.inf) if kind == "f" else values) for kind, values in columns]
            return loaded.csv_rows(columns, *args)

    assert native_io._first_disagreement(loaded) is None
    assert native_io._first_disagreement(OffByOne()) == "csv_rows"


# ------------------------------------------------------------------------------------- JSON

def random_json(rng, depth=0):
    roll = rng.random()
    if depth > 4 or roll < 0.45:
        return rng.choice([
            lambda: float(rng.normal() * 10.0 ** rng.integers(-30, 30)),
            lambda: float(rng.choice([0.0, -0.0, math.nan, math.inf, -math.inf, 5e-324, 1e16, 1e-5, 0.1])),
            lambda: int(rng.integers(-2**62, 2**62)) * int(rng.choice([1, 10**20])),
            lambda: bool(rng.integers(0, 2)),
            lambda: None,
            lambda: "".join(chr(int(c)) for c in rng.choice(
                [0, 8, 9, 10, 12, 13, 31, 32, 34, 47, 92, 126, 127, 128, 233, 0x2028, 0x4E2D, 0xFFFF, 0x1F600],
                size=int(rng.integers(0, 6)))),
        ])()
    if roll < 0.75:
        return [random_json(rng, depth + 1) for _ in range(int(rng.integers(0, 5)))]
    if roll < 0.8:
        return tuple(random_json(rng, depth + 1) for _ in range(int(rng.integers(0, 3))))
    return {"".join(rng.choice(list("abcZé中\"\\\n"), size=int(rng.integers(0, 4)))): random_json(rng, depth + 1)
            for _ in range(int(rng.integers(0, 5)))}


OPTIONS = [
    {"indent": 2, "ensure_ascii": False},
    {"indent": 2},
    {"indent": 2, "sort_keys": True},
    {"indent": 0, "ensure_ascii": False},
    {"indent": 4, "sort_keys": True, "ensure_ascii": False},
    {},
    {"sort_keys": True},
    {"separators": (",", ":"), "ensure_ascii": False},
    {"separators": (",", ":"), "sort_keys": True},
]


@pytest.mark.parametrize("options", OPTIONS)
def test_json_matches_json_dumps(options):
    rng = np.random.default_rng(len(str(options)))
    for _ in range(400):
        value = random_json(rng)
        assert native_io.json_bytes(value, **options) == json.dumps(value, **options).encode("utf-8")


@pytest.mark.parametrize("value", [
    {1: "int key"}, {"a": {None: 1}}, {"a": {1.5}}, [b"bytes"], [decimal.Decimal("1.5")], [np.float64(1.5)],
    [np.int64(3)], {"a": type("Text", (str,), {})("subclass")}, [type("Number", (int,), {})(3)],
    [type("Real", (float,), {})(1.5)], type("Mapping", (dict,), {})(a=1), {"a": "\ud800"},
])
def test_json_leaves_other_shapes_to_json_dumps(value):
    assert native_io.json_bytes(value, indent=2, ensure_ascii=False) is None


def test_json_leaves_nan_to_json_dumps_when_it_is_refused():
    assert native_io.json_bytes([math.nan], allow_nan=False) is None
    with pytest.raises(ValueError):
        native_io.dumps([math.nan], allow_nan=False)


def test_json_leaves_cycles_and_deep_nesting_to_json_dumps():
    cycle: list = []
    cycle.append(cycle)
    assert native_io.json_bytes(cycle) is None
    with pytest.raises(ValueError, match="Circular reference"):
        native_io.dumps(cycle)
    deep: list = []
    for _ in range(500):
        deep = [deep]
    assert native_io.json_bytes(deep) is None
    assert native_io.dumps(deep) == json.dumps(deep)


def test_a_shared_container_is_not_a_cycle():
    shared = {"x": [1.5]}
    value = [shared, shared, {"again": shared}]
    assert native_io.json_bytes(value, indent=2) == json.dumps(value, indent=2).encode()


def test_write_json_writes_the_bytes_json_dumps_writes(tmp_path):
    rng = np.random.default_rng(7)
    value = {"rows": [random_json(rng) for _ in range(300)], "text": "é\n中😀"}
    write_json(tmp_path / "native.json", value)
    (tmp_path / "reference.json").write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    assert (tmp_path / "native.json").read_bytes() == (tmp_path / "reference.json").read_bytes()


def test_write_json_still_raises_what_json_raises(tmp_path):
    with pytest.raises(TypeError):
        write_json(tmp_path / "x.json", {"a": {1, 2}})
    with pytest.raises(UnicodeEncodeError):
        write_json(tmp_path / "y.json", {"a": "\ud800"})


def test_the_report_template_embeds_the_same_json():
    from jinja2 import Environment

    rng = np.random.default_rng(11)
    value = {"evidence": [random_json(rng) for _ in range(200)], "html": "<b>&'</b>"}
    template = "{{ value | tojson(indent=2) }}|{{ value | tojson }}"
    reference = Environment(autoescape=True).from_string(template).render(value=value)
    environment = Environment(autoescape=True)
    environment.policies["json.dumps_function"] = native_io.dumps
    assert environment.from_string(template).render(value=value) == reference


# ------------------------------------------------------------------------------------- json_safe

def typed(value):
    """Structure with types, so 1 == 1.0 == True do not compare equal."""
    if isinstance(value, dict):
        return ("dict", [(type(key).__name__, key, typed(item)) for key, item in value.items()])
    if isinstance(value, list):
        return ("list", [typed(item) for item in value])
    if isinstance(value, float) and math.isnan(value):
        return ("float", "nan")
    return (type(value).__name__, value)


def survival_like(rng, size):
    return {
        "kaplan_meier": [{"group": "all", "time": float(t), "survival": float(s), "n_at_risk": int(n)}
                         for t, s, n in zip(rng.random(size), rng.random(size), rng.integers(0, 99, size))],
        "residuals": np.where(rng.random(size) < 0.1, np.nan, rng.normal(size=size)),
        "numpy": [np.float64(math.nan), np.float32(1.5), np.int64(4), np.bool_(True), np.array([[1.0, np.inf]])],
        "pandas": [pd.Series([1.0, None]), pd.DataFrame({"a": [1, 2]})],
        "keys": {1: "int", 2.5: "float", None: "none", ("t",): "tuple", "1": "later wins"},
        "floats": [math.inf, -math.inf, math.nan, -0.0, 1e308],
        "tuple": (1, [2.0, math.nan]),
        "nested": [[[[{"deep": math.nan}]]]],
    }


def test_json_safe_matches_the_runtime_reference(monkeypatch):
    rng = np.random.default_rng(3)
    value = survival_like(rng, 2000)
    native = runtime._json_safe(value)
    without_native(monkeypatch)
    assert typed(native) == typed(runtime._json_safe(value))


def test_json_safe_writes_the_same_packet(monkeypatch, tmp_path):
    rng = np.random.default_rng(5)
    value = survival_like(rng, 5000)
    write_json(tmp_path / "native.json", runtime._json_safe(value))
    without_native(monkeypatch)
    write_json(tmp_path / "reference.json", runtime._json_safe(value))
    assert (tmp_path / "native.json").read_bytes() == (tmp_path / "reference.json").read_bytes()


def test_json_safe_propagates_the_reference_errors():
    class Broken:
        def __str__(self):
            raise ValueError("no text")

    with pytest.raises(ValueError, match="no text"):
        runtime._json_safe({Broken(): 1})
    deep: list = []
    for _ in range(100_000):
        deep = [deep]
    with pytest.raises(RecursionError):
        runtime._json_safe(deep)


# ------------------------------------------------------------------------------------- canonical

def canonical_without_native(monkeypatch, value):
    monkeypatch.setattr(canonical, "_native_canonical_list", lambda values: None)
    monkeypatch.setattr(canonical, "_native_list_kind", lambda values: 0)
    try:
        return canonical.canonical_json_v1(value)
    except Exception as error:  # the same error type and message are expected
        return type(error), str(error)


def canonical_with_native(value):
    try:
        return canonical.canonical_json_v1(value)
    except Exception as error:
        return type(error), str(error)


N = 100_000


def float_list(rng):
    magnitudes = 10.0 ** rng.integers(-320, 309, N)
    values = rng.normal(size=N) * magnitudes
    values[:40] = [0.0, -0.0, 1e-6, 9.999999e-7, 1e21, 9.99999999e20, 5e-324, 1.7976931348623157e308, 0.1, 1 / 3,
                   100.0, 1e16, 123456789012345680.0, 2.0**53, 1e-5, 1.5e-7, -2.5e22, 1e300, 1e-300, 7.0,
                   *rng.normal(size=20)]
    return [float(item) for item in values if math.isfinite(item)]


@pytest.mark.parametrize("make", [
    float_list,
    lambda rng: [float(np.round(item, 2)) for item in rng.normal(30, 10, N)],
    lambda rng: rng.integers(-2**63, 2**63 - 1, N, dtype=np.int64, endpoint=True).tolist(),
    lambda rng: [*rng.integers(0, 50, N).tolist(), 2**63 - 1, -(2**63)],
    lambda rng: [*range(N), 10**20],
    lambda rng: [*range(N), 2.0**60, 2**60],
    lambda rng: [2**60, *[float(item) for item in range(N)], 2.0**60],
    lambda rng: [*[float(item) for item in range(N)], math.nan],
    lambda rng: [*range(N), True],
    lambda rng: [*range(N), 10**400],
    lambda rng: tuple(float(item) for item in rng.normal(size=N)),
    lambda rng: [str(item) for item in range(N)],
    lambda rng: [*(str(item) for item in range(N)), 'q"uote'],
    lambda rng: [*(str(item) for item in range(N)), "tab\t"],
    lambda rng: [*(str(item) for item in range(N)), "é"],
    lambda rng: [*(str(item) for item in range(N)), 7],
])
def test_canonical_lists_match_the_reference(monkeypatch, make):
    value = {"fingerprint_type": "t", "value": {"rows": make(np.random.default_rng(N))}}
    native = canonical_with_native(value)
    assert native == canonical_without_native(monkeypatch, value)


def test_point_estimation_fingerprint_is_unchanged(monkeypatch):
    rng = np.random.default_rng(9)
    arguments = dict(
        y=np.round(rng.normal(20, 5, 300_000), 2).tolist(),
        X={"a": rng.integers(0, 20, 300_000).tolist(), "b": rng.normal(size=300_000).tolist()},
        weights=None, intercept=True, categorical_encoding={"a": "numeric", "b": "numeric"},
        missing_policy="statsmodels_patsy_drop_rows", rows=[str(item) for item in rng.permutation(300_000)],
        solver_options=None,
    )
    native = fingerprints.point_estimation_fingerprint(**arguments)
    monkeypatch.setattr(canonical, "_native_canonical_list", lambda values: None)
    monkeypatch.setattr(canonical, "_native_list_kind", lambda values: 0)
    assert native == fingerprints.point_estimation_fingerprint(**arguments)


def original_sample_fingerprint(row_set, row_order):
    wire = json.dumps({"fingerprint_type": "analysis_sample_v1",
                       "value": {"row_set": sorted(row_set), "row_order": row_order}},
                      ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(wire).hexdigest()


@pytest.mark.parametrize("rows", [
    [], ["0"], ["10", "9", "010", "1", "1"], [str(item) for item in np.random.default_rng(1).permutation(200_000)],
])
def test_sample_fingerprint_matches_the_json_wire(rows):
    assert fingerprints.analysis_sample_fingerprint(rows, rows) == original_sample_fingerprint(rows, rows)
    assert fingerprints.analysis_sample_fingerprint(rows, tuple(reversed(rows))) == \
        original_sample_fingerprint(rows, list(reversed(rows)))


@pytest.mark.parametrize("rows", [["1", ""], ["", ""], ["1", "x"], ["1", "١"], ["1", 2]])
def test_sample_ids_that_are_not_decimal_keep_the_generic_path(rows):
    expected = fingerprints._fingerprint("analysis_sample_v1", {
        "row_set": sorted(rows, key=canonical.canonical_json_v1), "row_order": rows})
    assert fingerprints.analysis_sample_fingerprint(rows, rows) == expected
