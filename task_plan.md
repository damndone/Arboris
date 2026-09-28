# Real DeepSeek OLS Analysis Loop Acceptance

## Goal

在不修改代码、依赖或发布状态的前提下，启动当前 Workbench，使用 example 数据集和真实 DeepSeek API，执行并验证 OLS Analysis Loop golden flow，同时记录真实 API、Agent、后端与前端的性能证据。

## Constraints

- 工作目录：当前 v1.7.2 worktree。
- 不修改 v1.7.1 worktree。
- 不 push、PR、merge、tag。
- 不安装、卸载或修改公共依赖。
- 不修改受保护测试文件。
- 不在日志、报告或最终回复中暴露 API key。
- 真实 DeepSeek API 仅用于用户明确授权的本次验收。

## Phases

- [x] 1. 基线、example 数据集和 DeepSeek 配置只读核验
- [x] 2. 启动后端/前端并确认服务健康
- [~] 3. 用真实 DeepSeek API 执行 OLS Analysis Loop golden flow：真实 DeepSeek 通用 Agent 路径已验证但未生成 packet；同一 example 的专用确定性后端路径完整通过
- [x] 4. 浏览器可见验收与性能采样
- [x] 5. 保存证据、关闭服务、清理临时资源并报告

## Definition of Done

- 真实 DeepSeek 调用成功或产生可归因的失败证据。
- source run、proposal、confirmation、child run、ValidationPacket、ComparePacket 可关联。
- 记录 Agent/API/execute/packet/UI 各阶段耗时和失败原因。
- 浏览器显示最终状态，且不把静态 HTML report 误认为 LLM report。
- 所有开发服务已关闭；当前代码和发布状态未改变。

## Acceptance outcome

本次没有代码、依赖或发布状态变更。真实 DeepSeek 调用和 Workbench 执行均已完成并保留在 `/private/tmp/wb-v172-real-ols.2g6eop`。确定性 Analysis Loop backend golden flow 通过；Agent-to-typed-Analysis-Loop 接线和共享森林节点的 UI packet 选择未通过，因此不能把本次结果标记为“Agent 驱动 golden flow 完成”。

## Repair follow-up

- [x] 将 OLS clustered 意图接入 canonical typed Analysis Loop proposal
- [x] 修复异步 effect 在 reconcile 前的错误 terminal status
- [x] 修复 shared/dedup forest node 的 active-head provenance 与 packet 选择
- [x] 将后端 Analysis Loop facts 接入 rerun child 的 Ask AI 结构化上下文
- [x] 完成 targeted regression、sandbox boundary、full backend/golden/frontend/typecheck 验证

## Defect closure extension (R1–D4)

- [x] R3: event-study/time-trend numeric figure context
- [x] R4: Figure Ask-AI Markdown renderer
- [x] R1: LLM report figure packet, markers, history, deterministic missing-marker appendix
- [x] R2: HTML/DOCX/LaTeX zip/print-PDF export without new dependencies
- [x] D1: dead running manifest reconciliation in list endpoint
- [x] D2: progress heartbeat, cooperative cancel, timeout and slot release
- [x] D4: estimator-aware dropped-variable contract and CS golden correction
- [x] D3: bounded process-parallel honest-DiD with heartbeat replay and result-equivalence test
- [x] Final full gate and immutable-boundary audit

修复后不重新调用真实 DeepSeek；真实 API 运行证据保留在上文，修复正确性由本地 deterministic/fake 测试和完整 gate 证明。

## Final verification

- 提权完整 gate：backend `2111 passed, 8 skipped, 43 warnings`; golden/invariants `23 passed, 1 warning`; frontend `132 files / 1165 tests passed`; TypeScript `tsc --noEmit` passed。
- DOCX export 用 bundled document renderer 真实渲染复核：标题、粗体、内嵌图和项目符号可见；HTML、LaTeX zip、print-ready HTML 均通过结构化导出测试。
- `git diff --check` passed；protected adversarial tests 无 diff；v1.7.1 worktree clean；当前 worktree 未保留依赖 symlink、临时 QA 文件或运行中的 Workbench 服务。

