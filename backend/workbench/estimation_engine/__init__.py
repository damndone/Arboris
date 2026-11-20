"""Which engine fits a model: the reference libraries (default) or the opt-in native engine.

``reference`` is the default and keeps every result bit for bit. ``fast`` asks for the native
engine (`native/engine`, Rust): it computes the same estimator by the same definitions, but not
bit for bit. Independent accuracy checks and reference agreement are separate; known reference
differences are retained in the fixtures rather than counted as agreement.
A request the fast engine does not cover runs on the reference, and the result says why.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

REFERENCE = "reference"
FAST = "fast"
ENGINE_CHOICES = (REFERENCE, FAST)
FAST_ENGINE_NAME = "arboris-engine"
# Comparison thresholds, not a universal error bound. Independently checked differences
# outside these thresholds remain explicit in fast_engine_iv_independent/reference_gaps.json.
AGREEMENT_RELATIVE = 1e-9
AGREEMENT_ABSOLUTE = 1e-12
# n R^2-type statistics: the reference forms them as n - SSR, whose rounding error grows with n,
# while the fast engine sums the explained part directly (scripts/oracles/iv_high_precision.py).
AGREEMENT_ABSOLUTE_PER_ROW = 1e-15


class EstimationEngineError(ValueError):
    """An engine choice the product does not know."""


def normalize_engine_choice(value: Any) -> str:
    text = "" if value is None else str(value).strip().lower()
    if text in {"", REFERENCE}:
        return REFERENCE
    if text == FAST:
        return FAST
    raise EstimationEngineError(
        f"ESTIMATION_ENGINE_UNKNOWN: estimation_engine is one of {', '.join(ENGINE_CHOICES)} (got {value!r})."
    )


def stored_choice(value: Any) -> str:
    """The choice as a run stores it: "" for the reference, so a default run keeps its exact inputs."""
    choice = normalize_engine_choice(value)
    return "" if choice == REFERENCE else choice


def engine_provenance(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """Bound recorded execution facts for display/context, without certifying accuracy.

    The durable selection keeps the full build receipt. Public summaries need
    only its identity digest; they must not copy compiler or filesystem paths.
    Missing facts (including bit identity on a fallback) remain missing.
    """
    selection = result.get("engine_selection")
    if not isinstance(selection, Mapping):
        return None
    requested, used = selection.get("requested"), selection.get("used")
    if not isinstance(requested, str) or not isinstance(used, str):
        return None
    public: dict[str, Any] = {"requested": requested[:128], "used": used[:128]}
    reason = selection.get("reason")
    if isinstance(reason, str) and reason:
        public["reason"] = reason[:500] + ("…" if len(reason) > 500 else "")
    bit_identity = selection.get("bit_identical_to_reference")
    if isinstance(bit_identity, bool):
        public["bit_identical_to_reference"] = bit_identity
    build = selection.get("build")
    digest = build.get("build_identity_sha256") if isinstance(build, Mapping) else None
    if isinstance(digest, str) and len(digest) == 64 and all(char in "0123456789abcdefABCDEF" for char in digest):
        public["build_identity_sha256"] = digest
    return public


def validate_genesis_estimation_engine(spec: Mapping[str, Any]) -> str:
    """The shared manual/Agent admission boundary for the experimental engine.

    This validates the offered family/covariance combination without loading a
    binary or running a self-check. Runtime integrity failures remain execution
    errors, and an absent binary retains the existing named reference dispatch.
    """
    branches = spec.get("branches") or ()
    for branch in branches:
        if isinstance(branch, Mapping) and "estimation_engine" in branch:
            raise EstimationEngineError(
                "ESTIMATION_ENGINE_BRANCH_OVERRIDE: estimation_engine applies to the whole model.genesis step"
            )
    if "estimation_engine" not in spec:
        return ""
    if not isinstance(spec["estimation_engine"], str):
        raise EstimationEngineError("ESTIMATION_ENGINE_UNKNOWN: estimation_engine must be reference or fast")
    engine = stored_choice(spec["estimation_engine"])
    if not engine:
        return ""
    family = spec.get("model_family") or spec.get("model_type")
    if family != "iv_2sls":
        raise EstimationEngineError("ESTIMATION_ENGINE_NOT_COVERED: fast is offered only for iv_2sls")
    from .iv import COVERED_COVARIANCES
    from ..contracts.model.family import model_family_contract

    default = model_family_contract(str(family)).default_covariance
    covariances = [branch.get("covariance") or spec.get("covariance") or default
                   for branch in branches if isinstance(branch, Mapping)] or [spec.get("covariance") or default]
    if any(not isinstance(value, str) or value not in COVERED_COVARIANCES for value in covariances):
        raise EstimationEngineError(
            "ESTIMATION_ENGINE_NOT_COVERED: fast IV requires covariance " + ", ".join(sorted(COVERED_COVARIANCES))
            + ". Choose reference to retain this covariance, or choose a supported covariance."
        )
    return engine


@dataclass(frozen=True)
class EngineSelection:
    """What was asked for, what ran, and why the fast engine stood aside when it did."""

    requested: str
    used: str
    reason: str | None = None
    build: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {"requested": self.requested, "used": self.used}
        if self.reason:
            record["reason"] = self.reason
        if self.used == FAST_ENGINE_NAME:
            record["agreement_with_reference"] = {
                "relative": AGREEMENT_RELATIVE, "absolute": AGREEMENT_ABSOLUTE,
                "absolute_per_row_for_n_r_squared_statistics": AGREEMENT_ABSOLUTE_PER_ROW,
                "basis": "bounded fixtures against the reference library, R and finite high-precision arithmetic; not a universal error bound",
                "field_rules": {
                    "counts_degrees_and_applicability": "exact",
                    "standard_errors": "relative only, no absolute floor",
                    "covariance": "also bounded relative to sqrt(diagonal products)",
                    "probabilities": "positive tails require relative and log agreement; reference tails use survival functions",
                },
            }
            record["bit_identical_to_reference"] = False
        if self.build:
            record["build"] = dict(self.build)
        return record
