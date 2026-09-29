# Arboris manual

Arboris is a local statistics workbench: SPSS- and
Stata-style data management and analysis, a lineage graph that records every
step, and an AI Agent that runs analyses from plain language — under rules it
cannot talk its way around.

## For people doing analysis

| Chapter | What it covers |
|---|---|
| [Getting started](user/01-getting-started.md) | Starting Arboris, projects, importing CSV, Excel, SPSS and Stata files |
| [Working with data](user/02-data.md) | Data view, Variable view, labels, missing-value codes, data operations, export |
| [Analysis](user/03-analysis.md) | Descriptive statistics, tests, models, reruns, the lineage graph, reports |
| [The Agent](user/04-agent.md) | What to ask, what runs at once and what waits for you, how numbers are checked |
| [Trust and records](user/05-trust.md) | The analysis ledger, disclosure in reports, data sharing with AI providers, accuracy evidence |
| [Coming from Stata or SPSS](user/06-stata-spss.md) | Commands and menus mapped to Arboris |

## For people extending Arboris

| Chapter | What it covers |
|---|---|
| [Architecture](developer/01-architecture.md) | How a run, the graph, the Agent and the safety layers fit together |
| [Extending](developer/02-extending.md) | Adding a data operation, a model or test, an Agent tool, a UI action |
| [Testing and release](developer/03-testing.md) | Test suites, reference-software oracles, live Agent evaluation, gates |

## Reference (generated from the code)

These pages are written by `scripts/generate_manual_reference.py` from the
registries themselves, and a test fails when they fall out of date.

- [Capabilities](reference/capabilities.md) — every model family, test and pack
- [Data operations](reference/data-operations.md) — fields and a worked example each
- [Workflow steps](reference/workflow-steps.md) — what a composed workflow can contain
- [Agent tools](reference/agent-tools.md) — and what each may send to a model provider
- [Analysis ledger](reference/analysis-ledger.md) — how every step is categorized
- [Export formats](reference/export-formats.md)
