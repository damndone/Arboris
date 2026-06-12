"""Factory functions that produce recommended_actions arrays for known
failure modes. These are injected into failure_evidence so the frontend
FailureCard can render one-click recovery buttons.

Contract: docs/api-contracts/recommended-actions.md
Schema:   tests/contracts/test_schema_recommended_actions.py::ACTION_SCHEMA
"""
from __future__ import annotations


_RERUN_AUTO: dict = {
    "key": "rerun_auto",
    "label": "Re-run with auto",
    "severity": "primary",
    "form_overrides": {"model_type": "auto"},
}

_CHANGE_MODEL: dict = {
    "key": "change_model",
    "label": "Change model type",
    "severity": "secondary",
}

_CHECK_Y: dict = {
    "key": "check_y_column",
    "label": "Check y column",
    "severity": "secondary",
}

_CHECK_DATA: dict = {
    "key": "check_data",
    "label": "Inspect data profile",
    "severity": "primary",
    # No form_overrides — user needs to investigate, not re-run blindly.
}


# Action keys this module emits directly. A pack-declared RerunAction.key must
# not collide with any of these (guarded in pack.register_pack — the frontend
# treats "key" as unique, so a clash renders duplicate/colliding buttons).
# "verify_panel_columns" is emitted inline by actions_for_panel_fields_missing.
BUILTIN_ACTION_KEYS: frozenset[str] = frozenset({
    _RERUN_AUTO["key"],
    _CHANGE_MODEL["key"],
    _CHECK_Y["key"],
    _CHECK_DATA["key"],
    "verify_panel_columns",
})


def _rerun_action_to_dict(ra) -> dict:
    return {
        "key": ra.key,
        "label": ra.label,
        "severity": "secondary",
        "form_overrides": dict(ra.param_overrides),
    }


def actions_for_model_fit_failure(
    *, requested_model_type: str, y_type: str | None,
) -> list[dict]:
    """Build the actions array for a MODEL_FIT_FAILED issue.

    - Explicit failures (requested_model_type != "auto"): primary action
      = re-run with auto (one-click recovery). Secondary = pick a
      different model, check y column.
    - Auto failures (requested_model_type == "auto"): re-run with auto
      would just repeat the failure. Primary = inspect data profile.
    """
    if requested_model_type != "auto":
        actions: list[dict] = [dict(_RERUN_AUTO), dict(_CHANGE_MODEL)]
        check_y = dict(_CHECK_Y)
        if y_type == "continuous" and requested_model_type in {"logit", "probit"}:
            check_y["hint"] = (
                f"Your y appears continuous; {requested_model_type} needs a binary 0/1 column."
            )
        elif y_type == "binary" and requested_model_type in {"ols", "panel_ols"}:
            check_y["hint"] = (
                f"Your y is binary; {requested_model_type} is built for continuous y."
            )
        actions.append(check_y)
        from .pack import RERUN_ACTION_REGISTRY
        actions.extend(
            _rerun_action_to_dict(ra) for ra in RERUN_ACTION_REGISTRY
            if ra.applies_to is None or requested_model_type in ra.applies_to
        )
        return actions
    return [dict(_CHECK_DATA), dict(_CHANGE_MODEL)]


def actions_for_panel_fields_missing() -> list[dict]:
    """PANEL_FIELDS_MISSING — user requested panel_ols but data has no
    entity/time. One-click recovery: re-run with auto."""
    return [
        dict(_RERUN_AUTO),
        {
            "key": "verify_panel_columns",
            "label": "Verify entity/time columns",
            "severity": "secondary",
            "hint": "Panel models need at least one of: entity id column, time column.",
        },
    ]
