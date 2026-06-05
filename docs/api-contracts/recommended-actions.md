# Recommended Actions Contract

## Intent

`failure_evidence.recommended_actions` is the **first concrete producer** of the V1.5.4 spec §2.5 declared `AnalysisPack.recommended_actions` slot. Both producers share the same item schema below. Future producers (agent failures, pack diagnostics, etc.) MUST conform to this same schema.

## Schema

`application/schema+json` — JSON Schema **Draft 2020-12**. Each item in the `recommended_actions[]` array validates against:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["key", "label", "severity"],
  "properties": {
    "key": {"type": "string", "minLength": 1},
    "label": {"type": "string", "minLength": 1},
    "severity": {"type": "string", "enum": ["primary", "secondary"]},
    "form_overrides": {"type": "object"},
    "hint": {"type": "string"}
  },
  "additionalProperties": false
}
```

## Severity rules

- `primary` — red **filled** button. **At most one** primary action per array in a failure context (the one-click recovery).
- `secondary` — **outlined** button. Zero or more per array.

## `form_overrides`

When present, clicking the button **merges these key/values into the run form state**. The frontend submits the merged form. Example: `{"model_type": "auto"}` triggers a one-click re-run with auto model inference.

## `hint`

Optional tooltip / helper text shown alongside the button to explain why the user might want to click it.

## Sample

See [`tests/contracts/recommended_actions.model_fit_failure.sample.json`](../../tests/contracts/recommended_actions.model_fit_failure.sample.json).

## Producer

`backend/workbench/engine/recommended_actions.py` factory functions (slice 2) produce these arrays for each known failure code. There must be no hand-rolled action dicts at API-layer call sites.
