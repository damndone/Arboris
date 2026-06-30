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
