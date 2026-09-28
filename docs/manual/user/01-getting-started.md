# Getting started

## Starting Arboris

Arboris is a backend server and a web interface, both on your own computer.

```bash
./scripts/run-local-contained.sh        # backend on http://127.0.0.1:8000
cd frontend && npm run dev               # interface on http://localhost:5173
```

`run-local-contained.sh` starts the backend in the profile that allows
sandboxed code (`code.execute`) and linear mixed models; the plain
`uvicorn workbench.api:app` start refuses both. To use the Agent, configure a
language-model provider under **Settings** (the gear at the top right): a
provider name, its base URL, an API key and a model. Without one, everything
except the Agent and AI-written text works.

## Projects

A project is a folder: your imported data, every run, and the project's
records (the Agent's conversations, the analysis ledger, the data-sharing
policy) live inside it. Nothing is stored anywhere else.

**Home → New project** asks for a *Parent folder* (an absolute path the
backend can reach, e.g. `/Users/you/research`) and a *Project name*; the
project is created as a folder inside it and opens straight into the import
step. **Home** lists recent projects. Opening Arboris again takes you back to
the last one. If a project folder has been moved or deleted, you get *Run not
found* with **Back to Home**, which shows the project as stale with a
**Remove** button (removing it from the list leaves files on disk alone).

## Importing data

**Import data and create analysis** opens the **New pipeline** panel. It has
four steps, done in order.

**1. Data file.** Choose a file:

| Format | What comes with it |
|---|---|
| CSV (`.csv`) | values only |
| Excel (`.xlsx`) | values; choose the sheet in step 2 |
| SPSS (`.sav`, `.zsav`) | variable labels, value labels, user-missing codes, measurement levels |
| Stata (`.dta`) | variable labels, value labels |

The panel reports the rows and columns found, and shows one card per variable
with its type, number of distinct values, mean and standard deviation. For
SPSS and Stata files, the codes the file declares as missing (in the GSS,
−100 "inapplicable", −99 "no answer", −98 "don't know" ...) are left out of
those figures, so the cards describe answers, not codes. The original file is
copied into the project and never changed.

**2. Table.** For Excel, the sheet. *Transpose* is for a file stored sideways
(variables in rows). **Save table**.

**3. Model.** The first analysis of the project:

- *Model type* — **Auto (infer from y)** picks OLS for a continuous outcome,
  logit for a binary one, Poisson for counts, and multinomial or ordinal logit
  for categories. Or choose one of 22 families directly: OLS, logit,
  probit, Poisson, negative binomial, GLMs, panel OLS, linear mixed effects,
  IV/2SLS, four difference-in-differences estimators, ANOVA/ANCOVA,
  multinomial and ordinal logit, quantile regression, Cox, ARMA-GARCH, ETS.
- *Impute missing values (MICE)* — off by default: rows missing a model
  variable are dropped (complete cases), which the run reports. Consider it
  when more than 5–10% of rows would be dropped.
- *Frequency*, *Analysis* and *Sampling weight* — a sampling weight also needs
  a survey design (strata, PSU, FPC or replicate weights); without one the run
  is refused rather than guessed.
- *Covariance* — *Robust* (HC1, the default), *Clustered* or *Unadjusted*
  (what Stata's `regress` reports without options).
- *Dependent variable (y)* and *Regressors (x)* — pick y from the list, then
  type the regressors or tick **x** on the variable cards. Choosing y fills x
  with every other variable; clear it and list the ones you want.

**Save model**, then **4. Run → Validate and run**. The run appears in the
**Runs** list on the left and in the graph; the **Logs** tab at the bottom
shows each stage as it completes.

Rows are never removed silently. Identical rows are kept — in survey data they
are different people — and the run tells you how many there are; declared
missing codes are treated as missing and reported per variable.

## The workbench

| Tab | What it shows |
|---|---|
| **Graph** | The lineage graph: every stage of every run as a node. Click a node for its details and the actions on it. |
| **Data** | The SPSS-style Data View and Variable View of any dataset node, with transforms, export and AI sharing settings. See [Working with data](02-data.md). |
| **Table** | Results: coefficients, Table 1, statistical evidence, figures, saved explorations, data export. |
| **Report** | The report writer, the analysis path, and exports (HTML, Word, LaTeX). |
| **Notebook** | Plan an analysis in words; Arboris proposes evidence-backed options. |

At the bottom: **Agent**, **Logs** and **AI activity**. At the top right:
**New analysis** (a new first run from a new file) and **Rerun** (run the
current analysis again with changes).
