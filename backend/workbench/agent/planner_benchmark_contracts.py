"""Typed local planner-evaluation and provider-boundary contracts.

This module is intentionally separate from the production Notebook planner.
The deterministic evaluator is a local correctness oracle: it never imports a
model adapter, reads provider configuration, opens a network connection, or
turns an unavailable case into an accepted proposal.  A future real-provider
benchmark consumes :class:`PlannerProviderRequestV1`; evaluator expectations
remain private to the benchmark runner.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

PLANNER_BENCHMARK_SCHEMA_VERSION = "planner-benchmark.v1"
DETERMINISTIC_EVALUATOR_VERSION = "deterministic-evaluator.v2"
_SOURCE_VALUES = frozenset({"deterministic", "provider"})
_OUTCOME_STATUS_VALUES = frozenset({"accepted", "refused", "unavailable", "error"})
_REFUSAL_REASONS = {
    "ambiguous": "ambiguous_request",
    "missing_required": "missing_required_information",
    "unsupported_causal": "unsupported_causal_claim",
    "prompt_injection": "unsafe_instruction",
}


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=lambda item: sorted(item) if isinstance(item, (set, frozenset, tuple)) else str(item),
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _case_payload(case: Any) -> dict[str, Any]:
    """Return the immutable case fields used by the benchmark identity."""

    return {
        "capability_id": case.capability_id,
        "capability_kind": case.capability_kind,
        "summary": case.summary,
        "route": case.route,
        "outer_operation_id": case.outer_operation_id,
        "step_operation_id": case.step_operation_id,
        "scenario": case.scenario,
        "seed": case.seed,
        "prompt": case.prompt,
        "source_columns": case.source_columns,
        "allowed_ids": sorted(case.allowed_ids),
        "required_binding_fields": case.required_binding_fields,
        "required_option_fields": case.required_option_fields,
    }


def _case_id(case: Any) -> str:
    return _sha256(_case_payload(case))[:32]


def _contract_payload(case: Any) -> dict[str, Any]:
    """Project only provider-visible declaration data, never evaluator labels."""

    return {
        "capability_id": case.capability_id,
        "capability_kind": case.capability_kind,
        "route": case.route,
        "outer_operation_id": case.outer_operation_id,
        "step_operation_id": case.step_operation_id,
        "source_columns": case.source_columns,
        "required_binding_fields": case.required_binding_fields,
        "required_option_fields": case.required_option_fields,
    }


@dataclass(frozen=True)
class PlannerCaseSnapshotV1:
    """Stable, non-secret identity of one generated planner case."""

    schema_version: str
    evaluator_version: str
    case_id: str
    seed: int
    surface: Literal["agent", "notebook"]
    scenario: str
    capability_id: str
    outer_operation_id: str
    step_operation_id: str | None
    prompt_sha256: str
    source_columns: tuple[str, ...]
    allowed_ids_sha256: str
    contract_digest: str
    input_sha256: str

    @classmethod
    def from_case(cls, case: Any) -> "PlannerCaseSnapshotV1":
        payload = _case_payload(case)
        contract = _contract_payload(case)
        return cls(
            schema_version=PLANNER_BENCHMARK_SCHEMA_VERSION,
            evaluator_version=DETERMINISTIC_EVALUATOR_VERSION,
            case_id=_case_id(case),
            seed=case.seed,
            surface="notebook" if case.route == "composition" else "agent",
            scenario=case.scenario,
            capability_id=case.capability_id,
            outer_operation_id=case.outer_operation_id,
            step_operation_id=case.step_operation_id,
            prompt_sha256=_sha256(case.prompt),
            source_columns=tuple(case.source_columns),
            allowed_ids_sha256=_sha256(sorted(case.allowed_ids)),
            contract_digest=_sha256(contract),
            input_sha256=_sha256(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evaluator_version": self.evaluator_version,
            "case_id": self.case_id,
            "seed": self.seed,
            "surface": self.surface,
            "scenario": self.scenario,
            "capability_id": self.capability_id,
            "outer_operation_id": self.outer_operation_id,
            "step_operation_id": self.step_operation_id,
            "prompt_sha256": self.prompt_sha256,
            "source_columns": list(self.source_columns),
            "allowed_ids_sha256": self.allowed_ids_sha256,
            "contract_digest": self.contract_digest,
            "input_sha256": self.input_sha256,
        }


@dataclass(frozen=True)
class PlannerEvaluatorIntentV1:
    """Evaluator-only expectation; it must never be sent to a provider."""

    schema_version: str
    case_id: str
    expected_status: Literal["accepted", "refused"]
    expected_reason_code: str | None
    expected_outer_operation_id: str | None
    expected_step_operation_id: str | None
    evaluator_digest: str

    @classmethod
    def from_case(
        cls,
        case: Any,
        *,
        snapshot: PlannerCaseSnapshotV1 | None = None,
    ) -> "PlannerEvaluatorIntentV1":
        snapshot = snapshot or PlannerCaseSnapshotV1.from_case(case)
        reason = _REFUSAL_REASONS.get(case.scenario)
        expected_status: Literal["accepted", "refused"] = (
            "refused" if reason is not None else "accepted"
        )
        payload = {
            "case_id": snapshot.case_id,
            "expected_status": expected_status,
            "expected_reason_code": reason,
            "expected_outer_operation_id": (
                case.outer_operation_id if reason is None else None
            ),
            "expected_step_operation_id": (
                case.step_operation_id if reason is None else None
            ),
        }
        return cls(
            schema_version=PLANNER_BENCHMARK_SCHEMA_VERSION,
            case_id=snapshot.case_id,
            expected_status=expected_status,
            expected_reason_code=reason,
            expected_outer_operation_id=payload["expected_outer_operation_id"],
            expected_step_operation_id=payload["expected_step_operation_id"],
            evaluator_digest=_sha256(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "expected_status": self.expected_status,
            "expected_reason_code": self.expected_reason_code,
            "expected_outer_operation_id": self.expected_outer_operation_id,
            "expected_step_operation_id": self.expected_step_operation_id,
            "evaluator_digest": self.evaluator_digest,
        }


@dataclass(frozen=True)
class PlannerProviderRequestV1:
    """Blind provider request; v2 wire removes target-specific answer hints.

    Case/contract digests are opaque audit identifiers, not capability selectors.
    Providers must use their complete live catalog, never evaluator target fields.
    """

    schema_version: str
    case_id: str
    surface: Literal["agent", "notebook"]
    prompt: str
    source_columns: tuple[str, ...]
    contract_digest: str
    input_sha256: str

    @classmethod
    def from_case(
        cls,
        case: Any,
        *,
        snapshot: PlannerCaseSnapshotV1 | None = None,
        intent: PlannerEvaluatorIntentV1 | None = None,
    ) -> "PlannerProviderRequestV1":
        # ``intent`` is accepted only to make the trust boundary explicit at
        # call sites. It is intentionally not stored or projected.
        del intent
        snapshot = snapshot or PlannerCaseSnapshotV1.from_case(case)
        return cls(
            schema_version="planner-provider-request.v2",
            case_id=snapshot.case_id,
            surface=snapshot.surface,
            prompt=case.prompt,
            source_columns=tuple(case.source_columns),
            contract_digest=snapshot.contract_digest,
            input_sha256=snapshot.input_sha256,
        )

    def to_provider_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "surface": self.surface,
            "prompt": self.prompt,
            "source_columns": list(self.source_columns),
            "contract_digest": self.contract_digest,
            "input_sha256": self.input_sha256,
        }


@dataclass(frozen=True)
class ProviderCallReceiptV1:
    """Observation made by the benchmark driver, not a provider self-report."""

    schema_version: str
    called: bool
    call_count: int
    driver: str
    request_digest: str | None = None
    error_code: str | None = None
    observed_by: str = "benchmark-driver"

    def __post_init__(self) -> None:
        if self.schema_version != PLANNER_BENCHMARK_SCHEMA_VERSION:
            raise ValueError("provider receipt schema_version is unsupported")
        if type(self.call_count) is not int or self.call_count < 0:
            raise ValueError("call_count must be a non-negative integer")
        if not isinstance(self.driver, str) or not self.driver.strip():
            raise ValueError("driver is required")
        if not self.called and self.call_count != 0:
            raise ValueError("call_count must be zero when called is false")
        if self.called and self.call_count == 0:
            raise ValueError("call_count must be positive when called is true")

    @classmethod
    def not_called(cls, *, driver: str = "deterministic-evaluator") -> "ProviderCallReceiptV1":
        return cls(
            schema_version=PLANNER_BENCHMARK_SCHEMA_VERSION,
            called=False,
            call_count=0,
            driver=driver,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "called": self.called,
            "call_count": self.call_count,
            "driver": self.driver,
            "request_digest": self.request_digest,
            "error_code": self.error_code,
            "observed_by": self.observed_by,
        }


@dataclass(frozen=True)
class PlannerOutcomeV1:
    """A scoreable outcome with source and provider-call evidence attached."""

    schema_version: str
    case_id: str
    input_sha256: str
    source: Literal["deterministic", "provider"]
    outcome: Mapping[str, Any]
    provider_receipt: ProviderCallReceiptV1

    def __post_init__(self) -> None:
        if self.schema_version != PLANNER_BENCHMARK_SCHEMA_VERSION:
            raise ValueError("planner outcome schema_version is unsupported")
        if self.source not in _SOURCE_VALUES:
            raise ValueError("planner outcome source is unsupported")
        if not isinstance(self.outcome, Mapping):
            raise ValueError("planner outcome must be an object")
        status = self.outcome.get("status")
        if status not in _OUTCOME_STATUS_VALUES:
            raise ValueError("planner outcome status is unsupported")
        if self.source == "deterministic" and self.provider_receipt.called:
            raise ValueError("deterministic outcome cannot claim a provider call")

    @property
    def status(self) -> str:
        return str(self.outcome.get("status"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "input_sha256": self.input_sha256,
            "source": self.source,
            "outcome": dict(self.outcome),
            "provider_receipt": self.provider_receipt.to_dict(),
        }


class _DeterministicContractGap(ValueError):
    """Raised when a live declaration cannot be safely projected locally."""


_TYPE_MAP = {
    "string": "string",
    "str": "string",
    "list": "array",
    "array": "array",
    "object": "object",
    "mapping": "object",
    "dict": "object",
    "nullable_string": ["string", "null"],
    "number": "number",
    "float": "number",
    "integer": "integer",
    "int": "integer",
    "boolean": "boolean",
    "bool": "boolean",
}


def _live_schema_for_case(case: Any) -> Mapping[str, Any]:
    """Resolve the exact live declaration selected by the evaluation case."""

    if case.route == "composition":
        from .workflow_contracts import workflow_step_vocabulary

        step_id = case.step_operation_id
        declarations = workflow_step_vocabulary().get("step_operations", {})
        declaration = declarations.get(step_id)
        if not isinstance(declaration, Mapping):
            raise _DeterministicContractGap(
                f"workflow step declaration is unavailable: {step_id!r}"
            )
        return _declaration_to_schema(declaration, case=case)

    from .operations import OperationRegistry, UnknownOperationError

    try:
        definition = OperationRegistry().require(case.outer_operation_id)
    except (KeyError, UnknownOperationError, ValueError) as exc:
        raise _DeterministicContractGap(
            f"operation declaration is unavailable: {case.outer_operation_id!r}"
        ) from exc
    schema = definition.editable_schema or definition.proposal_schema
    if not isinstance(schema, Mapping):
        raise _DeterministicContractGap(
            f"operation declaration has no object schema: {case.outer_operation_id!r}"
        )
    return schema


def _declaration_to_schema(
    declaration: Mapping[str, Any], *, case: Any | None = None
) -> dict[str, Any]:
    """Project a workflow declaration's field vocabulary into JSON-schema form."""

    if isinstance(declaration.get("properties"), Mapping):
        return dict(declaration)

    fields: list[str] = []
    for field_name in (
        *(declaration.get("required", ()) or ()),
        *(declaration.get("fields", {}) or {}).keys(),
        *(declaration.get("field_types", {}) or {}).keys(),
        *(declaration.get("field_schemas", {}) or {}).keys(),
        *(declaration.get("field_enums", {}) or {}).keys(),
    ):
        if str(field_name) not in fields:
            fields.append(str(field_name))

    field_types = declaration.get("field_types", {})
    field_schemas = declaration.get("field_schemas", {})
    field_enums = declaration.get("field_enums", {})
    properties: dict[str, Any] = {}
    for field_name in fields:
        schema = dict(field_schemas.get(field_name, {})) if isinstance(field_schemas, Mapping) else {}
        declared_type = field_types.get(field_name) if isinstance(field_types, Mapping) else None
        if declared_type is not None:
            schema.setdefault("type", _TYPE_MAP.get(str(declared_type), declared_type))
        values = field_enums.get(field_name) if isinstance(field_enums, Mapping) else None
        if isinstance(values, (list, tuple)):
            schema["enum"] = list(values)
        properties[field_name] = schema

    required = list(declaration.get("required", ()) or ())
    if case is not None and case.required_binding_fields:
        if "column_bindings" not in required:
            required.append("column_bindings")
        if "input_mode" in properties and "input_mode" not in required:
            required.append("input_mode")
    if case is not None and case.required_option_fields:
        if "options" not in required:
            required.append("options")
        if "input_mode" in properties and "input_mode" not in required:
            required.append("input_mode")
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def _fixture_string(case: Any, *, binding: bool, field_name: str | None) -> str:
    """Return a fixed, declaration-safe string without inventing a data name."""

    if binding:
        if not case.source_columns:
            raise _DeterministicContractGap("case declares no source columns for a binding")
        return str(case.source_columns[0])
    if field_name == "step_id" and "step_1" in case.allowed_ids:
        return "step_1"
    if field_name in {"run_id", "node_ref", "artifact_id"}:
        for identity in ("run:eval", "node:source", "artifact:source"):
            if identity in case.allowed_ids:
                return identity
        raise _DeterministicContractGap(
            f"no fixed fixture identity is allowed for {field_name!r}"
        )
    if field_name == "operation_id":
        for operation_id in (
            case.step_operation_id,
            case.outer_operation_id,
            case.capability_id,
        ):
            if operation_id and operation_id in case.allowed_ids:
                return operation_id
        raise _DeterministicContractGap("no declared operation identity is allowed")
    return "fixture"


