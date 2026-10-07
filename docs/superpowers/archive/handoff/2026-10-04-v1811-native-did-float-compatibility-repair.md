# DID 原生准备的 float 文本兼容与明确拒绝修复

基线 `f546d584`，受审生产基线 `60203b15`。独立冻结复审首轮 90 PASS / 12 RED：cohort 合法下划线及全角数字的 6 个逐行值差异；非 mapping scalar / 全 keys sequence 的 6 个未结构化异常。另在真实 public DID owner 中确认数值相等的 `N.0_0` cohort 可完成 Workbench 拟合，但旧三语言导出并不等价。旧 Stata 追踪工具解析缺失数值也有 harness 错误，其分类与原程序 r(9) 分开保留，不把 harness 栈冒称产品异常。

根会话从实际 `engine/did_spec.py::_coerce_cohort_value` 追到原生产使用 `float()`，旧 exporter 使用 pandas/R/Stata 的默认数字解析，合法词法范围不同。只修 exporter：

- Python cohort 使用相同 `float()` 并保留非有限/非正数过滤。
- R/Stata 独立原生命令将 Unicode Nd 十进制数字映射为 ASCII，仅移除原 `float()` 接受的前后空白，严格校验数字、点、指数及合法数字间下划线后转换。非法下划线、上标数字不被重新解释。真正 Boolean 源列按已有类型声明处理。
- 词法表由 Python Unicode 数据生成并缓存，冷构造实测 0.068 秒（760 个 Nd、25 个空白字符）；这不是 50 节点整条路径性能认证。
- 仅缺少 preparation 字段保留旧 plan 的明确快照行为；显式空值、空对象、非 mapping、未知 mode/type/version 明确 `ScriptExportRefusal`。不声称 public HTTP 可以提交任意 ScriptPlan。

生产 DID normalize、时间/处理标志转换、统计定义、默认、参考数据和容差均未改。生成的三语言程序不依赖 Workbench 或 Python 来转换 R/Stata cohort。

根 TDD：新增 15 RED / 3 PASS，日志 `local/v1811-coordination/native-did-float-grammar-red.txt`；首轮 51 PASS，29.21 秒，日志 `native-did-float-grammar-green.txt`。再补 Unicode 空白、Nd、科学计数与下划线共存控制例。最终相关回归、原 R/Stata 数值对照、只读 LMM host owner 导出和 family literal 守卫：**299 passed，5 warnings，105.14 秒**，日志 `native-did-float-final-green.txt`。`tsc`、`git diff --check` 通过。逐行 helper 值比较 atol=rtol=0，缺失位置不变。

本修复尚待新冻结版本独立复验及新版本 browser public-artifact 验收。`60203b15` 的浏览器记录仍只覆盖其原普通数值 cohort 场景，不改写旧记录为新版本认证。VIX GAP、三个待批准合入、正式 E、17 族真机、live/chaos、Claude 两次总审、宿主 gate 仍未关闭。
