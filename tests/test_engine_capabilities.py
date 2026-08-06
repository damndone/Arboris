"""Capability manifest derivation for V1.5.4.1."""
from __future__ import annotations

import jsonschema

# Importing these modules registers built-in model and imputation handlers.
import workbench.engine.stages.estimation  # noqa: F401
import workbench.engine.stages.imputation  # noqa: F401
from tests.contracts.test_schema_capabilities import SCHEMA
from workbench.engine.capabilities import build_capabilities


def test_build_capabilities_matches_contract_schema():
    payload = build_capabilities()

    jsonschema.validate(payload, SCHEMA)


def test_build_capabilities_includes_all_v1_5_3_2_models():
    payload = build_capabilities()

    keys = {entry["key"] for entry in payload["model_types"]}
    expected = {
        "auto",
        "ols",
        "logit",
        "probit",
        "poisson",
        "negative_binomial",
        "panel_ols",
        "glm:binomial",
        "glm:poisson",
        "glm:negative_binomial",
    }
    assert expected.issubset(keys), f"missing model_types: {expected - keys}"


def test_build_capabilities_includes_mice_imputation():
    payload = build_capabilities()

    keys = {entry["key"] for entry in payload["imputation_methods"]}
    assert "mice" in keys


def test_panel_ols_declares_entity_or_time_requirement():
    payload = build_capabilities()

    panel = next(entry for entry in payload["model_types"] if entry["key"] == "panel_ols")
    assert "entity_or_time" in panel.get("requires", [])


def test_iv_2sls_declares_endog_instruments_requirement():
    payload = build_capabilities()
    iv = next(entry for entry in payload["model_types"] if entry["key"] == "iv_2sls")
    assert iv.get("requires") == ["endog", "instruments"]
    assert iv["group"] == "IV"


def test_groups_match_known_vocabulary():
    payload = build_capabilities()

    groups = {entry["group"] for entry in payload["model_types"]}
    assert groups.issubset(
        {
            "auto", "Linear", "Binary", "Count", "Panel", "GLM", "IV", "DID",
            "Time Series", "Ordinal", "Nominal", "Survival", "Quantile",
            "ANOVA",
        }
    )
