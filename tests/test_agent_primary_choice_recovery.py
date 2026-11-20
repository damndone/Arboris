"""An answer that stops before choosing the primary model resumes on its own.

2026-11-10 NVIDIA position binary_logit.open.r3: two eligible fits existed, the delivery check said
"Several fits are eligible as the primary model ... call update_plan with completion_evidence" and
listed them, yet carried no recovery action because no model was bound in the evidence yet, the
very thing the next step asks for. The Agent wrote its summary and the turn waited for a nudge.
The choice stays the Agent's: the recovery only resumes the turn with the gate's next step.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests.test_agent_completion_survival import build_native_products
from tests.test_agent_plan_criteria import approved_plan
from workbench.agent.delivery import delivery_check

FAMILIES = Path(__file__).parent / 'fixtures/v186_families/families.csv'


@pytest.fixture(scope='module')
def products(tmp_path_factory):
    return build_native_products(tmp_path_factory.mktemp('primary-choice'), FAMILIES)


def test_unchosen_primary_candidates_get_the_bounded_recovery(products):
    project, contract, _ = products
    plan, _ = approved_plan(project, contract, None)
    checked = delivery_check(project, replace(plan, completion_evidence=None))
    assert checked['status'] == 'partial' and len(checked['primary_candidates']['survival']) == 2
    assert checked['next_step'].startswith('Several fits are eligible as the primary model')
    assert checked['recovery_action'] == 'inspect_and_repair' and checked['recovery_question_sha256']


def test_a_chosen_primary_needs_no_recovery(products):
    project, contract, evidence = products
    plan, _ = approved_plan(project, contract, evidence)
    checked = delivery_check(project, plan)
    assert checked['status'] == 'requirements_met' and 'recovery_action' not in checked
