# Architecture

Arboris is a FastAPI backend (`backend/workbench`, served as
`workbench.app:app`) and a React front end (`frontend/`, Vite). Everything
runs on the user's machine; a project is a directory, and every result is a
file in it. The only network traffic is to the language-model provider the
user configures, and it passes one checkpoint (see *Egress*).

## Projects, runs and the lineage graph

```
project/
  data/                 imported files (never modified)
  runs/<run_id>/        one run: inputs, manifest, decisions, errors,
                        artifacts_index.json, processed data, tables,
                        figures, reports
  workbench/            project state: Agent sessions and events, proposals,
                        operation records, chains and forks, the analysis
                        ledger, egress policy and audit, report settings
```

A **run** is one pass of the engine pipeline over a dataset: source, profile,
validation, cleaning, roles, routing, imputation, estimation, diagnostics,
statistical tests, report (`engine/stages/`). Each stage records a node in the
**lineage graph**; nodes are content-addressed (`lineage/hashing.py`), so two
runs that share a stage share its node. Runs across a project form a forest
(`lineage/project_forest.py`).

Nothing is edited in place. A data operation produces a new dataset node; a
changed model is a rerun that produces a child run recording what changed
(`lineage/rerun_provenance.py`). Deleting a run is itself recorded.

Models live in **packs** registered through `engine/pack.py`; the built-in
families use the same `register_pack` an extension would. See
[`docs/extensions.md`](../../extensions.md) for the engine extension contract.

## One declaration per capability

What Arboris can do is declared once and every surface reads the declaration:

| Registry | Declares | Read by |
|---|---|---|
| `data_operation_registry` + `data_operation_catalog` | the 11 data operations: fields, validation, execution, a worked example, a one-line description | executor, HTTP route, Agent workflow vocabulary and validation, proposal sentences, the manual |
| `agent/capability_contract.capability_inventory()` | every model family, test, pack, prediction model and operation | Agent planning and reachability checks, evaluation case generation, the manual |
| `agent/workflow_contracts` | workflow step operations and their `spec` fields | the Agent protocol (rendered from it), the workflow compiler, the manual |
| `egress.TOOL_CONTENT_CLASSES` | what content each Agent tool can return | the egress guard, the manual |
| `analysis_ledger._EXACT` / `_PREFIXES` | the category of every step | the read-only policy, disclosure, the manual |

Tests fail when a surface drifts from its declaration: a registered Agent tool
missing from the egress table, a UI route that changes data without a ledger
hook, a reference page out of date.

## The Agent

Two kinds of Agent session exist. A **Chain Agent** works on one branch of the
graph (a run and its descendants) and can propose changes to it. The **Main
Agent** answers across the whole project from read-only evidence tools.

- `agent/core.py` — `AgentCore`, the provider-neutral loop: build context,
  stream a model response, run tool calls, persist every message to the
  session log (`workbench/agent-sessions/<id>.jsonl`) and every event to the
  event stream. Budgets bound steps, time and repeated calls.
- `agent/model.py` — the OpenAI-compatible adapter. A request that fails before
  any output is retried twice with backoff; each retry is an event.
- `agent/context_tools.py` — the evidence and action tools, each a
  `ToolDefinition` with a JSON schema and a declared side effect.
- `agent/orchestrator.py` — proposals and their lifecycle. `propose_operation`
  creates a proposal; anything that changes data, metadata, a model or a
  report waits for the user's confirmation, then executes as an auditable
  operation record.
- `agent/read_only_policy.py` — which workflows run without confirmation:
  those whose every step only reads data, within a step and test budget.
- `agent/analysis_integrity.py` — the rules against p-hacking, shared by both
  protocols.
- `agent/numeric_grounding.py` — the numeric check and the `calculate` tool.
- `http/agent_routes.py` — the two protocols (system prompts), with the step
  vocabulary rendered from the registry.

The model never executes anything itself. It returns tool calls; Arboris
validates them against schemas and contracts, runs what is read-only, and
turns everything else into a proposal a person confirms.

## Safety layers

Each layer is enforced in code, at one place, whatever the model says.

| Layer | Where | What it guarantees |
|---|---|---|
| Confirmation | `orchestrator`, `read_only_policy` | Nothing that changes data, metadata, a model or a report runs without the user's click |
| Analysis ledger | `analysis_ledger.py`, hooks in every mutating route | Every executed analysis and data change, from the UI or the Agent, is recorded with who authorized it |
| Disclosure | `analysis_disclosure.py` | Reports state the analysis path: how many tests, what changed, what was deleted; written by Arboris, not the model |
| Numeric check | `numeric_grounding.py`, called in `AgentCore._run_turn` | No number reaches the user unless it matches a result, correctly rounded, or is flagged |
| Egress | `egress.py`, called only in `llm.client._chat_request_payload` | Data leaves the machine only as the project's sharing policy allows; every call is audited |
| Containment | `native_containment`, `sandbox.py`, `frozen_containment.py` | User code (`code.execute`) runs in a macOS sandbox with a fail-closed profile |

### Egress

Every provider call is built in one function, which passes the messages through
`guard_outgoing_messages`. Tool results are classified by the tool that made
them; server evidence records by protocol. Classes not allowed by the
project's policy (`workbench/egress/policy.json`; rows are withheld from
remote providers by default) are replaced by a note, and the model is told the
user saw them. Columns marked sensitive or restricted are redacted wherever
they appear. Every call is appended to `workbench/egress/audit.jsonl`.

### Numeric check

Before a final reply is persisted, `numeric_grounding.check` extracts every
decimal number and every whole number from 1,000 up (years excepted) and
requires each to equal some number the model was given —
tool results, server records, the user's own words, or a `calculate` value
whose operands are themselves supported — rounded correctly to the digits
written (thresholds such as "p < 0.05" excepted). A failing reply is kept as a
withdrawn draft (`stop_reason: "revised"`), and the model is asked once, in a
new user-role turn, to answer again; providers with private reasoning refuse a
second answer inside a turn that already used tools. If the rewrite fails too,
the reply is shown with a warning naming the numbers. A check that cannot run
says so rather than passing.

## Front end

`frontend/src/workbench` holds the workbench shell: the graph, table,
notebook, report and data views, the Agent panel, and panels for AI activity
and logs. `dataView/` is the SPSS-style Data and Variable view; `report/`
renders reports, including the analysis disclosure. The front end holds no
statistical logic: every number comes from the backend.
