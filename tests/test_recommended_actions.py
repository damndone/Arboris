"""Factory functions produce schema-compliant action arrays."""
import json
from pathlib import Path

import jsonschema

from workbench.engine.recommended_actions import (
    actions_for_model_fit_failure,
    actions_for_panel_fields_missing,
)
from tests.contracts.test_schema_recommended_actions import ACTION_SCHEMA


def _validate_all(actions: list[dict]) -> None:
    for action in actions:
        jsonschema.validate(action, ACTION_SCHEMA)


def test_explicit_logit_on_continuous_y_offers_rerun_auto():
    actions = actions_for_model_fit_failure(
        requested_model_type="logit", y_type="continuous",
    )
    _validate_all(actions)
    keys = [a["key"] for a in actions]
    assert "rerun_auto" in keys
    primary = next(a for a in actions if a["severity"] == "primary")
    assert primary["form_overrides"] == {
        "model_type": "auto",
        "model_options": {},
    }


def test_auto_failure_does_not_offer_rerun_auto():
    """When the run was already auto and both primary + OLS fallback failed,
    re-running with auto is pointless. The primary action should be
    'check_data' or similar — never `rerun_auto`."""
    actions = actions_for_model_fit_failure(
        requested_model_type="auto", y_type="binary",
    )
    _validate_all(actions)
    keys = [a["key"] for a in actions]
    assert "rerun_auto" not in keys


def test_panel_fields_missing_offers_rerun_auto():
    actions = actions_for_panel_fields_missing()
    _validate_all(actions)
    primary = next(a for a in actions if a["severity"] == "primary")
    assert primary["form_overrides"].get("model_type") == "auto"


def test_iv_switch_to_ols_does_not_leak_to_non_iv_failures():
    # iv_switch_to_ols is registered on CORE_PACK with applies_to=["iv_2sls"];
    # a non-IV explicit failure must NOT receive it. Import the estimation
    # stage so CORE_PACK is registered even when this file runs in isolation.
    import workbench.engine.stages.estimation  # noqa: F401
    actions = actions_for_model_fit_failure(
        requested_model_type="logit", y_type="binary",
    )
    _validate_all(actions)
    assert "iv_switch_to_ols" not in {a["key"] for a in actions}
    # and confirm the positive case: an IV failure DOES get it
    iv_actions = actions_for_model_fit_failure(
        requested_model_type="iv_2sls", y_type="continuous",
    )
    _validate_all(iv_actions)
    assert "iv_switch_to_ols" in {a["key"] for a in iv_actions}


def test_at_most_one_primary_action_per_recovery():
    """The story has one starring button. Other actions are secondary."""
    for actions in [
        actions_for_model_fit_failure(requested_model_type="logit", y_type="continuous"),
        actions_for_model_fit_failure(requested_model_type="auto", y_type="binary"),
        actions_for_panel_fields_missing(),
    ]:
        primaries = [a for a in actions if a["severity"] == "primary"]
        assert len(primaries) <= 1
