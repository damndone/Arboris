# `POST /runs` Form Contract

## Endpoint

`POST /runs` — content type `multipart/form-data`.

## Existing fields

These are the current form fields accepted by `backend/workbench/api.py` (pre-V1.5.4.1):

| field | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `project_root` | string | — | yes | absolute path to project root |
| `mode` | string | `auto` | no | run mode |
| `model_type` | string | `auto` | no | requested model type (key from `/capabilities`) |
| `y` | string | — | yes | y column name |
| `x` | string | — | yes | comma-separated x column names |
| `file` | file | — | yes | uploaded data file (CSV/XLSX) |
| `sheet_name` | string | `""` | no | excel sheet selector |
| `transpose` | string | `false` | no | `"true"` to swap rows/columns |

## New in V1.5.4.1

| field | type | default | required | meaning |
| --- | --- | --- | --- | --- |
| `imputation` | string (JSON) | `""` | no | When non-empty: JSON object like `{"method":"mice"}`. When empty: falls back to `config.imputation_method`. |

The value is a JSON-encoded **string** (not a structured multipart part) so the form encoding stays flat. The backend parses it once at request entry; downstream code receives a normal dict.

## Response

Unchanged from prior versions:

```json
{"run_id": "...", "status": "running"}
```

## Forward compatibility

- **Never repurpose** existing field names. If semantics change, add a new field instead.
- **New fields are additive only.** Clients that don't send them get the documented default behaviour.
- Field names are stable within a major version.
