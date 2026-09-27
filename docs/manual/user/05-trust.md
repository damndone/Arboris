# Trust and records

A result is only as good as the path that produced it. Arboris records that
path, discloses it, controls what leaves your computer, and checks its own
numbers against the software your reviewers use.

## Your data is never changed in place

Importing a file copies it into the project; the copy is never modified. Every
filter, recode, merge or missing-value rule produces a new dataset node in the
lineage graph, next to the original. A changed model is a new run that records
what changed. Arboris does not drop, deduplicate or repair data on its own:
identical rows, for example, are kept (in survey data they are different
people) and you are told how many there are; removing them is a *Dedupe* you
choose.

## The analysis ledger

Every analysis that runs and every change to data is recorded in the project's
analysis ledger (`workbench/analysis_ledger.jsonl`) — whether you did it in the
interface or the Agent did it, and whether you confirmed it or it ran as a
read-only analysis. Each entry says:

- **what** ran (the operation, and a readable sentence),
- **who** asked for it and **who authorized** it — you, the Agent with your
  confirmation, or the Agent under the read-only rule,
- **which data** it used (the source file's fingerprint),
- whether it **changed data**, and how many **inferential tests** it ran.

Deleting a run is recorded too, so a deleted analysis still counts.

## Disclosure in reports

Each report shows an **Analysis path** section, written by Arboris from the
ledger — never by the AI:

> 7 inferential tests (Agent without confirmation 5 · Agent confirmed by you 0 · you 2) · 2 models · 3 descriptive · 1 data change · 0 metadata changes · 0 runs deleted

followed by every data change, with when, who, and a one-line description. It
counts every test run on the report's data, including tests the report does not
show — this is what makes selective reporting visible.

Under the section:

- **Include in exported reports** — on by default. You may turn it off; the
  report then says *Exports omit this section; the change is recorded in the
  log*, and the change itself is recorded in the ledger.
- **Detail** — *Summary and data changes* (default) or *Full analysis log*,
  which lists every ledger entry.

## Sharing data with AI providers

The Agent and AI writing features send text to the language-model provider you
configure. What they may send is decided per project, by kind of content:

| Kind | Sent to a remote provider by default |
|---|---|
| Workbench state (operations, lineage, contracts) | yes |
| Column names and types | yes |
| Labels and missing-value codes | yes |
| Summary statistics and frequency tables | yes |
| Model results | yes |
| Individual rows | **no** |

A provider that runs on your computer (for example through Ollama) receives
everything by default. Everything else is replaced by a note, and the Agent
is told the content was shown to you and not to it.

To change it: **Data view → AI sharing…** lists what the current provider may
receive, with **Save for this project** and **Use default**, and **Recent
sends** — the audit of what was actually sent, when and to whom
(`workbench/egress/audit.jsonl`).

Columns can be protected individually in **Variable view → Sharing**:

- *public* — sent as the kind allows;
- *internal* — the default;
- *sensitive* — the column's values reach only a provider on your computer;
- *restricted* — its values reach no provider.

Columns whose names look personal — name, phone, email, address, ID card or
passport number, date of birth, in English or Chinese — are suggested as
sensitive; the suggestion is shown in the Sharing column and
takes effect until you choose otherwise. The column's name and label are still
sent, so the Agent can refer to it.

## How the numbers are checked

The Agent's numbers are checked against the results before you see them; see
[The Agent](04-agent.md#how-numbers-are-checked).

The statistics themselves are tested against the software your readers trust:

| Reference | What is compared |
|---|---|
| Stata 18 | OLS with conventional and robust standard errors, logit, t-tests, `summarize, detail` (percentiles, variance, skewness, kurtosis), frequency tables, recode; Stata opens the `.dta` files Arboris writes |
| R | Difference-in-differences (Callaway–Sant'Anna, Sun–Abraham, de Chaisemartin–D'Haultfœuille, HonestDiD), Cox models, survey-weighted regression, GLM extensions, matching, meta-analysis, marginal effects, nonparametric tests and more |
| R `foreign` (an independent SPSS reader) | SPSS files read the same in Arboris; the `.sav` files Arboris writes read back with the same values, labels and missing codes. Checked on the public GSS 2022 release: all 1,297 variables agree. |

Agreement is to within 1e-6 relative or better (most comparisons agree to 12
digits or more).
