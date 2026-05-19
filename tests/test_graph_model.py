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
    resolve_decision_id,
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
    """Derive() infers 'needed' when checks are listed and no status given."""
    c = Contestability.derive(assumption_checks_needed=("breusch_pagan",))
    assert c.review_status == "needed"


def test_contestability_derive_with_explicit_status_passes_through():
    c = Contestability.derive(
        assumption_checks_needed=("breusch_pagan",),
        review_status="passed",
    )
    assert c.review_status == "passed"


def test_contestability_direct_construction_without_status_does_not_derive():
    """Direct construction uses the literal default ('not_needed'); derivation
    only happens via Contestability.derive(). This avoids object.__setattr__
    on a frozen dataclass."""
    import warnings as _w
    with _w.catch_warnings():
        _w.simplefilter("ignore")  # the consistency check will warn; not our concern here
        c = Contestability(assumption_checks_needed=("breusch_pagan",))
    assert c.review_status == "not_needed"


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
        contestability=Contestability.derive(
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


def test_node_minimal():
    n = Node(
        id="stage:raw",
        kind=NodeKind.DATASET_STAGE,
        display_label="Raw data",
        created_at="2026-05-13T10:23:00+00:00",
        parent_stage_id=None,
        branch_id="main",
    )
    assert n.trust == Trust.OK
    assert n.trust_reason is None
    assert n.archived is False
    assert n.payload_ref is None
    assert n.decision_point is None
    assert n.annotations == ()


def test_node_with_decision_point():
    dp = DecisionPoint(
        decision_id="model_type_auto_select",
        selected="logit",
        candidates=("ols", "logit", "poisson"),
        source="data_driven_default",
    )
    n = Node(
        id="model:primary",
        kind=NodeKind.MODEL,
        display_label="logit primary",
        created_at="2026-05-13T10:25:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        decision_point=dp,
    )
    assert n.decision_point is dp
    assert n.decision_point.selected == "logit"


def test_node_is_frozen():
    n = Node(
        id="x",
        kind=NodeKind.VARIABLE,
        display_label="x",
        created_at="2026-05-13T10:25:00+00:00",
        parent_stage_id=None,
        branch_id="main",
    )
    with pytest.raises((AttributeError, Exception)):
        n.archived = True  # type: ignore[misc]


def test_edge_minimal():
    e = Edge(
        id="e1",
        source_id="stage:raw",
        target_id="stage:cleaned",
        op="drop_na",
        params={},
    )
    assert e.reversible is False
    assert e.inverse_op is None


def test_edge_with_inverse():
    e = Edge(
        id="e2",
        source_id="var:income:cleaned",
        target_id="var:log_income:transformed",
        op="np.log(x + 1)",
        params={"offset": 1},
        reversible=True,
        inverse_op="np.exp(x) - 1",
    )
    assert e.reversible is True
    assert e.inverse_op == "np.exp(x) - 1"


def test_branch_ref_minimal():
    b = BranchRef(id="main", forked_from_node_id=None, head_node_ids=("model:primary",))
    assert b.archived is False


def test_graph_minimal():
    g = Graph(
        schema_version=1,
        run_id="run_42",
        nodes={},
        edges={},
        branches={"main": BranchRef(id="main", forked_from_node_id=None, head_node_ids=())},
    )
    assert g.legacy is False
    assert "main" in g.branches


def test_graph_legacy_empty():
    """Pre-V1.4 runs surface as legacy=True empty graphs."""
    g = Graph(
        schema_version=1,
        run_id="run_old",
        nodes={},
        edges={},
        branches={},
        legacy=True,
    )
    assert g.legacy is True
    assert g.nodes == {}


# -- Enum value constructors ---------------------------------------------------


def test_node_kind_construct_from_value():
    assert NodeKind("dataset_stage") == NodeKind.DATASET_STAGE
    assert NodeKind("model") == NodeKind.MODEL
    with pytest.raises(ValueError):
        NodeKind("nonexistent")


def test_trust_construct_from_value():
    assert Trust("ok") == Trust.OK
    assert Trust("blocker") == Trust.BLOCKER
    with pytest.raises(ValueError):
        Trust("nonexistent")


# -- Node with optional fields -------------------------------------------------


def test_node_with_all_optional_fields():
    n = Node(
        id="var:x:cleaned",
        kind=NodeKind.VARIABLE,
        display_label="x (cleaned)",
        created_at="2026-05-18T12:00:00+00:00",
        parent_stage_id="stage:cleaned",
        branch_id="main",
        trust=Trust.WARNING,
        trust_reason="auto-coerced from string",
        archived=False,
        payload_ref="processed/x_stats.json",
        annotations=("outlier_flag",),
    )
    assert n.trust == Trust.WARNING
    assert n.trust_reason == "auto-coerced from string"
    assert n.payload_ref == "processed/x_stats.json"
    assert n.annotations == ("outlier_flag",)
    assert n.decision_point is None


def test_node_archived_flag():
    n = Node(
        id="model:old",
        kind=NodeKind.MODEL,
        display_label="old model",
        created_at="2026-05-18T12:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        archived=True,
    )
    assert n.archived is True


# -- Edge with params ----------------------------------------------------------


def test_edge_with_params():
    e = Edge(
        id="e_transform",
        source_id="var:x:raw",
        target_id="var:x:cleaned",
        op="np.log",
        params={"base": "e", "offset": 1.0},
        reversible=True,
        inverse_op="np.exp",
    )
    assert e.params == {"base": "e", "offset": 1.0}
    assert e.reversible is True
    assert e.inverse_op == "np.exp"


# -- BranchRef edge cases ------------------------------------------------------


def test_branch_ref_archived():
    b = BranchRef(id="experiment", forked_from_node_id="model:primary",
                  head_node_ids=("model:alt",), archived=True)
    assert b.archived is True
    assert b.forked_from_node_id == "model:primary"
    assert b.head_node_ids == ("model:alt",)


# -- Graph with populated content ----------------------------------------------


def test_graph_with_nodes_and_edges():
    n1 = Node(id="stage:raw", kind=NodeKind.DATASET_STAGE, display_label="Raw",
              created_at="t1", parent_stage_id=None, branch_id="main")
    n2 = Node(id="stage:cleaned", kind=NodeKind.DATASET_STAGE, display_label="Cleaned",
              created_at="t2", parent_stage_id=None, branch_id="main")
    e = Edge(id="e1", source_id="stage:raw", target_id="stage:cleaned", op="clean_frame")
    g = Graph(
        schema_version=1, run_id="run_full",
        nodes={"stage:raw": n1, "stage:cleaned": n2},
        edges={"e1": e},
        branches={"main": BranchRef(id="main", forked_from_node_id=None,
                                     head_node_ids=("stage:cleaned",))},
    )
    assert len(g.nodes) == 2
    assert len(g.edges) == 1
    assert g.branches["main"].head_node_ids == ("stage:cleaned",)


def test_graph_multi_branch():
    g = Graph(
        schema_version=1, run_id="run_forked",
        nodes={}, edges={},
        branches={
            "main": BranchRef(id="main", forked_from_node_id=None,
                              head_node_ids=("model:primary",)),
            "experiment": BranchRef(id="experiment",
                                    forked_from_node_id="model:primary",
                                    head_node_ids=("model:alt",)),
        },
    )
    assert len(g.branches) == 2
    assert g.branches["experiment"].forked_from_node_id == "model:primary"


# -- Literal types are importable ----------------------------------------------


def test_decision_source_and_reason_type_importable():
    from workbench.graph_model import DecisionSource, ReasonType, ReviewStatus
    # Verify these are usable as type annotations (import-time check)
    assert DecisionSource is not None
    assert ReasonType is not None
    assert ReviewStatus is not None


def _graph_with_dp(decision_id: str, aliases: tuple[str, ...] = ()) -> Graph:
    dp = DecisionPoint(decision_id=decision_id, decision_id_alias=aliases)
    node = Node(
        id="n1", kind=NodeKind.MODEL, display_label="m",
        created_at="2026-05-18T00:00:00Z", parent_stage_id=None,
        branch_id="main", decision_point=dp,
    )
    return Graph(schema_version=1, run_id="r", nodes={"n1": node}, edges={}, branches={})


def test_resolve_decision_id_via_canonical():
    g = _graph_with_dp("model_type_auto_select")
    assert resolve_decision_id(g, "model_type_auto_select") == "model_type_auto_select"


def test_resolve_decision_id_via_alias():
    g = _graph_with_dp("model_type_auto_select", aliases=("old_model_pick", "legacy_name"))
    assert resolve_decision_id(g, "old_model_pick") == "model_type_auto_select"
    assert resolve_decision_id(g, "legacy_name") == "model_type_auto_select"


def test_resolve_decision_id_unknown_returns_none():
    g = _graph_with_dp("model_type_auto_select", aliases=("old_model_pick",))
    assert resolve_decision_id(g, "nonexistent") is None


def test_resolve_decision_id_skips_nodes_without_dp():
    node_no_dp = Node(
        id="n2", kind=NodeKind.DATASET_STAGE, display_label="s",
        created_at="2026-05-18T00:00:00Z", parent_stage_id=None,
        branch_id="main", decision_point=None,
    )
    dp = DecisionPoint(decision_id="x", decision_id_alias=("y",))
    node_with_dp = Node(
        id="n1", kind=NodeKind.MODEL, display_label="m",
        created_at="2026-05-18T00:00:00Z", parent_stage_id=None,
        branch_id="main", decision_point=dp,
    )
    g = Graph(
        schema_version=1, run_id="r",
        nodes={"n2": node_no_dp, "n1": node_with_dp},
        edges={}, branches={},
    )
    assert resolve_decision_id(g, "y") == "x"
    assert resolve_decision_id(g, "missing") is None
