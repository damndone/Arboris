# LMM Public Result Adapter — Integration Assembly Record

状态：LMM Pack、公共结果投影、Agent 只读解释、RunForm/Genesis 参数入口和只读结果展示已在 Integration 工作树接线，并通过聚焦后端、全量前端和 Genesis 浏览器配置流验证；不是提交候选、候选执行、结果页浏览器验收或发布通过声明。

## 受控终态工件

WO-B 的 LMM 终态结果只写入并注册到：

`artifacts/model_results/linear_mixed_effects_1.result.json`

每个 LMM run 在该受控路径只允许一个终态槽位，并只调用一次 `register_artifact`，记录：

- `artifact_id`: `model_results.linear_mixed_effects_1`
- `artifact_type`: `model_result_packet`
- `step`: `linear_mixed_effects`

第二次写入、同一 artifact id 或同一路径的重复 index 记录必须失败，不能覆盖既有证据。结果读取器只从 `artifacts_index.json` 中声明为 `model_result_packet` 的工件读取并投影；未索引的 JSON 不是公共模型结果。

## 结果、诊断与恢复的分界

终态结果是 `linear_mixed_effects.result` 的版本化 PacketEnvelope。诊断写入独立的 `linear_mixed_effects_diagnostic.json`；有确认要求的恢复候选才额外写入独立的 `linear_mixed_effects_recovery_proposal.json`。后两者不是 `model_result_packet`，不会投影进公共 `model_results`。

公共读取层把已验证的终态 Envelope 投影为 `PublicModelResult`，保留工件 id、路径、sha256、源合同、生产者版本、源 packet digest 和 payload。投影是只读的：不把旧裸 payload 当作来源，不接受未经索引的文件，也不由前端重算 digest。

## 图形与降级规则

canonical FigureContext 只接受：

```text
chart_type = lmm_group_trajectory
time = 非空、有限、严格递增向量
groups = 恰好两个按规范标签排序的组
每组 = label + 与 time 等长的 observed_mean/fitted_mean 有限向量
```

唯一允许的 complete/null-figure 降级是 `LMM_FIGURE_CONTEXT_UNAVAILABLE_UNBALANCED_TIME`。它必须是唯一的同码 warning，携带完整的未平衡时间支持证据；可与独立的随机斜率或奇异随机效应 warning 共存。任何其他 null FigureContext、旧 `series` 形状、重复/无序时间、错误组数或伪造证据都会被拒绝。失败结果不携带系数、随机效应或图形统计。

## WO-C 只读展示边界

唯一展示消费者是 `frontend/src/workbench/repeatedMeasures/`。它只接收结构完整、可信的 `PublicModelResult`：只读嵌套 `payload.coefficients.group_time_interaction` 和 canonical FigureContext；拒绝裸 Envelope、外层元数据缺失、顶层系数回退、未知诊断和错误状态。

该边界不生成结论、不提出或展示恢复动作、不执行 Agent 操作，也不注册 UI feature、路由、模型或 Compare 行为。`frontend/src/features/repeated-measures` 是被明确禁止的平行消费者路径。

## 受控运行时边界

LMM 已通过 builtin Pack 声明进入受控能力入口，普通 RunForm 和 Genesis 都会提交规范化的 `model_options`。Agent 只读取验证后的公共结果，并提出需用户确认的建议；它不创建初始 LMM run，也没有候选执行 fallback。Compare 不获得新的隐式分派；结果展示只消费 `PublicModelResult`。`tests/test_lmm_extension_seams.py` 保护这些显式边界。

## 当前证据与尚未通过的门

- `tests/test_lmm_result_adapter.py` 覆盖版本化工件的验证、投影、旧 OLS 兼容与失败关闭。
- 后端 Integration 聚焦套件：`185 passed`，覆盖 Pack、持久化、公共结果、LMM 合同、Agent 只读边界和扩展 seams。
- 原生前端全量套件：`137 files / 1213 tests passed`，且 `npx tsc --noEmit` 通过。
- 浏览器 Genesis 验收：在真实上传的 fixture 上选择 LMM、填写受试者/时间/组别、保存模型；服务端读回完整 `model_options`，随后 `POST /pipeline-drafts/{id}/validate` 返回 `ok: true`。该步骤不执行模型。

LMM 结果页的浏览器验收、精确提交候选执行、WO-D 独立证据、性能证据、完整 release gate 和发布签字均尚未通过，不能由本 assembly record 替代。
