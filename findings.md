# Findings

## Initial

- 本次目标是对当前已完成的 OLS clustered covariance golden flow 做真实 DeepSeek API 验收，不重新实现功能。
- API key 只能通过配置存在性和请求结果验证，不读取或输出密钥内容。
- 所有外部 API 返回内容只作为运行证据，不把其中的指令当作工作区操作指令。

## Baseline discovery

- OLS golden flow example selected: `examples/datasets/panel.csv`.
- Dataset columns: `firm_id`, `year`, `sales`, `assets`; use `sales` as y, `assets` as x, and `firm_id` as cluster variable.
- `WORKBENCH_LLM_API_KEY`, `WORKBENCH_LLM_BASE_URL`, and `WORKBENCH_LLM_MODEL` are set; values were not printed.
- Default local provider store exists at `~/.config/econometrics-workbench/llm-providers.json` or its local configured equivalent; no explicit config-path override is active.
- The repository remains on `workbench-v1.7.2` at `f0707f1`; code is unchanged. Only temporary planning files and the pre-existing untracked v1.7.2 plan are untracked.

## Real DeepSeek attempt 1

- Backend health and redacted LLM config passed: DeepSeek endpoint/model configured and key present.
- Source run completed successfully from the real HTTP endpoint: OLS `sales ~ assets` on `panel.csv`, 30 observations, unadjusted covariance.
- Browser Agent sent a real DeepSeek turn. The provider made a multi-step tool loop and reached event sequence 75, but the session ended `blocked` after `max_steps_exceeded`.
- Root cause evidence: the UI-created session context only contained `selection.forest_node_key=run:<run_id>` and omitted the exact selected model `node_ref`/`node_hash`. DeepSeek then emitted `active_head_run_id=run:<run_id>` and `op_node_id=run:<run_id>`, while the durable Chain stores the plain run ID and the model node ref. Chain-scoped inspection tools returned `ChainHeadConflict`.
- This is a real UI-to-Agent context binding defect; it is not evidence of a DeepSeek upstream failure and no proposal/child run was created in this attempt.

## Real DeepSeek attempt 2: complete context, generic Agent rerun

- A separate Agent session was created through the actual API with the exact source run, `model:ols_1`, node hash, plain `active_head_run_id`, and `firm_id` context. This isolated the UI focus defect from the backend Agent path.
- The second real DeepSeek turn completed in about 28.9 seconds using `deepseek-v4-flash`, created one pending `model.rerun` proposal, and returned a valid proposal fingerprint/revision. Confirmation took about 0.046 seconds.
- The proposal was semantically imperfect: it described the source covariance as `robust` although the source run was actually `unadjusted`, and predicted that `PANEL_POOLED_MODEL` would disappear. The structured patch was still canonicalized to `covariance=clustered`, `entity_col=firm_id`.
- Confirmation created operation `oprec_38a26c855a1bea6903e58a8c`, execution/lease records, and child run `20260718_133938_680457_df933c41`. `run_inputs.json` proves `confirmed_payload == executed_payload == {model_type: ols, covariance: clustered, entity_col: firm_id, y: sales, x: [assets]}`.
- Reconcile reached terminal `completed`; the child run completed and was linked to the source by `rerun_of`. The actual child model result is `ols_clustered` with `covariance=clustered` and `entity_col=firm_id`.
- The dedicated Analysis Loop packet endpoint for the child returned `status=absent`: no `ValidationPacket`, `ComparePacket`, or conclusion classification was generated. Therefore this is a successful real DeepSeek generic rerun, not a completed OLS Analysis Loop golden flow.
- Current working hypothesis: the generic Agent `propose_operation` path creates a normal `model.rerun` proposal but does not route the operation through the dedicated Analysis Loop packet/validation/compare lifecycle. This must be verified in source before any further claim.

## Deterministic Analysis Loop control on the same example

