"""Declaration-derived planner evaluation cases."""

from __future__ import annotations

from workbench.agent.capability_contract import CapabilityContract
from workbench.agent import planner_evaluation as evaluation


def test_cases_cover_live_reachable_capabilities_without_a_second_id_list() -> None:
    report = evaluation.build_evaluation_cases(seed=17)

    assert len(report.cases) == len(report.reachable_capabilities) * len(
        evaluation.SCENARIO_KINDS
    )
    assert {case.capability_id for case in report.cases} == {
        item.capability_id for item in report.reachable_capabilities
    }
    assert {case.scenario for case in report.cases} == set(evaluation.SCENARIO_KINDS)
    assert {item.capability_id for item in report.exemptions} == {
        "code.execute",
        "data.column.cast",
    }


def test_case_route_prefers_live_composition_and_prompts_hide_internal_ids() -> None:
    report = evaluation.build_evaluation_cases(seed=23)

    composed = next(case for case in report.cases if case.capability_id == "model.ols")
    assert composed.route == "composition"
    assert composed.outer_operation_id == "operation.multi_step"
    assert composed.step_operation_id == "model.genesis"
    for case in report.cases:
        assert case.capability_id not in case.prompt
        assert case.outer_operation_id not in case.prompt
        if case.step_operation_id:
            assert case.step_operation_id not in case.prompt


def test_injected_live_declaration_changes_case_inventory_without_test_edits(
    monkeypatch,
) -> None:
    baseline = evaluation.build_evaluation_cases(seed=7)
    fake = CapabilityContract(
        capability_id="pack.injected_for_planner_eval",
        kind="pack",
        summary="A synthetic registered analysis capability.",
        proposed_by=("data.append",),
    )
    monkeypatch.setattr(
        evaluation,
        "live_capability_inventory",
        lambda: (*baseline.inventory, fake),
    )

    injected = evaluation.build_evaluation_cases(seed=7)

    assert len(injected.cases) == len(baseline.cases) + len(evaluation.SCENARIO_KINDS)
    assert {
        case.capability_id for case in injected.cases
    } - {case.capability_id for case in baseline.cases} == {
        fake.capability_id
    }


def test_holdout_seed_changes_prompt_surface_but_not_typed_route() -> None:
    first = evaluation.build_evaluation_cases(seed=11)
    second = evaluation.build_evaluation_cases(seed=12)
    first_by_key = {(item.capability_id, item.scenario): item for item in first.cases}
    second_by_key = {(item.capability_id, item.scenario): item for item in second.cases}

    assert set(first_by_key) == set(second_by_key)
    assert any(
        first_by_key[key].prompt != second_by_key[key].prompt
        for key in first_by_key
    )
    assert all(
        (first_by_key[key].outer_operation_id, first_by_key[key].step_operation_id)
        == (second_by_key[key].outer_operation_id, second_by_key[key].step_operation_id)
        for key in first_by_key
    )
