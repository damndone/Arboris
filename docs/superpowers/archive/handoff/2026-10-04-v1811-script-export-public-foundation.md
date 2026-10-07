# v1.8.11 脚本导出公共入口：基础交付

基线：485ce4fc。S 候选 8102b5a7 已按用户批准合入 b3fdfd40。本交付完成公共路径基础设施，不表示 C3 全覆盖、浏览器、性能或发版验收完成。

## 实现

- 从真实完成的 owner 构建 ScriptPlan：核对执行输入、图、注册产物 SHA、跨运行 rerun 源、数据操作/特征 recipe 源和 schema；保留原上传文件、每一步操作及显式快照接续。
- 完成模型及持久化 Wald、lincom、nlcom、margins、双模型 LR 的目标；后估计重读原 owner kernel 和设计，重算并核对已持久化结果，拒绝结果或 workflow 绑定被改。非默认置信水平明确标为快照接续，require_native 拒绝。
- HTTP、Agent、模型详情入口调用同一服务，先走 local artifact egress 管控，再生成有覆盖表、依赖、计划及每个文件 SHA 的确定性 ZIP；用户不能注入结果、路径或 projector。同一路径重复导出保持 ID/内容稳定。
- 实际 Stata 源文件按原数值读入，R haven 转普通 data.frame 后处理聚类；仅统计文件采用新读取器，旧 CSV 基础脚本保持逐字节兼容。
- 修复公共数据模型入口遗漏 entity_col、诊断摘要注册 SHA 早于最终 GVIF 重写两处真实问题；不改变估计及方差公式。

## RED → GREEN 与对照

新增 tests/test_script_export_lineage_builder.py 共 33 项。先证实 builder/HTTP/Agent/UI 缺失、聚类字段遗漏、最终诊断 SHA 不一致、后估计缺 nobs、R tibble 聚类取值错误、重复导出污染 lineage hash、recipe 源 SHA 篡改、重新登记后估计伪数字及双模型 LR 输入身份问题均失败，再实现。

真实公共流程：原始 .dta → subset → derived multiply → clustered OLS → 持久化后估计。40 个 cluster、n=400、t(39)，Wald F(2,39)。Wald/lincom/nlcom/margins/LR 五条路径在 Stata/R/Python 实跑，共 15 项原生数值自检，使用 S 冻结容差。完整双模型 LR 来自不同 run 的真实完成 owner，经过真实样本一致性核对。

- `tests/test_script_export_lineage_builder.py tests/test_script_export_render.py tests/test_script_export_result_sidecars.py`：107 PASS / 33.36 s，日志 local/v1811-coordination/script-export-compat-green.txt，退出 0。
- ScriptExportSection / DetailDrawer / sectionRegistry 前端：42 PASS；tsc --noEmit 退出 0。日志 script-export-ui-related-green.txt / script-export-ui-related-green-tsc.txt。
- 较早 11 文件相关检查：259 PASS、5 FAIL。3 项旧测试把已开放 GLM-poisson 当作未开放，改为检查仍未开放的 NB2-nlcom；2 项 CSV 字节兼容失败已通过选择性读取器修复，原 golden fixture 未改。上述 107 项复验全部通过。
- 唯一警告为既有 Starlette TestClient httpx 弃用提示。

## 剩余与边界

- 当前统计适配器候选仍需 P2 独立复验及用户合入批准；本报告不宣称 FPC/GLM-NB 公共导出已通过。
- 仍需扩展实际 GLM 限定模型 identity、抽样/分析权重及 survey design 的真实执行适配；未知/不足的 provenance 明确拒绝。
- UI 当前入口针对模型，持久化后估计目标选择器待补；API/Agent 已可指定真实后估计 artifact。
- 所有族/数据操作闭环、50 节点性能、真实浏览器三主题、17 族真机、独立整体 E、Claude 两次汇总、宿主 gate 未完成。
- 旧历史日志敏感 header 风险仍需 push 前处理；未重写历史、push、tag、发布或删除。
