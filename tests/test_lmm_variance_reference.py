"""Validate the independent variance reference without bypassing admission."""
import hashlib
import json
import math
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures/admission/linear_mixed_effects"


def test_variance_reference_is_bound_to_the_existing_lmm_sample():
    reference = json.loads((FIXTURE / "variance_oracle.json").read_text())
    old = json.loads((FIXTURE / "oracle.json").read_text())
    assert reference["meta"]["data_sha256"] == hashlib.sha256((FIXTURE / "data.csv").read_bytes()).hexdigest()
    assert reference["meta"]["nobs"] == old["meta"]["n"]
    assert reference["meta"]["reml"] is True
    assert reference["meta"]["formula"] == "y ~ arm * time + x + (1 | g)"
    assert reference["meta"]["verification_level"] == "R-only; host Workbench verification pending"
    for name, value in reference["random_effects"].items():
        assert name in {"intercept_variance", "residual_variance"}
        assert math.isfinite(value) and value > 0
    for name, value in reference["coefficients"].items():
        assert abs(value - old["coefficients"][name]) < 1e-12
    for name, value in reference["std_error"].items():
        assert abs(value - old["std_error"][name]) < 1e-12
