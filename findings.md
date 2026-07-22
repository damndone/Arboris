# Findings — v1.7.3 Integration

- Integration is a dirty, uncommitted assembly workspace at lock `0251f0a`; it is not yet a release candidate.
- Current native frontend evidence is real Integration evidence: `npm ci --offline --ignore-scripts`, focused repeated-measures tests 38/38, full frontend 1211/1211, and typecheck pass.
- The former full-suite failure was a contract-fixture/test assertion mismatch, not an LMM/UI behavior failure.
- WO-A's risk is filesystem persistence authority: all reads/writes must be capability-bound and not reopen paths or reconstruct authority.
- WO-D's risk is execution attribution: C1 is source-only/fail-closed; C2 must not be represented as executable evidence before host canary acceptance.

## v1.8 VIX browser reproduction — 2026-07-21

- Authoritative input is the attached 1013-line Stata Do-file and committed `examples/datasets/VIXCLS.csv`.
- The Stata reference uses joint ARMA(1,1)-GARCH(1,1) MLE, while v1.8 intentionally refuses joint estimation when MA q>0. Parameter equality and joint variance-model IC replication are out of scope; workflow/directional evidence must remain explicit.
- Required visible coverage includes data audit, trading-day semantics, level/log/difference/log-return profiles, ADF/ACF/PACF, ARMA candidate IC, mean residual and squared-residual diagnostics, ARCH signal, sequential variance candidates, conditional variance/volatility, standardized residuals, rolling intervals, next observation, ARMA-only comparison, persistence/half-life, QQ/normality, and chart gallery.
- User explicitly authorized real DeepSeek API calls through natural-language Agent interaction.
- The visible browser successfully uploaded `examples/datasets/VIXCLS.csv` through a real file chooser; the earlier handoff warning that the embedded browser had no upload mechanism is stale for the current Browser plugin.
- The new project reports the expected raw shape: 2,610 rows and two columns (`observation_date`, `VIXCLS`).
- Selecting ARMA-GARCH in the Genesis/new-analysis drawer does not itself reveal the graph-native five-step controls. Source wiring places those controls in `RunForm` and the graph-node `ArmaGarchOperationSection`, so the next check is the model-node drawer rather than immediately treating the absence as a runtime bug.
- The persisted provider is a real DeepSeek endpoint with a present secret, but its active model is currently Flash. The user's explicit requirement is `deepseek-v4-pro`, so no paid Agent turn is valid until the visible provider setting is changed.
- The visible provider selector successfully persisted `deepseek-v4-pro`; both the node Ask AI card and Agent model selector subsequently showed DeepSeek V4 Pro.
- The supported but off-navigation `/submit` route contains the complete five-step ARMA-GARCH form and can submit the workflow against the current project. This permits QA without modifying product code, but it does not cure the Genesis integration defect.
- Raw-run evidence: `20260721_200829_505438_443bf21a` failed with `VALUE_PARSE_FAILED: value column contains missing entries`. That conflicts with the reference Do-file's explicit `drop if missing(VIXCLS)` and prevents the advertised raw VIX known-truth fixture from running end-to-end without preprocessing.
- Real Agent evidence: session `agent_chain_9bdac9db230b4ac1873e4eb6495cfc4b` used DeepSeek V4 Pro, ended idle after 111 events and 1,473 displayed context tokens, and correctly concluded that row deletion is unsupported. It made many failed inspection calls because the failed run had no model node and only the OLS clustered-covariance analysis-loop operation was registered.
- The failed run's raw data drawer exposes a sandboxed Python editor, but both `Run preview` and `Apply as new node` remain disabled even after valid filtering code is entered. This makes the visible fallback non-operational for this failed-run node.
- A mechanical derivative `/private/tmp/VIXCLS_nonmissing.csv` was created with only the Stata-equivalent missing-value deletion: 2,542 data rows plus header, versus 2,610 raw rows plus header; no blank VIXCLS values remain.
- Manual run `20260721_201344_532869_f49478a8` completed with ARMA(1,1)-GARCH(1,1), 20/20 rolling origins, RMSE 7.4409, pinball 0.5840, coverage 1.0, persistence 0.775232, half-life 2.722574, a complete full-sample child, and 17 structured chart artifacts.
- The manual run has 2,520 aligned finite conditional variance/volatility pairs and satisfies `h_t = sd_t^2` with maximum absolute difference 0.
- Automatic run `20260721_201913_716716_77fe0555` evaluated 26 mean and 12 variance candidates, froze selection before validation, and selected ARMA(2,1) without a constant plus ARCH(4). It completed 20/20 origins with RMSE 7.5304 and pinball 0.5842.
- The frontend gallery visibly renders 16 figures from 17 chart artifacts: `series_transform` yields two figures, while the zero-row `model_comparison` and `quantile_exceptions` artifacts are not rendered as separate charts.
- Generated stage nodes have correct artifact ownership but broken drawer audit context: `missing_node_hash`, empty upstream path, disabled Ask AI/code actions, and a terminal result card repeated in every stage drawer.
- The Report builder exposes 37 generic facts but omits the time-series parameter, diagnostic, forecast, persistence, and rolling-validation artifacts; `model_options` appears as `[object Object]`.
- Visible Compare created project-forest node `1def99e0515e071532df71a76bce4413c1919ce0db7d18877f496af571b5dd41` without writing either run's `graph.json`, but integrity validation blocked it with `SOURCE_CHILD_LINEAGE_MISMATCH` and `SPLIT_HASH_MISMATCH`.
- The two compared runs have the same analysis-view hash, sample counts, and exact 20 forecast-origin/target row IDs. Their split payloads differ only in `contract_hash` and derived `split_hash`, proving model options are incorrectly part of frozen-split identity for Compare.
- Durable browser QA report: `docs/superpowers/handoffs/2026-07-21-v1.8-vix-browser-reproduction.md`.

