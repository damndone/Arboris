"""M2 independent postconditions. Failures are review findings, never xfails."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.econometrics.runner import run_glm, run_negative_binomial

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = json.loads(Path(__file__).with_name("m2_review_evidence.json").read_text())
R = json.loads(Path(__file__).with_name("m2_review_r.json").read_text())


def test_evidence_is_bound_to_current_production_and_inputs():
    for path, expected in EVIDENCE["hashes"].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected


def test_fixed_alpha_glm_matches_independently_polished_native_r_optimum():
    fitted = EVIDENCE["probes"]["glm_precision"]
    np.testing.assert_allclose(fitted["params"], R["polished"]["beta"], rtol=0, atol=1e-8)
    assert max(abs(s) for s in R["polished"]["score"]) < 1e-10
    assert max(abs(s) for s in fitted["natural_score"]) < 1e-8
    assert R["glm"][0]["max_abs_score"] > 1e-6


@pytest.mark.parametrize("family", ["negative_binomial", "poisson"])
def test_count_glm_rejects_negative_support_before_returning_inference(family):
    frame = pd.read_csv(ROOT/"tests/fixtures/count_models/reference-v3/nb2.csv").astype({"y":float})
    frame.loc[0,"y"] = -1
    with pytest.raises(ValueError):
        run_glm(frame,"y",["x1","x2"],"review",family,alpha=.5 if family=="negative_binomial" else None)


@pytest.mark.parametrize("form,index", [("mean",0),("constant",1)])
def test_uncertified_interior_ancillary_point_does_not_publish_regular_oim_inference(form,index):
    frame = pd.read_csv(ROOT/"tests/fixtures/count_models/reference-v3/poisson.csv",float_precision="round_trip")
    try:
        result, fitted = run_negative_binomial(frame,"y",["x1","x2"],"review",dispersion=form)
    except ValueError as error:
        assert any(word in str(error).lower() for word in ["converg","infer","boundary","unavailable"])
        return
    natural_score = fitted.model.score(np.asarray(fitted.params))
    # This checks regular inference at a strictly positive point, not a proposed
    # boundary estimate. No alpha=0 fit is asserted or manufactured.
    ancillary = result["ancillary_parameters"]
    assert R["boundary"][index]["score_at_zero"] < -20
    assert all(p["natural_score_fd"] < -20 for p in R["boundary"][index]["grid"])
    if not ancillary or ancillary[1]["std_error"] is None:
        availability = str({key:result.get(key) for key in ["warnings","ancillary_inference_status","inference_status"]}).lower()
        assert any(word in availability for word in ["uncertif","unavailable","not verified"])
        return
    natural = ancillary[1]
    assert natural["estimate"] > 0
    if natural["std_error"] is not None:
        # Production's reported mean-score tolerance cannot certify regular
        # natural-parameter inference when its unscaled score is O(20).
        n = result["nobs"]
        assert abs(natural_score[-1])/n <= result["convergence"]["tolerance"]
