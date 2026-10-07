# v1.8.11 脚本集成补充波次

本波次在批准合入 S 的 `b3fdfd4062e7ebc6336d6189841fd6b0767b312c` 上冻结接口。
release baseline 为 `1af5498e7e0d327b97edd6910624267b801d8fb4`；原 ScriptPlan 合同为 `6f0f87c6`，结果 sidecar 合同为 `511616d5`。
本文件提交即本波次 contract lock；所有新增生产者与其独立审查 worktree 从该提交开始。

## 设计选择

不另建统计实现或改变默认值。导出器调用已验证的引擎或目标软件的相同口径；无法复现时用已完成结果 sidecar 明示接续。
GLM-NB 使用显式固定 alpha、log、最终 EIM、scale=1；固定 alpha 的独立负二项仍使用 OIM。
FPC 只消费已批准的单阶段定义。原生 R/Stata 使用相同抽样设计、完整设计框架及 domain；Python 使用 Workbench 的已验证设计引擎。不得仅在脚本标题宣称 FPC。

集成方从已完成 owner 的登记资产构建 ScriptPlan，验证实际运行参数、输入数据与结果的 SHA 和身份。客户端只能指定已登记项目、运行/节点、语言与 require_native，不能提供 expected、投影函数或输入路径。
参数来自已执行输入，完整精度期望值来自 inference kernel/后估计结果；原始输入、数据操作及预处理必须逐步原生执行或显式快照接续。无法证明血缘或参数时拒绝，不猜测。
生成前验证覆盖；require_native 的拒绝在写文件前发生。脚本、源文件、快照和结果 sidecar 写新本地目录，响应与 Agent 仅返回有界元数据；向模型或外部分享内容仍走 egress。

## 所有权

- 脚本统计适配线：仅 `backend/workbench/script_export/exporters/{survey,models,__init__}.py`、新 `tests/test_script_export_v1811_statistical_adapters.py`、新 `tests/fixtures/script_export/v1811_statistical_adapters/**`、其专属完成报告。
- 集成方：其余中心文件、ScriptPlan 构建/导出服务、HTTP、UI、Agent、egress、准入/后估计注册、集成测试。
- 独立审查：专属新攻击测试、数值证据及报告；不得改被审生产代码、旧参考或容差。

## 验证及移交

适配线先写失败测试：三语言 FPC counts/fractions/domain/certainty、GLM-NB 五种后估计和不同 alpha；真实 R/Stata 对照并保留失败日志，公开日志去除许可证字段，原始日志本机保留。
采用共享独占锁，不跑全量/gate、不触碰 Downloads、不调用模型、不安装/删除。
完成报告记录精确提交、owned files、失败/通过证据、原生完整精度差异、性能及未覆盖范围。独立审查修复后，由用户批准合入。
