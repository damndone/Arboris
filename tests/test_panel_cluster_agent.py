"""v1.8.11 step 2: the Agent path clusters panel and DID fits by entity by default."""

from __future__ import annotations

import pytest

from workbench.agent.context_tools import _bounded_inference
from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
from workbench.services.draft_materialization import normalize_ols_genesis_model_params


@pytest.mark.parametrize("family", ["panel_ols", "did"])
def test_panel_families_default_to_clustered_and_forward_a_cluster_column(family) -> None:
    contract = MODEL_FAMILY_CONTRACTS[family]
    assert contract.default_covariance == "clustered"
    spec = {"model_family": family, "entity_col": "county", "time_col": "year", "did_mode": "cohort",
            "did_cohort_col": "first_treat", "model_options": {"cluster": "state"}}
    params = contract.build_model_params(spec, {"outcome": "y"}, ["x"], "clustered")
    assert params["model_options"] == {"covariance": "clustered", "cluster": "state"}
    normalized = normalize_ols_genesis_model_params(params)
    assert normalized["model_options"]["cluster"] == "state"


def test_other_families_keep_the_conventional_default() -> None:
    assert MODEL_FAMILY_CONTRACTS["ols"].default_covariance == "unadjusted"


def test_the_agent_is_told_an_old_panel_result_is_not_clustered() -> None:
    legacy = {"entity_col": "firm", "covariance_evidence": {"covariance": "robust", "cluster_entity": False}}
    inference = _bounded_inference(legacy)
    assert inference["not_clustered_by_entity"] is True
    assert "predates v1.8.11" in inference["inference_note"]
    current = {"entity_col": "firm", "covariance_evidence": {
        "covariance": "clustered", "cluster_entity": True, "cluster_variable": "firm", "cluster_count": 50,
        "inference_version": "workbench.inference.v2", "inference_distribution": "t", "effective_df": 49}}
    inference = _bounded_inference(current)
    assert "not_clustered_by_entity" not in inference
    assert inference["cluster_variable"] == "firm"
