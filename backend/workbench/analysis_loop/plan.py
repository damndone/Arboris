"""Canonical, side-effect-free plans for the OLS clustered covariance loop."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .canonical import sha256_canonical
from .contracts import (
    ClusterPreflightResult,
    ComparisonTarget,
    IntentValidationResult,
    SourceRunContract,
    _freeze,
    _thaw,
    plan_diff_logical_key,
)
from .policy import OLSClusterPolicyV1, ols_cluster_policy_v1
from .preflight import (
    preflight_cluster_variable,
    resolve_comparison_target,
    validate_source_contract,
)
from .recovery import get_recovery_action


ACTION_ID = "ols.use_clustered_covariance_v1"
OPERATION_ID = "model.rerun"
PLAN_DIFF_SCHEMA_VERSION = "plan_diff_v1"
PLAN_SCHEMA_VERSION = PLAN_DIFF_SCHEMA_VERSION
PLAN_STRATEGY_VERSION = "ols_cluster_strategy_v1"
STRATEGY_VERSION = PLAN_STRATEGY_VERSION

_INTENT_FIELDS = frozenset({"action_id", "patch", "requested_result_id", "target"})
_PATCH_FIELDS = frozenset({"covariance", "cluster_variable"})
_IDENTITY_FIELDS = frozenset({"run_id", "node_ref", "node_hash", "forest_node_key"})

_PLAN_INVARIANTS: dict[str, Any] = {
    "dataset_unchanged": True,
    "sample_unchanged": True,
    "analysis_sample_unchanged": True,
    "analysis_row_set_unchanged": True,
    "analysis_row_order_unchanged": True,
    "point_estimation_unchanged": True,
    "coefficient_schema_unchanged": True,
    "formula_unchanged": True,
    "rows_unchanged": True,
    "y_unchanged": True,
    "X_unchanged": True,
    "point_estimates_unchanged": True,
    "only_inference_config_changes": True,
    "covariance_only": True,
    "cluster_field_is_group_vector_only": True,
    "wire_field": "entity_col",
}


class PlanValidationError(ValueError):
    """A structured rejection before a PlanDiff can be persisted."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


PlanBuildError = PlanValidationError


class PlanBindingError(PlanValidationError):
    """A confirmation no longer matches the immutable PlanDiff binding."""


def _error(code: str, message: str, **details: Any) -> PlanValidationError:
    return PlanValidationError(message, code=code, details=details)


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _error("INTENT_NOT_OBJECT", f"{field_name} must be an object")
    if any(type(key) is not str for key in value):
        raise _error("INTENT_FIELDS_INVALID", f"{field_name} keys must be strings")
    return value


def _require_non_empty_string(value: Any, field_name: str, *, code: str) -> str:
    if type(value) is not str or not value:
        raise _error(code, f"{field_name} must be a non-empty string")
    return value


def _strict_fields(
    value: Mapping[str, Any],
    *,
    allowed: frozenset[str],
    field_name: str,
    code: str,
) -> None:
    extra = set(value) - allowed
    if extra:
        raise _error(
            code,
            f"{field_name} contains unsupported field(s): {', '.join(sorted(extra))}",
            fields=sorted(extra),
        )


