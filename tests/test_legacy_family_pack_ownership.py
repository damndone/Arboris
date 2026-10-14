"""Legacy public imports retain identity while family implementations own fits."""

import pytest

from workbench.econometrics import runner
from workbench.engine.stages import estimation


@pytest.mark.parametrize("family,pack", [
    ("logit", "binary_models"), ("probit", "binary_models"),
    ("poisson", "count_regression"), ("negative_binomial", "count_regression"),
    ("glm", "count_regression"),
])
def test_legacy_fit_and_stage_adapter_are_owned_by_model_pack(family, pack):
    prefix = f"workbench.engine.packs.{pack}"
    run = getattr(runner, f"run_{family}")
    fit = getattr(estimation, f"_fit_{family}")
    assert run.__module__ == f"{prefix}.runner"
    assert fit.__module__ == f"{prefix}.adapters"
