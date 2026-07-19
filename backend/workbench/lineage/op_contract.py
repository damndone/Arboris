"""Node -> OperationContract resolution + layer-1 structural validation.

Manifest-driven, ZERO per-estimator branches. Addressing is by stage/op_type only,
never by label. Semantic validation (column existence, estimability, role conflicts)
is NOT done here — it stays in the pipeline's per-estimator validators."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..engine.capabilities import build_capabilities
from ..model_options import ModelOptionsError, canonicalize_model_options

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


def _model_type_options() -> list[dict[str, str]]:
    """Selectable model types for the `model_type` control (concrete models only —
    excludes the submit-time 'auto'). Built from the registered handlers so a new
    estimator shows up automatically."""
    caps = build_capabilities()
    return [
        {"value": e["key"], "label": e.get("label", e["key"])}
        for e in caps["model_types"]
        if e["key"] != "auto"
    ]


def _fill_model_type_options(params: list[dict]) -> list[dict]:
    """Inject the model list into the `model_type` select so the dropdown is usable.
    Copies (never mutates the shared capabilities params); a control that already
    declares its own options is left untouched."""
    options = _model_type_options()
    out: list[dict] = []
    for param in params:
        if param.get("key") == "model_type" and "options" not in param:
            out.append({**param, "options": options})
        else:
            out.append(param)
    return out


def _contract_for_model_type(op_type: str) -> OperationContract | None:
    entry = _model_entry(op_type)
    if entry is None or "params" not in entry or "schema_id" not in entry:
        return None
    return OperationContract(
        op_type=op_type,
        schema_id=entry["schema_id"],
        editable_schema=_fill_model_type_options(entry["params"]),
    )


def _model_op_type(manifest: dict) -> str | None:
    """Map a run's model to a capabilities model_type key (the op_type).

    The manifest's `effective_model_type` is an engine-internal id (e.g. "ols_robust"),
    NOT a capabilities key. `requested_model_type` IS a capabilities key for explicit
    runs ("ols"); for "auto" runs we normalize the effective id by longest-prefix match
    against the known capabilities keys (e.g. "ols_robust" -> "ols")."""
    routing = manifest.get("model_routing") or {}
    caps_keys = {e["key"] for e in build_capabilities()["model_types"] if e["key"] != "auto"}

    for candidate in (routing.get("requested_model_type"), routing.get("effective_model_type")):
        if candidate in caps_keys:
            return candidate

    effective = routing.get("effective_model_type") or ""
    for key in sorted(caps_keys, key=len, reverse=True):
        if effective == key or effective.startswith(f"{key}_"):
            return key
    return None


def resolve_operation_contract(*, stage: str | None, manifest: dict) -> OperationContract | None:
    """Resolve a graph node's OperationContract from its stage + the run manifest.
    Returns None for non-editable / unresolvable nodes (defensive)."""
    caps = build_capabilities()
    if stage not in caps.get("editable_stages", []):
        return None
    if stage == EDITABLE_STAGE_MODEL:
        op_type = _model_op_type(manifest)
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
        # model_options is a generic, server-normalized rerun transport. It
        # intentionally stays out of legacy UI editable schemas until a model
        # pack declares an actual object control for it.
        if key == "model_options":
            if not isinstance(value, dict):
                raise OpOverrideError("Value for 'model_options' must be an object")
            try:
                canonicalize_model_options(value)
            except ModelOptionsError as exc:
                raise OpOverrideError(exc.code) from exc
            continue
        if key == "model_options_binding":
            raise OpOverrideError("model_options_binding is server-managed")
        if key not in by_key:
            raise OpOverrideError(
                f"Unknown field {key!r} for op {contract.op_type!r} ({contract.schema_id})"
            )
        spec = by_key[key]
        if spec.get("kind") == "object" and not isinstance(value, dict):
            raise OpOverrideError(f"Value for {key!r} must be an object")
        options = spec.get("options")
        allowed = [o if not isinstance(o, dict) else o.get("value") for o in options or []]
        if options and spec.get("kind") in {"columns", "multiselect"} and isinstance(value, list):
            valid = all(item in allowed for item in value)
        else:
            valid = value in allowed if options else True
        if not valid:
            raise OpOverrideError(
                f"Value {value!r} not allowed for {key!r}; options={options}"
            )