## v1.8 browser debug closure — 2026-07-21

- The earlier gap list above is historical discovery evidence, not current product status. The current fixed project is `/private/tmp/wb-v18-vix-fixed-20260721`.
- The original 2,610-row VIX file now runs without a derivative CSV when the user explicitly confirms `drop_missing_confirmed`; 68 excluded observations remain auditable and the source upload is unchanged.
- Blocking missing values still produces a truthful configured-not-fitted tombstone (`20260721_215735_929627_e6a8dcb8`, `VALUE_PARSE_FAILED`).
- Real DeepSeek V4 Pro recovered the failed run through a typed, confirmed patch. The first execution exposed a shallow nested merge; key-wise section merge now preserves unpatched ARMA keys and the second proposal completed child `20260721_220801_961534_7896256d`.
- The Report now exposes 80/80 citable facts, including transform, missing policy, sequential estimation semantics, 2,542 analysis observations, and 68 excluded observations; real-provider report `rpt_mrv708hf_avts5k` was regenerated.
- Automatic rerun `20260721_221730_928253_74b5a888` completed after project-wide unrelated node sharing was removed from the family-scoped write fingerprint. It selected ARMA(2,1), no constant, plus ARCH(4) from training evidence only.
- Compare read resolution now follows the active run's nearest owning ancestor. Its persisted reader now includes `ts.train_validation_split`, so identical row membership is not falsely blocked by different contract-bound split hashes.
- Durable compare node `91181f965958880ef2ec9aba272f1ee2921c0518d7a61add15309c5483c898ac` is complete, has no integrity findings, and concludes `COMPARABLE_WITH_NO_AUTOMATIC_WINNER`.
- All 17 chart artifacts load and 18 visible panels are represented; the four missing Stata sequence charts and browser-safe SVG export are covered by regression tests.
- Remaining model limitation is deliberate: joint MA-GARCH estimation is excluded and reference semantics remain `directional_or_workflow_regression`.
- Table's generic gallery previously filtered strictly on `artifact_type === "figure"`, so it exposed only the four EDA PNGs and relegated all 17 ARMA-GARCH `time_series_json` chart artifacts to download links. The Table view now reuses the existing structured chart loader/gallery; real VIX browser QA shows 17 loaded artifacts, 18 displayed panels, 16 downloadable SVG figures, one comparison table, one exception-state panel, and zero console errors.

