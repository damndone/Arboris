"""Node -> OperationContract resolution + layer-1 structural validation.

Manifest-driven, ZERO per-estimator branches. Addressing is by stage/op_type only,
never by label. Semantic validation (column existence, estimability, role conflicts)
is NOT done here — it stays in the pipeline's per-estimator validators."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..engine.capabilities import build_capabilities

EDITABLE_STAGE_MODEL = "model"


class OpOverrideError(ValueError):
    """A structural validation failure on op_overrides (unknown key / bad enum / type)."""


@dataclass(frozen=True)
class OperationContract:
    op_type: str
    schema_id: str
    editable_schema: list[dict[str, Any]]


def _model_entry(op_type: str) -> dict | None:
    caps = build_capabilities()
    for entry in caps["model_types"]:
        if entry["key"] == op_type:
            return entry
    return None


def _contract_for_model_type(op_type: str) -> OperationContract | None:
    entry = _model_entry(op_type)
    if entry is None or "params" not in entry or "schema_id" not in entry:
        return None
    return OperationContract(
        op_type=op_type,
        schema_id=entry["schema_id"],
        editable_schema=list(entry["params"]),
    )


def resolve_operation_contract(*, stage: str | None, manifest: dict) -> OperationContract | None:
    """Resolve a graph node's OperationContract from its stage + the run manifest.
    Returns None for non-editable / unresolvable nodes (defensive)."""
    caps = build_capabilities()
    if stage not in caps.get("editable_stages", []):
        return None
    if stage == EDITABLE_STAGE_MODEL:
        op_type = (manifest.get("model_routing") or {}).get("effective_model_type")
        if not op_type:
            return None
        return _contract_for_model_type(op_type)
    return None


def resolve_overrides_target(
    contract: OperationContract, op_overrides: dict
) -> OperationContract:
    """Guardrail #4 (schema-switching order): if op_overrides switches model_type,
    re-resolve the contract against the NEW model's schema. Otherwise return as-is."""
    new_model = op_overrides.get("model_type")
    if new_model and new_model != contract.op_type:
        switched = _contract_for_model_type(new_model)
        if switched is None:
            raise OpOverrideError(f"Unknown model_type override: {new_model!r}")
        return switched
    return contract


def validate_overrides(contract: OperationContract, op_overrides: dict) -> None:
    """Layer-1 structural validation against the (already target-resolved) contract:
    keys must be known; enum (options) values must be allowed. Deep semantics stay
    in the pipeline."""
    by_key = {p["key"]: p for p in contract.editable_schema}
    for key, value in op_overrides.items():
        if key not in by_key:
            raise OpOverrideError(
                f"Unknown field {key!r} for op {contract.op_type!r} ({contract.schema_id})"
            )
        spec = by_key[key]
        options = spec.get("options")
        if options and value not in [
            o if not isinstance(o, dict) else o.get("value") for o in options
        ]:
            raise OpOverrideError(
                f"Value {value!r} not allowed for {key!r}; options={options}"
            )
