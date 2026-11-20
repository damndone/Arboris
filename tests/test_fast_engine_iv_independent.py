"""Independent IV arithmetic and properties; no reference-engine output is the oracle."""
from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.oracles.iv_high_precision import high_precision

from workbench.estimation_engine import native
from workbench.estimation_engine.iv import fast_iv_2sls


FIXTURE = Path(__file__).parent / "fixtures/fast_engine_iv_independent"
SHAPES = ("plain", "weak", "near_collinear", "near_collinear_endog", "scaled", "small", "missing")


def design(rows=96):
    rng = np.random.default_rng(31)
    w, z1, z2, z3, u, v1, v2 = (rng.normal(size=rows) for _ in range(7))
    d1 = .6 * z1 + .4 * z2 + .5 * u + v1
    d2 = -.3 * z1 + .7 * z3 + .2 * w - .4 * u + v2
    return pd.DataFrame(dict(y=1 + .3 * w + .8 * d1 - .5 * d2 + u * (1 + abs(w)),
                             w=w, d1=d1, d2=d2, z1=z1, z2=z2, z3=z3))


def fast(data, covariance="robust", endog=("d1", "d2"), instruments=("z1", "z2", "z3")):
    fitted, selection = fast_iv_2sls(data, y="y", exog=["w"], endog=list(endog),
                                     instruments=list(instruments), covariance=covariance)
    assert fitted is not None, selection.reason
    return fitted


def numerical_fields(fitted):
    out = {f"params.{name}": float(value) for name, value in fitted.params.items()}
    out.update({f"cov.{a}.{b}": float(fitted.cov.loc[a, b]) for a in fitted.params.index for b in fitted.params.index})
    for attr in ("std_errors", "tstats"):
        out.update({f"{attr}.{name}": float(value) for name, value in getattr(fitted, attr).items()})
    for attr in ("nobs", "df_model", "df_resid", "ssr", "centered_tss", "rsquared", "rsquared_adj"):
        out[attr] = float(getattr(fitted, attr))
    for name, row in fitted.first_stage.diagnostics.iterrows():
        out[f"first_stage.{name}"] = float(row["f.stat"])
        out[f"first_stage.{name}.df"] = fitted.model.instruments.shape[1]
        if fitted.cov_type == "unadjusted":
            out[f"first_stage.{name}.df_denom"] = fitted.nobs-fitted.model.exog.shape[1]-fitted.model.instruments.shape[1]
    for attr in ("wooldridge_regression", "wooldridge_overid", "sargan"):
        test = getattr(fitted, attr)
        if np.isfinite(test.stat):
            out[attr], out[f"{attr}.df"] = float(test.stat), float(test.df)
    if fitted.cov_type == "unadjusted":
        test = fitted.wu_hausman()
        key = "wu_hausman_control_function"
        out[key], out[f"{key}.df"], out[f"{key}.df_denom"] = float(test.stat), float(test.df), float(test.df_denom)
    return out


def shaped_data(shape):
    # The R generator reads exactly these persisted input doubles.
    data = pd.read_csv(FIXTURE / "data.csv", float_precision="round_trip")
    if shape == "weak":
        data["d1"] -= .595*data.z1 + .395*data.z2
    elif shape == "near_collinear":
        data["z2"] = data.z1 + 1e-5*data.z2
    elif shape == "near_collinear_endog":
        data["d2"] = data.d1 + 1e-5*data.d2
    elif shape == "scaled":
        for name, scale in {"y": 1e6, "w": 1e3, "d1": 1e-3, "z2": 1e-3}.items():
            data[name] *= scale
    elif shape == "small":
        data = data.iloc[:8].copy()
    elif shape == "missing":
        for row, name in enumerate(["y", "w", "d1", "z1"]):
            data.loc[row, name] = np.nan
    elif shape == "shifted":
        data["z1"] += 7 + 4*data.w
        data["z2"] += -3 + 2*data.w
    elif shape == "tail":
        data["y"] += 6*data.d1
    return data


def assert_probability(actual, expected):
    assert math.isfinite(actual) and 0 <= actual <= 1
    assert actual == pytest.approx(expected, rel=1e-9, abs=0)
    if expected > 0:
        assert actual > 0
        assert abs(math.log(actual)-math.log(expected)) <= 1e-9


def assert_fields(actual, expected, nobs):
    """Existing scalar limits, with extra scale-sensitive covariance/SE and exact-df gates."""
    for name, value in actual.items():
        assert name in expected, name
        oracle = expected[name]
        if name in {"nobs", "df_model", "df_resid"} or name.endswith((".df", ".df_denom")):
            assert value == oracle, name
        elif name.startswith("std_errors."):
            assert value == pytest.approx(oracle, rel=1e-9, abs=0), name
        else:
            absolute = max(1e-12, nobs*1e-15) if name in {"sargan", "wooldridge_overid"} else 1e-12
            assert value == pytest.approx(oracle, rel=1e-9, abs=absolute), name
        if name.startswith("cov."):
            _, a, b = name.split(".")
            scale = math.sqrt(expected[f"cov.{a}.{a}"] * expected[f"cov.{b}.{b}"])
            assert abs(value-oracle)/scale <= 1e-9, name


