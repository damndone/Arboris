# DID 原生导出：CSV 与浮点边界修复

独立复审基线 `cb296ba3`，报告 tip `c4227271`，原始 RED 与所有既有证据保留。本修复仅改变导出输入转换及明确拒绝，不改变 Workbench DID 拟合、统计定义、默认标准误、参考文件或容差。

## 修复范围

1. Stata CSV 原生读取采用 `bindquotes(strict) maxquotedrows(unlimited)`，让带引号的多行单元格保留为同一行。原列名、UTF-8、asdouble 和 reader options 仍保留。Stata 官方依据：<https://www.stata.com/manuals/dimportdelimited.pdf>。
2. R cohort 文本沿用生产 float 词法域；合法文本规范为 JSON 数字后交给本机已有 jsonlite 的数值解析器，避免 R as.numeric 在极端指数输入上的数个 ulp 差异。`jsonlite` 在 R 覆盖与依赖声明中列出，未安装任何依赖。
3. 从实际执行源声明有限正 cohort 的最小/最大值。超出 Stata 已验证的全精度 double 范围时，在导出生成阶段以 `UNREPRESENTABLE_COHORT_PERIOD` 明确拒绝（普通和 require_native 两种请求均拒绝），不将有限处理期转成 missing。支持范围依据：<https://www.stata.com/manuals/m-5mindouble.pdf>。该声明是导出内部输入元数据，不进入模型选项、统计默认或历史运行哈希。
4. 旧低层 ScriptPlan 未声明范围时，生成的 Stata 脚本对数字词法匹配但解析为 missing 的单元格明确 exit 459。此保守检查可能拒绝旧手写 plan 中 `1e309` 这样的非有限 token；不宣称它与生产 never-treated 语义完全等价。公共 builder 的新声明区分实际有限范围，不触发此不确定情况。

## TDD 与真实执行

- `local/v1811-coordination/native-did-boundaries-red.txt`：7 个真实失败、2 passed、54 deselected，覆盖 Stata 多行 CSV、R 四个极端 IEEE 值及 Stata 生成阶段范围拒绝。
- 首轮 green 为 62 passed、1 failed：生成脚本自己的输入行数自检已通过，测试捕获文件未给字符串加 CSV 引号，造成重新读捕获文件失败。只在测试捕获中加入 `export delimited ..., quote replace`；原始日志保留。
- `native-did-boundaries-green-r02.txt`：63 passed；`native-did-public-range-green.txt`：4 passed、63 deselected，后者使用新完成的真实 DID owner，Stata 两种请求明确拒绝，R/Python 真正执行导出原自检。
- R 用 `%a` 对 `1e308`、`9e307`、`1e-300`、`2.2250738585072014e-308` 比較，精确匹配 Python float 的 IEEE 值，不调整容差。
- 扩大相关套件：403 passed、1 failed、5 warnings，113.28 秒（`native-did-boundary-final-green.txt`）。唯一失败是旧 `sidecar_none_baseline_92c90b59` 期待 Stata 旧读入命令的逐字节检查。原基线文件没有改；兼容检查仅识别新增的两个 CSV quote binding 选项，剩余程序仍逐字节比较。该生成脚本字节变化是有意的，不宣称 Stata 导出字节保持原样，也没有更新统计 oracle。
- 修正上述字节迁移检查后，三语言 3 passed、60 deselected、1.10 秒（`native-did-csv-byte-migration-green.txt`）。没有改生产代码，其他 403 通过项未重复运行。`tsc --noEmit`、`git diff --check` 与 devline verify 通过。
- 独立新冻结复验待结论。旧 frozen 浏览器 PASS 仅认证原提交；本修复需要新的冻结服务公共产物验收。

## 保留的边界

本修复不替代评估线 E、17 族真机、全量 live/chaos、两次 Claude 总审与用户宿主 gate。LMM 宿主真实 canary 的 3 passed 已独立记录。三项补充候选的合入批准及 VIX omega 参数验收仍未关闭。
