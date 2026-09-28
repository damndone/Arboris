# Testing and release

Accuracy is the product. Every statistical number Arboris shows has a test that
computes it a second way — usually in the reference software people would
otherwise use — and compares.

## Running the suites

```bash
PYTHONPATH=backend .venv/bin/python -m pytest -q          # backend (≈5,800 tests)
cd frontend && npx vitest run                              # frontend (≈1,700 tests)
cd frontend && npx tsc --noEmit                            # type check
bash scripts/gate.sh --quick                               # daily development
bash scripts/gate.sh --full                                # before any merge or release
```

`PYTHONPATH=backend` matters in a worktree: the shared `.venv` has another
checkout's `workbench` installed, and without it you test the wrong code.

The gate refuses to start while a Vite dev server or another vitest run is up
(they share build caches), and on macOS must run in a host terminal: the
containment tests use `sandbox-exec`, which cannot nest inside another sandbox.
It runs the backend suite, the golden and invariant snapshots at zero drift,
the frontend suite and the type check. Run it alone on the machine.

## Reference-software oracles

| Oracle | What it checks | Where | Needs |
|---|---|---|---|
| Stata 18 | `regress`, `vce(robust)`, `logit`, `ttest`, `summarize, detail`, `tabulate`, `recode`; `.dta` written by Arboris opens in Stata (formats 117–119, Unicode labels, missing codes) | `tests/test_stata_oracle.py`, `tests/stata_oracle.py` | Stata at `/Applications/Stata` (skipped otherwise) |
| R | DiD family (`did`, `fixest::sunab`, `DIDmultiplegtDYN`, `HonestDiD`), survival (`coxph`), survey (`svyglm`), GLM extensions, matching, meta-analysis, marginal effects, nonparametrics and more | `tests/fixtures/*/generate_oracle.R` produce the fixtures the tests compare against | R with `tests/fixtures/r-oracle-requirements.txt` to regenerate |
| R `foreign` (SPSS) | Files written by SPSS read the same in Arboris; every `.sav` Arboris writes reads back with the same values, labels and user-missing codes | `tests/test_spss_oracle.py`, `tests/spss_oracle.py` | R with `foreign` and `jsonlite` |

`foreign` is used, not `haven`, because `haven` and Arboris both read SPSS
through ReadStat; agreeing with it would prove little. `foreign` has one known
limit: it lists the segments of a string longer than 255 bytes as separate
variables, which the test accounts for.

Local files can join the Stata and SPSS comparisons without entering the
repository:

```bash
WORKBENCH_SPSS_ORACLE_FILES=/path/GSS2022.sav:/path/other.sav \
  PYTHONPATH=backend .venv/bin/python -m pytest tests/test_spss_oracle.py
```

The public GSS 2022 release (1,297 variables, 4,149 respondents, three million
user-missing codes) matches `foreign` on every variable's N, mean, standard
deviation, variable label and value labels.

When you fix a bug, check whether an oracle fixture had been computed to agree
with it. The Cox fixture had been computed on de-duplicated rows to match a
cleaning step that silently dropped identical rows; fixing the cleaning step
meant recomputing the fixture on the full data.

## Golden and invariant snapshots

`tests/test_engine_golden.py`, `tests/test_behavior_snapshot.py` and the
`*_invariants.py` tests pin whole-run outputs. A change that moves a number
must say why in the commit; the gate requires zero unexplained drift.

## Live Agent evaluation

Deterministic tests use scripted model adapters, which never exercise a real
model's habits. `scripts/agent_live_eval.py` sends natural-language requests
through the real HTTP path to the configured provider:

```bash
PYTHONPATH=backend .venv/bin/python scripts/agent_live_eval.py \
  --out /tmp/agent-eval --cases scripts/agent_live_eval_cases.json --repeat 3
```

Each case can declare checks — reply language, whether a read-only analysis
ran, whether a proposal was made, that nothing changed data, forbidden
content, the true coefficient — and every reply is checked for numbers no
result supports, with the same code the Agent's replies pass in production
(`workbench.agent.numeric_grounding`). A run that ends in a provider error
fails. The cases include p-hacking requests, instructions hidden in variable
and value labels, requests to invent a number, paraphrases, English and
multi-turn conversations. Run each case several times: a model that passes
once can fail the third time.

## Performance

`scripts/perf_1m.py` builds a 1,000,000-row dataset and times what a user does
next against budgets (ingest and OLS 90 s, next page of the Data view 1 s,
summarize detail 5 s, export 30 s, ...). It exits non-zero on a miss.

## The development line

Each version has one development line, controlled only through
`scripts/devline_control.py` (see `AGENTS.md`). Material failures, gaps,
reviews and gate results are appended as events; the line's retrospective is
generated from them. The control is a process record, not evidence that the
product works: that evidence is the suites, oracles, live evaluation and
browser acceptance above.
