# Arboris

**An AI-native statistics workbench that runs on your machine.** Open an SPSS,
Stata, Excel or CSV file, ask questions in plain language (Chinese or English),
and get answers computed by a deterministic statistics engine — with every
number traceable to the result it came from and every step recorded.

Arboris is meant to cover the everyday work people do in Stata or SPSS, across
disciplines, while being easier to start with: you can drive it from the menus,
from a lineage graph, or by talking to the Agent.

**Current release: v1.8.11** (2026-10-07) — [release notes](docs/releases/v1.8.11-release-notes.md) ·
[all releases](docs/releases/) · [manual](docs/manual/README.md)

---

## Why it is different

- **The AI never computes the statistics.** The language model understands the
  question, picks the analysis and explains the result; the numbers come from
  the engine. Before a reply is shown, every number in it is checked against
  the results — including that it is rounded correctly. Derived numbers
  (differences, ratios, percentages) must come from a `calculate` tool, not the
  model's head. A reply that fails is withdrawn and rewritten.
- **Nothing changes without your confirmation.** Descriptive statistics and
  tests run at once; filtering, recoding, merging, changing a model or writing
  a report is a proposal you confirm. A confirmed change never overwrites
  anything — it adds a node to the lineage graph.
- **It will not chase significance.** Dropping observations, redefining a
  variable or picking a specification *in order to* make a result significant
  is refused — for the user and the Agent alike. Every test and data change is
  recorded in an analysis ledger, and reports disclose the full analysis path.
- **Your data stays local.** The only network call is to the LLM provider you
  configure. By default it receives column names, labels, summaries and results
  — not your rows — and every outgoing request is audited.

## What you can do

**Data.** Read and write `.sav` / `.zsav` (SPSS), `.dta` (Stata), `.xlsx`,
`.csv` and `.parquet`, keeping variable labels, value labels, measurement
levels and user-missing codes. A data view and variable view; filter, recode
(SPSS `RECODE INTO`), merge, append, reshape, aggregate, deduplicate, rename,
fill missing values, lags and time/panel declarations — each recorded as a
node. Export with a chosen format, Stata version, variables, rows and label
handling, with a report of anything a format cannot carry.

**Descriptive statistics.** `summarize` / `summarize, detail` (Stata's
percentile definition), frequencies with value labels, missing-value tables,
correlations, grouped summaries, scatter plots.

**Tests.** t-tests, ANOVA with post-hoc comparisons (Tukey, Bonferroni,
Scheffé, Games–Howell), chi-square and Fisher exact, Pearson / Spearman /
Kendall, Mann–Whitney, Kruskal–Wallis, Wilcoxon, Friedman, McNemar,
Cramér's V, effect sizes, assumption checks, power analysis, bootstrap and
permutation inference, multiple-comparison adjustment.