def _schema_value(
    schema: Mapping[str, Any],
    case: Any,
    *,
    binding: bool = False,
    field_name: str | None = None,
) -> Any:
    """Build one value from declared schema constraints and fixed fixtures."""

    if "const" in schema:
        return schema["const"]
    for alternatives_key in ("oneOf", "anyOf"):
        alternatives = schema.get(alternatives_key)
        if isinstance(alternatives, list):
            last_error: Exception | None = None
            for alternative in alternatives:
                if isinstance(alternative, Mapping):
                    try:
                        return _schema_value(
                            alternative,
                            case,
                            binding=binding,
                            field_name=field_name,
                        )
                    except _DeterministicContractGap as exc:
                        last_error = exc
            raise _DeterministicContractGap(
                f"no {alternatives_key} branch can be synthesized"
            ) from last_error
    if "default" in schema:
        return schema["default"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    expected = schema.get("type")
    if isinstance(expected, list):
        expected = next((item for item in expected if item != "null"), None)
    if expected is None:
        if not schema:
            return {}
        raise _DeterministicContractGap("schema has no usable type, enum, const, or default")
    if expected == "string":
        value = _fixture_string(case, binding=binding, field_name=field_name)
        minimum = int(schema.get("minLength", 0))
        if len(value) < minimum:
            raise _DeterministicContractGap("fixed fixture string is shorter than minLength")
        return value
    if expected == "boolean":
        return False
    if expected == "integer":
        minimum = schema.get("minimum", 0)
        value = int(minimum) if isinstance(minimum, (int, float)) else 0
        if schema.get("exclusiveMinimum") is True:
            value += 1
        return value
    if expected == "number":
        minimum = schema.get("minimum", 0)
        value = float(minimum) if isinstance(minimum, (int, float)) else 0.0
        if schema.get("exclusiveMinimum") is True:
            value += 1.0
        return value
    if expected == "array":
        minimum = int(schema.get("minItems", 0))
        item_schema = schema.get("items")
        if not isinstance(item_schema, Mapping):
            item_schema = {"type": "string"}
        return [
            _schema_value(item_schema, case, binding=binding)
            for _ in range(minimum)
        ]
    if expected == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            properties = {}
        required = schema.get("required", ())
        if not isinstance(required, (list, tuple)):
            required = ()
        result: dict[str, Any] = {}
        for field_name in required:
            field_schema = properties.get(field_name)
            if not isinstance(field_schema, Mapping):
                raise _DeterministicContractGap(
                    f"required field has no schema: {field_name!r}"
                )
            result[str(field_name)] = _schema_value(
                field_schema,
                case,
                binding=binding or str(field_name) in {"column_bindings", "columns"},
                field_name=str(field_name),
            )
        return result
    raise _DeterministicContractGap(f"unsupported declared schema type: {expected!r}")


def _synthesize_proposal(case: Any) -> dict[str, Any]:
    schema = _live_schema_for_case(case)
    if case.route == "composition":
        if not case.step_operation_id:
            raise _DeterministicContractGap("composition case has no selected step declaration")
        step_schema = schema
        spec = _schema_value(step_schema, case)
        return {
            "operation_id": case.outer_operation_id,
            "changes": {
                "steps": [
                    {
                        "step_id": "step_1",
                        "operation_id": case.step_operation_id,
                        "spec": spec,
                    }
                ]
            },
        }
    return {
        "operation_id": case.outer_operation_id,
        "changes": _schema_value(schema, case),
    }


class DeterministicPlannerEvaluatorV1:
    """Generate typed local proposals from live operation declarations."""

    def evaluate(self, case: Any) -> PlannerOutcomeV1:
        snapshot = PlannerCaseSnapshotV1.from_case(case)
        receipt = ProviderCallReceiptV1.not_called()
        if case.scenario in _REFUSAL_REASONS:
            outcome: dict[str, Any] = {
                "status": "refused",
                "reason_code": _REFUSAL_REASONS[case.scenario],
                "message": "The local deterministic baseline requires a safer, clearer request.",
            }
        else:
            try:
                proposal = _synthesize_proposal(case)
                candidate = {"status": "accepted", "proposal": proposal}
                outcome = candidate
            except _DeterministicContractGap as exc:
                outcome = {
                    "status": "unavailable",
                    "reason_code": "DETERMINISTIC_CONTRACT_GAP",
                    "message": "The live declaration cannot be safely synthesized by the local evaluator.",
                    "contract_gap": str(exc),
                }
        return PlannerOutcomeV1(
            schema_version=PLANNER_BENCHMARK_SCHEMA_VERSION,
            case_id=snapshot.case_id,
            input_sha256=snapshot.input_sha256,
            source="deterministic",
            outcome=outcome,
            provider_receipt=receipt,
        )


__all__ = [
    "DETERMINISTIC_EVALUATOR_VERSION",
    "PLANNER_BENCHMARK_SCHEMA_VERSION",
    "DeterministicPlannerEvaluatorV1",
    "PlannerCaseSnapshotV1",
    "PlannerEvaluatorIntentV1",
    "PlannerOutcomeV1",
    "PlannerProviderRequestV1",
    "ProviderCallReceiptV1",
]
