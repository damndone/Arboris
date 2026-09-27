# Extending Arboris

A new capability is added by declaring it once. The declaration reaches the UI,
the Agent, validation, the ledger and the manual; tests fail when one of them
is missed. Each section ends with the test that will tell you.

## A data operation

1. Write the executor in `backend/workbench/data_operations.py` as
   `_execute_<name>(frame, spec)` (or `(frame, spec, secondary)` for an
   operation that reads a second dataset). It returns a new frame and never
   modifies its input.
2. Declare it in `backend/workbench/data_operation_catalog.py`: a contract
   literal (summary, fields, required fields, JSON types and schemas, enums,
   whether the Agent may use it) and a `_declare(...)` call with
   - `referenced_columns` and `output_columns`, so workflows can check column
     names before running;
   - `validate`, which rejects a bad spec with a message a person can act on;
   - `describe`, the one-line sentence shown on proposal cards
     ("Keep rows where age is between 25 and 55"), using variable labels when
     the data has them;
   - `example` and `example_frame`, a complete spec and a small frame. The
     registry's contract test executes every example, so a declaration whose
     example does not run cannot be merged.
   - `binding_fields` for spec fields that name an input dataset rather than
     parameterize the operation (merge and append).
3. Regenerate the manual reference (`scripts/generate_manual_reference.py`).

The operation is then offered by the HTTP route, reachable by the Agent as the
workflow step `data.<name>`, described in proposals and recorded in the ledger
as `data_change` (the `data.` prefix).

Tests: `tests/test_data_operation_registry.py`, `tests/test_proposal_text.py`,
`tests/test_manual_reference.py`.

## A model family, test or statistical pack

Follow the engine extension contract in [`docs/extensions.md`](../../extensions.md):
register a pack, declare its option vocabulary, and let the capability
inventory pick it up.

- **Reference values first.** A new estimator is not done until it matches the
  reference implementation people trust — an R package or Stata — on a
  fixture: add `tests/fixtures/<family>/generate_oracle.R` (or a Stata do-file
  through `tests/stata_oracle.py`) and compare element-wise.
- **Classify it.** Every workflow step needs a ledger category. Most ids fall
  under an existing prefix in `analysis_ledger._PREFIXES`; a new prefix, or an
  id that is descriptive under an inferential prefix, goes in `_EXACT`. Only
  `descriptive` and `inferential` steps can run without confirmation, so a
  step that fits a model or produces a dataset must never be classified as
  either.
- **Name what it cannot claim.** If a quantity is easily mistaken for a
  stronger one, add it to the pack's `prohibited_claims`; the Agent is bound
  by them even when a user asks.

Tests: `tests/test_read_only_analysis.py::test_every_registered_step_has_a_category`,
`::test_a_step_that_produces_a_dataset_is_never_read_only`, the capability
reachability tests under `tests/evaluation/`, and your oracle test.

## An Agent tool

1. Write a `ToolDefinition` in `backend/workbench/agent/context_tools.py`: a
   JSON schema with `additionalProperties: false`, the `side_effect`, a
   `max_output_budget`, and a `description` that says what the tool returns and
   when to use it (the model chooses tools from the description alone).
2. Register it in the Chain list, the Main list, or both.
3. Classify its content in `egress.TOOL_CONTENT_CLASSES`. A tool that returns
   data rows is `rows` and must also return an `egress_summary` — the only part
   a remote provider receives under the default policy.
4. If it returns numbers the model will quote, return them at full precision;
   the numeric check compares the reply against them. Never hand the model a
   pre-rounded value alone.
5. If it changes anything, it must not act: it creates a proposal through the
   orchestrator and the user confirms.

Tests: `tests/test_egress.py::test_every_tool_declares_what_it_can_send`, the
tool-set pins in `tests/test_agent_routes.py`, `tests/test_manual_reference.py`.

## A UI action that changes data or runs an analysis

Any `POST`, `PUT`, `PATCH` or `DELETE` route must either record the action in
the analysis ledger after it succeeds —

```python
from ..analysis_ledger import record_ui_action

record_ui_action(project_root, source="data.transform", steps=[operation_id],
                 run_id=run_id, node_id=node_id, summary=sentence)
```

— or be listed, with a reason, in the exemptions of
`tests/test_analysis_ledger_routes.py` (settings, drafts, anything that
computes nothing). A deletion records the source file's hash before the run is
removed, so the report can still disclose it.

Tests: `tests/test_analysis_ledger_routes.py::test_every_state_changing_route_is_recorded_or_exempt`.

## Rules that hold for every extension

- Never change a user's data silently. Any cleaning, dropping or recoding is
  either a confirmed operation or a visible notice. (Arboris once dropped
  identical rows during cleaning; in survey data identical rows are different
  people.)
- The model proposes; code decides. Validation, execution, rounding,
  arithmetic and what leaves the machine are never delegated to the model.
- Every surface reads the declaration. If you find yourself writing a second
  list of operation names, derive it instead.
