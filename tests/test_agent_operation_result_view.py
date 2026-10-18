"""The executed operation's result as the Agent sees it: bounded, scalars kept."""

from __future__ import annotations

import json
from decimal import Decimal

from workbench.agent import numeric_grounding
from workbench.agent.operation_outcome import RESULT_VIEW_CHARS, result_view


def _km_like(points: int) -> dict:
    curve = {"group": "drug=1", "times": [i * 0.37 for i in range(points)],
             "survival": [1 - i / (points + 1) for i in range(points)],
             "censored": [i % 3 == 0 for i in range(points)],
             "median_survival": 21.4375}
    return {"record_id": "oprec_1", "operation_id": "operation.multi_step", "status": "completed", "error": None,
            "outputs": {"post_estimation_results": [{
                "artifact_id": "art_km", "operation_id": "survival.kaplan_meier",
                "result": {"curves": [curve, {**curve, "group": "drug=0", "median_survival": 15.8125}]}},
                {"artifact_id": "art_cox", "operation_id": "survival.cox",
                 "result": {"coefficients": [{"term": "drug", "estimate": -0.3751, "std_error": 0.0912,
                                              "p_value": 0.00004}], "concordance": 0.6123}}]}}


def test_small_result_is_unchanged():
    payload = {"record_id": "r", "status": "completed", "outputs": {"estimate": 1.25, "rows": [1, 2, 3]}}
    assert result_view(payload) == json.dumps(payload, ensure_ascii=False, sort_keys=True)


def test_long_series_are_shortened_and_scalars_kept():
    payload = _km_like(3000)
    assert len(json.dumps(payload)) > 100_000
    text = result_view(payload)
    assert len(text) <= RESULT_VIEW_CHARS
    assert text.startswith("Workbench: this result was shortened")
    for kept in ("art_km", "art_cox", "oprec_1", "21.4375", "15.8125", "-0.3751", "0.0912", "0.6123", '"length": 3000'):
        assert kept in text
    # The numbers the Agent would cite remain evidence for the numeric check (stored unsigned).
    evidence = numeric_grounding.evidence_from_messages([{"role": "system", "content": text}])
    assert evidence.supports(Decimal("0.375")) and evidence.supports(Decimal("21.44"))


def test_oversized_result_falls_back_to_a_named_prefix():
    payload = {"record_id": "r", "outputs": {f"table_{i}": [{"k": "x" * 400}] * 10 for i in range(40)}}
    text = result_view(payload)
    assert len(text) <= RESULT_VIEW_CHARS
    assert "_omitted_keys" in text or "_truncated_keys" in text


def test_the_shortened_note_gives_the_exact_read_arguments():
    text = result_view(_km_like(3000), read_with={"owner_run_id": "run-a", "op_node_id": "stage:cleaned",
                                                  "operation_record_id": "oprec_1"})
    assert ("inspect_operation_artifact with owner_run_id run-a, op_node_id stage:cleaned, "
            "operation_record_id oprec_1 and the artifact_id") in text
