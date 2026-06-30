# tests/test_focal_x_persistence.py
from workbench.api import _parse_focal_x, _STRUCTURAL_FOCAL_FAMILIES


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
