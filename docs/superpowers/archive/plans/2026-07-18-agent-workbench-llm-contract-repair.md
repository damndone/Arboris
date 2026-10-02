# v1.7.2 Agent / Workbench / DeepSeek 契约修复计划

## 目标

修复真实 `cs_did_staggered` 运行暴露的三类一致性问题：诊断状态与文件事实不一致、DID 关键警告没有进入 Agent 上下文、LLM 报告输出没有在产品边界内被验证。修复后，Workbench 负责确定性状态和数值事实，DeepSeek 负责解释；不合格的报告不会被 UI 静默修补或保存。

## 不变边界

- 只在 `workbench-v1.7.2` worktree 工作，不修改已发布的 v1.7.1 worktree。
- 不修改 `tests/test_honest_did_adversarial.py` 或 `tests/test_honest_did_sd_adversarial.py`。
- 不新增、升级或卸载公共依赖；不 push、PR、merge、tag。
- 修复测试使用本地 mock provider；除非用户再次明确授权，不调用真实 DeepSeek API。
- 保留 Agent 的确认门槛：DeepSeek 不能直接确认、执行或发明 unsupported operation。

## 实施顺序

### 1. 报告状态与 Agent 诊断一致性

- 先补测试：报告渲染完成后，`diagnostic_summary.json` 必须为 `complete/true`；渲染失败必须为 `failed/false`，且 warning 可见。
- 将 CS/SA-DiD 结果中的 omitted-cell 和 single-cohort dynamic warnings 聚合为结构化 GuardrailIssue。
- diagnostic preview/Agent bounded diagnostics 暴露最终 `report_render_status`、`report_available` 和 warning trust 状态。
- 刷新已注册 `diagnostic_summary` artifact 的 SHA-256，避免内容回写后索引过期。

### 2. DeepSeek 报告响应契约

- 先补测试：重复 fact/figure id、未知 citation、未知/重复/遗漏 figure marker、一次纠正重试成功、二次失败 fail-closed。
- 新增后端报告契约模块，校验 fact/figure packet 和模型 Markdown marker。
- 对可安全归一化的 `[[c:5]]` 只在 `c5` 存在时转换；其他非法 marker 不猜测。
- 第一次响应不合格时最多向同一 provider 发起一次纠正请求；仍不合格返回 `502 LLM_RESPONSE_CONTRACT_INVALID`，不返回坏报告。

### 3. 前端图表事实包与诚实失败边界

- 为图表 numeric source 生成有限、稳定的 citable facts，并记录 preview truncation。
- ReportView 将图表 facts 与 lineage facts 一起展示、筛选、保存到 history。
- 删除客户端 `ensureFigureMarkers` 静默补图；后端契约失败直接显示错误。
- 更新前端测试，确保真实缺 marker 时不会伪造一份“完整报告”。

### 4. 验证

```bash
pytest -q tests/test_report_contract.py tests/test_diagnostic_summary.py tests/test_agent_context_tools.py
pytest -q tests/test_llm_chat.py tests/test_engine_golden.py tests/test_cs_did_wiring.py tests/test_sa_did_wiring.py
cd frontend && npm test -- --run src/report/ReportView.test.tsx src/report/factTable.test.ts
cd frontend && npm run typecheck
scripts/gate.sh
git diff --check
```

完成标准：定向测试与完整 gate 通过；Agent 能看到 CS-DiD 薄支持警告；报告状态与文件一致；DeepSeek 报告输出不符合契约时可重试或明确失败；保护文件和发布 worktree 未变化。
