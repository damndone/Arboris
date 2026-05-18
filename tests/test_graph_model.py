"""Unit tests for backend/workbench/graph_model.py — audit trail substructures."""
from __future__ import annotations

import json
import warnings

import pytest

from workbench.graph_model import (
    AutoChosenReason,
    BranchRef,
    Contestability,
    DecisionPoint,
    Edge,
    Graph,
    Node,
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