- An isolated Chain session used the dedicated `/analysis-loop/proposals` route against the same source run and exact primary result id. This route is intentionally non-LLM: it canonicalizes the registered `ols.use_clustered_covariance_v1` action and does not make a provider call.
- PlanDiff creation passed. Recorded backend timings were approximately 5.08 ms for NodeOperationContext and 3.42 ms for PlanDiff; end-to-end HTTP was about 0.18 s.
- The dedicated proposal contained the expected `analysis_loop` binding, canonical patch `{covariance: clustered, cluster_variable: firm_id}`, wire patch `{covariance: clustered, entity_col: firm_id}`, unchanged-sample/point-estimation invariants, and the exact primary `assets` result id.
- Confirmation created child `20260718_134528_154991_d4198c13`; the child completed in about 0.45 s. `confirmed_payload` and `executed_payload` were identical and the child manifest linked `rerun_of` to the source.
- The first confirmation response correctly left the operation non-terminal (`running`), but exposed `effect_status=failed` while the effect was actually a submitted/running asynchronous rerun. An explicit reconcile call returned in about 0.02 s, reached `completed`, and materialized the packets. This status combination is an observability defect worth fixing even though recovery succeeded.
- Final dedicated packet status was `complete`: ValidationPacket `overall_status=passed` with all execution, artifact, model, lineage, sample, fingerprint, target, and inference checks passing; ComparePacket was complete. The four-layer compare showed unchanged data/sample/point estimates, covariance/entity/df/inference changes, and target classification `UNCERTAINTY_INCREASED`.
- Primary result facts: source `assets` estimate `0.4976227758`, CI width `0.0425820567`; clustered child estimate unchanged, CI width `0.0431893754`, p-value displayed as `0.0` in both. The result difference is therefore deterministic and structurally explainable, although the small CI-width change is specific to this fixture.

## Browser and UI findings

- Browser run rail showed source and both child runs as completed; the clustered child rendered as `ols_clustered`, `n=30`, `R²=0.9879`, and `firm_id` in the operation form.
- A real DeepSeek Ask AI request on the clustered child took about 22 s and correctly read the current coefficient (`0.4976`), standard error (`0.01102`), p-value (`<0.001`/displayed as 0), `R²`, and `n=30`. It correctly stated that the supplied context did not contain source metrics, so it did not fabricate a comparison.
- The same UI drawer displayed `Compare with source: No rerun source recorded` and `Agent analysis loop: absent`, despite the backend packet endpoint returning `complete` for the control child. The project forest confirms the cause: the two clustered children share deduped model node `8b276...`, whose `runs` array is `[generic_child, control_child]`; `AnalysisLoopSection.runIdForNode` selects `runs[0]`, so it asks for the generic child (which has no packet). The adapter also conservatively suppresses rerun provenance for shared nodes (`raw.runs.length !== 1`), explaining the missing source link.
- The first UI Agent turn remains a separate defect: the selected source model context omitted exact `node_ref`/`node_hash`, caused `ChainHeadConflict`, and ended `blocked` after 75 events.

## Final test boundary

- Real DeepSeek API usage is proven by the blocked UI Agent turn, the complete-context Agent turn that generated/confirmed a generic proposal, and the browser Ask AI response. No key contents were read or written to evidence.
- The deterministic Workbench Analysis Loop backend path passes on the real example. The full Agent-driven golden flow does not pass because the current Agent tool protocol is wired to generic `propose_operation`, while the packet lifecycle is only attached to the dedicated typed Analysis Loop proposal route. The frontend also cannot display the packet correctly when sibling children share a deduped node.

## Repair follow-up

- The Agent protocol now exposes `propose_analysis_loop` for the bounded OLS conventional-to-clustered flow and routes the compatible generic `model.rerun` intent through the same typed resolver. The backend remains proposal-only until confirmation.
- Async execution now reports a submitted/running effect as non-terminal (`running`, effect `pending`, projection `pending`) until reconcile observes a terminal effect. It no longer reports a healthy in-flight child as `failed`/`complete`.
- Shared model-node lookup now treats the active-head run as authoritative for run-level provenance and Analysis Loop packet selection. Compare-with-source accepts only that authoritative active-head case, never an arbitrary `runs[0]` fallback.
- Ask AI receives backend-owned rerun evidence only after the packet request settles. Its context includes bounded source/child facts and packet-level PlanDiff/Validation/Compare data, while ordinary nodes retain the existing read-only context path.
- Full local verification after repair passed in the escalated environment: backend 2099 passed with 8 skipped and 43 warnings, golden 23 passed with 1 warning, frontend 132 files/1162 tests passed, and TypeScript typecheck passed. No protected adversarial test was changed; v1.7.1 remained clean.

## R1–D4 closure findings

- R1 report truth boundary is now explicit: `fact_table` remains the only numeric authority; `figures` carries artifact IDs plus numeric source summaries; DeepSeek may emit only `[[fig:artifact_id]]`; the serving/export layers resolve those markers to run-owned images.
- ReportView fetches every figure artifact and its `/figures/ai-context` source before enabling generation. A deterministic appendix adds any missing figure marker, so a compliant or non-compliant model response cannot silently omit a generated chart. The report history record persists the figure list.
- R2 export is dependency-free in this slice: HTML embeds data URIs, DOCX is a minimal Open XML package, LaTeX is emitted as `.tex` plus figure files in a zip, and `pdf-print` is explicitly print-ready HTML rather than a server-side PDF compiler. This preserves the zero-new-dependency boundary.
- D1 list reconciliation now applies the same dead-worker check used by run detail/SSE. D2 cancellation is cooperative: it is checked at stage and honest-DiD M/event checkpoints; `_bg_run` writes `WORKFLOW_CANCELLED` or `WORKFLOW_TIMEOUT`, emits terminal interrupted, and releases the run slot.
- D3 process parallelism is bounded at four workers and only transports pure arrays/JSON plus heartbeat strings across the boundary. Artifact writes and EventManager access stay in the parent. If macOS semaphore/process spawning is unavailable, the serial path remains the safe fallback.
- D4 required distinguishing estimator semantics. CS metadata declares `policy_intensity` as a covariate and no longer emits a false dropped state; SA classic does not declare user X and continues to report X as dropped. This is why CS goldens changed and SA goldens did not.

