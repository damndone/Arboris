"""The Notebook's published-artifact vocabulary comes from the family contracts (v1.8.12).

Until v1.8.12 `agent/notebook/vocabulary.py` kept its own table of what each
family publishes (`"ols": {"ols_1": "model_result"}` and twenty more), beside
the contract that already declares each family's artifacts. Each family now
declares what a Notebook option of it publishes; the vocabulary derives it.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.contracts.model.family import MODEL_FAMILY_CONTRACTS
from workbench.agent.notebook.vocabulary import CAPABILITY_ARTIFACT_TYPES, capability_artifact_types

# The table as it stood before v1.8.12: deriving it must not change what any
# family publishes.
BEFORE = {
    "ols": {"ols_1": "model_result"},
    "logit": {"logit_1": "model_result"},
    "probit": {"probit_1": "model_result"},
    "poisson": {"poisson_1": "model_result"},
    "negative_binomial": {"negative_binomial_1": "model_result"},
    "panel_ols": {"panel_ols_1": "model_result"},
    "iv_2sls": {"iv_2sls_1": "model_result"},
    "did": {"did_1": "model_result"},
    "cs_did": {"cs_did_1": "model_result"},
    "sa_did": {"sa_did_1": "model_result"},
    "dcdh": {"dcdh_1": "model_result"},
    "glm:binomial": {"glm_1": "model_result"},
    "glm:poisson": {"glm_1": "model_result"},
    "glm:negative_binomial": {"glm_1": "model_result"},
    "ordinal_logit": {"ordinal_logit_1": "model_result", "diagnostics_ordinal_logit_1": "diagnostic_result"},
    "multinomial_logit": {
        "multinomial_logit_1": "model_result", "diagnostics_multinomial_logit_1": "diagnostic_result",
    },
    "survival_cox": {"survival_cox_1": "model_result", "survival_evidence": "survival_evidence"},
    "anova": {"anova_1": "model_result"},
    "quantile_regression": {"quantile_regression_1": "model_result"},
    "linear_mixed_effects": {"linear_mixed_effects_1.result": "model_result_packet"},
}


def test_every_family_publishes_what_its_contract_declares() -> None:
    assert set(BEFORE) == set(MODEL_FAMILY_CONTRACTS)
    for family, contract in MODEL_FAMILY_CONTRACTS.items():
        assert dict(capability_artifact_types(family)) == dict(contract.published_artifact_types), family


def test_deriving_the_vocabulary_changed_nothing_a_family_publishes() -> None:
    assert {family: dict(CAPABILITY_ARTIFACT_TYPES[family]) for family in BEFORE} == BEFORE


def test_a_family_publishes_only_its_own_artifacts() -> None:
    ols = MODEL_FAMILY_CONTRACTS["ols"]
    with pytest.raises(ValueError, match="published artifact"):
        replace(ols, published_artifacts=(("logit_1", "model_result"),))
    with pytest.raises(ValueError, match="published artifact"):
        replace(ols, published_artifacts=(("ols_1", ""),))
    # A part of a declared artifact (`<artifact>.<part>`) is the family's own.
    assert replace(ols, published_artifacts=(("ols_1.result", "model_result_packet"),)).published_artifact_types == {
        "ols_1.result": "model_result_packet"
    }
