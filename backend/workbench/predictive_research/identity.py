"""Deterministic identity layers for typed predictive-research runs."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any

from .contracts import SampleSpecV1, _canonical


def _content_hash(payload: Any) -> str:
    encoded = json.dumps(
        _canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PredictionIdentityV1:
    """The identities needed to separate transform reuse from evaluation reuse."""

    sample_spec_hash: str
    transformation_identity_hash: str
    evaluation_identity_hash: str
    prediction_identity_hash: str
    run_identity_hash: str

    def to_dict(self) -> dict[str, str]:
        return {
            "sample_spec_hash": self.sample_spec_hash,
            "transformation_identity_hash": self.transformation_identity_hash,
            "evaluation_identity_hash": self.evaluation_identity_hash,
            "prediction_identity_hash": self.prediction_identity_hash,
            "run_identity_hash": self.run_identity_hash,
        }

    @property
    def transformation_hash(self) -> str:
        return self.transformation_identity_hash

    @property
    def evaluation_hash(self) -> str:
        return self.evaluation_identity_hash

    @property
    def prediction_hash(self) -> str:
        return self.prediction_identity_hash


def build_prediction_identity(
    sample_spec: SampleSpecV1,
    *,
    model_type: str,
    model_id: str,
) -> PredictionIdentityV1:
    """Build stable identities without using opaque split-reference fields.

    ``SampleSpecV1.transformation_hash`` intentionally excludes its SplitPlan.
    The prediction layer adds the effective SplitPlan and model identity, so a
    changed split parameter cannot reuse a prior prediction identity.
    """

    sample_spec.validate()
    sample_spec_hash = sample_spec.content_hash
    transformation_identity_hash = sample_spec.transformation_hash
    evaluation_identity_hash = sample_spec.evaluation_hash
    prediction_identity_hash = _content_hash(
        {
            "payload_schema": "workbench.prediction.prediction-identity",
            "schema_version": 1,
            "transformation_identity_hash": transformation_identity_hash,
            "evaluation_identity_hash": evaluation_identity_hash,
            "split_plan": sample_spec.split_plan.to_dict(),
            "model_type": model_type,
            "model_id": model_id,
        }
    )
    run_identity_hash = _content_hash(
        {
            "payload_schema": "workbench.prediction.run-identity",
            "schema_version": 1,
            "prediction_identity_hash": prediction_identity_hash,
        }
    )
    return PredictionIdentityV1(
        sample_spec_hash=sample_spec_hash,
        transformation_identity_hash=transformation_identity_hash,
        evaluation_identity_hash=evaluation_identity_hash,
        prediction_identity_hash=prediction_identity_hash,
        run_identity_hash=run_identity_hash,
    )