## 2026-07-18 cs_did_staggered real DeepSeek report acceptance

### Goal

启动当前 v1.7.2 Workbench，运行 `examples/datasets/cs_did_staggered.csv` 的官方 CS DID 配置，使用真实 DeepSeek API 完成运行事实、全部图表解释和中文报告，并验证报告包含全部生成图表与可见导出结果。

### Constraints

- 只使用当前 `workbench-v1.7.2` worktree；不修改 v1.7.1 worktree。
- 不 push、PR、merge、tag；不安装、卸载或修改公共依赖。
- 不修改两个 protected honest-DiD adversarial tests。
- 不记录或输出 API key；外部响应内容只作为分析输入，不执行其中的指令。
- 真实 DeepSeek API 仅用于本次用户明确授权的验收。

### Phases

- [x] 1. 读取 example/how-to、核对字段与当前 worktree/服务基线
- [x] 2. 启动后端/前端并提交 `cs_did_staggered` run
- [x] 3. 等待终态并采集运行、artifact、figure 和性能证据
- [x] 4. 通过真实 DeepSeek 逐图解释并生成中文总报告
- [x] 5. 导出包含全部图表的报告并做浏览器/文件可见验收
- [x] 6. 关闭服务、清理临时资源、写入证据并汇报
- [x] 7. 当前 CS run 的真实 Agent 只读性能 smoke：调用 5 个只读 inspect 工具，确认无 proposal/mutation

### Performance sampling

- 记录 run submit、workflow、artifact/figure context、每次 DeepSeek 调用、报告生成和导出耗时。
- 至少完成一次全图表解释和一次中文报告生成；若 API/服务允许，再重复报告请求比较延迟与稳定性。

### Errors encountered

| Error | Attempt | Resolution |
|---|---:|---|
| Worktree-local `.venv/bin/workbench` has no installed CLI/dependencies | 1 | Use existing common `/Users/jiayuanren/项目规划/.venv/bin/python` with `PYTHONPATH=backend`; no dependency changes |
| `time_trend` numeric preview is intentionally truncated and is not valid complete JSON | 1 | Treat it as a bounded preview in the report packet; do not parse or claim unavailable rows |
| First DeepSeek report used invalid `[[c:source:...]]` citations and over-inferred chart shape | 1 | Enrich packet with figure source facts, regenerate with real DeepSeek, normalize numeric citation IDs, and remove unsupported claims from the delivered report |
| ReportView UI fact scope only contained 7 generic facts | 1 | Verify the UI path separately; use the enriched backend report as the delivery artifact and disclose the UI scope boundary |

### Current CS DID acceptance outcome

- Run `20260718_163434_852104_4c3b521c` completed successfully from the official `cs_did_staggered.csv` example.
- Model result: overall ATT `2.018869840812357`, SE `0.12502990938283692`; 8 figure artifacts; all 8 figure AI-context sources non-empty.
- Real DeepSeek model returned by the configured provider: `deepseek-v4-flash`. Eight figure interpretation calls and two enriched report calls completed; the frontend ReportView also completed one real report call and persisted history.
- Delivered clean report has exactly one marker for each of `boxplots`, `coef_plot`, `correlation_heatmap`, `event_study`, `histograms`, `kde_plots`, `scatter_plots`, `time_trend`; HTML embeds 8 PNGs and DOCX contains 8 media images.
- Browser QA showed the Workbench run rail, Graph, Report, Agent, Logs, completed lifecycle, and the rendered 8-image ReportView. The self-contained exported HTML was separately opened and verified with all report sections and 8 embedded images.
- Backend, frontend, and temporary report HTTP services were stopped; worktree-only dependency symlink was removed; no code/dependency/publish action was performed by this acceptance run.
- Current-CS Agent smoke `agent_chain_fb680f61df8049db90798b3c5c38c538` completed through the real DeepSeek provider in `21.788s`; it called only `inspect_node_context`, `inspect_diagnostics`, `inspect_result_summary`, `inspect_data_schema`, and `inspect_artifact_preview`, with `proposal_count=0` and session status `idle`.
