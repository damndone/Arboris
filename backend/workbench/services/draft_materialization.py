"""Domain constructors for Notebook-owned Pipeline Draft materialization.

The HTTP draft routes and the Notebook materializer must create the same draft
shape.  These functions contain no request models and never execute a draft;
they only validate the source identity and persist a reviewable Draft.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from ..graph_store import GraphStore
from ..lineage.node_index import NODE_INDEX_FILENAME
from ..lineage.node_write_validation import NodeWriteOperationRequestV1, validate_rerun_operation_target
from ..lineage.op_contract import resolve_operation_contract
from ..lineage.pipeline_drafts import (
    PipelineDraftStore,
    StoredDraft,
    compute_executable_draft_hash,
    new_draft_id,
    schema_hash,
    utc_now,
    validate_draft_id,
)
from ..lineage.run_inputs import read_run_inputs
from ..lineage.upload_store import verify_upload
from ..repository.run_repository import _read_manifest, _resolve_project_runs_dir, _resolve_run_root
from ..services.run_service import _STRUCTURAL_FOCAL_FAMILIES, _parse_focal_x, parse_column_selector
from ..artifacts import read_json
from pydantic import ValidationError


_TERMINAL_RUN_STATUSES = {
    "completed", "failed", "cancelled", "interrupted", "partial", "blocked",
}

GENESIS_SELECTOR_SCHEMA_ID = "genesis.selector@v1"


def _genesis_column_kind(key: str, raw_kind: str | None) -> str:
    """Return the wire shape used by the Genesis model-parameter editor."""

    if raw_kind in {"columns", "multiselect"}:
        return "columns"
    return "column"


def _recipe_leaf_schema(
    field: Mapping[str, Any],
    columns: tuple[str, ...],
    *,
    server_owned: bool = False,
) -> dict[str, Any]:
    """Project one declared Recipe field without flattening its wire path."""

    property_schema: dict[str, Any] = {}
    kind = field.get("kind")
    declared_type = field.get("type")
    if kind in {"column", "column_name"}:
        property_schema["type"] = "string"
        property_schema["column_options"] = list(columns)
    elif kind == "positive_integer":
        property_schema["type"] = "integer"
        property_schema["minimum"] = 1
    elif kind == "integer":
        property_schema["type"] = "integer"
    elif kind == "boolean":
        property_schema["type"] = "boolean"
    elif declared_type in {"string", "integer", "number", "boolean", "array", "object"}:
        property_schema["type"] = declared_type

    allowed_values = field.get("allowed_values")
    enum_values = field.get("enum", allowed_values)
    if isinstance(enum_values, list) and enum_values:
        property_schema["enum"] = list(enum_values)
    for bound in ("minimum", "maximum"):
        value = field.get(bound)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            property_schema[bound] = value
    if field.get("nullable") is True:
        property_schema["nullable"] = True
    if server_owned or field.get("agent_editable") is False:
        property_schema["server_owned"] = True
    return property_schema


def _insert_recipe_field(
    schema: dict[str, Any],
    path: str,
    field: Mapping[str, Any],
    columns: tuple[str, ...],
    *,
    server_owned: bool = False,
) -> None:
    """Insert a dotted declaration into a nested object schema."""

    segments = [segment for segment in path.split(".") if segment]
    if not segments:
        return
    cursor = schema
    for segment in segments[:-1]:
        properties = cursor.setdefault("properties", {})
        existing = properties.get(segment)
        if existing is None:
            existing = {
                "type": "object",
                "required": [],
                "properties": {},
                "additionalProperties": False,
            }
            properties[segment] = existing
        elif existing.get("type") != "object":
            raise ValueError(f"Recipe field path conflicts at {segment!r}")
        cursor = existing
    leaf_name = segments[-1]
    properties = cursor.setdefault("properties", {})
    properties[leaf_name] = _recipe_leaf_schema(
        field,
        columns,
        server_owned=server_owned,
    )
    if field.get("required") is True:
        required = cursor.setdefault("required", [])
        if leaf_name not in required:
            required.append(leaf_name)


def _recipe_option_schema(model_type: str, columns: tuple[str, ...]) -> dict[str, Any]:
    from ..agent.recipe_contracts import recipe_contract_for_model_type

    contract = recipe_contract_for_model_type(model_type)
    if contract is None:
        return {}
    raw_fields = (contract.parameter_vocabulary or {}).get("fields", {})
    if isinstance(raw_fields, list):
        fields = {
            str(item.get("path")): item
            for item in raw_fields
            if isinstance(item, Mapping) and item.get("path")
        }
    elif isinstance(raw_fields, Mapping):
        fields = {
            str(name): value
            for name, value in raw_fields.items()
            if isinstance(value, Mapping)
        }
    else:
        fields = {}
    schema: dict[str, Any] = {
        "type": "object",
        "required": [],
        "properties": {},
        "additionalProperties": False,
    }
    for name, field in fields.items():
        _insert_recipe_field(schema, name, field, columns)
    for name in contract.source_option_fields:
        if name not in schema["properties"]:
            _insert_recipe_field(
                schema,
                name,
                {"kind": "column", "required": True},
                columns,
            )
        required = schema.setdefault("required", [])
        if name not in required:
            required.append(name)
    for name in contract.server_owned_option_fields:
        _insert_recipe_field(
            schema,
            name,
            {"type": "string", "required": True},
            columns,
            server_owned=True,
        )
    return schema


def _family_option_schema(
    model_type: str,
    columns: tuple[str, ...],
    *,
    covariance_options: tuple[str, ...] = (),
    exposes_covariance: bool = False,
) -> dict[str, Any]:
    from ..agent.workflow_contracts import model_family_contract

    contract = model_family_contract(model_type)
    properties: dict[str, dict[str, Any]] = {}
    for name in contract.model_options_fields:
        # Do not invent a scalar type for a family option whose contract
        # validator has not declared one.  The family validator remains the
        # source of truth; an invented string type would reject valid arrays
        # and numbers before that validator can inspect them.
        property_schema: dict[str, Any] = {}
        if name in contract.model_options_column_fields:
            property_schema = {"type": "string", "column_options": list(columns)}
        elif name == "random_slope":
            property_schema = {"type": "boolean"}
        elif name in {"maxiter", "bootstrap_reps", "random_state"}:
            property_schema = {"type": "integer"}
        properties[name] = property_schema
    if exposes_covariance and covariance_options:
        # OLS keeps the human-facing top-level covariance control for legacy
        # runs, while the typed Agent envelope stores the same declaration
        # under model_options. The live capability manifest owns the values.
        properties.setdefault(
            "covariance",
            {"type": "string", "enum": list(covariance_options)},
        )
    return {
        "type": "object",
        "required": list(contract.model_options_required_fields),
        "properties": properties,
        "additionalProperties": False,
    }


def _family_wire_projection(
    model_type: str,
    family: Any,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Probe the declared family builder to discover its persisted wire keys."""

    if not family.builds_native_params:
        return {}, {}
    family_spec: dict[str, Any] = {
        "model_family": model_type,
        "branches": [{"branch_id": "schema_probe", "outcome": "__outcome__", "predictors": []}],
    }
    for field_name in family.context_spec_fields:
        if field_name in {"iv_endog", "iv_instruments"}:
            family_spec[field_name] = [f"__{field_name}__"]
        elif field_name == "did_mode":
            family_spec[field_name] = "cohort"
        else:
            family_spec[field_name] = f"__{field_name}__"
    try:
        projected = family.build_model_params(
            family_spec,
            {"outcome": "__outcome__"},
            [],
            "unadjusted",
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"MODEL_FAMILY_SCHEMA_PROJECTION_FAILED: {model_type}"
        ) from exc
    if not isinstance(projected, Mapping):
        raise ValueError(f"MODEL_FAMILY_SCHEMA_PROJECTION_FAILED: {model_type}")
    aliases: dict[str, list[str]] = {}
    for field_name in family.context_spec_fields:
        source_value = family_spec[field_name]
        matching = [
            str(key)
            for key, value in projected.items()
            if str(key) != field_name and value == source_value
        ]
        if matching:
            aliases[field_name] = sorted(matching)
    return dict(projected), aliases


