"""Evaluation evidence only: LR/margins admission remains closed.

Run this file directly to regenerate actual owner quantities and preserve the
interaction-derivative FAIL; pytest verifies the bounded evidence and refusal.
"""
import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from scipy.stats import chi2

from workbench.engine.packs.linear_mixed_effects.input import prepare_lmm_input
from workbench.engine.packs.linear_mixed_effects.runner import _fit_prepared, _record_fixed_effects_kernel
from workbench.postestimation import PostestimationRefusal, lr_test
from workbench.postestimation.margins import marginal_effects
from workbench.postestimation.registry import require_validated

FIXTURE = Path(__file__).parent / "fixtures/postestimation/lmm_v1813"
DATA = {
    "random_intercept": FIXTURE.parent.parent / "admission/linear_mixed_effects/data.csv",
    "random_slope": FIXTURE.parent / "lmm_v1811/random_slope.csv",
}
TOLERANCES = json.loads((FIXTURE / "tolerances.json").read_text())


def close(actual, expected, kind="numerical"):
    tolerance = TOLERANCES[kind]
    return bool(abs(actual - expected) <= tolerance["absolute"] + tolerance["relative"] * abs(expected))


def native_stata():
    output = {}
    for row in csv.DictReader((FIXTURE / "native_stata.csv").open()):
        output.setdefault(row["setting"], {})[row["quantity"]] = float(row["value"])
    return output


def evaluate():
    reference = json.loads((FIXTURE / "native_r.json").read_text())
    stata = native_stata()
    output = {"tolerances": TOLERANCES, "admission": "CLOSED", "gaps": [
        "LR refuses actual lmm_gls_conditional covariance: NOT_MODEL_BASED_VARIANCE.",
        "Kernel lacks random-structure and variance-boundary provenance; fixed-name nesting alone is insufficient.",
        "Row fingerprint identifies row labels, not dataset identity; same source must be checked externally.",
        "Generic margins treats time and arm:time as independent design columns; population time derivative is wrong.",
        "Identity link supplied only for this explicit fixed-only evaluation; this does not admit LMM prediction context.",
    ]}
    for setting, path in DATA.items():
        frame = pd.read_csv(path).dropna(subset=["y", "x", "time", "g", "arm"])
        fits = []
        kernels = []
        for controls in (["x"], []):
            prepared = prepare_lmm_input(frame, outcome="y", controls=controls, options={
                "subject_id": "g", "time": "time", "group": "arm", "fit_method": "ml",
                "random_slope": setting == "random_slope"})
            fitted = _fit_prepared(prepared)
            ctx = SimpleNamespace(artifacts={})
            _record_fixed_effects_kernel(ctx, fitted)
            fits.append(fitted)
            kernels.append(ctx.artifacts["_inference_kernels"]["linear_mixed_effects_1"])
        full, reduced = fits
        kernel = kernels[0]
        design = dict(zip(kernel["param_names"], np.asarray(full.model.exog).T))
        margins = marginal_effects(kernel, design, inverse_link="identity", variables=["x", "time"])
        actual_margins = {effect["variable"]: effect for effect in margins["effects"]}
        statistic = 2 * (full.llf - reduced.llf)
        quantities = {"loglik_full": float(full.llf), "loglik_restricted": float(reduced.llf),
                      "statistic": float(statistic), "df": 1, "p_value": float(chi2.sf(statistic, 1))}
        checks = {}
        for name, actual in quantities.items():
            kind = "p_value" if name == "p_value" else "numerical"
            checks[name] = {"R": close(actual, reference[setting][name], kind), "Stata": close(actual, stata[setting][name], kind)}
        for variable in ("x", "time"):
            for name in ("estimate", "std_error"):
                actual = actual_margins[variable][name]
                checks[f"margins.{variable}.{name}"] = {
                    "R": close(actual, reference[setting]["margins"][variable][name]),
                    "Stata": close(actual, stata[setting][f"{variable}.{name}"]),
                }
        try:
            lr_test(*kernels)
            refusal = None
        except PostestimationRefusal as exc:
            refusal = {"code": exc.code, "message": exc.message}
        output[setting] = {
            "data_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "nobs": int(full.nobs), "converged": bool(full.converged and reduced.converged),
            "sample_fingerprints_match": kernels[0]["estimation_sample_fingerprint"] == kernels[1]["estimation_sample_fingerprint"],
            "kernel_fields": sorted(kernel), "covariance_estimator": kernel["covariance_estimator"],
            "computed_lr_quantity_only": quantities, "public_lr_refusal": refusal,
            "margins": actual_margins, "comparisons": checks,
            "status": "PASS" if all(all(v.values()) for v in checks.values()) else "FAIL",
        }
    return output


@pytest.fixture(scope="module")
def live_owner_results():
    # Saved FAIL is historical evidence; tests must still evaluate current code.
    # Leave the original evidence file untouched on every verification run.
    return evaluate()


@pytest.mark.parametrize("setting", DATA)
def test_native_lmm_quantity_agreement_and_recorded_semantic_gap(setting, live_owner_results):
    r = json.loads((FIXTURE / "native_r.json").read_text())[setting]
    s = native_stata()[setting]
    result = live_owner_results[setting]
    provenance = json.loads((FIXTURE / "provenance.json").read_text())
    assert result["data_sha256"] in provenance["source_sha256"].values()
    assert r["converged"] and not r["singular"] and r["same_sample"]
    assert s["full_converged"] == s["restricted_converged"] == 1
    assert result["converged"] and result["sample_fingerprints_match"]
    for key in ("loglik_full", "loglik_restricted", "statistic"):
        assert close(s[key], r[key])
        assert all(result["comparisons"][key].values())
    for variable in ("x", "time"):
        for quantity in ("estimate", "std_error"):
            assert close(s[f"{variable}.{quantity}"], r["margins"][variable][quantity])
        assert close(r["margins"][variable]["prediction_derivative"], r["margins"][variable]["estimate"])
    assert all(result["comparisons"]["margins.x.estimate"].values())
    assert all(result["comparisons"]["margins.x.std_error"].values())
    # This is an expected recorded failure, NOT successful margins validation.
    assert result["status"] == "FAIL"
    assert not any(result["comparisons"]["margins.time.estimate"].values())
    assert result["public_lr_refusal"]["code"] == "NOT_MODEL_BASED_VARIANCE"


@pytest.mark.parametrize("operation", ["lr", "margins"])
def test_evaluation_does_not_open_admission(operation):
    with pytest.raises(PostestimationRefusal) as caught:
        require_validated("linear_mixed_effects", operation)
    assert caught.value.code == "NOT_YET_VALIDATED"


if __name__ == "__main__":
    result = evaluate()
    (FIXTURE / "owner_results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    for setting in DATA:
        print(setting, result[setting]["status"], result[setting]["public_lr_refusal"]["code"])
    raise SystemExit(1 if any(result[setting]["status"] == "FAIL" for setting in DATA) else 0)
