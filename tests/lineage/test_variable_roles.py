# tests/lineage/test_variable_roles.py
from workbench.lineage.variable_roles import Role, RoleAssignment, ROLE_EDGE_OP

def test_every_role_has_an_edge_op():
    for role in Role:
        assert role in ROLE_EDGE_OP

def test_edge_ops_match_spec():
    assert ROLE_EDGE_OP[Role.OUTCOME] == "enters_as_outcome"
    assert ROLE_EDGE_OP[Role.FOCAL] == "enters_as_focal"
    assert ROLE_EDGE_OP[Role.TREATMENT] == "enters_as_treatment"
    assert ROLE_EDGE_OP[Role.COVARIATES] == "enters_as_covariates"
    assert ROLE_EDGE_OP[Role.EXPLANATORY_UNSPECIFIED] == "enters_as_explanatory_unspecified"
    assert ROLE_EDGE_OP[Role.EXPOSURE] == "offsets_as_exposure"
    assert ROLE_EDGE_OP[Role.INSTRUMENTS] == "identifies_as_instruments"
    assert ROLE_EDGE_OP[Role.UNIT] == "configures_unit"
    assert ROLE_EDGE_OP[Role.TIME] == "configures_time"
    assert ROLE_EDGE_OP[Role.CLUSTER] == "configures_cluster"

def test_role_assignment_edge_kind_derived_from_op():
    ra = RoleAssignment(column="x1", role=Role.FOCAL, source="focal_x",
                        estimator_family="regression", estimator_key="ols")
    assert ra.edge_op == "enters_as_focal"
    assert ra.edge_kind == "enters_as_"
    cl = RoleAssignment(column="firm", role=Role.CLUSTER, source="_cs_cluster_var",
                        estimator_family="did", estimator_key="cs_did")
    assert cl.edge_kind == "configures_"


from workbench.lineage.variable_roles import canonicalize_focal_x

def test_canonicalize_orders_by_resolved_rhs_and_dedups():
    rhs = ["age", "education", "income", "region"]
    assert canonicalize_focal_x("income, education", rhs) == ["education", "income"]

def test_canonicalize_strips_whitespace_and_dups_preserves_case():
    rhs = ["Income", "Education"]
    assert canonicalize_focal_x(" Income , Income ,Education ", rhs) == ["Income", "Education"]
    # case-sensitive: a differently-cased token that is not in rhs is dropped
    assert canonicalize_focal_x("income", ["Income"]) == []

def test_canonicalize_accepts_list_input():
    assert canonicalize_focal_x(["b", "a"], ["a", "b", "c"]) == ["a", "b"]

def test_canonicalize_empty():
    assert canonicalize_focal_x("", ["a"]) == []
    assert canonicalize_focal_x(None, ["a"]) == []


import pytest
from workbench.lineage.variable_roles import (
    ResolvedRoleInputs, derive_roles, RoleConflictError,
)


def _roles(assignments):
    return {(a.column, a.role) for a in assignments}


# --- A3 regression ---------------------------------------------------------

def test_regression_focal_declared():
    ri = ResolvedRoleInputs(
        estimator_family="regression", estimator_key="ols",
        outcome="y", rhs=["education", "age", "region"], focal_x=["education"],
    )
    assert _roles(derive_roles(ri)) == {
        ("y", Role.OUTCOME),
        ("education", Role.FOCAL),
        ("age", Role.COVARIATES),
        ("region", Role.COVARIATES),
    }


def test_regression_focal_empty_is_unspecified():
    ri = ResolvedRoleInputs(
        estimator_family="regression", estimator_key="logit",
        outcome="y", rhs=["a", "b"], focal_x=[],
    )
    assert _roles(derive_roles(ri)) == {
        ("y", Role.OUTCOME),
        ("a", Role.EXPLANATORY_UNSPECIFIED),
        ("b", Role.EXPLANATORY_UNSPECIFIED),
    }


# --- A4 poisson ------------------------------------------------------------