@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
@pytest.mark.parametrize("shape", SHAPES)
def test_independent_moment_oracle_is_stable_at_80_and_110_digits(shape, covariance):
    data = shaped_data(shape)
    a = high_precision(data, ["d1", "d2"], ["z1", "z2", "z3"], covariance)
    b = high_precision(data, ["d1", "d2"], ["z1", "z2", "z3"], covariance, precision=110)
    assert a == b


@pytest.mark.skipif(not native.available(), reason="native engine not built")
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
@pytest.mark.parametrize("shape", SHAPES)
def test_kernel_quantities_match_independent_moment_oracle(shape, covariance):
    data = shaped_data(shape)
    expected = high_precision(data, ["d1", "d2"], ["z1", "z2", "z3"], covariance)
    fitted = fast(data, covariance)
    assert_fields(numerical_fields(fitted), expected, fitted.nobs)
    corr = fitted.cov.to_numpy()/np.outer(fitted.std_errors, fitted.std_errors)
    assert np.linalg.eigvalsh(corr).min() >= -1e-12
    if shape == "weak":
        assert fitted.first_stage.diagnostics.loc["d1", "f.stat"] < 2


def r_fields(case, covariance):
    fields = {key: float(case[key]) for key in ("nobs", "df_model", "df_resid")}
    values = case[covariance]
    for key in ("params", "std_errors", "tstats"):
        fields.update({f"{key}.{name}": value for name, value in values[key].items()})
    fields.update({f"cov.{a}.{b}": value for a, row in values["cov"].items() for b, value in row.items()})
    for name, row in values["first_stage"].items():
        fields[f"first_stage.{name}"] = row["stat"]
        fields[f"first_stage.{name}.df"] = row["df"]
        if row["df_denom"] is not None:
            fields[f"first_stage.{name}.df_denom"] = row["df_denom"]
    for key in ("wooldridge_regression", "wooldridge_overid", "sargan", "wu_hausman_excluded_projection", "wu_hausman_control_function"):
        if key not in values:
            continue
        fields[key], fields[f"{key}.df"] = values[key]["stat"], values[key]["df"]
        if values[key]["df_denom"] is not None:
            fields[f"{key}.df_denom"] = values[key]["df_denom"]
    return fields


@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
@pytest.mark.parametrize("shape", ["plain", "weak", "small", "missing", "shifted", "tail", "just"])
def test_decimal_moments_match_independent_r_fixest_and_auxiliary_qr(shape, covariance):
    case = json.loads((FIXTURE / "oracle.json").read_text())["cases"][shape]
    endog = ["d1"] if shape == "just" else ["d1", "d2"]
    instruments = ["z1"] if shape == "just" else ["z1", "z2", "z3"]
    expected = high_precision(shaped_data(shape), endog, instruments, covariance)
    assert_fields(r_fields(case, covariance), expected, case["nobs"])
    if covariance == "unadjusted":
        assert case[covariance]["wu_hausman_fixest"]["stat"] == pytest.approx(expected["wu_hausman_control_function"], rel=1e-9)


@pytest.mark.skipif(not native.available(), reason="native engine not built")
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
@pytest.mark.parametrize("shape", ["plain", "weak", "small", "missing", "shifted", "tail", "just"])
def test_native_covariance_statistics_df_and_tail_probabilities_match_r(shape, covariance):
    case = json.loads((FIXTURE / "oracle.json").read_text())["cases"][shape]
    endog = ["d1"] if shape == "just" else ["d1", "d2"]
    instruments = ["z1"] if shape == "just" else ["z1", "z2", "z3"]
    fitted = fast(shaped_data(shape), covariance, endog, instruments)
    numbers = numerical_fields(fitted)
    r_numbers = r_fields(case, covariance)
    assert_fields({key: value for key, value in numbers.items() if key in r_numbers}, r_numbers, fitted.nobs)
    for name, pvalue in case[covariance]["pvalues"].items():
        assert_probability(float(fitted.pvalues[name]), pvalue)
    critical_values = json.loads((FIXTURE / "oracle.json").read_text())["meta"]["normal_critical_values"]
    for level, critical in critical_values.items():
        interval = fitted.conf_int(level=float(level))
        for name, beta in case[covariance]["params"].items():
            se = case[covariance]["std_errors"][name]
            for side, expected in (("lower", beta-critical*se), ("upper", beta+critical*se)):
                assert interval.loc[name, side] == pytest.approx(expected, rel=1e-9, abs=1e-12)
                assert abs(interval.loc[name, side]-expected)/se <= 1e-9
    for name, test in case[covariance]["first_stage"].items():
        assert_probability(float(fitted.first_stage.diagnostics.loc[name, "f.pval"]), test["pval"])
    for key in ("wooldridge_regression", "wooldridge_overid", "sargan"):
        if key in case[covariance]:
            assert_probability(getattr(fitted, key).pval, case[covariance][key]["pval"])
    if covariance == "unadjusted":
        assert_probability(fitted.wu_hausman().pval, case[covariance]["wu_hausman_control_function"]["pval"])
    if shape == "tail":
        assert 0 < fitted.pvalues["d1"] < 1e-100


