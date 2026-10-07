"""v1.8.10 step 3e: the admission kit.

Every family's admission items are verified against the repository; a family
missing an item must have a planned version for it; a family registered
without an oracle is refused and told which item it lacks.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from workbench.admission import ADMISSION_EVIDENCE, ADMISSION_ITEMS, PLANNED, Oracle, assess, gap_list
from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS
from workbench.contracts.model.result_envelope_registry import declaration_for

ROOT = Path(__file__).resolve().parents[1]


def test_every_family_has_an_admission_record() -> None:
    assert set(ADMISSION_EVIDENCE) == set(MODEL_FAMILY_CONTRACTS)


def test_every_missing_item_has_a_planned_version() -> None:
    unplanned = [
        (gap["family"], item) for gap in gap_list(ROOT) for item, version in gap["planned"].items() if not version
    ]
    assert unplanned == [], f"admission items missing without a plan: {unplanned}"


def test_no_plan_is_kept_for_an_item_that_is_already_met() -> None:
    stale = [
        (family, item) for family, items in PLANNED.items() for item in items
        if item not in assess(family, root=ROOT)["missing"]
    ]
    assert stale == [], f"planned items already met; remove them from PLANNED: {stale}"


def test_ols_is_admitted() -> None:
    report = assess("ols", root=ROOT)
    assert report["admitted"], report
    assert set(report["items"]) == set(ADMISSION_ITEMS)


def test_a_family_registered_without_an_oracle_is_refused_and_told_which_item() -> None:
    """Developer acceptance in the objective: a fake family that lacks oracle
    data fails, and the report names the missing item."""
    declaration = replace(declaration_for("logit"), family="fake_logit")
    evidence = {"fake_logit": {"oracle": (), "live_eval": ("logit_union",)}}
    report = assess("fake_logit", root=ROOT, evidence=evidence, declaration=declaration)
    assert report["admitted"] is False
    assert report["missing"] == ["oracle"]
    assert "reference data" in report["items"]["oracle"]["detail"]


def test_a_referenced_oracle_that_does_not_exist_does_not_count() -> None:
    declaration = replace(declaration_for("logit"), family="fake_logit")
    evidence = {"fake_logit": {
        "oracle": (Oracle("r_oracle", "tests/fixtures/nowhere/oracle.json", "tests/test_nowhere.py"),),
        "live_eval": ("logit_union",),
    }}
    report = assess("fake_logit", root=ROOT, evidence=evidence, declaration=declaration)
    assert report["missing"] == ["oracle"] and "missing" in report["items"]["oracle"]["detail"]


def test_lmm_host_verified_oracles_cover_fixed_effects_and_variance_components() -> None:
    report = assess("linear_mixed_effects", root=ROOT)
    assert report["items"]["oracle"]["met"] is True
    fixtures = {oracle.fixture for oracle in ADMISSION_EVIDENCE["linear_mixed_effects"]["oracle"]}
    assert fixtures == {
        "tests/fixtures/admission/linear_mixed_effects/oracle.json",
        "tests/fixtures/admission/linear_mixed_effects/variance_oracle.json",
        # v1.8.11: fixed-effect inference (GLS covariance) for REML/ML x intercept/slope.
        "tests/fixtures/postestimation/lmm_v1811/gls_reference_r.json",
    }
    # Live: host-contained run with real deepseek-flash on 2026-10-07.
    assert report["missing"] == []
    assert "v1811_linear_mixed_effects" in ADMISSION_EVIDENCE["linear_mixed_effects"]["live_eval"]
    assert "linear_mixed_effects" not in PLANNED


def test_v1811_families_with_completed_live_evidence_are_registered() -> None:
    import json
    cases = json.loads((ROOT / "scripts/agent_live_eval_cases.json").read_text())
    verified = {c["fixture"]: c["id"] for c in cases[37:] if c["fixture"] != "linear_mixed_effects"}
    for family, case_id in verified.items():
        family = {"glm_binomial":"glm:binomial", "glm_poisson":"glm:poisson", "glm_negative_binomial":"glm:negative_binomial"}.get(family, family)
        assert case_id in ADMISSION_EVIDENCE[family]["live_eval"], family
        assert assess(family, root=ROOT)["items"]["live_eval"]["met"] is True
        assert "live_eval" not in PLANNED.get(family, {})