def test_poisson_rate_exposure_is_offset_not_covariate():
    ri = ResolvedRoleInputs(
        estimator_family="regression", estimator_key="poisson_rate",
        outcome="claims", rhs=["age"], focal_x=[], exposure="exposure_years",
    )
    got = {(a.column, a.role) for a in derive_roles(ri)}
    assert got == {
        ("claims", Role.OUTCOME),
        ("age", Role.EXPLANATORY_UNSPECIFIED),
        ("exposure_years", Role.EXPOSURE),
    }


def test_poisson_focal_must_not_be_exposure():
    ri = ResolvedRoleInputs(
        estimator_family="regression", estimator_key="poisson_rate",
        outcome="claims", rhs=["age"], focal_x=["exposure_years"],
        exposure="exposure_years",
    )
    with pytest.raises(RoleConflictError):
        derive_roles(ri)


# --- A5 panel + iv ---------------------------------------------------------

def test_panel_unit_time_plus_focal():
    ri = ResolvedRoleInputs(
        estimator_family="panel", estimator_key="panel_ols",
        outcome="y", rhs=["x1", "x2"], focal_x=["x1"], unit="firm", time="year",
    )
    assert _roles(derive_roles(ri)) == {
        ("y", Role.OUTCOME), ("x1", Role.FOCAL), ("x2", Role.COVARIATES),
        ("firm", Role.UNIT), ("year", Role.TIME),
    }


def test_iv_endog_is_focal_instruments_separate():
    ri = ResolvedRoleInputs(
        estimator_family="iv", estimator_key="iv_2sls",
        outcome="wage", rhs=["age"], endog=["schooling"],
        instruments=["quarter_of_birth"],
    )
    assert _roles(derive_roles(ri)) == {
        ("wage", Role.OUTCOME),
        ("schooling", Role.FOCAL),
        ("quarter_of_birth", Role.INSTRUMENTS),
        ("age", Role.COVARIATES),
    }


# --- A6 did ----------------------------------------------------------------

def test_classic_did_multi_column_treatment():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="did",
        outcome="emp", rhs=["sector"], unit="county", time="year",
        treatment=["treat", "post"], cluster=None,
    )
    assert _roles(derive_roles(ri)) == {
        ("emp", Role.OUTCOME), ("treat", Role.TREATMENT), ("post", Role.TREATMENT),
        ("sector", Role.COVARIATES), ("county", Role.UNIT), ("year", Role.TIME),
    }


def test_sa_did_has_cluster_no_covariates():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="sa_did",
        outcome="emp", rhs=[], unit="county", time="year",
        treatment=["cohort"], cluster="county",
    )
    got = {(a.column, a.role) for a in derive_roles(ri)}
    assert got == {
        ("emp", Role.OUTCOME), ("cohort", Role.TREATMENT),
        ("county", Role.UNIT), ("year", Role.TIME), ("county", Role.CLUSTER),
    }


def test_did_no_cluster_when_absent():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="dcdh",
        outcome="emp", rhs=[], unit="county", time="year",
        treatment=["switch"], cluster=None,
    )
    assert not any(a.role == Role.CLUSTER for a in derive_roles(ri))


# --- A7 conflict policy + dedup --------------------------------------------

def test_unit_plus_cluster_allowed():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="cs_did",
        outcome="y", rhs=["z"], unit="firm", time="year",
        treatment=["cohort"], cluster="firm",   # cluster == unit -> allowed
    )
    pairs = {(a.column, a.role) for a in derive_roles(ri)}
    assert ("firm", Role.UNIT) in pairs and ("firm", Role.CLUSTER) in pairs


def test_unit_plus_covariate_rejected():
    # firm appears both as entity AND as a covariate -> hard conflict
    ri = ResolvedRoleInputs(
        estimator_family="panel", estimator_key="panel_ols",
        outcome="y", rhs=["firm", "x"], focal_x=[], unit="firm", time="year",
    )
    with pytest.raises(RoleConflictError):
        derive_roles(ri)


def test_dedup_same_column_role_two_sources_one_edge():
    ri = ResolvedRoleInputs(
        estimator_family="did", estimator_key="did",
        outcome="y", rhs=[], unit="c", time="t",
        treatment=["treat", "treat"],   # duplicate source resolution
    )
    treat = [a for a in derive_roles(ri) if a.column == "treat"]
    assert len(treat) == 1
    assert "treatment" in treat[0].source  # provenance retained
