"""Synthetic Notebook/Option packets for the v1.8.1 evaluation harness.

These exist so the harness's own checkers can be proven to *catch* the bugs they
claim to catch, before any lane produces a real packet. A checker that has never
been shown a counterexample is not evidence.

Nothing here is a golden output. The canonical fixtures live in
``tests/fixtures/contracts/v181/`` and are integration-owned and read-only.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

CONTRACT_FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "v181"


def load_contract_fixture(name: str) -> dict[str, Any]:
    """Read one integration-owned canonical fixture (read-only)."""

    return json.loads((CONTRACT_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _sha(tag: str) -> str:
    return "sha256:" + hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _fresh(tag: str) -> str:
    return "fresh1:" + hashlib.sha256(tag.encode("utf-8")).hexdigest()


def option_packet(
    *,
    rank: int,
    batch_id: str = "batch_eval_001",
    generation_context_id: str = "ctx_eval_001",
    generation_tag: str = "ctx_eval_001",
    freshness_tag: str = "deps_eval_001",
    freshness_status: str = "fresh",
    **overrides: Any,
) -> dict[str, Any]:
    """A minimal, contract-shaped NotebookOptionRevision.

    ``generation_tag`` and ``freshness_tag`` are hashed separately on purpose:
    the two fields answer different questions (spec §4.0) and a producer that
    reuses one value for both is the bug the contract forbids.
    """

    packet: dict[str, Any] = {
        "contract_version": "1.0",
        "option_id": f"opt_eval_{rank}",
        "option_revision": 1,
        "notebook_id": "nb_eval_0001",
        "run_family_id": "run-family:22222222-2222-4222-8222-222222222222",
        "generation_context_id": generation_context_id,
        "generation_context_hash": _sha(generation_tag),
        "freshness_dependency_fingerprint": _fresh(freshness_tag),
        "typed_proposal_id": f"prop_eval_{rank}",
        "typed_proposal_revision": 1,
        "artifact_contract": {
            "contract_version": "1.0",
            "expected": [
                {
                    "artifact_id": f"ets_{rank}",
                    "artifact_type": "model_result",
                    "required": True,
                    "count": 1,
                    "step": "estimation",
                }
            ],
            "checked_dimensions": ["artifact_id", "artifact_type", "count", "step"],
            "not_evaluated_dimensions": ["payload_schema"],
        },
        "rationale": "An ETS baseline on the modelled series.",
        "assumptions": ["regular calendar", "no interior gaps"],
        "risk_level": "low",
        "lifecycle_status": "proposed",
        "freshness_status": freshness_status,
        "validation_status": "valid",
        "rank": rank,
        "batch_id": batch_id,
        "created_at": "2026-07-22T18:00:00+00:00",
        "supersedes_option_revision": None,
    }
    packet.update(overrides)
    return packet


def healthy_batch(size: int = 3) -> list[dict[str, Any]]:
    """A batch of ``size`` options that all share one context and stay fresh."""

    return [option_packet(rank=index + 1) for index in range(size)]


def self_staling_batch(size: int = 3) -> list[dict[str, Any]]:
    """The bug spec §4.0 exists to prevent: options stale themselves.

    Each option's freshness fingerprint is computed over a context that already
    contains the *previous* options, so by the time the batch is complete every
    earlier option's fingerprint no longer matches and the producer marks it
    stale.
    """

    batch = []
    for index in range(size):
        batch.append(
            option_packet(
                rank=index + 1,
                freshness_tag=f"deps_after_{index}_options",
                freshness_status="fresh" if index == size - 1 else "stale",
            )
        )
    return batch


def merged_hash_packet() -> dict[str, Any]:
    """A producer that stored one value in both hash fields.

    The value is prefixed ``sha256:`` so it passes the prefix check on
    ``generation_context_hash``; only the equality check catches it.
    """

    merged = _sha("one_value_for_both")
    return option_packet(
        rank=1,
        generation_context_hash=merged,
        freshness_dependency_fingerprint=merged,
    )


def divergent_batch_context() -> list[dict[str, Any]]:
    """Options in one batch claiming different generation contexts."""

    first, second, third = healthy_batch(3)
    third = deepcopy(third)
    third["generation_context_id"] = "ctx_eval_OTHER"
    third["generation_context_hash"] = _sha("ctx_eval_OTHER")
    return [first, second, third]


# --- ETS result variants for the overclaim scanner -------------------------


def clean_ets_result() -> dict[str, Any]:
    return load_contract_fixture("ets_result")


def volatility_overclaim_result() -> dict[str, Any]:
    """An ETS result that has grown a conditional-variance vocabulary."""

    result = clean_ets_result()
    result["params"] = dict(result["params"])
    result["params"]["conditional_volatility_forecast"] = 3.9
    return result


def var_overclaim_result() -> dict[str, Any]:
    """An ETS result narrated as a risk model."""

    result = clean_ets_result()
    result["interpretation"] = (
        "The fitted level implies a one-day 99% Value at Risk of 4.1 index points."
    )
    return result


def cross_family_aic_claim() -> dict[str, Any]:
    """A compare payload ranking ETS against ARMA-GARCH by AIC."""

    return {
        "left": {"model_type": "time_series.ets", "aic": 12043.72},
        "right": {"model_type": "time_series.arma_garch", "aic": 11890.10},
        "comparability": "full",
        "verdict": "ARMA-GARCH is better: its AIC is 153.6 lower.",
    }


def honest_cross_family_compare() -> dict[str, Any]:
    return {
        "left": {"model_type": "time_series.ets", "aic": 12043.72},
        "right": {"model_type": "time_series.arma_garch", "aic": 11890.10},
        "comparability": "restricted",
        "reason_code": "ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE",
        "verdict": (
            "Information criteria are not comparable across these families; "
            "no ranking is reported."
        ),
    }


__all__ = [
    "CONTRACT_FIXTURES",
    "clean_ets_result",
    "cross_family_aic_claim",
    "divergent_batch_context",
    "healthy_batch",
    "honest_cross_family_compare",
    "load_contract_fixture",
    "merged_hash_packet",
    "option_packet",
    "self_staling_batch",
    "var_overclaim_result",
    "volatility_overclaim_result",
]
