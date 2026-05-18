"""Unit tests for backend/workbench/graph_model.py — audit trail substructures."""
from __future__ import annotations

import json
import warnings

import pytest

from workbench.graph_model import (
    AutoChosenReason,
    Contestability,
    DecisionPoint,
    NodeKind,
    Trust,
)


def test_node_kind_values():
    assert NodeKind.DATASET_STAGE.value == "dataset_stage"
    assert NodeKind.VARIABLE.value == "variable"
    assert NodeKind.OPERATION.value == "operation"
    assert NodeKind.MODEL.value == "model"
    assert NodeKind.TEST.value == "test"
    assert NodeKind.PLOT.value == "plot"
    assert NodeKind.REPORT.value == "report"


def test_trust_values():
    assert Trust.OK.value == "ok"
    assert Trust.CAUTION.value == "caution"
    assert Trust.WARNING.value == "warning"
    assert Trust.BLOCKER.value == "blocker"


def test_contestability_review_status_default_when_checks_empty():
    c = Contestability()
    assert c.assumption_checks_needed == ()
    assert c.review_status == "not_needed"


def test_contestability_review_status_default_when_checks_present():
    c = Contestability(assumption_checks_needed=("breusch_pagan",))
    assert c.review_status == "needed"


def test_contestability_review_status_explicit_passed_with_checks():
    """Override is allowed: 'passed' with non-empty checks is valid (a check ran)."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # turn warnings into exceptions; should NOT warn
        c = Contestability(
            assumption_checks_needed=("breusch_pagan",),
            review_status="passed",
        )
    assert c.review_status == "passed"


def test_contestability_review_status_explicit_waived_with_checks():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        c = Contestability(
            assumption_checks_needed=("missingness_mechanism_audit",),
            review_status="waived",
        )
    assert c.review_status == "waived"


def test_contestability_review_status_inconsistent_warns_needed_no_checks():
    with pytest.warns(UserWarning, match="empty.*Did you mean 'not_needed'"):
        Contestability(review_status="needed")


def test_contestability_review_status_inconsistent_warns_not_needed_with_checks():
    with pytest.warns(UserWarning, match="not_needed.*Did you mean 'needed'"):
        Contestability(
            assumption_checks_needed=("foo",),
            review_status="not_needed",
        )


def test_contestability_is_frozen():
    c = Contestability()
    with pytest.raises((AttributeError, Exception)):
        c.is_contestable = False  # type: ignore[misc]


def test_contestability_default_is_contestable_true():
    c = Contestability()
    assert c.is_contestable is True
    assert c.warnings == ()


def test_auto_chosen_reason_minimal():
    r = AutoChosenReason(reason_type="system_default")
    assert r.reason_type == "system_default"
    assert r.explanation is None
    assert r.chosen_params_schema is None
    assert r.chosen_params == {}


def test_auto_chosen_reason_with_params():
    r = AutoChosenReason(
        reason_type="data_driven_default",
        explanation="y is binary",
        chosen_params={"y_unique": 2, "y_dtype": "int64"},
    )
    assert r.chosen_params == {"y_unique": 2, "y_dtype": "int64"}


def test_auto_chosen_reason_with_schema_version():
    r = AutoChosenReason(
        reason_type="system_default",
        chosen_params_schema="MissingValueStrategy.v1",
        chosen_params={"method": "drop_rows_with_missing_required_fields"},
    )
    assert r.chosen_params_schema == "MissingValueStrategy.v1"


def test_auto_chosen_reason_is_frozen():
    r = AutoChosenReason(reason_type="system_default")
    with pytest.raises((AttributeError, Exception)):
        r.reason_type = "fallback"  # type: ignore[misc]


def test_auto_chosen_reason_chosen_params_must_be_json_safe():
    """Indirect: AutoChosenReason allows dict[str, Any] at type level, but downstream
    GraphStore enforces JSON-safety at serialization time. Document that intent here
    by constructing one with a known-bad value and verifying the dataclass itself
    does NOT reject (rejection is GraphStore's job)."""
    class _NotJsonSafe:
        pass

    # This must NOT raise here — JSON enforcement is at serialization, not construction.
    AutoChosenReason(
        reason_type="system_default",
        chosen_params={"obj": _NotJsonSafe()},
    )


def test_decision_point_minimal():
    dp = DecisionPoint(decision_id="model_type_auto_select")
    assert dp.decision_id == "model_type_auto_select"
    assert dp.decision_id_alias == ()
    assert dp.selected is None
    assert dp.candidates == ()
    assert dp.source == "system_default"
    assert isinstance(dp.contestability, Contestability)
    assert dp.reason is None


def test_decision_point_full():
    dp = DecisionPoint(
        decision_id="model_type_auto_select",
        selected="logit",
        candidates=("ols", "logit", "poisson"),
        source="data_driven_default",
        contestability=Contestability(
            assumption_checks_needed=("variable_role_inference",),
        ),
        reason=AutoChosenReason(
            reason_type="data_driven_default",
            explanation="y is binary",
            chosen_params={"y_unique": 2},
        ),
    )
    assert dp.selected == "logit"
    assert dp.candidates == ("ols", "logit", "poisson")
    assert dp.contestability.review_status == "needed"
    assert dp.reason is not None
    assert dp.reason.chosen_params == {"y_unique": 2}


def test_decision_point_aliases_preserved_across_renames():
    """Schema evolution rule: renaming a decision_id keeps old IDs in alias."""
    dp = DecisionPoint(
        decision_id="model_type_auto_select_v2",
        decision_id_alias=("model_type_auto_select",),
        selected="logit",
    )
    assert "model_type_auto_select" in dp.decision_id_alias


def test_decision_point_is_frozen():
    dp = DecisionPoint(decision_id="test")
    with pytest.raises((AttributeError, Exception)):
        dp.decision_id = "other"  # type: ignore[misc]