def _family_context_wire_kind(
    field_name: str,
    family: Any,
    projected_params: Mapping[str, Any],
    projected_aliases: Mapping[str, list[str]],
) -> str:
    """Derive a context control's scalar/list shape from its family builder."""

    if field_name not in family.column_spec_fields:
        return "column"
    candidate_keys = [field_name, *projected_aliases.get(field_name, [])]
    if any(isinstance(projected_params.get(key), list) for key in candidate_keys):
        return "columns"
    return "column"


def _genesis_model_editor_schema(
    model_type: str | None,
    columns: tuple[str, ...],
) -> tuple[str, list[dict[str, Any]]]:
    """Build the server-owned two-phase Genesis editor schema.

    The model selector and field vocabulary come from the live capability
    manifest. Family and Recipe contracts add roles that the generic manifest
    intentionally does not own. Column options are projected from the current
    table node, so a schema hash always identifies both the selected family and
    the source columns it is allowed to read.
    """

    from ..agent.recipe_contracts import recipe_contract_for_model_type
    from ..agent.workflow_contracts import (
        DID_MODE_VALUES,
        WORKFLOW_SPLIT_KINDS,
        model_family_contract,
    )
    from ..engine.cs_attgt import (
        CS_BASE_PERIOD_VALUES,
        CS_CONTROL_GROUP_VALUES,
        CS_EST_METHOD_VALUES,
    )
    from ..engine.capabilities import build_capabilities

    manifest = build_capabilities()
    model_entries = {
        str(entry["key"]): entry
        for entry in manifest.get("model_types", [])
        if isinstance(entry, Mapping) and entry.get("key")
    }
    model_options = sorted(model_entries)
    selected = model_type or "auto"
    if selected not in model_options:
        raise ValueError(f"MODEL_TYPE_UNSUPPORTED: {selected}")
    if model_type is None:
        return GENESIS_SELECTOR_SCHEMA_ID, [
            {
                "key": "model_type",
                "kind": "select",
                "label": "Model",
                "required": True,
                "options": model_options,
            },
            {
                "key": "y",
                "kind": "column",
                "label": "Dependent variable (y)",
                "required": True,
                "options": list(columns),
            },
            {
                "key": "x",
                "kind": "columns",
                "label": "Regressors (X)",
                "required": True,
                "options": list(columns),
            },
        ]

    entry = model_entries[selected]
    recipe = recipe_contract_for_model_type(selected)
    family = None if recipe is not None else model_family_contract(selected)
    projected_params, projected_aliases = (
        _family_wire_projection(selected, family)
        if family is not None
        else ({}, {})
    )
    controls: dict[str, dict[str, Any]] = {}

    def add(control: Mapping[str, Any]) -> None:
        key = str(control.get("key") or "")
        if not key:
            return
        current = controls.get(key)
        if current is None:
            controls[key] = dict(control)
        else:
            merged = {**current, **dict(control)}
            if current.get("required") is True or control.get("required") is True:
                merged["required"] = True
            controls[key] = merged

    for raw in entry.get("params") or ():
        if not isinstance(raw, Mapping):
            continue
        control = dict(raw)
        key = str(control.get("key") or "")
        if key == "model_type":
            control.update(required=True, options=model_options)
        elif key == "model_options":
            control["kind"] = "object"
            control.pop("options", None)
            control["schema"] = (
                _recipe_option_schema(selected, columns)
                if recipe is not None
                else _family_option_schema(
                    selected,
                    columns,
                    covariance_options=tuple(
                        str(item.get("key"))
                        for item in manifest.get("covariance_options", [])
                        if isinstance(item, Mapping) and item.get("key")
                    ),
                    exposes_covariance=bool(
                        family is not None
                        and family.allows_covariance
                        and any(
                            isinstance(item, Mapping)
                            and item.get("key") == "covariance"
                            for item in (entry.get("params") or ())
                        )
                    ),
                )
            )
        elif key == "x" and family is not None:
            control["required"] = bool(family.requires_nonempty_predictors)
        elif family is not None and key in family.column_spec_fields:
            control["options"] = list(columns)
            control["kind"] = _family_context_wire_kind(
                key,
                family,
                projected_params,
                projected_aliases,
            )
        elif key in {"x", "focal_x"} or control.get("kind") == "columns":
            control["options"] = list(columns)
            control["kind"] = _genesis_column_kind(key, str(control.get("kind") or ""))
        elif key.endswith("_weight") or key.endswith("_col"):
            control["options"] = list(columns)
            control["kind"] = "column"
        add(control)

    if recipe is None:
        add(
            {
                "key": "y",
                "kind": "column",
                "label": "Dependent variable (y)",
                "required": True,
                "options": list(columns),
            }
        )
        add(
            {
                "key": "x",
                "kind": "columns",
                "label": "Regressors (X)",
                "required": bool(family is None or family.requires_nonempty_predictors),
                "options": list(columns),
            }
        )

    if family is not None:
        for field_name in family.context_spec_fields:
            # Native family contracts own the persisted wire names. Legacy DID
            # aliases are only a UI compatibility surface for the non-native
            # TWFE family; projecting them onto CS/SA/DCDH made a valid
            # Notebook materialization look incomplete to the Draft schema.
            key = field_name
            add(
                {
                    "key": key,
                    "kind": (
                        "select"
                        if key == "did_mode"
                        else _family_context_wire_kind(
                            field_name,
                            family,
                            projected_params,
                            projected_aliases,
                        )
                    ),
                    "label": key,
                    "required": field_name in family.required_spec_fields,
                    "options": (
                        list(DID_MODE_VALUES)
                        if key == "did_mode"
                        else list(columns)
                    ),
                }
            )
        for field_name in family.model_options_column_fields:
            # The nested model_options schema owns these values. Do not expose
            # a duplicate flat control that could be mistaken for an override.
            continue

        for source_field, aliases in projected_aliases.items():
            if source_field in controls:
                controls[source_field]["satisfied_by"] = aliases
            for alias in aliases:
                if alias in controls:
                    controls[alias]["server_projection_of"] = source_field
                    continue
                projected_value = projected_params.get(alias)
                if alias == "did_mode":
                    alias_control = {
                        "key": alias,
                        "kind": "select",
                        "label": alias,
                        "required": False,
                        "options": list(DID_MODE_VALUES),
                        "server_projection_of": source_field,
                    }
                elif isinstance(projected_value, list):
                    alias_control = {
                        "key": alias,
                        "kind": "columns",
                        "label": alias,
                        "required": False,
                        "options": list(columns),
                        "server_projection_of": source_field,
                    }
                else:
                    alias_control = {
                        "key": alias,
                        "kind": "column",
                        "label": alias,
                        "required": False,
                        "options": list(columns),
                        "server_projection_of": source_field,
                    }
                add(alias_control)

        # A builder may emit a fixed declaration (for example CS/SA's
        # ``did_mode=cohort``) that has no corresponding input field. It is
        # still part of the persisted Draft and therefore must be declared.
        for projected_key, projected_value in projected_params.items():
            if projected_key in controls or projected_key == "model_type":
                continue
            if projected_key == "did_mode":
                add(
                    {
                        "key": projected_key,
                        "kind": "select",
                        "label": projected_key,
                        "required": False,
                        "options": list(DID_MODE_VALUES),
                        "server_projection": True,
                    }
                )

    for key, kind, label, options in (
        ("focal_x", "columns", "Focal explanatory variable(s)", list(columns)),
        ("prediction_entity_column", "column", "Prediction entity column", list(columns)),
        ("prediction_group_column", "column", "Prediction group column", list(columns)),
        ("prediction_time_column", "column", "Prediction time column", list(columns)),
        ("imputation", "json", "Imputation request", None),
    ):
        control = {"key": key, "kind": kind, "label": label, "required": False}
        if options is not None:
            control["options"] = options
        add(control)

    prediction_models = {
        str(entry["key"]): entry
        for entry in manifest.get("prediction_models", [])
        if isinstance(entry, Mapping) and entry.get("key")
    }
    sampling_methods = {
        str(entry["key"]): entry
        for entry in manifest.get("sampling_methods", [])
        if isinstance(entry, Mapping) and entry.get("key")
    }
    for key, options in (
        ("prediction_model_type", sorted(prediction_models)),
        ("prediction_sampling_method", sorted(sampling_methods)),
        ("prediction_data_structure", list(WORKFLOW_SPLIT_KINDS)),
        ("cs_control_group", list(CS_CONTROL_GROUP_VALUES)),
        ("cs_est_method", list(CS_EST_METHOD_VALUES)),
        ("cs_base_period", list(CS_BASE_PERIOD_VALUES)),
    ):
        add({"key": key, "kind": "select", "label": key, "required": False, "options": options})
    for key, kind in (
        ("prediction_cv_folds", "integer"),
        ("prediction_final_holdout_fraction", "number"),
        ("cs_anticipation", "integer"),
        ("prediction_shuffle", "toggle"),
        ("honest_did", "toggle"),
    ):
        add({"key": key, "kind": kind, "label": key, "required": False})

    schema_id = str(entry.get("schema_id") or f"{selected}@v1")
    return schema_id, list(controls.values())