**Models.** OLS, logit, probit, Poisson, negative binomial, GLM families,
ordinal and multinomial logit, quantile regression, zero-inflated and hurdle
models, beta regression, panel fixed/random effects, linear mixed effects,
IV/2SLS and GMM with weak-instrument diagnostics, Cox proportional hazards,
ANOVA/ANCOVA, MANOVA and repeated-measures ANOVA — with robust, clustered,
Newey–West and survey-design standard errors (design degrees of freedom as in
Stata `svy`, or R `survey`'s convention), weights, and multiple imputation
(MICE with Rubin pooling and Barnard–Rubin degrees of freedom). Any model or
test can be run separately by group, with a test of whether the groups differ
and the comparisons counted for multiple testing; under a survey design each
group is a subpopulation of the full design.

**Post-estimation.** Wald tests, likelihood-ratio tests, linear and nonlinear
combinations (`lincom`, `nlcom`) and average or at-means marginal effects,
read from each result's stored coefficients and covariance rather than
refitted. Assumption checks — collinearity (GVIF), perfect fit, separation,
weak instruments with Anderson–Rubin intervals — apply by the properties a
model declares, and a model family is admitted only with reference checks.

**Causal inference.** Difference-in-differences from TWFE with event studies
and Goodman-Bacon decomposition to Callaway–Sant'Anna, Sun–Abraham and
de Chaisemartin–D'Haultfœuille, with Honest-DiD sensitivity analysis; matching
with balance diagnostics; synthetic control with placebo inference.

**Time series.** ARIMA/SARIMA, ETS, ARMA–GARCH, ADF and KPSS, cointegration,
VAR/VECM, Granger causality, impulse responses, ACF/PACF.

**Multivariate and more.** PCA, exploratory factor analysis, Cronbach's alpha,
clustering, discriminant analysis, correspondence analysis / MCA, survival
curves (Kaplan–Meier, log-rank, RMST), meta-analysis, ROC and calibration,
spatial autocorrelation (Moran's I, Geary's C, Getis–Ord G), out-of-sample
prediction (lasso, ridge, random forest).

**Reports.** Drafted from a run's evidence, every number cited to its source,
exported as HTML, Word or LaTeX, with the analysis path appended.

The complete, generated list is in the
[capability reference](docs/manual/reference/capabilities.md).

## How results are validated

Estimators are checked against reference implementations, not only against
themselves: Stata 18 for descriptive statistics and Stata file interchange,
R (`foreign`, `haven`, `fixest`, `did`, `HonestDiD`, `DIDmultiplegtDYN`,
`survey`, …) for SPSS files and estimators, typically to 1e-10 or better.
Each release passes a full gate — about 6,500 backend tests, golden and
invariant snapshots, 1,700 frontend tests and a type check — plus live
evaluations of the Agent against a real provider, including injected network
faults and adversarial requests. Evidence for each release is in
[`docs/superpowers/evaluations/`](docs/superpowers/evaluations/).

## Quick start

Requires Python 3.11+ and Node.js 18+.

```bash
python3 -m pip install -e ".[dev]"
uvicorn workbench.api:app --reload
```

```bash
cd frontend && npm install && npm run dev
```

Open the address Vite prints, create a project and upload a data file. To use
the Agent, add an LLM provider under **Settings** (any OpenAI-compatible API;
DeepSeek is the one the live evaluations use).

From the command line, without the UI. The commands are generated from the
same declarations the API and the Agent use, and run through the same
services, so a command-line run is recorded like any other:

```bash
workbench create /tmp workbench-demo
workbench models                          # the model catalog; `workbench models negative_binomial` lists its options
workbench run /tmp/workbench-demo examples/datasets/cross_section.csv wage --x education
```

`workbench run` prints the run id on stdout (`RUN=$(workbench run ...)`) and
takes every field of the run form, for example
`--model-type negative_binomial --model-options '{"dispersion": "constant"}'`
(JSON options also accept `@file.json`). Post-estimation and script export
work on the run:

```bash
workbench postestimation wald /tmp/workbench-demo "$RUN" --model-ref model:negative_binomial_1 \
    --constraints '[{"terms": {"x1": 1}, "value": 0}, {"terms": {"x2": 1}, "value": 0}]'
workbench export-targets /tmp/workbench-demo "$RUN" --model model:negative_binomial_1
workbench export-script /tmp/workbench-demo "$RUN" --target artifact:<id> --language stata --require-native --output .
```

`workbench --help` and `workbench <command> --help` list everything.

Optional extras:

```bash
pip install -e ".[panel]"       # linearmodels, for panel models
pip install -e ".[ml]"          # scikit-learn, for prediction models
pip install -e ".[imbalanced]"  # imbalanced-learn, for SMOTE and resampling
```

## Documentation

- [User manual](docs/manual/README.md) — getting started, working with data,
  analysis, the Agent, trust and records, SPSS/Stata equivalents.
- [Developer handbook](docs/manual/README.md#for-people-extending-arboris) — architecture,
  adding a capability, testing and releasing.
- [Release notes](docs/releases/) — one per version.
- [History and archives](docs/history/README.md) — every version, every past
  development worktree and stash, archived as git tags, and how to open any of them.

## Where it is going

Next (v1.8.11): post-estimation for IV, panel, difference-in-differences,
mixed-effects and GLM families, and reproducible script export (Stata do-file,
R, Python) from the lineage graph. Then a redesigned workspace with a single
Agent that follows what you are looking at. After that: classification and time-aware
machine learning, then a research pack for quantitative finance — factor
research and strategy validation that shows why a backtest can be trusted and
where it cannot. See [the roadmap notes](docs/superpowers/roadmap/).

## Deployment contract

The default backend profile is fail-closed. Local LMM and sandboxed
`code.execute` require an explicit opt-in on every start, which is not
persisted:

```bash
./scripts/run-local-contained.sh
```

The launcher runs a native macOS sandbox canary before accepting the server.
When ready, `GET /health` reports `execution_profile: local_contained`. This
profile runs reviewed Workbench code only; it is not hostile-plugin or
public-deployment certification.

Agent state uses a project-local JSONL and file-lock control plane, so the
deployment contract is **single worker**: the backend rejects
`WORKBENCH_WORKERS` or `WEB_CONCURRENCY` other than `1` at startup.

The backend answers only this computer's UI. It accepts only loopback host
names (`localhost`, `127.0.0.1`, `[::1]`), which defeats DNS rebinding, and it
refuses any request whose `Origin` is not the UI. It also refuses cross-site
writes, so another web page, even one on another local port, cannot drive or
read it. Refused requests return `403` with a `LOCAL_REQUEST_*_REJECTED` code
and are logged to `~/.workbench/egress_audit.jsonl`. The CLI and scripts send
no `Origin` and are unaffected. The default UI origin is Vite's
`http://localhost:5173`; listing one loopback name also covers the other two
on the same port. Allowances are explicit only:

```bash
WORKBENCH_ALLOWED_ORIGINS=http://localhost:5190   # a Vite dev server on another port (comma-separated)
WORKBENCH_ALLOWED_HOSTS=workbench.test            # extra host names (comma-separated)
```

## Development

```bash
pytest                      # backend
bash scripts/gate.sh --full # the full release gate
```

The gate is the checkpoint before any merge or release: backend suite, golden
and invariant snapshots at zero drift, frontend tests and a TypeScript check.
It refuses to start alongside a dev server or another gate. Working in a
worktree? Link the shared dependencies first — never `npm install` inside one:

```bash
bash scripts/link-shared-deps.sh <worktree-path>
```

All checkouts share one virtualenv. Its editable install names the main
checkout, so `workbench` and `uvicorn workbench.api:app` run the released code
from anywhere, while a process started inside a worktree (or by one) imports
that worktree. Reinstall from the main checkout after merging a release; the
gate checks the install and the `workbench` command:

```bash
.venv/bin/python scripts/install_dev_env.py   # from the main checkout
.venv/bin/python scripts/check_dev_env.py     # what the gate runs
```

Install the pre-push guard once per clone. It refuses pushes of private refs,
license-bearing history, license header values and withheld raw-log hashes:

```bash
python3 scripts/install_git_hooks.py
```

Large raw evidence stays in the ignored `local/`; the repository keeps
manifests and hashes, and a per-version size budget is part of the suite
(`scripts/repo_evidence_budget.py`). New evaluation sources go under
`evaluations/<version>/`, outside the test suite.

| Path | Contents |
|---|---|
| `backend/workbench/` | Engine, model packs, contracts, HTTP layer, Agent |
| `frontend/src/` | React UI: data editor, lineage graph, result views, Agent panel, reports |
| `tests/` | Backend suite, oracles, golden and invariant snapshots |
| `docs/manual/` | User manual and developer handbook |
| `docs/releases/` | Release notes, one per version |
| `docs/superpowers/` | Working documents: objectives, evaluations, roadmap, backlog |
| `scripts/` | Gate, live Agent evaluations, shared-dependency linking, contained launcher, git hooks, repository size budget |

Branches are deleted after they merge; every deleted branch tip is preserved
under an `archive/branch-tip/*` tag.