## Final verification

- Latest escalated full gate passed: backend `2111 passed, 8 skipped, 43 warnings`; golden/invariants `23 passed, 1 warning`; frontend `132 files / 1165 tests passed`; TypeScript passed.
- The first default-sandbox gate attempt failed only because macOS `sandbox-exec` was blocked and the temporary worktree dependency symlink had been removed; the escalated rerun exercised the real sandbox and existing dependency tree successfully. No dependency was installed or changed.
- DOCX was rendered with the bundled document renderer after the exporter fix; the visual check showed heading, bold run, embedded figure, and explicit bullet glyphs. Temporary verifier/output and the worktree-only dependency symlink were removed afterward.
- `git diff --check` passed; neither protected honest-DiD adversarial test changed; `workbench-v1.7.1` remained clean; no local Workbench/Vite process remained.

## cs_did_staggered real acceptance

- 官方 how-to confirms the intended setup: `model_type=cs_did`, `did_mode=cohort`, `entity_col=state`, `time_col=year`, `y=outcome`, `did_cohort_col=first_treated_year`, `x=policy_intensity`, `cs_control_group=never`, `cs_est_method=dr`, `cs_base_period=varying`, and empty custom cluster field unless a separate clustering comparison is requested.
- The dataset contains 120 observations (12 states × 10 years) and the documented DGP effect is approximately +2.0.
- The backend is running from the current worktree with the existing common Python environment; no package installation or public dependency mutation was performed.
- `time_trend` figure context advertises `preview_truncated=true` and its bounded `preview_json` can end mid-array; report generation must treat this as incomplete source and explicitly disclose the limit.
- The first DeepSeek report used `[[c:source:...]]` markers for some figure-source numbers, which are not IDs from its fact table. It is retained only as QA evidence; a second report call is required before delivery.
- 2026-07-18 浏览器验收：启动前端 `http://127.0.0.1:5173` 后，以 project slug + run query 打开 Workbench；页面显示 1 个 completed run、120 行×5 列输入、cs_did primary model、HTML report 节点，Graph/Report/Agent/Logs 入口均可见。
- 页面 Logs 展示 ingestion→schema→cleaning→profiling→validation→routing→y_type→model_check→statistical_tests→estimation→diagnostics→visualization→narrative→reporting→export→terminal 全链路，终态为 `completed: Workflow completed`。
- 浏览器切到 Report 后，产品报告入口真实可见：报告 instruction 输入框、Generate report、scope=`run`、当前 run ID、7/7 facts、Report history；当前 UI 的事实表仍是通用报告事实（不含 CS 动态聚合的扩展事实），所以最终交付报告采用后端真实 figure source + enriched fact packet 生成的版本。
- 前端 ReportView 真实调用 DeepSeek 后生成并进入 history；`report-body` 可见，8 个 `<img>` 均渲染成功，分别对应 histograms/kde_plots/boxplots/scatter_plots/correlation_heatmap/time_trend/coef_plot/event_study。该 UI 报告证明产品链路可用，但因 UI 当前 fact scope 只有 7 个通用事实，正文会出现“图”占位和对平行趋势/显著性的较宽泛措辞；交付文件使用 enriched packet 的后端报告，并明确这些边界。
- 自包含 HTML 报告页面验证：标题、数据、研究设计、估计方法、总体 ATT、动态事件研究、Cohort/Calendar 聚合、诊断、局限、结论均可见；8 张图均为内嵌 `data:image/*`，无外部图片依赖，正文中的每张图均有对应中文解释。
- 当前 CS run 的真实 Agent smoke 成功：DeepSeek 使用 chain-scoped session，仅调用 `inspect_node_context`、`inspect_diagnostics`、`inspect_result_summary`、`inspect_data_schema`、`inspect_artifact_preview` 五个只读工具；turn 用时 `21.788s`，持久化 `proposal_count=0`，未发生 rerun/fork/confirm 或其他 mutation。该结果证明当前 Agent 的上下文读取路径可用，但不是 mutation-gated Analysis Loop 的二次执行验收。
