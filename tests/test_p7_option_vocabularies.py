"""Frozen-pack options with a closed vocabulary are served with that vocabulary.

Each enum in the operation catalog must be the very set the pack's kernel
validates the option against (one object, imported by both), every string
option must be either closed or declared open, and a value outside the set is
refused before any kernel runs.
"""

from __future__ import annotations

import pytest

from workbench.agent.p7_option_vocabularies import OPEN_STRING_OPTIONS, OPTION_VOCABULARIES
from workbench.agent.p7_pack_registry import P7_REQUEST_SCHEMAS, P7PackRegistryError


def test_every_string_option_is_closed_or_declared_open():
    unaccounted = {
        (operation_id, name)
        for operation_id, schema in P7_REQUEST_SCHEMAS.items()
        for name, shape in schema.option_shapes.items()
        if shape in {"string", "nullable_string"}
        and name not in schema.option_enums
        and name not in OPEN_STRING_OPTIONS.get(operation_id, frozenset())
    }
    assert unaccounted == set(), "declare a vocabulary or mark the option open in p7_option_vocabularies"


def test_vocabularies_reach_the_schemas_and_name_declared_options():
    for operation_id, options in OPTION_VOCABULARIES.items():
        schema = P7_REQUEST_SCHEMAS[operation_id]
        for name, values in options.items():
            assert tuple(schema.option_enums[name]) == values
            served = schema.field_schemas()["options"]["properties"][name]
            assert served["enum"] == list(values) and "nullable" not in served


def test_each_vocabulary_is_the_object_its_kernel_validates_against():
    # The kernels import these names from the contracts; the identity check
    # proves there is one copy, so the served set cannot drift from the kernel.
    from workbench.contracts.model import multivariate, nonparametric, resampling, time_series_pack, iv_gmm
    from workbench.engine.packs.iv_gmm import gmm
    from workbench.engine.packs.multivariate import clustering, correspondence, discriminant, efa, pca
    from workbench.engine.packs.nonparametric import rank_tests
    from workbench.engine.packs.resampling import bootstrap, common as resampling_common, permutation
    from workbench.engine.packs.time_series import cointegration, diagnostics, input as ts_input, models, var

    pairs = {
        "CLUSTERING_ALGORITHMS": (clustering, multivariate),
        "CLUSTERING_LINKAGES": (clustering, multivariate),
        "PCA_COMPONENT_SELECTIONS": (pca, multivariate),
        "EFA_ROTATIONS": (efa, multivariate),
        "DISCRIMINANT_METHODS": (discriminant, multivariate),
        "MCA_MISSING_POLICIES": (correspondence, multivariate),
        "GMM_ESTIMATORS": (gmm, iv_gmm),
        "BOOTSTRAP_STATISTICS": (resampling_common, resampling),
        "BOOTSTRAP_INTERVAL_METHODS": (bootstrap, resampling),
        "PERMUTATION_ALTERNATIVES": (permutation, resampling),
        "TIME_ORDER_POLICIES": (ts_input, time_series_pack),
        "ARIMA_TRENDS": (models, time_series_pack),
        "GRANGER_TESTS": (var, time_series_pack),
        "VECM_DETERMINISTICS": (cointegration, time_series_pack),
        "ADF_AUTOLAGS": (diagnostics, time_series_pack),
        "MANN_WHITNEY_METHODS": (rank_tests, nonparametric),
        "WILCOXON_ZERO_METHODS": (rank_tests, nonparametric),
        "KENDALL_VARIANTS": (rank_tests, nonparametric),
    }
    for name, (kernel, contract) in pairs.items():
        assert getattr(kernel, name) is getattr(contract, name), name


@pytest.mark.parametrize("call", [
    lambda: __import__("workbench.engine.packs.nonparametric", fromlist=["x"]).run_mann_whitney([1, 2, 3], [4, 5, 6], method="bogus"),
    lambda: __import__("workbench.engine.packs.nonparametric", fromlist=["x"]).run_kendall([1, 2, 3], [3, 2, 1], variant="a"),
    lambda: __import__("workbench.engine.packs.nonparametric", fromlist=["x"]).run_spearman([1, 2, 3], [3, 2, 1], missing_policy="drop"),
])
def test_kernels_still_refuse_values_outside_the_vocabulary(call):
    with pytest.raises(Exception):
        call()


def test_the_registry_refuses_a_value_outside_the_vocabulary_before_the_kernel():
    schema = P7_REQUEST_SCHEMAS["time_series.adf"]
    request = {"column_bindings": {"time": "t", "value": "y"}, "options": {"time_order": "declared_monotonic", "regression": "q"}}
    with pytest.raises(P7PackRegistryError, match="regression must be one of: c, ct, ctt, n"):
        schema.validate(request)
    schema.validate({**request, "options": {"time_order": "declared_monotonic", "regression": "ct"}})