@pytest.mark.parametrize("actual, expected", [(0, 1e-110), (1.01e-110, 1e-110), (float("nan"), .1)])
def test_probability_check_rejects_zeroed_or_wrong_small_tail(actual, expected):
    with pytest.raises(AssertionError):
        assert_probability(actual, expected)


@pytest.mark.parametrize("field, actual, expected", [("std_errors.d1", 1.01e-15, 1e-15),
                                                       ("cov.d1.d1", 1.01e-30, 1e-30),
                                                       ("df_resid", 92.001, 92)])
def test_scale_sensitive_checks_reject_errors_hidden_by_a_fixed_absolute_tolerance(field, actual, expected):
    oracle = {field: expected}
    with pytest.raises(AssertionError):
        assert_fields({field: actual}, oracle, 96)


@pytest.mark.skipif(not native.available(), reason="native engine not built")
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
def test_nearly_collinear_instrument_basis_preserves_first_stage_wald(covariance):
    """This invertible change of instrument basis leaves the tested subspace unchanged."""
    data = design()
    expected = fast(data, covariance).first_stage.diagnostics["f.stat"]
    changed = data.assign(z2=data.z1 + 1e-5 * data.z2)
    actual = fast(changed, covariance).first_stage.diagnostics["f.stat"]
    np.testing.assert_allclose(actual, expected, rtol=1e-9, atol=1e-12)


@pytest.mark.skipif(not native.available(), reason="native engine not built")
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
def test_nearly_collinear_endogenous_basis_preserves_joint_endogeneity_wald(covariance):
    data = design()
    expected = fast(data, covariance).wooldridge_regression.stat
    changed = data.assign(d2=data.d1 + 1e-5 * data.d2)
    actual = fast(changed, covariance).wooldridge_regression.stat
    assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12)


def test_high_precision_oracle_includes_covariance_and_degrees_of_freedom():
    expected = high_precision(design(), ["d1", "d2"], ["z1", "z2", "z3"])
    assert "cov.d1.d2" in expected
    assert expected["df_resid"] == 92
    assert expected["wu_hausman_control_function.df_denom"] == 90


@pytest.mark.skipif(not native.available(), reason="native engine not built")
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
def test_column_reordering_preserves_named_quantities(covariance):
    data = design()
    before = fast(data, covariance)
    after = fast(data[data.columns[::-1]], covariance, ("d2", "d1"), ("z3", "z2", "z1"))
    assert_fields(numerical_fields(after), numerical_fields(before), before.nobs)


@pytest.mark.skipif(not native.available(), reason="native engine not built")
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
def test_measurement_units_transform_parameters_covariance_and_se(covariance):
    data = design()
    before = fast(data, covariance)
    scales = {"y": 1e-6, "w": 1e3, "d1": 1e-3, "d2": 1e2, "z1": 1e-2, "z2": 1e3, "z3": 1e-1}
    after = fast(data.assign(**{name: data[name]*scale for name, scale in scales.items()}), covariance)
    factor = np.array([scales["y"], *[scales["y"]/scales[name] for name in ("w", "d1", "d2")]])
    expected = numerical_fields(before)
    for i, name in enumerate(before.params.index):
        expected[f"params.{name}"] *= factor[i]
        expected[f"std_errors.{name}"] *= factor[i]
        for j, other in enumerate(before.params.index):
            expected[f"cov.{name}.{other}"] *= factor[i]*factor[j]
    expected["ssr"] *= scales["y"]**2
    expected["centered_tss"] *= scales["y"]**2
    assert_fields(numerical_fields(after), expected, before.nobs)


