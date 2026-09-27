# Analysis

## Descriptive statistics

Click a dataset node in the **Graph** (*Raw input data*, *Cleaned data*, or one
a transform created) and open **Statistical exploration**:

| Action | Stata equivalent |
|---|---|
| **Summarize** | `summarize` |
| **Summarize detail** | `summarize, detail` — Stata's percentile definition, variance, skewness, kurtosis, the four smallest and largest values |
| **Missing values** | `misstable summarize` |
| **Frequencies** | `tabulate`, with value labels and a row for missing |
| **Correlation** | `pwcorr` |
| **Derived percentile variable** | a grouping variable from a percentile cut (e.g. top quartile) |
| **Scatter plot** | `scatter` |

Choose the **Variables**, optionally **Group by** a variable (for Summarize)
and **Filters (AND)**. **Preview** shows how many rows the
filters keep and the missing-value policy (*variablewise*: each variable uses
its own non-missing values). **Save exploration** stores the result; it
appears under *Statistical exploration* in the **Table** view, laid out as
Stata prints it. **Use filtered context for OLS** fits a regression on exactly
the filtered rows.

Anything here can also be asked of the Agent, which runs it at once — including
grouped *Summarize detail*, which the panel does not offer.

## Tests

Every run computes a standard set of tests on its variables and shows them in
the Table view under *Statistical evidence*: Welch t-tests, ANOVA, chi-square
and Fisher exact tests, Pearson, Spearman and Kendall correlations,
Mann–Whitney and Kruskal–Wallis, with effect sizes (Cohen's d, eta and omega
squared) and assumption checks (Levene, Bartlett, Shapiro–Wilk). These are
computed automatically for context and are *not* counted as tests you ran.

For a specific test — *is the wage difference between men and women
significant?* — ask the Agent. It runs the test at once and answers with the
statistic, the p-value and how many tests have been run on this data so far;
every one of those is recorded and disclosed in the report
([Trust and records](05-trust.md)). The full list of tests and packs, from
power analysis to spatial statistics, is in the
[capability reference](../reference/capabilities.md).

## Models

The first model is set up when you import data. After that:

- **Rerun** (top right) opens the model node's **Rerun source with changes**
  panel: the model family, which regressors to keep (untick to drop one), the
  covariance (*robust*, *clustered* with a cluster variable, *unadjusted*),
  weights, and the survey design (strata, PSU, FPC, replicate weights and
  method, the single-PSU policy, subpopulation). **Preview source changes**,
  then confirm: the current run stays as it is and the change becomes a new
  child run. To add a variable that was not in the model, start from the data
  (below) or ask the Agent.
- **Run OLS from this data node** on any dataset node fits a regression on that
  dataset — for example on the subset a transform produced.
- **Notebook** plans an analysis from a question: describe what you want to
  find out under **Plan**, and it proposes evidence-backed options (models,
  diagnostics, comparisons) to choose from. Nothing runs until you confirm.
- The **Agent** can fit, change and compare models from a sentence (*add
  experience squared*, *run a logit of union on education and female*); each
  is a proposal you confirm.

A model node shows its specification (*realrinc ~ educ + age + sex*), the
estimated equation, and the **Decisions** Arboris made — *Model type: OLS, y
appears continuous; Standard errors: HC1, system default* — each with its
alternatives. *Review required* marks decisions taken by default that you may
want to confirm or change.

## Results

The **Table** view shows, for the selected run:

- **Coefficients** — each term by its variable label, with estimate, standard
  error, p-value and 95% CI, plus n, R² and adjusted R² (or the family's own
  fit statistics); significance-star cutoffs are adjustable where stars are
  shown.
- **Table 1** — N, missing, mean and SD of every variable.
- **Statistical evidence** — the tests above.
- **Post-estimation** — joint F tests, White's test and quadratic turning
  points, when a workflow computed them.
- **Figures** — histograms, density and box plots, a correlation heatmap,
  category counts, scatter plots, residual and Q–Q plots, a coefficient plot,
  residuals and fitted values against each regressor. **Ask AI about this
  figure** explains one from its underlying numbers, not its pixels.
- **Statistical exploration** — the explorations you saved.
- **Export data** — the run's datasets (see [Working with data](02-data.md#export)).

**Download the authoritative result table as XLSX** (the **Result table**
button in the Report tab) exports the numbers exactly as computed.

## The lineage graph

The **Graph** is the record of an analysis. Each run is a chain of nodes —
*Raw input data → Cleaned data → variables → model* — and every rerun,
transform and fork adds nodes rather than changing any. Click a node for its
detail: what it is, the decisions behind it, its lineage path, **Ask AI about
this node**, **Compare with another node…**, and the actions available on it.
Views: *Horizontal*, *Vertical*, *Fit*, *Fullscreen*; **Runs → View all** lists
every run of the project.

## Reports

The **Report** tab drafts a report from a run's evidence. **New** starts one;
type what the report should cover in the box at the top, and choose which
results and figures it may draw on (*Include all* / *Exclude all* per group).
The writer may only use numbers from the evidence it is given, and each
number must carry a citation to its source; a draft that breaks this is
rejected, not shown.

Each report carries the **Analysis path** section — every test, model and data
change behind it, written by Arboris from the ledger, not by the AI; see
[Trust and records](05-trust.md#disclosure-in-reports). **Export** downloads
the report; **More formats** offers HTML, Word and LaTeX (.zip).