## v1.8 delivery artifact and release-truth audit — 2026-07-21

- The browser result and its structured `ts.*` artifacts are not the same thing as a publishable human deliverable. The VIX browser session proves the former, not the latter.
- `reports/report.html` and `report.pdf` are legacy deterministic summaries, while the richer DeepSeek report seen in the UI is browser-local. Calling both “the report” is a two-source-of-truth defect.
- Three inspected successful ARMA–GARCH VIX workbooks each contained only an empty `coefficients` sheet. The report stage supplies only `_coefficient_rows_for_models(model_results)` to `export_xlsx`; ARMA–GARCH’s meaningful data live in `ts.*` artifacts, so a non-empty export requires application work and a real acceptance test.
- Compare is computationally conservative for the inspected VIX runs: same analysis membership, manual ARMA(1,1)-GARCH(1,1) versus automatic ARMA(2,1)-ARCH(4), and no automatic winner. Its machine JSON alone is nevertheless not a review-ready explanation, and “contract hash changed” must not be phrased as “the sample changed” when frozen membership matches.
- Agent parent session JSONL is a valid audit source but not a complete human transcript, because confirmed execution and the final child can be recorded in separate child/operation records.
- The exact current tree remains dirty and has no final candidate SHA. Existing green browser/gate evidence is useful but cannot substitute for a host full gate and independent acceptance on the final immutable candidate.
- v1.8 therefore remains `directional_or_workflow_regression`. The joint ARMA(p,q)-ARCH/GARCH conditional-MLE work package is recorded in `docs/superpowers/followups/BACKLOG.md`; it requires a frozen Stata oracle, explicit conditioning, joint LL/IC, convergence, conditional-series and forecast parity before any numerical-reproduction claim.

## Failure-memory design decisions

## v1.8 delivery closeout — 2026-07-22

- The delivery fixes use the registered `ts.*` artifacts as their deterministic source: VIX run `20260722_011832_368932_550d4414` completed with a 6.4 KB report HTML, 9.4 KB report PDF, and 11 KB eight-sheet workbook (Overview 11 rows, candidates 2/2, Parameters 7, Diagnostics 2, Rolling forecasts 21, Next forecast 8, Acceptance 8).
- A first direct VIX rerun correctly failed because the submitted contract omitted the confirmed missing-value policy. The preserved failed run is `20260722_011653_897158_febaef6e`; the successful rerun carries `drop_missing_confirmed` and retains the original source unchanged.
- The restricted complete gate was not a valid pass: it stopped around 60% at the nested sandbox/code-execute tests. The independent host rerun of those exact tests passed 33/33, and the non-sandbox test groups that appeared in cache passed 121/121. This is an environment limitation pending Claude's independent Step-5 acceptance, not a concealed green full gate.
- The in-app Browser control channel returned a stale-session error during final visible QA. Existing browser evidence remains historical; the final source-level and real-VIX checks are durable. Do not label the current browser QA as passed until Claude repeats it on the final candidate.

- Events are append-only JSONL and validated before append.
- Promotion is deterministic by normalized issue fingerprint: line memory at one event, candidate global rule at two distinct line occurrences, mandatory global rule/automation candidate at three.
- Metrics are computed from event history, not hand-entered totals.
- Token waste is reported as `unknown` unless an event explicitly marks a numeric token measurement as measured; zero is not used as a placeholder.
- The 1/2/3 promotion threshold is event-occurrence based, including repeated churn within one line; limiting it to distinct lines would hide WO-A's repeated persistence boundary failure.
- Token measurements are optional numeric evidence; unknown is recorded as unknown rather than estimated.