@pytest.mark.skipif(not native.available(), reason="native engine not built")
@pytest.mark.parametrize("covariance", ["robust", "unadjusted"])
def test_translation_preserves_slopes_and_transforms_intercept_covariance(covariance):
    data = design()
    before = fast(data, covariance)
    shifts = {"y": 3, "w": -2, "d1": 5, "d2": -1, "z1": 7, "z2": -3, "z3": 2}
    after = fast(data.assign(**{name: data[name]+shift for name, shift in shifts.items()}), covariance)
    transform = np.eye(4)
    transform[0, 1:] = -np.array([shifts[name] for name in ("w", "d1", "d2")])
    beta = transform @ before.params.to_numpy()
    beta[0] += shifts["y"]
    cov = transform @ before.cov.to_numpy() @ transform.T
    np.testing.assert_allclose(after.params, beta, rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(after.cov, cov, rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(after.std_errors, np.sqrt(np.diag(cov)), rtol=1e-9, atol=0)
    for attr in ("wooldridge_regression", "wooldridge_overid", "sargan"):
        if np.isfinite(getattr(before, attr).stat):
            assert getattr(after, attr).stat == pytest.approx(getattr(before, attr).stat, rel=1e-9, abs=1e-12)
    np.testing.assert_allclose(after.first_stage.diagnostics["f.stat"], before.first_stage.diagnostics["f.stat"], rtol=1e-9, atol=1e-12)
    if covariance == "unadjusted":
        assert after.wu_hausman().stat == pytest.approx(before.wu_hausman().stat, rel=1e-9, abs=1e-12)
        assert_probability(after.wu_hausman().pval, before.wu_hausman().pval)


def test_legacy_excluded_only_projection_defect_is_retained_under_instrument_translation():
    base = high_precision(shaped_data("plain"), ["d1", "d2"], ["z1", "z2", "z3"])
    shifted = high_precision(shaped_data("shifted"), ["d1", "d2"], ["z1", "z2", "z3"])
    assert shifted["wu_hausman_control_function"] == pytest.approx(base["wu_hausman_control_function"], rel=1e-12)
    assert abs(shifted["wu_hausman_excluded_projection"]-base["wu_hausman_excluded_projection"]) > .5


@pytest.mark.parametrize("kind", ["robust", "unadjusted"])
def test_decimal_oracle_rejects_infinite_values_and_nonpositive_control_df(kind):
    data = design()
    data.loc[0, "d1"] = np.inf
    with pytest.raises(ValueError, match="non-finite"):
        high_precision(data, ["d1", "d2"], ["z1", "z2", "z3"], kind)
    with pytest.raises(ValueError, match="positive augmented"):
        high_precision(design().iloc[:6], ["d1", "d2"], ["z1", "z2", "z3"], kind)


REFERENCE_GAPS = json.loads((FIXTURE / "reference_gaps.json").read_text())["cases"]


@pytest.mark.skipif(not native.available(), reason="native engine not built")
@pytest.mark.parametrize("case", REFERENCE_GAPS, ids=lambda case: f"{case['rows']}-{case['case']}-{case['covariance']}")
def test_explicit_reference_disagreements_pass_independent_precision_gates(case):
    """A compatibility FAIL is retained even when independent arithmetic supports the fast value."""
    from test_fast_engine_iv import DESIGNS, _design, _fast

    assert case["reference_agreement"] is False and case["precision_stable_as_float"] is True
    data = _design(case["rows"], case["seed"], scale=1e6)
    assert hashlib.sha256(data.to_numpy().tobytes()).hexdigest() == case["input_array_sha256"]
    fitted = _fast(data, *DESIGNS[case["case"]], case["covariance"])
    for item in case["fields"]:
        field, expected = item["field"], item["independent"]
        assert item["reference_agreement"] is False
        if field.startswith("cov."):
            _, a, b = field.split(".")
            actual = fitted.cov.loc[a, b]
            assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12), field
            assert abs(actual-expected)/item["independent_covariance_scale"] <= 1e-9, field
            with pytest.raises(AssertionError):
                assert item["reference"] == pytest.approx(expected, rel=1e-9, abs=1e-12), field
        else:
            if field.startswith("pvalues."):
                actual = fitted.pvalues[field.removeprefix("pvalues.")]
            elif field.startswith("first_stage."):
                actual = fitted.first_stage.diagnostics.loc[field.split(".")[1], "f.pval"]
            else:
                # Retain the old raw evidence for the legacy arithmetic, but
                # validate current Wu against the independently derived standard F.
                from scipy import stats
                hp = high_precision(data, *DESIGNS[case["case"]], case["covariance"])
                df, denominator = hp["wu_hausman_control_function.df"], hp["wu_hausman_control_function.df_denom"]
                legacy_p = float(stats.f.sf(hp["wu_hausman_excluded_projection"], df, denominator))
                assert_probability(legacy_p, expected)
                with pytest.raises(AssertionError):
                    assert_probability(item["reference"], expected)
                expected = float(stats.f.sf(hp["wu_hausman_control_function"], df, denominator))
                actual = fitted.wu_hausman().pval
                assert_probability(float(actual), expected)
                continue
            assert_probability(float(actual), expected)
            with pytest.raises(AssertionError):
                assert_probability(item["reference"], expected)
