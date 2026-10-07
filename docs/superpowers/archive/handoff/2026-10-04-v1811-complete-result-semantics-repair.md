# 完成结果导出：语义一致性修复

受审基线：`4baf40200b9fa299b92ddd1173352a6a55f79142`。本修复仅收紧导出准入；估计器、默认值、原数值参考和容差不变。

独立审查在完整文档快照中发现两组问题：QR 的嵌套 reference fit 可以与实际主系数冲突，分位数标签和请求的 fit 集合也未核对；ETS 的 typed schema 虽有效，样本量、因变量、规格和结果身份却可以与实际输入冲突。文档 SHA 一致不足以证明这些语义关系。

主线先新增 `tests/test_script_export_result_semantics.py`，QR/ETS 8 个场景全部得到真实 RED，再实现族声明的输入校验。QR 核对实际请求、所有分位数标签、各 fit 的参数集合、置信区间及 reference fit 与 flat/kernel 的一致性。ETS 复用生产输入准备器和现有 result identity 算法，核对规格、样本指纹、排除计数、时间语义和拟合方法；不重拟合。

另以实际 schema 检查 CS/SA 的 `aggregations.simple.overall/overall_se/overall_pointwise_ci`，以及 dCDH 的 `overall_att.estimate/se`，与同一 owner 的主 ATT 投影一致。8 个新增场景先得到真实 RED，再用族声明文档校验器关闭。CS/SA 的 `simple.estimate` 是 series 空列表，不能误当标量；独立审查首次该两例停在测试自身断言处，不计产品 RED。主线的 8 个 RED 使用实际标量字段，日志完整保留。

校验发生在共享 builder 调用声明回调的边界；共享代码没有新增族名分支。旧完整系数守卫继续保留。无新统计数字，也没有把 dCDH experimental overall ATT 改成另一原生软件的不同 estimand。

## 验证

- RED：`local/v1811-coordination/result-semantics-red.txt`（8 failed）；`effect-document-semantics-red.txt`（8 failed）。
- 首轮 QR/ETS 修复及七族三语言执行：36 passed，27.21 秒。
- 最终相关测试、原 CS/SA/dCDH/QR/ETS 数值参考、实际新 LMM 宿主 owner 的只读三语言导出：203 passed，5 warnings，71.24 秒。日志：`result-semantics-final-green-r02.txt`。
- `npx tsc --noEmit` 与 `git diff --check` 通过。
- 最终测试入口第一轮拼错 ETS 测试文件名，未运行测试；错误日志 `result-semantics-final-green.txt` 保留，不计失败数或验证通过。

独立复审尚待冻结提交后的新工作树重验。这份报告不是全部 objective 完成、真机 Agent 评测或 full gate 通过声明。
