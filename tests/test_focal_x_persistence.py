# tests/test_focal_x_persistence.py
from workbench.api import (
    _inject_focal_x_control,
    _parse_focal_x,
    _STRUCTURAL_FOCAL_FAMILIES,
)


def test_parse_focal_x_canonicalizes_against_x():
    assert _parse_focal_x("income, education", ["age", "education", "income"]) == [
        "education", "income",
    ]


def test_parse_focal_x_empty():
    assert _parse_focal_x("", ["a"]) == []


def test_parse_focal_x_drops_tokens_not_in_x():
    # a focal token that is not a regressor is dropped (case-sensitive)
    assert _parse_focal_x("Education", ["education"]) == []


def test_structural_focal_families_listed():
    # focal_x is cleared for these families (focal/treatment is structural)
    assert _STRUCTURAL_FOCAL_FAMILIES == {"iv_2sls", "did", "cs_did", "sa_did", "dcdh"}
    # panel and poisson are user-focal, so NOT in the structural set
    assert "panel_ols" not in _STRUCTURAL_FOCAL_FAMILIES
    assert "poisson_rate" not in _STRUCTURAL_FOCAL_FAMILIES


def test_inject_focal_x_control_adds_multiselect_for_user_focal_family():
    schema = [{"key": "model_type", "kind": "select", "label": "Model", "value": "ols"}]
    form = {"x": "age, education, income", "focal_x": "education"}
    out = _inject_focal_x_control(schema, form, "ols")
    control = next(c for c in out if c["key"] == "focal_x")
    assert control["kind"] == "multiselect"
    assert control["options"] == ["age", "education", "income"]
    assert control["value"] == ["education"]
    # original schema is not mutated in place
    assert all(c["key"] != "focal_x" for c in schema)


def test_inject_focal_x_control_omitted_for_structural_family():
    schema = [{"key": "model_type", "kind": "select", "label": "Model", "value": "did"}]
    form = {"x": "age, treat, post", "focal_x": "treat"}
    out = _inject_focal_x_control(schema, form, "did")
    assert all(c["key"] != "focal_x" for c in out)


def test_inject_focal_x_control_noop_without_x_columns():
    schema = [{"key": "model_type", "kind": "select", "label": "Model", "value": "ols"}]
    out = _inject_focal_x_control(schema, {"x": ""}, "ols")
    assert all(c["key"] != "focal_x" for c in out)


def test_inject_focal_x_control_idempotent():
    schema = [
        {"key": "focal_x", "kind": "multiselect", "label": "Focal X",
         "options": ["a"], "value": []},
    ]
    out = _inject_focal_x_control(schema, {"x": "a, b"}, "ols")
    assert sum(1 for c in out if c["key"] == "focal_x") == 1
