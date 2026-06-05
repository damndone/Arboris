# Capabilities Contract

## Endpoint

`GET /capabilities`

Returns a JSON document describing the model types and imputation methods the backend currently supports. The document conforms to the JSON Schema below. Clients may cache the response for the lifetime of a session (the schema is stable within a release).

## JSON Schema

`application/schema+json` — JSON Schema **Draft 2020-12**.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["schema_version", "model_types", "imputation_methods"],
  "properties": {
    "schema_version": {"type": "integer", "minimum": 1},
    "model_types": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["key", "label", "group"],
        "properties": {
          "key": {"type": "string", "minLength": 1},
          "label": {"type": "string", "minLength": 1},
          "group": {"type": "string", "minLength": 1},
          "description": {"type": "string"},
          "requires": {
            "type": "array",
            "items": {"type": "string"}
          }
        },
        "additionalProperties": false
      }
    },
    "imputation_methods": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["key", "label"],
        "properties": {
          "key": {"type": "string", "minLength": 1},
          "label": {"type": "string", "minLength": 1},
          "description": {"type": "string"}
        },
        "additionalProperties": false
      }
    }
  },
  "additionalProperties": false
}
```

## Sample

See [`tests/contracts/capabilities.sample.json`](../../tests/contracts/capabilities.sample.json).

The same file doubles as the **frontend mock fixture** consumed in slice 3 — keep it in sync with the schema by updating both together (the test in `tests/contracts/test_schema_capabilities.py` is the guard).

## Forward compatibility

- New `model_types[].group` values **must** be added to the frontend `Group` union (TS type) **before** they are published from the backend. Otherwise the UI will fall through its rendering switch.
- New **top-level keys** are additive only. Clients MUST ignore unknown top-level keys to remain forward-compatible.
- Existing field names and types are stable across patch releases. A breaking change requires bumping `schema_version`.

## Producer

`backend/workbench/engine/capabilities.py::build_capabilities()` (slice 2) derives this document from `MODEL_REGISTRY` + `IMPUTATION_REGISTRY`. There must NEVER be a parallel hand-maintained list of model/imputation keys anywhere else in the codebase.
