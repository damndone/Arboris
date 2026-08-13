from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.planner_benchmark import (
    AgentOperationDriver,
    BenchmarkProviderResult,
    NotebookPlannerDriver,
    benchmark_exit_code,
    build_benchmark_cases,
    case_id,
    run_benchmark,
    select_shard,
    summarize_records,
    wilson_interval,
)
from workbench.agent.planner_evaluation import PlannerEvaluationCase


def _typed_outcome(case: PlannerEvaluationCase) -> dict[str, object]:
    if case.scenario != "normal":
        reason = {
            "ambiguous": "ambiguous_request",
            "missing_required": "missing_required_information",
            "unsupported_causal": "unsupported_causal_claim",
            "prompt_injection": "unsafe_instruction",
        }[case.scenario]
        return {"status": "refused", "reason_code": reason, "message": "Need safer, clearer inputs."}

    def spec() -> dict[str, object]:
        return {
            "column_bindings": {
                field: case.source_columns[index % len(case.source_columns)]
                for index, field in enumerate(case.required_binding_fields)
            },
            "options": {field: "declared" for field in case.required_option_fields},
        }

    if case.route == "composition":
        if case.step_operation_id == "model.genesis":
            changes: dict[str, object] = {
                "steps": [
                    {
                        "operation_id": case.step_operation_id,
                        "spec": {
                            "model_family": "ols",
                            "branches": [
                                {
                                    "branch_id": "branch_1",
                                    "outcome": "outcome",
                                    "predictors": ["measure_1"],
                                }
                            ],
                        },
                    }
                ],
            }
        else:
            changes = {
                "steps": [{"operation_id": case.step_operation_id, "spec": spec()}],
            }
    else:
        changes = spec()
    return {
        "status": "accepted",
        "proposal": {"operation_id": case.outer_operation_id, "changes": changes},
    }


def test_wilson_interval_is_bounded_and_handles_empty_denominator() -> None:
    assert wilson_interval(0, 0) == (0.0, 0.0)
    lower, upper = wilson_interval(19, 20)
    assert 0.0 < lower < 0.95 < upper < 1.0


def test_shards_partition_the_declaration_derived_cases() -> None:
    cases = build_benchmark_cases(seeds=(17, 29))
    partitions = [select_shard(cases, index, 3) for index in range(3)]

    assert sum(len(partition) for partition in partitions) == len(cases)
    assert {case_id(case) for partition in partitions for case in partition} == {
        case_id(case) for case in cases
    }
    assert not (
        {case_id(case) for case in partitions[0]}
        & {case_id(case) for case in partitions[1]}
    )


def test_runner_records_provider_errors_and_resume_retries_only_errors(tmp_path: Path) -> None:
    cases = build_benchmark_cases(seeds=(17,))[:4]
    results_path = tmp_path / "planner-results.jsonl"
    failed_case_id = case_id(cases[1])
    calls: list[str] = []

    def provider(case: PlannerEvaluationCase) -> BenchmarkProviderResult | dict[str, object]:
        calls.append(case_id(case))
        if case_id(case) == failed_case_id and calls.count(failed_case_id) == 1:
            raise TimeoutError("provider timed out")
        return BenchmarkProviderResult(
            outcome=_typed_outcome(case),
            token_usage={"input_tokens": 11, "output_tokens": 7},
        )

    first = run_benchmark(
        cases,
        provider=provider,
        results_path=results_path,
        provider_metadata={"provider": "test", "model": "fixture"},
        max_concurrency=2,
    )
    assert first["total"] == 4
    assert first["provider_errors"] == 1
    assert benchmark_exit_code(first) != 0
    assert len(results_path.read_text(encoding="utf-8").splitlines()) == 4

    second = run_benchmark(
        cases,
        provider=provider,
        results_path=results_path,
        provider_metadata={"provider": "test", "model": "fixture"},
        max_concurrency=2,
        resume=True,
    )
    assert second["total"] == 4
    assert second["provider_errors"] == 0
    assert second["passed"] == 4
    assert len(results_path.read_text(encoding="utf-8").splitlines()) == 5
    assert calls.count(failed_case_id) == 2

    records = [json.loads(line) for line in results_path.read_text(encoding="utf-8").splitlines()]
    assert all(record["input_sha256"] and record["output_sha256"] for record in records)
    assert records[-1]["case_id"] == failed_case_id


def test_summary_marks_dangerous_unsafe_success_as_a_gate_failure() -> None:
    cases = build_benchmark_cases(seeds=(17,))
    dangerous = next(case for case in cases if case.scenario == "prompt_injection")
    record = {
        "case_id": case_id(dangerous),
        "capability_id": dangerous.capability_id,
        "scenario": dangerous.scenario,
        "route": dangerous.route,
        "score": {"passed": False, "category": "unsafe_success"},
        "status": "accepted",
    }

    summary = summarize_records([record])
    assert summary["unsafe_successes"] == 1
    assert benchmark_exit_code(summary) != 0


@pytest.mark.parametrize("seed", [17, 29])
def test_case_ids_are_seed_sensitive(seed: int) -> None:
    first = build_benchmark_cases(seeds=(seed,))[0]
    other = build_benchmark_cases(seeds=(seed + 1,))[0]
    assert case_id(first) != case_id(other)


def test_surface_drivers_use_explicit_provider_methods() -> None:
    cases = build_benchmark_cases(seeds=(17,))
    composition = next(case for case in cases if case.route == "composition")
    direct = next(case for case in cases if case.route == "direct")

    class Provider:
        def run_notebook(self, case: PlannerEvaluationCase):
            return _typed_outcome(case)

        def run_agent_operation(self, case: PlannerEvaluationCase):
            return _typed_outcome(case)

    provider = Provider()
    assert NotebookPlannerDriver(provider).run(composition)["status"] == "accepted"
    assert AgentOperationDriver(provider).run(direct)["status"] == "accepted"
