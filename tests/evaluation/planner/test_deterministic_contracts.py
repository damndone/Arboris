"""Local deterministic planner/evaluator and provider-boundary contracts."""

from __future__ import annotations

from workbench.agent.planner_benchmark_contracts import (
    DeterministicPlannerEvaluatorV1,
    PLANNER_BENCHMARK_SCHEMA_VERSION,
    PlannerCaseSnapshotV1,
    PlannerEvaluatorIntentV1,
    PlannerProviderRequestV1,
    ProviderCallReceiptV1,
)
from workbench.agent.planner_evaluation import (
    PlannerEvaluationCase,
    build_evaluation_cases,
    score_case,
)


def _case(scenario: str = "normal"):
    report = build_evaluation_cases(seed=47)
    return next(
        item
        for item in report.cases
        if item.capability_id == "model.ols" and item.scenario == scenario
    )


def test_snapshot_is_typed_and_does_not_make_prompt_text_part_of_the_identity() -> None:
    case = _case()
    snapshot = PlannerCaseSnapshotV1.from_case(case)

    assert snapshot.case_id
    assert len(snapshot.prompt_sha256) == 64
    assert snapshot.surface == "notebook"  # composition is the Notebook surface
    assert snapshot.scenario == "normal"
    assert "prompt" not in snapshot.to_dict()


def test_evaluator_intent_is_not_visible_to_a_provider_request() -> None:
    case = _case("prompt_injection")
    snapshot = PlannerCaseSnapshotV1.from_case(case)
    intent = PlannerEvaluatorIntentV1.from_case(case, snapshot=snapshot)
    request = PlannerProviderRequestV1.from_case(case, snapshot=snapshot, intent=intent)
    payload = request.to_provider_payload()

    assert payload["case_id"] == snapshot.case_id
    assert payload["prompt"] == case.prompt
    assert "evaluator_intent" not in payload
    assert "expected_reason_code" not in payload
    assert "prompt_injection" not in payload["contract_digest"]


def test_provider_request_cannot_reveal_target_operation_or_required_fields() -> None:
    from dataclasses import fields
    request = PlannerProviderRequestV1.from_case(_case())
    hidden = {"capability_id", "outer_operation_id", "step_operation_id",
              "required_binding_fields", "required_option_fields", "scenario"}
    assert hidden.isdisjoint(request.to_provider_payload())
    assert hidden.isdisjoint(field.name for field in fields(request))


def test_deterministic_evaluator_refuses_dangerous_case_without_an_llm() -> None:
    case = _case("prompt_injection")
    result = DeterministicPlannerEvaluatorV1().evaluate(case)

    assert result.source == "deterministic"
    assert result.provider_receipt == ProviderCallReceiptV1.not_called()
    assert score_case(case, result.outcome).category == "safe_refusal"


def test_deterministic_evaluator_produces_a_scored_model_genesis_baseline() -> None:
    case = _case()
    result = DeterministicPlannerEvaluatorV1().evaluate(case)

    assert result.source == "deterministic"
    assert result.outcome["status"] == "accepted"
    assert score_case(case, result.outcome).passed


def test_deterministic_evaluator_is_repeatable_for_the_same_seeded_case() -> None:
    case = _case()
    evaluator = DeterministicPlannerEvaluatorV1()

    first = evaluator.evaluate(case)
    second = evaluator.evaluate(case)

    assert first.to_dict() == second.to_dict()


def test_provider_receipt_rejects_a_false_not_called_claim() -> None:
    try:
        ProviderCallReceiptV1(
            schema_version=PLANNER_BENCHMARK_SCHEMA_VERSION,
            called=False,
            call_count=1,
            driver="test",
        )
    except ValueError as exc:
        assert "call_count" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("an impossible provider receipt must be rejected")


def test_deterministic_evaluator_synthesizes_all_live_normal_holdout_cases() -> None:
    evaluator = DeterministicPlannerEvaluatorV1()
    cases = tuple(
        case
        for seed in (17, 29)
        for case in build_evaluation_cases(seed=seed).cases
        if case.scenario == "normal"
    )

    assert len(cases) == 254
    failures = []
    for case in cases:
        result = evaluator.evaluate(case)
        score = score_case(case, result.outcome)
        if not score.passed:
            failures.append(
                {
                    "capability_id": case.capability_id,
                    "route": case.route,
                    "step_operation_id": case.step_operation_id,
                    "status": result.status,
                    "category": score.category,
                    "detail": score.detail,
                }
            )

    assert failures == []


def test_deterministic_evaluator_reports_a_contract_gap_for_unknown_declaration() -> None:
    case = PlannerEvaluationCase(
        capability_id="fixture.unknown",
        capability_kind="analysis",
        summary="an unknown declared operation",
        route="direct",
        outer_operation_id="fixture.unknown_operation",
        step_operation_id=None,
        scenario="normal",
        prompt="Please use the unknown declared operation.",
        source_columns=("outcome",),
        allowed_ids=frozenset({"fixture.unknown_operation"}),
    )

    result = DeterministicPlannerEvaluatorV1().evaluate(case)

    assert result.status == "unavailable"
    assert result.outcome["reason_code"] == "DETERMINISTIC_CONTRACT_GAP"
    assert isinstance(result.outcome.get("contract_gap"), str)
    assert result.outcome["contract_gap"]
