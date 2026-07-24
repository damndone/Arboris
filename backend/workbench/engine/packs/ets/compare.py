"""Compare adapter for the ETS pack.

Point 3 of the locked contract: information criteria are a *within-family,
same-sample* statement. This adapter is the single place that decides whether
an AIC/BIC delta may be produced at all:

* the other side is not an ETS result → `restricted`,
  `ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE`, and no delta;
* both ETS but different samples → `restricted`, `ETS_SAMPLE_DIFFERS`,
  and no delta;
* both ETS on the same sample → `full`, with the delta. `reason_code` is then
  `ETS_SPECIFICATION_DIFFERS` when the two specifications differ (the normal,
  meaningful case) and `None` when they are the same model refitted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from workbench.contracts.model.ets import (
    COMPARE_REASON_CODES,
    ETS_CONTRACT_VERSION,
    ETS_MODEL_TYPE,
)

from .estimation import ETSFitOutcome, PRODUCER_VERSION


COMPARE_CONTRACT = "time_series.ets.compare"


@dataclass(frozen=True)
class CompareSide:
    """One side of a comparison, described only by facts the pack can see."""

    model_type: str
    label: str
    sample_fingerprint: str | None = None
    aic: float | None = None
    bic: float | None = None
    specification: str | None = None

    @classmethod
    def from_outcome(cls, outcome: ETSFitOutcome, *, label: str) -> "CompareSide":
        return cls(
            model_type=outcome.result.model_type,
            label=label,
            sample_fingerprint=outcome.sample_fingerprint,
            aic=outcome.result.aic,
            bic=outcome.result.bic,
            specification=outcome.result.specification.canonical,
        )

    @classmethod
    def from_foreign_result(
        cls,
        payload: Mapping[str, Any],
        *,
        label: str,
        sample_fingerprint: str | None = None,
    ) -> "CompareSide":
        """Describe a non-ETS model (e.g. ARMA-GARCH) without trusting its IC."""

        model_type = payload.get("model_type")
        if type(model_type) is not str or not model_type:
            raise ValueError("a compare side requires a model_type")
        return cls(
            model_type=model_type,
            label=label,
            sample_fingerprint=sample_fingerprint,
        )

    def _side_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "model_type": self.model_type,
            "specification": self.specification,
            "sample_fingerprint": self.sample_fingerprint,
        }


def build_ets_compare_packet(left: CompareSide, right: CompareSide) -> dict[str, Any]:
    """Return the pack's compare packet for two candidate models."""

    comparability = "full"
    reason_code: str | None = None
    criteria: dict[str, Any] | None = None

    if ETS_MODEL_TYPE not in (left.model_type, right.model_type):
        raise ValueError("the ETS compare adapter requires at least one ETS side")

    if left.model_type != ETS_MODEL_TYPE or right.model_type != ETS_MODEL_TYPE:
        comparability = "restricted"
        reason_code = "ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE"
    elif (
        left.sample_fingerprint is None
        or right.sample_fingerprint is None
        or left.sample_fingerprint != right.sample_fingerprint
    ):
        comparability = "restricted"
        reason_code = "ETS_SAMPLE_DIFFERS"
    else:
        if left.specification != right.specification:
            reason_code = "ETS_SPECIFICATION_DIFFERS"
        criteria = {
            "basis": "within_family_same_sample",
            "aic_delta": float(right.aic) - float(left.aic),
            "bic_delta": float(right.bic) - float(left.bic),
            "preferred_by_aic": left.label if left.aic <= right.aic else right.label,
            "preferred_by_bic": left.label if left.bic <= right.bic else right.label,
        }

    if reason_code is not None and reason_code not in COMPARE_REASON_CODES:
        raise ValueError(f"undeclared compare reason code: {reason_code}")

    return {
        "contract": COMPARE_CONTRACT,
        "contract_version": ETS_CONTRACT_VERSION,
        "producer_version": PRODUCER_VERSION,
        "comparability": comparability,
        "reason_code": reason_code,
        "left": left._side_dict(),
        "right": right._side_dict(),
        "criteria": criteria,
    }


__all__ = ["COMPARE_CONTRACT", "CompareSide", "build_ets_compare_packet"]