def _canonical_source_identity(
    source: SourceRunContract,
    source_identity: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if source_identity is None:
        identity: dict[str, Any] = {"run_id": source.run_id}
        lineage = source.lineage
        if isinstance(lineage, Mapping):
            for key in ("node_ref", "node_hash", "forest_node_key"):
                if isinstance(lineage.get(key), str) and lineage[key]:
                    identity[key] = lineage[key]
        return identity

    identity = dict(_require_mapping(source_identity, "source_identity"))
    _strict_fields(
        identity,
        allowed=_IDENTITY_FIELDS,
        field_name="source_identity",
        code="SOURCE_IDENTITY_EXTRA_FIELDS",
    )
    if not identity:
        raise _error("SOURCE_IDENTITY_REQUIRED", "source_identity must not be empty")
    for key, value in identity.items():
        _require_non_empty_string(
            value,
            f"source_identity.{key}",
            code="SOURCE_IDENTITY_INVALID",
        )
    if identity.get("run_id") != source.run_id:
        raise _error(
            "SOURCE_IDENTITY_MISMATCH",
            "source_identity.run_id must match the resolved source run",
            source_run_id=source.run_id,
            identity_run_id=identity.get("run_id"),
        )
    return identity


def _resolve_target(
    source: SourceRunContract,
    *,
    requested_result_id: str | None,
    explicit_target: ComparisonTarget | Mapping[str, Any] | None,
) -> ComparisonTarget:
    if explicit_target is not None:
        try:
            target = (
                explicit_target
                if isinstance(explicit_target, ComparisonTarget)
                else ComparisonTarget.from_dict(explicit_target)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _error("COMPARISON_TARGET_INVALID", str(exc)) from exc
        if requested_result_id is not None and requested_result_id != target.result_id:
            raise _error(
                "COMPARISON_TARGET_MISMATCH",
                "requested_result_id does not match the exact target",
            )
        if target.result_id not in source.result_ids:
            raise _error(
                "COMPARISON_TARGET_UNKNOWN",
                "target result_id is not present in the resolved source",
            )
        return target

    resolved = resolve_comparison_target(source, requested_result_id)
    if isinstance(resolved, IntentValidationResult):
        raise _error(resolved.code, resolved.message or resolved.code, **dict(resolved.evidence))
    return resolved


def _source_context_fingerprint(
    source: SourceRunContract,
    value: str | None,
) -> str:
    if value is not None:
        return _require_non_empty_string(
            value,
            "source_context_fingerprint",
            code="SOURCE_CONTEXT_FINGERPRINT_REQUIRED",
        )
    run_inputs = source.run_inputs
    if isinstance(run_inputs, Mapping):
        declared = run_inputs.get("context_fingerprint")
        if isinstance(declared, str) and declared:
            return declared
    return sha256_canonical(
        {
            "source_run_id": source.run_id,
            "lineage": _thaw(source.lineage),
            "run_inputs": _thaw(source.run_inputs),
            "result_artifact": _thaw(source.result_artifact),
        }
    )


def _canonical_intent(
    intent: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any], str | None, Any]:
    intent = _require_mapping(intent, "intent")
    _strict_fields(
        intent,
        allowed=_INTENT_FIELDS,
        field_name="intent",
        code="INTENT_EXTRA_FIELDS",
    )
    action_id = _require_non_empty_string(
        intent.get("action_id"), "intent.action_id", code="ACTION_ID_REQUIRED"
    )
    patch = _require_mapping(intent.get("patch"), "intent.patch")
    requested_result_id = intent.get("requested_result_id")
    if requested_result_id is not None and type(requested_result_id) is not str:
        raise _error("COMPARISON_TARGET_INVALID", "requested_result_id must be a string")
    return action_id, patch, requested_result_id, intent.get("target")


def _validate_patch(action_id: str, patch: Mapping[str, Any]) -> str:
    if action_id != ACTION_ID or get_recovery_action(action_id) is None:
        raise _error("RECOVERY_ACTION_UNSUPPORTED", "unsupported analysis-loop action")
    if "entity_col" in patch:
        raise _error(
            "ENTITY_COL_GUESS_FORBIDDEN",
            "entity_col is a wire field and must never be supplied by intent",
        )
    if set(patch) != _PATCH_FIELDS:
        raise _error(
            "INTENT_PATCH_NOT_COVARIANCE_ONLY",
            "the patch must contain exactly covariance and cluster_variable",
            received_fields=sorted(str(field) for field in patch),
        )
    covariance = patch.get("covariance")
    if covariance != "clustered":
        raise _error(
            "COVARIANCE_DIRECTION_UNSUPPORTED",
            "only unadjusted to clustered covariance is supported",
            requested_covariance=covariance,
        )
    cluster_variable = patch.get("cluster_variable")
    if type(cluster_variable) is not str or not cluster_variable:
        raise _error("CLUSTER_VARIABLE_REQUIRED", "cluster_variable is required")
    return cluster_variable


def _plan_hash_payload(
    *,
    source_identity: Mapping[str, Any],
    target_identity: Mapping[str, Any],
    source_context_fingerprint: str,
    action_id: str,
    operation_id: str,
    canonical_patch: Mapping[str, Any],
    product_patch: Mapping[str, Any],
    wire_patch: Mapping[str, Any],
    canonical_patch_hash: str,
    invariants: Mapping[str, Any],
    strategy_version: str,
    policy_version: str,
    schema_version: str,
) -> dict[str, Any]:
    return {
        "source_identity": _thaw(source_identity),
        "target_identity": _thaw(target_identity),
        "source_context_fingerprint": source_context_fingerprint,
        "action_id": action_id,
        "operation_id": operation_id,
        "canonical_patch": _thaw(canonical_patch),
        "product_patch": _thaw(product_patch),
        "wire_patch": _thaw(wire_patch),
        "canonical_patch_hash": canonical_patch_hash,
        "invariants": _thaw(invariants),
        "strategy_version": strategy_version,
        "policy_version": policy_version,
        "schema_version": schema_version,
    }


@dataclass(frozen=True)
class PlanDiff:
    """Immutable semantic and wire plan for one exact analysis target."""

    action_id: str
    operation_id: str
    source_identity: Mapping[str, Any]
    target_identity: Mapping[str, Any]
    source_context_fingerprint: str
    canonical_patch: Mapping[str, Any]
    wire_patch: Mapping[str, Any]
    canonical_patch_hash: str
    plan_hash: str
    logical_key: str
    invariants: Mapping[str, Any]
    strategy_version: str
    policy_version: str
    schema_version: str
    product_patch: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "action_id",
            "operation_id",
            "source_context_fingerprint",
            "canonical_patch_hash",
            "plan_hash",
            "logical_key",
            "strategy_version",
            "policy_version",
            "schema_version",
        ):
            _require_non_empty_string(
                getattr(self, field_name),
                field_name,
                code="PLAN_FIELD_INVALID",
            )
        for field_name in (
            "source_identity",
            "target_identity",
            "canonical_patch",
            "wire_patch",
            "invariants",
        ):
            value = _require_mapping(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, _freeze(value, field_name))
        product_patch = self.product_patch
        if product_patch is None:
            product_patch = self.canonical_patch
        product_patch = _require_mapping(product_patch, "product_patch")
        object.__setattr__(self, "product_patch", _freeze(product_patch, "product_patch"))

    @property
    def source(self) -> Mapping[str, Any]:
        return self.source_identity

    @property
    def target(self) -> Mapping[str, Any]:
        return self.target_identity

    @property
    def hash(self) -> str:
        return self.plan_hash

    def _hash_payload(self) -> dict[str, Any]:
        return _plan_hash_payload(
            source_identity=self.source_identity,
            target_identity=self.target_identity,
            source_context_fingerprint=self.source_context_fingerprint,
            action_id=self.action_id,
            operation_id=self.operation_id,
            canonical_patch=self.canonical_patch,
            product_patch=self.product_patch or {},
            wire_patch=self.wire_patch,
            canonical_patch_hash=self.canonical_patch_hash,
            invariants=self.invariants,
            strategy_version=self.strategy_version,
            policy_version=self.policy_version,
            schema_version=self.schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._hash_payload(),
            "plan_hash": self.plan_hash,
            "logical_key": self.logical_key,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PlanDiff":
        if not isinstance(value, Mapping):
            raise TypeError("plan diff must be a mapping")
        required = {
            "action_id",
            "operation_id",
            "source_identity",
            "target_identity",
            "source_context_fingerprint",
            "canonical_patch",
            "product_patch",
            "wire_patch",
            "canonical_patch_hash",
            "plan_hash",
            "logical_key",
            "invariants",
            "strategy_version",
            "policy_version",
            "schema_version",
        }
        extra = set(value) - required
        missing = required - set(value)
        if extra:
            raise ValueError("extra plan diff field(s): " + ", ".join(sorted(extra)))
        if missing:
            raise KeyError("missing plan diff field(s): " + ", ".join(sorted(missing)))
        plan = cls(**{key: value[key] for key in required})
        expected_patch_hash = sha256_canonical(plan.canonical_patch)
        if plan.canonical_patch_hash != expected_patch_hash:
            raise ValueError("canonical patch hash does not match plan diff")
        if plan.plan_hash != sha256_canonical(plan._hash_payload()):
            raise ValueError("plan hash does not match plan diff")
        target_hash = plan.target_identity.get("target_hash")
        if not isinstance(target_hash, str):
            raise ValueError("plan target identity is missing target_hash")
        expected_key = plan_diff_logical_key(
            source_run_id=str(plan.source_identity.get("run_id")),
            source_context_fingerprint=plan.source_context_fingerprint,
            action_id=plan.action_id,
            canonical_patch_hash=plan.canonical_patch_hash,
            comparison_target_hash=target_hash,
            schema_version=plan.schema_version,
        )
        if plan.logical_key != expected_key:
            raise ValueError("plan logical key does not match plan diff")
        return plan


def build_plan_diff(
    *,
    source: SourceRunContract,
    intent: Mapping[str, Any],
    requested_result_id: str | None = None,
    target: ComparisonTarget | Mapping[str, Any] | None = None,
    cluster_values: Sequence[Any] | None = None,
    model_row_ids: Sequence[str] | None = None,
    cluster_preflight: ClusterPreflightResult | None = None,
    source_context_fingerprint: str | None = None,
    source_identity: Mapping[str, Any] | None = None,
    policy: OLSClusterPolicyV1 = ols_cluster_policy_v1,
    strategy_version: str = PLAN_STRATEGY_VERSION,
    schema_version: str = PLAN_DIFF_SCHEMA_VERSION,
) -> PlanDiff:
    """Resolve, preflight, and canonicalize one untrusted cluster intent.

    This function is pure with respect to Workbench state. It performs no
    proposal, operation, run, or filesystem writes.
    """

    if not isinstance(source, SourceRunContract):
        raise _error("SOURCE_CONTRACT_UNSUPPORTED", "source must be a SourceRunContract")
    action_id, patch, intent_target_id, intent_target = _canonical_intent(intent)
    if intent_target_id is not None:
        if requested_result_id is not None and requested_result_id != intent_target_id:
            raise _error("COMPARISON_TARGET_MISMATCH", "target ids do not match")
        requested_result_id = intent_target_id
    if intent_target is not None:
        if target is not None:
            raise _error("COMPARISON_TARGET_MISMATCH", "target was supplied twice")
        target = intent_target

    source_validation = validate_source_contract(source)
    if not source_validation.valid:
        raise _error(source_validation.code, source_validation.code, **dict(source_validation.evidence))
    resolved_target = _resolve_target(
        source,
        requested_result_id=requested_result_id,
        explicit_target=target,
    )
    cluster_variable = _validate_patch(action_id, patch)
    action = get_recovery_action(action_id)
    if action is None:
        raise _error("RECOVERY_ACTION_UNSUPPORTED", "unsupported analysis-loop action")
    if source.model != action.allowed_model or source.covariance != action.source_covariance:
        raise _error(
            "RECOVERY_ACTION_SOURCE_MISMATCH",
            "the action requires an OLS source with unadjusted covariance",
            model=source.model,
            covariance=source.covariance,
        )
    if not isinstance(policy, OLSClusterPolicyV1):
        raise _error("CLUSTER_POLICY_INVALID", "policy must be OLSClusterPolicyV1")

    if cluster_preflight is None:
        if cluster_values is None or model_row_ids is None:
            raise _error(
                "CLUSTER_PREFLIGHT_REQUIRED",
                "cluster_values and model_row_ids are required for preflight",
            )
        cluster_preflight = preflight_cluster_variable(
            source,
            cluster_variable=cluster_variable,
            cluster_values=cluster_values,
            model_row_ids=model_row_ids,
            policy=policy,
        )
    if not isinstance(cluster_preflight, ClusterPreflightResult):
        raise _error("CLUSTER_PREFLIGHT_INVALID", "cluster_preflight has an invalid type")
    if not cluster_preflight.valid:
        raise _error(cluster_preflight.code, cluster_preflight.code)
    if (
        cluster_preflight.cluster_variable != cluster_variable
        or cluster_preflight.wire_field != "entity_col"
    ):
        raise _error(
            "CLUSTER_PREFLIGHT_MISMATCH",
            "cluster preflight does not match the canonical cluster field",
        )

    canonical_patch = {
        "covariance": action.target_covariance,
        "cluster_variable": cluster_variable,
    }
    wire_patch = {
        "covariance": action.target_covariance,
        "entity_col": cluster_variable,
    }
    canonical_patch_hash = sha256_canonical(canonical_patch)
    invariants = {
        **_PLAN_INVARIANTS,
        **dict(cluster_preflight.invariants),
    }
    source_identity_value = _canonical_source_identity(source, source_identity)
    target_identity = resolved_target.to_dict()
    source_context = _source_context_fingerprint(source, source_context_fingerprint)
    policy_version = action.policy_version
    plan_hash_payload = _plan_hash_payload(
        source_identity=source_identity_value,
        target_identity=target_identity,
        source_context_fingerprint=source_context,
        action_id=action_id,
        operation_id=action.operation_id,
        canonical_patch=canonical_patch,
        product_patch=canonical_patch,
        wire_patch=wire_patch,
        canonical_patch_hash=canonical_patch_hash,
        invariants=invariants,
        strategy_version=strategy_version,
        policy_version=policy_version,
        schema_version=schema_version,
    )
    return PlanDiff(
        action_id=action_id,
        operation_id=action.operation_id,
        source_identity=source_identity_value,
        target_identity=target_identity,
        source_context_fingerprint=source_context,
        canonical_patch=canonical_patch,
        product_patch=canonical_patch,
        wire_patch=wire_patch,
        canonical_patch_hash=canonical_patch_hash,
        plan_hash=sha256_canonical(plan_hash_payload),
        logical_key=plan_diff_logical_key(
            source_run_id=source.run_id,
            source_context_fingerprint=source_context,
            action_id=action_id,
            canonical_patch_hash=canonical_patch_hash,
            comparison_target_hash=resolved_target.target_hash,
            schema_version=schema_version,
        ),
        invariants=invariants,
        strategy_version=strategy_version,
        policy_version=policy_version,
        schema_version=schema_version,
    )


def canonicalize_intent(**kwargs: Any) -> PlanDiff:
    """Compatibility spelling for callers that name the step canonicalization."""

    return build_plan_diff(**kwargs)


def normalize_intent(**kwargs: Any) -> PlanDiff:
    return build_plan_diff(**kwargs)


def confirmed_payload_hash(
    *,
    proposal_id: str,
    revision: int,
    operation_id: str,
    operation_version: str,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    changes: Mapping[str, Any],
) -> str:
    """Hash the exact proposal payload that a later confirmation must repeat."""

    return sha256_canonical(
        {
            "proposal_id": proposal_id,
            "revision": revision,
            "operation_id": operation_id,
            "operation_version": operation_version,
            "target": target,
            "preconditions": {
                key: value
                for key, value in preconditions.items()
                if key != "confirmed_payload_hash"
            },
            "changes": changes,
        }
    )


def _plan_target_hash(plan: PlanDiff) -> str | None:
    value = plan.target_identity.get("target_hash")
    return value if isinstance(value, str) else None


def _confirmation_preconditions(preconditions: Mapping[str, Any]) -> dict[str, Any]:
    """Remove the self-referential field before hashing or validating a payload."""

    filtered = {
        key: value
        for key, value in preconditions.items()
        if key != "confirmed_payload_hash"
    }
    analysis_loop = filtered.get("analysis_loop")
    if isinstance(analysis_loop, Mapping) and "confirmed_payload_hash" in analysis_loop:
        filtered["analysis_loop"] = {
            key: value
            for key, value in analysis_loop.items()
            if key != "confirmed_payload_hash"
        }
    return filtered


def _confirmation_hash_payload(
    plan: PlanDiff,
    *,
    proposal_id: str,
    revision: int,
    operation_version: str,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    changes: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the canonical hash input for a PlanDiff-bound proposal payload."""

    return {
        "plan": {
            "logical_key": plan.logical_key,
            "plan_hash": plan.plan_hash,
            "canonical_patch_hash": plan.canonical_patch_hash,
            "target_hash": _plan_target_hash(plan),
            "source_context_fingerprint": plan.source_context_fingerprint,
        },
        "proposal": {
            "proposal_id": proposal_id,
            "revision": revision,
            "operation_id": plan.operation_id,
            "operation_version": operation_version,
            "target": target,
            "preconditions": _confirmation_preconditions(preconditions),
            "changes": changes,
        },
    }


def confirmed_payload_hash_for_plan(
    plan: PlanDiff,
    *,
    proposal_id: str,
    revision: int,
    operation_version: str,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    changes: Mapping[str, Any],
) -> str:
    """Compute the hash of the exact proposal payload bound to ``plan``."""

    if not isinstance(plan, PlanDiff):
        raise TypeError("plan must be a PlanDiff")
    return sha256_canonical(
        _confirmation_hash_payload(
            plan,
            proposal_id=proposal_id,
            revision=revision,
            operation_version=operation_version,
            target=target,
            preconditions=preconditions,
            changes=changes,
        )
    )


def _raise_binding_error(
    code: str,
    message: str,
    **details: Any,
) -> None:
    raise PlanBindingError(message, code=code, details=details)


def validate_confirmation_binding(
    plan: PlanDiff,
    *,
    bound_plan_hash: str,
    bound_canonical_patch_hash: str,
    bound_target_hash: str,
    bound_source_context_fingerprint: str,
    current_source_context_fingerprint: str,
    confirmed_payload_hash: str,
    proposal_id: str,
    revision: int,
    operation_version: str,
    target: Mapping[str, Any],
    preconditions: Mapping[str, Any],
    changes: Mapping[str, Any],
) -> None:
    """Fail closed unless a confirmation still matches its immutable PlanDiff.

    The caller is responsible for resolving the current source run and active
    head.  This pure check only validates the plan, source-context, and exact
    confirmed-payload bindings needed before that execution path proceeds.
    """

    if not isinstance(plan, PlanDiff):
        raise TypeError("plan must be a PlanDiff")

    target_hash = _plan_target_hash(plan)
    plan_fields = {
        "plan_hash": plan.plan_hash,
        "canonical_patch_hash": plan.canonical_patch_hash,
        "target_hash": target_hash,
        "source_context_fingerprint": plan.source_context_fingerprint,
        "plan_logical_key": plan.logical_key,
    }
    bound_fields = {
        "plan_hash": bound_plan_hash,
        "canonical_patch_hash": bound_canonical_patch_hash,
        "target_hash": bound_target_hash,
        "source_context_fingerprint": bound_source_context_fingerprint,
    }
    stale_fields = {
        key: {"plan": plan_fields[key], "bound": value}
        for key, value in bound_fields.items()
        if value != plan_fields[key]
    }
    filtered_preconditions = _confirmation_preconditions(preconditions)
    for key in plan_fields:
        if key in filtered_preconditions and filtered_preconditions[key] != plan_fields[key]:
            stale_fields[key] = {
                "plan": plan_fields[key],
                "bound": filtered_preconditions[key],
            }
    analysis_loop_binding = filtered_preconditions.get("analysis_loop")
    if isinstance(analysis_loop_binding, Mapping):
        for key in plan_fields:
            if key in analysis_loop_binding and analysis_loop_binding[key] != plan_fields[key]:
                stale_fields[key] = {
                    "plan": plan_fields[key],
                    "bound": analysis_loop_binding[key],
                }
    if stale_fields:
        _raise_binding_error(
            "STALE_PLAN",
            "confirmation is bound to a different PlanDiff",
            fields=stale_fields,
        )

    if current_source_context_fingerprint != plan.source_context_fingerprint:
        _raise_binding_error(
            "CONTEXT_FINGERPRINT_MISMATCH",
            "current source context fingerprint does not match the PlanDiff",
            expected=plan.source_context_fingerprint,
            actual=current_source_context_fingerprint,
        )

    expected_payload_hash = confirmed_payload_hash_for_plan(
        plan,
        proposal_id=proposal_id,
        revision=revision,
        operation_version=operation_version,
        target=target,
        preconditions=filtered_preconditions,
        changes=changes,
    )
    if confirmed_payload_hash != expected_payload_hash:
        _raise_binding_error(
            "CONFIRMED_PAYLOAD_MISMATCH",
            "confirmed payload hash does not match the PlanDiff-bound payload",
            expected=expected_payload_hash,
            actual=confirmed_payload_hash,
        )


compute_confirmed_payload_hash = confirmed_payload_hash_for_plan
validate_plan_confirmation_binding = validate_confirmation_binding


__all__ = [
    "ACTION_ID",
    "OPERATION_ID",
    "PLAN_DIFF_SCHEMA_VERSION",
    "PLAN_SCHEMA_VERSION",
    "PLAN_STRATEGY_VERSION",
    "STRATEGY_VERSION",
    "PlanBuildError",
    "PlanBindingError",
    "PlanDiff",
    "PlanValidationError",
    "build_plan_diff",
    "canonicalize_intent",
    "confirmed_payload_hash",
    "confirmed_payload_hash_for_plan",
    "compute_confirmed_payload_hash",
    "normalize_intent",
    "validate_confirmation_binding",
    "validate_plan_confirmation_binding",
]
