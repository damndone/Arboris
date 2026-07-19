from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel

from ..model_options import ModelOptionsError, canonicalize_model_options


class ManualPatchValidationError(ValueError):
    pass


class ManualRerunPatchTarget(BaseModel):
    owner_run_id: str
    op_node_id: str
    node_hash: str


class ManualRerunPatchChange(BaseModel):
    field_id: str
    old_value: Any
    new_value: Any


class ManualRerunPatch(BaseModel):
    patch_id: str
    patch_source: Literal["MANUAL_EDIT"]
    source_context_fingerprint: str
    editable_schema_version: str
    target: ManualRerunPatchTarget
    changes: list[ManualRerunPatchChange]


def normalize_for_compare(value: Any, schema: dict[str, Any] | None = None) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return json.dumps(float(value), separators=(",", ":"))
    if isinstance(value, str) and schema and schema.get("trim") is True:
        return json.dumps(value.strip(), separators=(",", ":"))
    if isinstance(value, list):
        values = [normalize_for_compare(item) for item in value]
        if schema and schema.get("order_insensitive") is True:
            values = sorted(values)
        return json.dumps(values, separators=(",", ":"))
    if isinstance(value, dict):
        normalized = {
            key: json.loads(normalize_for_compare(value[key]))
            for key in sorted(value)
        }
        return json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def validate_manual_patch(
    *,
    patch: ManualRerunPatch,
    current_values: dict[str, Any],
    editable_schema: list[dict[str, Any]],
    editable_schema_version: str,
) -> dict[str, Any]:
    if patch.editable_schema_version != editable_schema_version:
        raise ManualPatchValidationError("EDITABLE_SCHEMA_STALE")
    if not patch.changes:
        raise ManualPatchValidationError("EMPTY_PATCH")

    schema_by_key = {
        str(item.get("key")): item for item in editable_schema if item.get("key")
    }
    seen: set[str] = set()
    overrides: dict[str, Any] = {}
    for change in patch.changes:
        if change.field_id in seen:
            raise ManualPatchValidationError("DUPLICATE_FIELD")
        seen.add(change.field_id)
        field_schema = schema_by_key.get(change.field_id)
        if not field_schema or field_schema.get("editable") is False:
            raise ManualPatchValidationError("FIELD_NOT_EDITABLE")
        if field_schema.get("kind") == "object" and not isinstance(change.new_value, dict):
            raise ManualPatchValidationError("INVALID_FIELD_VALUE")
        if change.field_id == "model_options":
            try:
                canonicalize_model_options(change.new_value)
            except ModelOptionsError as exc:
                raise ManualPatchValidationError(exc.code) from exc
        current_value = current_values.get(change.field_id)
        if normalize_for_compare(change.old_value, field_schema) != normalize_for_compare(
            current_value, field_schema
        ):
            raise ManualPatchValidationError("FIELD_VALUE_STALE")
        if normalize_for_compare(change.old_value, field_schema) == normalize_for_compare(
            change.new_value, field_schema
        ):
            raise ManualPatchValidationError("NOOP_PATCH")
        if field_schema.get("options"):
            allowed = [
                opt.get("value") if isinstance(opt, dict) else opt
                for opt in field_schema["options"]
            ]
            if field_schema.get("kind") in {"columns", "multiselect"} and isinstance(
                change.new_value, list
            ):
                valid = all(item in allowed for item in change.new_value)
            else:
                valid = change.new_value in allowed
            if not valid:
                raise ManualPatchValidationError("INVALID_FIELD_VALUE")
        overrides[change.field_id] = change.new_value

    if not overrides:
        raise ManualPatchValidationError("EMPTY_PATCH")
    return overrides