def bind_genesis_recipe_server_owned_options(
    model_type: str,
    value: object,
    *,
    upload_sha256: str,
) -> object:
    """Bind Recipe-owned source identity while rejecting a forged replacement."""

    from ..agent.recipe_contracts import recipe_contract_for_model_type

    contract = recipe_contract_for_model_type(model_type)
    if contract is None or not contract.server_owned_option_fields:
        return value
    if not isinstance(value, Mapping):
        return value
    if not isinstance(upload_sha256, str) or not upload_sha256:
        raise ValueError("RECIPE_SOURCE_BINDING_INVALID")
    source_reference = f"upload:{upload_sha256}"
    bound = dict(value)
    for field_name in contract.server_owned_option_fields:
        if field_name in bound and bound[field_name] != source_reference:
            raise ValueError(
                "RECIPE_SERVER_OWNED_OPTION_MISMATCH: "
                f"{model_type}.{field_name} must match the pinned upload"
            )
        bound[field_name] = source_reference
    return bound


def _backfill_schema_values(editable_schema: list[dict[str, Any]], form: Mapping[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for param in editable_schema:
        copy = dict(param)
        key = copy.get("key")
        if key in form and form[key] not in (None, ""):
            if key == "x" and copy.get("kind") == "columns":
                raw = form[key]
                if isinstance(raw, list):
                    columns = [str(item).strip() for item in raw if str(item).strip()]
                elif isinstance(raw, str):
                    try:
                        decoded = json.loads(raw)
                    except json.JSONDecodeError:
                        decoded = None
                    if isinstance(decoded, list):
                        columns = [str(item).strip() for item in decoded if str(item).strip()]
                    else:
                        columns = [item.strip() for item in raw.split(",") if item.strip()]
                else:
                    columns = [str(raw).strip()]
                copy["value"] = columns
                copy["options"] = columns
            else:
                copy["value"] = form[key]
        out.append(copy)
    return out


def _inject_focal_x_control(
    editable_schema: list[dict[str, Any]],
    form: Mapping[str, Any],
    model_type: str,
) -> list[dict[str, Any]]:
    if model_type in _STRUCTURAL_FOCAL_FAMILIES:
        return editable_schema
    if any(item.get("key") == "focal_x" for item in editable_schema):
        return editable_schema
    try:
        x_columns = parse_column_selector(form.get("x", ""), "x")
    except ValueError:
        return editable_schema
    if not x_columns:
        return editable_schema
    value = _parse_focal_x(form.get("focal_x", ""), x_columns)
    return [
        *editable_schema,
        {
            "key": "focal_x",
            "kind": "multiselect",
            "label": "Focal explanatory variable(s)",
            "options": list(x_columns),
            "value": value,
        },
    ]


def _source_params_from_schema(editable_schema: list[dict[str, Any]]) -> dict[str, Any]:
    return {item["key"]: item.get("value") for item in editable_schema if item.get("key")}


def normalize_ols_genesis_model_params(model_params: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the linear-model Agent envelope and project it to legacy covariance.

    The top-level field remains part of the executable Draft schema for human
    controls and backward-compatible run inputs. It is a projection of the
    validated nested Agent option, not a replacement for that option. Keeping
    both prevents Genesis from accepting a typed option and then silently
    dropping the server-owned contract before execution.
    """
    normalized = dict(model_params)
    if normalized.get("model_type") not in {"ols", "panel_ols"} or "model_options" not in normalized:
        return normalized
    from ..contracts.model.ols import validate_ols_model_options

    options = normalized.get("model_options")
    if not isinstance(options, Mapping):
        raise ValueError("MODEL_OPTIONS_UNSUPPORTED_FOR_OLS_GENESIS")
    options = dict(options)
    if options:
        try:
            validate_ols_model_options(options)
        except ValueError as exc:
            raise ValueError(getattr(exc, "error_code", str(exc))) from exc
    normalized["model_options"] = options
    if "covariance" in options:
        nested_covariance = options["covariance"]
        current_covariance = normalized.get("covariance")
        if current_covariance is not None and current_covariance != nested_covariance:
            raise ValueError("MODEL_OPTIONS_COVARIANCE_CONFLICT")
        normalized["covariance"] = nested_covariance
    return normalized


def _read_indexed_node_hash(run_root: Path, node_id: str) -> str | None:
    index_path = run_root / NODE_INDEX_FILENAME
    if not index_path.is_file():
        return None
    index = read_json(index_path)
    entry = index.get(node_id) if isinstance(index, dict) else None
    if not isinstance(entry, dict):
        return None
    value = entry.get("node_hash")
    return str(value) if value else None


def _provenance_payload(provenance: Mapping[str, str] | None) -> dict[str, str] | None:
    if provenance is None:
        return None
    if not provenance or any(
        not isinstance(key, str) or not isinstance(value, str) or not value
        for key, value in provenance.items()
    ):
        raise ValueError("notebook_provenance must contain nonempty string values")
    return {str(key): str(value) for key, value in provenance.items()}


def _resolved_draft_id(draft_id: str | None) -> str:
    resolved = new_draft_id() if draft_id is None else draft_id
    validate_draft_id(resolved)
    return resolved


def create_rerun_draft_from_node(
    project_root: Path,
    *,
    source_run_id: str,
    source_model_node_id: str,
    source_op_node_id: str,
    source_node_hash: str,
    source_forest_node_key: str | None,
    source_context_fingerprint: str,
    notebook_provenance: Mapping[str, str] | None = None,
    persist: bool = True,
    draft_id: str | None = None,
) -> StoredDraft:
    """Create one source-pinned rerun-child Draft without executing it."""

    root = Path(project_root)
    resolved_draft_id = _resolved_draft_id(draft_id)
    runs_root = _resolve_project_runs_dir(str(root))
    run_root = _resolve_run_root(str(root), source_run_id)
    manifest = _read_manifest(run_root)
    if manifest.get("status") not in _TERMINAL_RUN_STATUSES:
        raise ValueError("SOURCE_RUN_NOT_TERMINAL")

    graph = GraphStore(runs_root=runs_root).read(source_run_id)
    node = graph.nodes.get(source_op_node_id)
    if node is None:
        raise ValueError("SOURCE_MODEL_NODE_NOT_FOUND")
    if source_model_node_id != source_op_node_id:
        raise ValueError("SOURCE_MODEL_NODE_MISMATCH")
    indexed_hash = _read_indexed_node_hash(run_root, source_op_node_id)
    if indexed_hash is None:
        raise ValueError("SOURCE_NODE_HASH_UNAVAILABLE")
    if indexed_hash != source_node_hash:
        raise ValueError("SOURCE_NODE_HASH_MISMATCH")

    try:
        request = NodeWriteOperationRequestV1(
            request_id="notebook_option_materialization",
            operation="rerun",
            context_version="node-operation-context/v1",
            context_fingerprint=source_context_fingerprint,
            owner_run_id=source_run_id,
            op_node_id=source_op_node_id,
            node_hash=source_node_hash,
            forest_node_key=source_forest_node_key or source_node_hash,
            owner_resolution="single_candidate",
            active_head_run_id=source_run_id,
        )
        validate_rerun_operation_target(runs_root, request)
    except (ValidationError, ValueError) as exc:
        raise ValueError(f"SOURCE_CONTEXT_MISMATCH: {exc}") from exc

    stage = node.stage.value if node.stage is not None else None
    contract = resolve_operation_contract(stage=stage, manifest=manifest)
    if contract is None:
        raise ValueError("MODEL_NODE_NOT_ELIGIBLE")
    try:
        inputs = read_run_inputs(run_root)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("SOURCE_RUN_INPUTS_UNAVAILABLE") from exc
    upload = inputs.get("upload") or {}
    source_input_fingerprint = upload.get("sha256")
    if not source_input_fingerprint:
        raise ValueError("SOURCE_INPUT_FINGERPRINT_UNAVAILABLE")

    form = inputs.get("form") or {}
    editable_schema = _backfill_schema_values(contract.editable_schema, form)
    editable_schema = _inject_focal_x_control(editable_schema, form, contract.op_type)
    source_params = _source_params_from_schema(editable_schema)
    now = utc_now()
    draft: dict[str, Any] = {
        "draft_id": resolved_draft_id,
        "schema_version": "pipeline_draft.v1",
        "created_at": now,
        "updated_at": now,
        "status": "draft",
        "created_from": {
            "source_type": "run",
            "source_run_id": source_run_id,
            "source_model_node_id": source_model_node_id,
            "source_op_node_id": source_op_node_id,
            "source_node_hash": source_node_hash,
            "source_context_fingerprint": source_context_fingerprint,
            "source_input_fingerprint": source_input_fingerprint,
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "input_1",
                    "node_type": "input.dataset",
                    "source_type": "run_input",
                    "run_input_id": source_run_id,
                    "schema_fingerprint": inputs.get("dag_hash") or source_input_fingerprint,
                    "input_fingerprint": source_input_fingerprint,
                    "columns_summary": [{"name": key} for key in sorted(form)],
                    "status": "bound",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": contract.op_type,
                    "schema_id": contract.schema_id,
                    "editable_schema": editable_schema,
                    "editable_schema_hash": schema_hash(editable_schema),
                    "source_ref": {
                        "source_run_id": source_run_id,
                        "source_model_node_id": source_model_node_id,
                        "source_op_node_id": source_op_node_id,
                        "source_node_hash": source_node_hash,
                        "source_context_fingerprint": source_context_fingerprint,
                    },
                    "source_params": source_params,
                    "params": dict(source_params),
                },
            ],
            "edges": [{"from": "input_1", "to": "model_1"}],
        },
        "default_execution_mode": "rerun_child",
    }
    provenance = _provenance_payload(notebook_provenance)
    if provenance is not None:
        draft["notebook_provenance"] = provenance
    candidate = StoredDraft(
        draft=draft,
        draft_hash=compute_executable_draft_hash(draft),
    )
    if not persist:
        return candidate
    try:
        return PipelineDraftStore(root).create(draft)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


def create_genesis_draft(
    project_root: Path,
    *,
    upload_sha256: str,
    filename: str,
    sheet_names: tuple[str, ...],
    columns: tuple[str, ...],
    model_family: str = "regression",
    model_params: Mapping[str, Any] | None = None,
    exploration_context: Mapping[str, Any] | None = None,
    notebook_provenance: Mapping[str, str] | None = None,
    draft_id: str | None = None,
) -> StoredDraft:
    """Create one parentless, upload-bound genesis Draft without executing it."""

    root = Path(project_root)
    resolved_draft_id = _resolved_draft_id(draft_id)
    _resolve_project_runs_dir(str(root))
    if not re.fullmatch(r"[0-9a-f]{64}", upload_sha256):
        raise ValueError("UPLOAD_NOT_FOUND")
    try:
        verify_upload(root, upload_sha256)
    except (OSError, ValueError) as exc:
        raise ValueError("UPLOAD_NOT_FOUND") from exc
    if not filename or Path(filename).name != filename:
        raise ValueError("FILENAME_INVALID")
    safe_columns = tuple(str(column) for column in columns if str(column))
    requested_model_type = (model_params or {}).get("model_type") if model_params else None
    model_node: dict[str, Any] = {
        "node_id": "model_1",
        "node_type": "model",
        "model_family": model_family,
        "model_type": requested_model_type if isinstance(requested_model_type, str) else "auto",
        "params": dict(model_params or {}),
        "status": "pending",
    }
    schema_model_type = requested_model_type if isinstance(requested_model_type, str) else None
    if schema_model_type == "custom" and model_family == "custom":
        # Custom capability drafts are gateway-owned provenance envelopes. They
        # are not built-in model families and must not be made executable by
        # pretending that a factory binding is part of the static capability
        # manifest or by inventing an editable model schema.
        schema_id, editable_schema = "custom.gateway@v1", []
    else:
        schema_id, editable_schema = _genesis_model_editor_schema(
            schema_model_type,
            safe_columns,
        )
    model_node.update(
        {
            "schema_id": schema_id,
            "editable_schema": editable_schema,
            "editable_schema_hash": schema_hash(editable_schema),
        }
    )
    draft: dict[str, Any] = {
        "draft_id": resolved_draft_id,
        "schema_version": "pipeline_draft.v1",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "status": "draft",
        "created_from": {
            "source_type": "genesis",
            "source_input_fingerprint": upload_sha256,
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "source_1",
                    "node_type": "input.upload",
                    "upload": {"sha256": upload_sha256, "filename": filename},
                    "sheet_names": list(sheet_names),
                    "status": "bound",
                },
                {
                    "node_id": "table_1",
                    "node_type": "table",
                    "params": {"sheet_name": None, "transpose": False},
                    "columns": list(safe_columns),
                    "status": "pending",
                },
                model_node,
            ],
            "edges": [
                {"from": "source_1", "to": "table_1"},
                {"from": "table_1", "to": "model_1"},
            ],
        },
        "default_execution_mode": "genesis",
    }
    if exploration_context is not None:
        draft["exploration_context"] = dict(exploration_context)
    provenance = _provenance_payload(notebook_provenance)
    if provenance is not None:
        draft["notebook_provenance"] = provenance
    try:
        return PipelineDraftStore(root).create(draft)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


__all__ = ["create_genesis_draft", "create_rerun_draft_from_node"]
