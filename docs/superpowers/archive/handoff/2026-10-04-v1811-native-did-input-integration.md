# 基础 DID 原生输入准备

基线 `5f78a68a`；按原 objective §7 与 C3 补齐基础 DID 整条路径的原生覆盖。统计定义、模型拟合、聚类默认、参考和容差均不变。

`ScriptResultLayout` 声明实际准备参数；builder 只消费声明及封印的执行表单，沿用冻结 `ScriptPlan` 的 `data.estimation_input`。准备类型为 `absorbing_treatment_panel`，包含原 mode/role fields，以及来自实际准备前数据类型的 Boolean 列声明。共享 builder 无族名分支。旧 plan 缺此声明时仍有明确快照说明，完全原生要求继续拒绝；未知准备类型/版本/参数明确拒绝。

新 renderer 在 pandas、base R、Stata 中独立生成 `_did_cohort`、`_did_D`、`_did_event_time`，覆盖 cohort、two_by_two、status 三种原模式。Stata 保留原列次序、原行次序，读完实际输入后才替换辅助列，临时变量不进入输出。真正 Boolean 输入与文本 `true` 不混淆。没有重新定义 never-treated、首次处理或 post 起点。

## 验证

- `native-did-input-red.txt`：真实 completed DID owner 的完全原生请求在三种语言中均先得到 RED。
- 第一轮原生实现 Python/R 通过；Stata 临时列未清理导致列自检失败，修正后 3 passed。
- 原生准备逐行值与原生产 `normalize_did_input` 对照，三语言完全相等（atol=rtol=0，NaN 位置一致）：三种模式、文本 cohort、缺失 entity、已有辅助列、Boolean treat/post、辅助列用作原输入、文本 Boolean 单词。完整准备与 public-owner 执行合计 33 passed，24.26 秒。
- 额外真实 RED 均保留：缺失 entity/已有辅助列 4 个；Boolean 导出 2 个；辅助列角色冲突 2 个；文本 `true` 被误作 Boolean 2 个。它们反映初版导出实现差异，已按原生产语义修复。初版逐行捕获测试把 runtime 的 `data` 容器错写成 `wb1`/`frames`，对应日志保留，相关入口失败不计产品 RED。
- 最终本轮相关套件及原 R/Stata 数值对照、实际 LMM host owner 只读导出、family literal 守卫：**278 passed，5 warnings，98.98 秒**，日志 `local/v1811-coordination/native-did-final-green-r03.txt`。`tsc`、`git diff --check` 通过。第一轮最终命令拼错 lineage 测试文件名，未运行测试，日志 `native-did-final-green.txt` 保留。
- 根会话此前 `d9bc7e98` 的完成结果语义修复已独立通过：提交 `9cf075444413b7d04e3db41c4aa39f16361dd671`，71 checks、36 次三语言执行、8682 项数字比较；4801 个原 tracked 文件及旧审查/owner/LMM host 文件字节均不变。此 PASS 只覆盖其冻结版本，不提前认证本次新 DID renderer。

当前新 DID 交付的独立复审与最终版本浏览器验收尚待完成。旧 `4baf4020` 浏览器中 DID 准备仍为快照的状态不改写；新代码关闭的是原生准备能力，不能把旧服务浏览器记录当作新代码验收。

VIX 原参数 GAP、三项待批准合入、正式 E、真实 17 族 Agent/全量 live/chaos、两次总审和宿主 gate 仍未完成。不声称本版可以发版。
