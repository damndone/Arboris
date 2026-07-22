# Arboris

A local econometrics workbench. You point it at a dataset, choose a model, and
it produces a run: every decision recorded, every artifact addressed, and a
lineage graph you can edit and re-execute node by node.

Everything runs on your machine. Nothing is uploaded, and the only network call
is to an LLM provider you configure yourself — for prose and for typed change
proposals, never for the statistics.

**Current release: v1.8.0** — see [docs/releases/](docs/releases/).

---

## Quick start

```bash
python3 -m pip install -e ".[dev]"
uvicorn workbench.api:app --reload
```

```bash
cd frontend && npm install && npm run dev
```

Or from the command line, without the UI:

```bash
workbench create /tmp workbench-demo
workbench run /tmp/workbench-demo examples/datasets/cross_section.csv wage --x education
```

A run writes into `project/runs/{run_id}/`: `run_manifest.json`,
`environment.json`, `decisions.json`, `errors.json`, `artifacts_index.json`,
plus reports, figures, tables and processed data.

## What it does

**Models.** OLS, Logit, Probit, Poisson, Negative Binomial, GLM families,
Panel OLS, Linear Mixed Effects, IV/2SLS.

**Difference-in-differences**, the full modern kit: classic TWFE with event
study and parallel-trends checks, Goodman-Bacon decomposition, Callaway–Sant'Anna,
Sun–Abraham, and de Chaisemartin–D'Haultfœuille for non-absorbing treatment.
Honest-DiD sensitivity analysis (ΔRM and ΔSD) runs on top of any of them. Each
estimator was validated element-wise against its R reference implementation.

**Time series** (v1.8): an ARMA–GARCH volatility workbench over any time and
value column — explicit transform confirmation, manual orders or bounded
automatic search, training-only selection, independent rolling evaluation.

**A lineage graph** as the working surface. Every stage of a run is a node.
Edit a node's parameters and re-execute from there; the original is never
mutated, and the child records what changed and why. Nodes are content-addressed,
so two runs that share a stage share the node.

**An Agent** that reads a run and proposes typed changes. It cannot execute
anything on its own: it produces a proposal against a published option
vocabulary, you confirm it, and the result is an auditable child run. The whole
session exports as JSON, Markdown or HTML.

## What it refuses to do

The workbench is built to be boring about claims, which is most of what makes
it useful:

- **It will not present a number it cannot support.** Sequential ARMA-then-GARCH
  estimation never reports a composite information criterion, because there is
  no joint likelihood behind it.
- **It will not relabel a quantity into a stronger one.** A lower conditional
  quantile is never called value-at-risk.
- **It records what it did not do.** Acceptance warnings — residual
  autocorrelation, rejected normality — stay visible in the report rather than
  being smoothed away.
- **It does not silently repair your data.** Missing values are excluded only
  after you confirm the policy, and the source file is never modified.

## Optional extras

```bash
pip install -e ".[panel]"       # linearmodels, for panel_ols
pip install -e ".[ml]"          # scikit-learn, for prediction_lasso/ridge/random_forest
pip install -e ".[imbalanced]"  # imbalanced-learn, for smote/oversample/undersample
```

Prediction-only mode (`prediction_enabled: true` in `config.yml`) writes into
`prediction_results/` and is never treated as causal inference.

## Deployment contract

The default backend profile is fail-closed. Local LMM and sandboxed
`code.execute` require an explicit opt-in on every start, which is not
persisted:

```bash
./scripts/run-local-contained.sh
```

The launcher runs a native macOS sandbox canary before accepting the server.
When ready, `GET /health` reports `execution_profile: local_contained`,
`lmm_admitted: true`, `high_risk_code_admitted: true`, `canary_status: passed`.
This profile runs reviewed Workbench code only; it is not hostile-plugin or
public-deployment certification.

Agent-confirmed operation state uses a project-local JSONL and file-lock control
plane, so the deployment contract is **single worker**. The backend rejects
`WORKBENCH_WORKERS` or `WEB_CONCURRENCY` other than `1` at startup, and
`/health` reports `control_plane_mode: single_worker`. Multiple workers would
need a transactional store with compare-and-swap semantics; the current local
deployment does not imply it.

## Development

```bash
pytest                      # backend
bash scripts/gate.sh --full # the full release gate
```

The gate is the checkpoint before any handoff, merge or release: backend suite,
golden and invariant snapshots at zero drift, frontend tests, and a TypeScript
check. It refuses to start alongside a dev server or another gate, and refuses a
worktree that installed its own dependencies instead of sharing the main
checkout's.

Working in a worktree? Link the shared dependencies first — never `npm install`
inside one:

```bash
bash scripts/link-shared-deps.sh <worktree-path>
```

## Repository layout

| Path | Contents |
|---|---|
| `backend/workbench/` | Engine, model packs, contracts, HTTP layer, Agent |
| `frontend/src/` | React UI: run form, lineage graph, result views, Agent panel |
| `tests/` | Backend suite, including golden and invariant snapshots |
| `examples/datasets/` | Known-truth datasets used by acceptance runs |
| `docs/releases/` | Release notes, one per version |
| `docs/superpowers/` | Working documents — see its README for the lifecycle rules |
| `scripts/` | Gate, shared-dependency linking, contained launcher |

Branches are deleted after they merge. Every deleted branch tip is preserved
under an `archive/branch-tip/*` tag, so an old branch is still reachable by name.
