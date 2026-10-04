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
