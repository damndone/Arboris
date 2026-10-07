# 完成结果的完整脚本导出

按原 objective §7 与 C3 集成，不改统计口径、默认值或容差。`ScriptPlan` 冻结合同不变。

实现选择：声明包承担族自己的结构适配；共享 builder 只读声明，不按族名分支。复用既有结果声明的 evidence_document、sidecars 和 fields，保留未截断的文档与标签。与只补主系数或逐族在 builder 写分支相比，这使其他分位数、cohort/time/horizon 结果不会因界面主投影而丢失。ETS/ARMA-GARCH/LMM 的不同 envelope 由显式声明读取，空推断核心不制造SE。

快照 sidecar 的 v1 扩展是可选 documents：每个角色声明本地裸 JSON 文件名、原artifact id、SHA。已有无扩展 sidecar 保持可读；reader 在数字自检前验证所有被声明文档。主要推断数字仍来自核；完整声明字段的数字按带文档角色的 JSON pointer 存为无分布的 snapshot 数字，并逐项从 sidecar 读取自检。完整文档保留字符串标签、null、不适用原因、解释限制、时间序列训练/生产角色，不能只靠数字集合证明完整性。

DID 先复用实际执行 normalize_did_input，以封印的 role fields 准备真实估计 frame；准备步骤有单独快照覆盖声明和理由，之后 DID 原生命令估计。尚未验证准备步骤的三语言独立重算时，完全原生请求明确拒绝。

测试顺序：真实完成 owner 再现缺口 RED；声明文档、量与标签的完整身份检查；三语言实际执行与原 native oracle；损坏文档、角色/身份冲突拒绝；原 native lineage/sidecar contracts/能力漂移检查与 tsc。最后冻结提交，由独立代理对照原缺口和工单复验。性能按原50节点预算，真实复杂结果耗时另记录。
