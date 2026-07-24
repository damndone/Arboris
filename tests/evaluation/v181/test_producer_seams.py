"""Producer-bound checks for the two work-order requirements that only mean
something against a *real* producer, not against a synthetic packet:

* self-reference — "一批 3 条 option 生成后全部仍为 fresh" (work order §produces);
* cross-family comparability — "ETS vs ARMA-GARCH 的 AIC 比较必须被拒绝".

The adversarial checkers behind both (``scan_batch_self_reference`` and
``scan_cross_family_ic_claims``) are already proven to catch their bugs in
``test_checkers_detect_their_own_bugs.py`` against hand-built counterexamples. A
checker that has only ever seen a synthetic packet is not, by itself, evidence
that the *shipped producer* is clean — so these tests point the same checkers at
the public seams the contracts imply (``capabilities.notebook_option_batch`` and
``capabilities.ets_compare_adapter``).

Neither seam exists in the v1.8.1 contract-lock worktree: the Agent Lane has not
shipped a public option-batch generator, and there is no cross-family ETS↔ARMA
compare adapter (the shipped ``time_series_compare`` module is ARMA-GARCH only).
So every test here is ``xfail(strict=True)`` while its capability is absent — the
body still runs, still fails, and is reported as ``xfailed`` naming the lane it
waits on; it is never a vacuous pass. When the seam lands the marker stops
applying and the producer's real output must satisfy the checker on its merits.

Following ``driver.py``'s rule, the harness drives the *public* seam and reports
a signature mismatch as a contract gap; it does not read a lane's internals to
discover a private entry point (ADR §7D).
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from workbench.agent.context_compiler import compile_notebook_planning_context
from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord
from workbench.agent.notebook.planning_agent import NotebookPlanningAgent
from tests.evaluation.v181 import capabilities
from tests.evaluation.v181.checks import (
    format_findings,
    scan_cross_family_ic_claims,
)
from tests.evaluation.v181.driver import ETSPackUnavailable, fit_ets
from tests.evaluation.v181.test_ets_known_truth import as_ets_result
from tests.fixtures.evaluation.v181 import ets_known_truth as oracle
from tests.test_notebook_support import make_project, model_rerun_proposal

_BATCH = capabilities.notebook_option_batch()
requires_option_batch = pytest.mark.xfail(
    not _BATCH.present, reason=_BATCH.reason, strict=True, run=True
)

_COMPARE = capabilities.ets_compare_adapter()
_ETS = capabilities.ets_model_pack()
_CROSS_FAMILY_PRESENT = _COMPARE.present and _ETS.present
requires_cross_family_adapter = pytest.mark.xfail(
    not _CROSS_FAMILY_PRESENT,
    reason=(
        f"awaiting cross-family compare: {_COMPARE.reason}"
        if not _COMPARE.present
        else _ETS.reason
    ),
    strict=True,
    run=True,
)


def _invoke_batch(
    generator: Any,
    *,
    notebook_id: str,
    count: int,
    planner: Any,
    context: Any,
    initial_evidence: DataEvidencePackV1,
) -> list[Any]:
    """Call the generator through the plausible contract-named signatures.

    A generator that accepts none of these keyword shapes is a contract gap: the
    harness reports which spellings it tried rather than reading the Agent Lane's
    implementation to discover the real one.
    """

    if generator is None:  # capability absent -> strict xfail catches this
        raise ETSPackUnavailable("no public option-batch generator is importable")

    attempts: list[dict[str, Any]] = [
        {
            "notebook_id": notebook_id,
            "count": count,
            "planner": planner,
            "context": context,
            "initial_evidence": initial_evidence,
        }
    ]
    signature = None
    try:
        signature = inspect.signature(generator)
    except (TypeError, ValueError):
        signature = None

    last_error: Exception | None = None
    for kwargs in attempts:
        if signature is not None:
            if not all(name in signature.parameters for name in kwargs):
                continue
        try:
            result = generator(**kwargs)
        except TypeError as error:
            last_error = error
            continue
        return list(result)
    raise AssertionError(
        "the option-batch generator accepted none of the contract-named "
        f"signatures {attempts}; last error: {last_error!r}. Reported as a "
        "contract gap, not patched."
    )


class _EvaluationPlanningAdapter:
    """Deterministic provider transcript driven through the real typed agent."""

    def __init__(self, submit_args: dict[str, Any]) -> None:
        self.submit_args = submit_args
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            arguments = {
                "requests": [
                    {
                        "inspection_id": "time_index.v1",
                        "target_ref": "run:active",
                        "arguments": {"max_rows": 10},
                        "why_needed": "validate the bounded time index",
                    }
                ]
            }
            tool_id = "request_notebook_inspections"
            tool_call_id = "eval-inspection"
        else:
            arguments = self.submit_args
            tool_id = "submit_notebook_option_batch"
            tool_call_id = "eval-options"
        yield ModelStreamEvent.tool_call_delta(
            request.request_id,
            {
                "tool_call_id": tool_call_id,
                "tool_id": tool_id,
                "arguments": arguments,
            },
        )
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


def _evaluation_option_batch() -> dict[str, Any]:
    options = []
    covariances = ("robust", "classic", "hc1")
    for rank, covariance in enumerate(covariances, start=1):
        proposal = model_rerun_proposal(
            f"prop_eval_{rank}", covariance=covariance, run_id="notebook:nb_eval_0001"
        )
        options.append(
            {
                "rank": rank,
                "rationale": f"Evidence-backed registered path {rank}.",
                "assumptions": ["the bounded time index remains valid"],
                "capability_id": "time_series.ets",
                "option_id": f"opt_eval_{rank}",
                "proposal": proposal,
                "expected_artifacts": [
                    {
                        "artifact_id": "ets_1",
                        "artifact_type": "model_result",
                        "required": True,
                        "count": 1,
                        "step": None,
                    }
                ],
                "evidence_refs": [
                    {
                        "evidence_id": "evidence:time",
                        "result_hash": "sha256:time-evaluation",
                        "source_refs": ["time_index:run_eval"],
                    }
                ],
                "comparative_claims": [
                    f"evidence:time supports registered path {rank}"
                ],
            }
        )
    return {"options": options}


@requires_option_batch
def test_real_option_batch_of_three_is_all_fresh_and_self_consistent(
    tmp_path: Path,
) -> None:
    """The public producer must drive the real typed agent, not synthesize paths."""

    project = make_project(tmp_path)
    context = compile_notebook_planning_context(
        project,
        notebook_id="nb_eval_0001",
        run_family_id="family_eval_0001",
        active_head_run_id=None,
        analysis_contract={"revision": 1, "target": "y"},
        available_capabilities=["time_series.ets"],
    )
    evidence = DataEvidencePackV1(
        source_id="run:run_eval",
        records=(
            EvidenceRecord(
                evidence_id="evidence:time",
                inspection_id="time_index.v1",
                source_refs=("time_index:run_eval",),
                protocol_version="time-index/v1",
                status="completed",
                observations={"candidate_column": "when"},
                result_hash="sha256:time-evaluation",
            ),
        ),
    )
    adapter = _EvaluationPlanningAdapter(_evaluation_option_batch())
    planner = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=lambda requests, current: evidence,
    )

    generator = capabilities.notebook_option_batch().handle
    batch = _invoke_batch(
        generator,
        notebook_id="nb_eval_0001",
        count=3,
        planner=planner,
        context=context,
        initial_evidence=DataEvidencePackV1("run:run_eval", ()),
    )

    assert len(batch) == 3
    assert [item.rank for item in batch] == [1, 2, 3]
    assert len({item.option_id for item in batch}) == 3
    assert len({item.proposal.canonical_hash() for item in batch}) == 3
    assert len({item.recommendation_decision_id for item in batch}) == 1
    assert all(item.evidence_refs for item in batch)
    assert len(adapter.requests) == 2


def _cross_family_compare(adapter: Any, tmp_path: Path) -> Any:
    """Drive a real cross-family compare of an ETS fit against ARMA-GARCH.

    The ETS side is a genuine pack result on a known-truth series; the ARMA-GARCH
    side is the family the compare must refuse to rank against. The exact adapter
    invocation is the seam this test pins — a signature mismatch is a contract
    gap, reported not patched.
    """

    if adapter is None:  # capability absent -> strict xfail catches this
        raise ETSPackUnavailable("no cross-family compare adapter is importable")

    truth = oracle.aadn_damped_trend()
    ets_result, _meta = fit_ets(
        truth.values, truth.spec, tmp_path=tmp_path, run_id="cross-family-ets"
    )
    left = as_ets_result(ets_result)
    right = {
        "model_type": "time_series.arma_garch",
        "aic": float(left.get("aic", 0.0)) - 150.0,
    }

    attempts = (
        {"left": left, "right": right},
        {"a": left, "b": right},
    )
    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            return adapter(**kwargs)
        except TypeError as error:
            last_error = error
            continue
    try:
        return adapter(left, right)
    except TypeError as error:
        raise AssertionError(
            "the cross-family compare adapter accepted none of the pinned "
            f"call shapes; last error: {last_error or error!r}. Reported as a "
            "contract gap."
        )


@requires_cross_family_adapter
def test_real_cross_family_compare_refuses_to_rank_ets_against_arma_garch(
    tmp_path: Path,
) -> None:
    """Contract point 3: an ETS↔ARMA-GARCH compare must return
    ``comparability: restricted`` with no superiority verdict built on AIC/BIC."""

    adapter = capabilities.ets_compare_adapter().handle
    packet = _cross_family_compare(adapter, tmp_path)
    payload = packet.to_dict() if hasattr(packet, "to_dict") else packet
    findings = scan_cross_family_ic_claims(payload, subject="real_cross_family_compare")
    assert findings == [], format_findings(findings)
