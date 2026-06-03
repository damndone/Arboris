# Imputation Summary Contract

## Location

`run_root / "model_results" / "imputation_summary.json"`.

Registered as artifact id `imputation_summary` with `inputs=[input_artifact]` (so the dependency from cleaned/raw → imputation → downstream model is materialised in the artifact DAG).

## Method-agnostic required fields

| field | type | notes |
| --- | --- | --- |
| `schema_version` | integer ≥ 1 | bump on breaking change |
| `method` | string | e.g. `"mice"`, future: `"knn"`, `"mean_fill"` |
| `status` | enum | `"completed"` \| `"skipped"` \| `"failed"` |
| `imputed_columns` | string[] | columns actually written to in the output |
| `input_artifact` | string | artifact id consumed as input (e.g. `"cleaned_dataset"`) |
| `output_artifact` | string | artifact id of the imputed dataset produced |

`rows_imputed` (integer ≥ 0) is **method-agnostic** but **optional** when `status="skipped"`.

## MICE-specific optional fields

`m`, `persisted_datasets`, `max_iter`, `random_seed`, `max_missing_rate`, `selected_columns`, `skipped_columns`, `row_count`, `warnings`, `pooled_estimates`.

## Forward compatibility

Future methods may add their own optional fields (e.g. KNN: `k`; mean_fill: `strategy`). The schema sets `additionalProperties: true` for this reason.

Frontend rendering rule: render the **core fields universally** and use a `method`-keyed switch for method-specific rows. Unknown methods fall through to a generic key/value table.

## Sample

See [`tests/contracts/imputation_summary.mice.sample.json`](../../tests/contracts/imputation_summary.mice.sample.json).

## Producer

`backend/workbench/imputation.run_mice_imputation()` already returns most fields. `ImputationStage` (slice 2):
1. writes the file to `model_results/imputation_summary.json`,
2. registers it as the `imputation_summary` artifact,
3. adds the three V1.5.4.1 method-agnostic fields (`rows_imputed`, `input_artifact`, `output_artifact`).
