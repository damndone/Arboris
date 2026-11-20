"""The opt-in fast IV engine against R fixest and linearmodels, and the default path left untouched."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd
import pytest

from workbench.econometrics.panel_iv import run_iv_2sls
from workbench.estimation_engine import (
    AGREEMENT_ABSOLUTE, AGREEMENT_RELATIVE, FAST_ENGINE_NAME, EstimationEngineError, native, stored_choice,
)
from workbench.estimation_engine.iv import N_R_SQUARED_STATISTICS, comparable_numbers, disagreements, fast_iv_2sls

pytestmark = pytest.mark.skipif(not native.available(), reason="native/engine/build.py has not been run")
FIXTURE = Path(__file__).parent / "fixtures/fast_engine_iv"
# The original grid's recorded envelope applies only to its original fields below.
# Expanded covariance/tail comparisons have separate independent oracles and explicit gaps.
MEASURED_WORST_RELATIVE = {"plain": 1e-12, "heavy_tails": 2e-11, "scaled": 5e-10}


def _reference(data, endog, instruments, covariance, exog=("w",)):
    from linearmodels.iv import IV2SLS

    formula = f"y ~ 1 + {' + '.join(exog)} + [{' + '.join(endog)} ~ {' + '.join(instruments)}]"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return IV2SLS.from_formula(formula, data=data).fit(cov_type=covariance)


def _fast(data, endog, instruments, covariance, exog=("w",)):
    fitted, selection = fast_iv_2sls(data, y="y", exog=list(exog), endog=list(endog),
                                     instruments=list(instruments), covariance=covariance)
    assert fitted is not None, selection.reason
    return fitted


def _design(rows, seed, *, scale=1.0, heavy_tails=False):
    rng = np.random.default_rng(seed)
    z1, z2, z3, w, u = (rng.normal(size=rows) for _ in range(5))
    noise = rng.standard_t(3, rows) if heavy_tails else rng.normal(size=rows)
    d1 = 0.6 * z1 + 0.4 * z2 + 0.5 * u + noise
    d2 = -0.3 * z1 + 0.7 * z3 + 0.2 * w - 0.4 * u + rng.normal(size=rows)
    y = 1 + 0.3 * w + 0.8 * d1 - 0.5 * d2 + u * (1 + np.abs(w))
    return pd.DataFrame({"y": y * scale, "w": w * scale, "d1": d1, "d2": d2, "z1": z1, "z2": z2 / scale, "z3": z3})


DESIGNS = {"over": (["d1"], ["z1", "z2"]), "just": (["d1"], ["z1"]), "two_endogenous": (["d1", "d2"], ["z1", "z2", "z3"])}


@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
def test_complete_case_design_passes_owned_contiguous_columns_to_native(monkeypatch, covariance):
    data = _design(47, 20261105)
    expected = data[["y", "w", "d1", "d2", "z1", "z2", "z3"]].to_numpy().copy()
    native_iv = native.iv_2sls
    calls = []

    def inspect_design(y, exog, endog, instruments, kind):
        if len(y) == len(data):  # the admitted model, apart from the engine self-check
            columns = [y, exog[1], *endog, *instruments]
            assert all(column.flags.c_contiguous for column in [*columns, exog[0]])
            assert np.column_stack(columns).tobytes() == expected.tobytes()
            assert np.all(exog[0] == 1.0)
            calls.append(kind)
        return native_iv(y, exog, endog, instruments, kind)

    monkeypatch.setattr(native, "iv_2sls", inspect_design)
    fitted = _fast(data, *DESIGNS["two_endogenous"], covariance)
    assert calls == [covariance]
    data["y"] = 0.0
    assert fitted.model.dependent.ndarray[:, 0].tobytes() == expected[:, 0].tobytes()


def test_complete_case_does_not_materialize_a_second_table_for_native_fit():
    class ColumnSource(pd.DataFrame):
        def __getitem__(self, key):
            assert not isinstance(key, list), "native input must be assembled from source columns"
            return super().__getitem__(key)

    data = ColumnSource(_design(49, 12345))
    original = data.y.to_numpy(copy=True)
    fitted = _fast(data, *DESIGNS["two_endogenous"], "robust")
    data.loc[:, "y"] = 0.0
    np.testing.assert_array_equal(fitted.model.dependent.ndarray[:, 0], original)


@pytest.mark.parametrize("case", sorted(DESIGNS))
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
def test_estimates_and_standard_errors_match_r_fixest(case, covariance):
    oracle = json.loads((FIXTURE / "oracle.json").read_text())["cases"][case]
    data = pd.read_csv(FIXTURE / "data.csv", float_precision="round_trip")
    fitted = _fast(data, *DESIGNS[case], covariance)
    for name, value in oracle[covariance]["coefficients"].items():
        assert fitted.params[name] == pytest.approx(value, rel=1e-10)
    for name, value in oracle[covariance]["std_error"].items():
        assert fitted.std_errors[name] == pytest.approx(value, rel=1e-10)


@pytest.mark.parametrize("case", sorted(DESIGNS))
def test_specification_statistics_match_r_fixest(case):
    oracle = json.loads((FIXTURE / "oracle.json").read_text())["cases"][case]
    data = pd.read_csv(FIXTURE / "data.csv", float_precision="round_trip")
    fitted = _fast(data, *DESIGNS[case], "unadjusted")
    first_stage = fitted.first_stage.diagnostics
    for name, value in oracle["first_stage_wald_f_unadjusted"].items():
        assert first_stage.loc[name, "f.stat"] == pytest.approx(value, rel=1e-10)
    if "sargan" in oracle:
        assert fitted.sargan.stat == pytest.approx(oracle["sargan"], rel=1e-10)
    assert fitted.wu_hausman().stat == pytest.approx(oracle["wu_hausman"], rel=1e-10)


@pytest.mark.parametrize("case", ["over", "two_endogenous"])
def test_wu_hausman_matches_standard_fixest_while_retaining_the_legacy_projection_defect(case):
    """The raw linearmodels 7.0 expression is retained as a defect regression."""
    oracle = json.loads((FIXTURE / "oracle.json").read_text())["cases"][case]
    data = pd.read_csv(FIXTURE / "data.csv", float_precision="round_trip")
    endog, instruments = DESIGNS[case]
    fast = _fast(data, endog, instruments, "unadjusted").wu_hausman().stat
    assert fast == pytest.approx(oracle["wu_hausman"], rel=1e-10)
    legacy = _reference(data, endog, instruments, "unadjusted").wu_hausman().stat
    assert 1e-9 < abs(legacy / oracle["wu_hausman"] - 1) < 1e-4


@pytest.mark.parametrize("rows", [30, 400, 20_000])
@pytest.mark.parametrize("case", sorted(DESIGNS))
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
@pytest.mark.parametrize("shape", ["plain", "scaled", "heavy_tails"])
def test_original_agreement_grid_and_explicit_expanded_reference_gaps(rows, case, covariance, shape):
    data = _design(rows, rows + len(case), scale=1e6 if shape == "scaled" else 1.0, heavy_tails=shape == "heavy_tails")
    endog, instruments = DESIGNS[case]
    try:
        reference_fit = _reference(data, endog, instruments, covariance)
    except ValueError as refused:
        assert "full column rank" in str(refused)
        fitted, selection = fast_iv_2sls(data, y="y", exog=["w"], endog=endog, instruments=instruments,
                                         covariance=covariance)
        assert fitted is None and selection.used == "reference"
        return
    fitted = _fast(data, endog, instruments, covariance)
    mine, reference = comparable_numbers(fitted), comparable_numbers(reference_fit)
    original_names = {name for name in reference if name.startswith(("params.", "std_errors."))
                      or name in {"rsquared", "rsquared_adj", "wooldridge_regression", "wooldridge_overid", "sargan", "wu_hausman"}
                      or name in {f"first_stage.{column}" for column in endog}}
    assert disagreements({name: mine[name] for name in original_names},
                         {name: reference[name] for name in original_names}, fitted.nobs) == []
    # A reference disagreement remains explicit and frozen, not a widened tolerance. The
    # separate tests require HP/R evidence that the fast result passes while reference fails.
    recorded = json.loads((FIXTURE.parent / "fast_engine_iv_independent/reference_gaps.json").read_text())["cases"]
    known = next((entry for entry in recorded if (entry["rows"], entry["case"], entry["covariance"], entry["shape"])
                  == (rows, case, covariance, shape)), None)
    expanded = disagreements(mine, reference, fitted.nobs)
    # Old Wu-tail records describe the excluded-only defect. Both current
    # product paths now use full-Z Wu T2 and remain compared at the same tolerances.
    assert [line.split(": fast ", 1)[0] for line in expanded] == ([] if known is None else [entry["field"] for entry in known["fields"] if entry["field"] != "wu_hausman.pval"])
    worst = max(abs(mine[name] - value) / abs(value) for name, value in reference.items() if name in original_names
                if abs(value) > AGREEMENT_ABSOLUTE and name not in N_R_SQUARED_STATISTICS)
    assert worst < MEASURED_WORST_RELATIVE[shape] < AGREEMENT_RELATIVE


def test_selected_fast_engine_outputs_match_stable_high_precision_arithmetic():
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts/oracles"))
    from iv_high_precision import high_precision

    for rows, case, shape in ((400, "two_endogenous", "scaled"), (3000, "two_endogenous", "heavy_tails")):
        data = _design(rows, rows + len(case), scale=1e6 if shape == "scaled" else 1.0, heavy_tails=shape == "heavy_tails")
        endog, instruments = DESIGNS[case]
        truth = high_precision(data, endog, instruments)
        higher = high_precision(data, endog, instruments, precision=110)
        assert truth == higher
        mine = comparable_numbers(_fast(data, endog, instruments, "unadjusted"))
        for name, value in truth.items():
            if not (name.startswith("params.") or name in {"sargan", "wooldridge_overid"}):
                continue
            assert abs(mine[name] - value) / abs(value) < 1e-13, name


def test_a_missing_exogenous_value_drops_its_row_as_the_reference_does():
    data = _design(500, 9)
    data.loc[[3, 70], "w"] = np.nan
    fitted = _fast(data, ["d1"], ["z1", "z2"], "robust")
    reference = _reference(data, ["d1"], ["z1", "z2"], "robust")
    assert fitted.nobs == reference.nobs == 498
    assert np.array_equal(fitted.model.notnull, np.asarray(reference.model.notnull))
    assert disagreements(comparable_numbers(fitted), comparable_numbers(reference), fitted.nobs) == []


@pytest.mark.parametrize("column", ["y", "d1", "z2"])
def test_a_missing_outcome_endogenous_or_instrument_value_drops_its_row_in_both_engines(column):
    """The formula interface used to refuse these rows, so every IV run with such a gap failed."""
    data = _design(600, 11)
    data.loc[[4, 250], column] = np.nan
    data.loc[9, "w"] = np.nan
    default, fitted = run_iv_2sls(data, y="y", exog=["w"], endog=["d1"], instruments=["z1", "z2"], model_id="iv_2sls_1")
    fast, fast_fit = run_iv_2sls(data, y="y", exog=["w"], endog=["d1"], instruments=["z1", "z2"], model_id="iv_2sls_1",
                                 estimation_engine="fast")
    assert default["nobs"] == fast["nobs"] == 597
    assert default["warnings"] == fast["warnings"] and "3 of 600 rows" in default["warnings"][0]
    assert np.array_equal(np.asarray(fitted.model.notnull), fast_fit.model.notnull)
    assert np.flatnonzero(~fast_fit.model.notnull).tolist() == [4, 9, 250]
    complete = _reference(data.dropna(), ["d1"], ["z1", "z2"], "robust")
    assert fitted.params.to_numpy().tobytes() == complete.params.to_numpy().tobytes()
    assert disagreements(comparable_numbers(fast_fit), comparable_numbers(fitted), fast_fit.nobs) == []


def test_without_such_gaps_the_reference_fit_is_the_formula_fit_bit_for_bit():
    data = _design(600, 12)
    data.loc[9, "w"] = np.nan
    default, fitted = run_iv_2sls(data, y="y", exog=["w"], endog=["d1"], instruments=["z1", "z2"], model_id="iv_2sls_1")
    formula = _reference(data, ["d1"], ["z1", "z2"], "robust")
    assert fitted.params.to_numpy().tobytes() == formula.params.to_numpy().tobytes()
    assert fitted.cov.to_numpy().tobytes() == formula.cov.to_numpy().tobytes()
    assert default["warnings"] == []


@pytest.mark.parametrize("change, reason", [
    (lambda data: data.assign(w=data.w.astype(str)), "not an integer or float column"),
    (lambda data: data.rename(columns={"w": "w 1"}), "needs formula quoting"),
])
def test_what_the_fast_engine_does_not_cover_runs_on_the_reference(change, reason):
    data = change(_design(300, 1))
    exog = ["w 1"] if "w 1" in data.columns else ["w"]
    fitted, selection = fast_iv_2sls(data, y="y", exog=exog, endog=["d1"], instruments=["z1", "z2"], covariance="robust")
    assert fitted is None and selection.used == "reference" and reason in selection.reason


def test_an_uncovered_covariance_and_a_collinear_design_run_on_the_reference():
    data = _design(300, 2)
    _, clustered = fast_iv_2sls(data, y="y", exog=["w"], endog=["d1"], instruments=["z1"], covariance="clustered")
    assert "not covered" in clustered.reason
    collinear = data.assign(w2=2 * data.w)
    fitted, selection = fast_iv_2sls(collinear, y="y", exog=["w", "w2"], endog=["d1"], instruments=["z1"], covariance="robust")
    assert fitted is None and selection.used == "reference" and "collinear regressors" in selection.reason


def test_the_default_path_is_the_reference_with_no_new_fields():
    data = _design(300, 3)
    default, fitted = run_iv_2sls(data, y="y", exog=["w"], endog=["d1"], instruments=["z1", "z2"], model_id="iv_2sls_1")
    explicit, _ = run_iv_2sls(data, y="y", exog=["w"], endog=["d1"], instruments=["z1", "z2"], model_id="iv_2sls_1",
                              estimation_engine="reference")
    assert default == explicit and default["engine"] == "linearmodels" and "engine_selection" not in default
    assert type(fitted).__module__.startswith("linearmodels")


def test_a_fast_request_names_the_engine_and_its_agreement_or_the_reason_it_stood_aside():
    data = _design(300, 4)
    fast, _ = run_iv_2sls(data, y="y", exog=["w"], endog=["d1"], instruments=["z1", "z2"], model_id="iv_2sls_1",
                          estimation_engine="fast")
    assert fast["engine"] == FAST_ENGINE_NAME
    assert fast["engine_selection"]["bit_identical_to_reference"] is False
    assert fast["engine_selection"]["agreement_with_reference"]["relative"] == AGREEMENT_RELATIVE
    fallback, _ = run_iv_2sls(data, y="y", exog=["w"], endog=["d1"], instruments=["z1", "z2"], model_id="iv_2sls_1",
                              covariance="kernel", estimation_engine="fast")
    assert fallback["engine"] == "linearmodels"
    assert fallback["engine_selection"]["used"] == "reference" and "not covered" in fallback["engine_selection"]["reason"]


def test_an_engine_choice_is_stored_only_when_it_is_not_the_default():
    from workbench.run_request import RunRequestError, form_from_request

    assert stored_choice(None) == stored_choice("") == stored_choice(" Reference ") == ""
    assert stored_choice("FAST") == "fast"
    with pytest.raises(EstimationEngineError, match="ESTIMATION_ENGINE_UNKNOWN"):
        stored_choice("turbo")
    assert "estimation_engine" not in form_from_request({"y": "y", "estimation_engine": "reference"})
    assert form_from_request({"y": "y", "estimation_engine": "fast"})["estimation_engine"] == "fast"
    with pytest.raises(RunRequestError, match="ESTIMATION_ENGINE_UNKNOWN"):
        form_from_request({"y": "y", "estimation_engine": "turbo"})


def _leaves(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{path}[{index}]")
    else:
        yield path, value


# Leaves that differ by design: identities, clocks, byte digests of numbers that differ in the last bits.
VOLATILE = ("run_id", "created_at", "started_at", "finished_at", "completed_at", "sha256", "dag_hash", "node_hash",
            "op_spec_hash", "parents[", "duration", "elapsed", "_seconds", "timestamp", "artifact_hash", "fingerprint")


@pytest.mark.parametrize("gap", ["w", "z2"])
def test_a_whole_iv_run_matches_the_reference_run_except_the_engine_record(tmp_path, gap):
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    data = _design(2000, 5)
    data.loc[7, gap] = np.nan
    source = tmp_path / "iv.csv"
    data[["y", "w", "d1", "z1", "z2"]].to_csv(source, index=False)
    runs = {}
    for engine in ("reference", "fast"):
        project = create_project(tmp_path, engine)
        outcome = run_workflow(project.root, [source], mode="auto", model_type="iv_2sls", y="y", x=["w"],
                               iv_endog=["d1"], iv_instruments=["z1", "z2"], estimation_engine=engine)
        assert outcome["status"] == "completed"
        runs[engine] = project.root / "runs" / outcome["run_id"]
    different = []
    for path in sorted(runs["reference"].rglob("*.json")):
        relative = path.relative_to(runs["reference"])
        mine = dict(_leaves(json.loads((runs["fast"] / relative).read_text())))
        theirs = dict(_leaves(json.loads(path.read_text())))
        for key in sorted(set(mine) | set(theirs)):
            if any(marker in key for marker in VOLATILE) or ".engine_selection." in key or "estimation_engine" in key:
                continue
            a, b = mine.get(key, "<absent>"), theirs.get(key, "<absent>")
            if isinstance(a, float) and isinstance(b, float):
                if not np.isclose(a, b, rtol=AGREEMENT_RELATIVE, atol=AGREEMENT_ABSOLUTE):
                    different.append(f"{relative}{key}")
            elif a != b and not (key.endswith(".engine") and {a, b} == {"linearmodels", FAST_ENGINE_NAME}):
                different.append(f"{relative}{key}: {a!r} vs {b!r}")
    assert different == []


def test_a_rerun_or_override_with_an_unknown_engine_is_refused_before_a_run_exists(tmp_path):
    from workbench.projects import create_project
    from workbench.services.run_service import _submit_run

    project = create_project(tmp_path, "engine")
    before = sorted((project.root / "runs").glob("*"))
    with pytest.raises(EstimationEngineError, match="ESTIMATION_ENGINE_UNKNOWN"):
        _submit_run(project.root, form={"model_type": "iv_2sls", "y": "y", "x": "w", "estimation_engine": "turbo"},
                    upload_bytes=b"y,w\n1,2\n", upload_filename="d.csv", started_at="2026-11-03T00:00:00Z")
    assert sorted((project.root / "runs").glob("*")) == before
