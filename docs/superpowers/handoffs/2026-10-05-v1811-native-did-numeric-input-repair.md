# DID 原生输入：数值精度与低层范围验证修复

第三轮冻结生产 `6fd4f43b` 的独立报告 `acc69d6a` 证明两项 P2：R 把已经精确的 numeric cohort 转成显示字符串会改变处理阈值；低层合法 JSON 大整数 cohort_range 会抛 OverflowError。旧 CSV quoted newline、Stata 范围拒绝、R 文本极值修复仍通过，原 RED 与报告不改写。

## 设计与限定修复

- 保留已是 numeric 的 R cohort、time、treat/post/status 的实际 double，只有真正文本才走 float 词法转换；logical 仅在实际源的 Boolean 声明下转换。这样 nextafter(3,+∞) 的处理期与 time=3 保持 D=0，equal-time 控制仍 D=1。
- 完成 CSV 入口的源精度检查：R read.csv/type.convert 本身在极端 decimal token 上也可能不同于原 float 解析，不能仅修改 prepare 后宣称全部解决。共享 R CSV reader 保留原 reader 的字段、类型、顺序、NA/Inf 与所有 read_options；只对已判为 double 的数字词法单元格，从同一文件及同一 options 的 character 视图用本机现有 jsonlite 解析原 token。无法等价转换的 numeric token 明确失败。DTA/SAV/XLSX 等原 reader 不变。
- 数字 JSON 规范化放入通用 `exact_numeric.py`，CSV 与文本 preparation 共用；通用文件不含模型族分支。jsonlite 是 R CSV 导出的明确依赖，没有安装或静默调用 Python。
- 超大整数范围通过合法 JSON 但无法表示为有限 float 时，以 ScriptExportRefusal 明确拒绝，不泄漏 OverflowError。
- 原 sidecar_none 基线逐字节保留；显式兼容检查只移除新增 R 精度 helper/调用及上轮 Stata quote 选项后检查其余整个程序。生成脚本字节确实有意变化，不冒称旧 R/Stata 字节保持原样。模型统计默认、生产 normalize、Stata/R 数值参考及容差均未改。

## 证据

新增 TDD 5 RED / 3 PASS / 67 deselected，3.42 秒（`local/v1811-coordination/native-did-numeric-input-red.txt`）；修复后同八项 8 PASS / 67 deselected，2.98 秒（`native-did-numeric-input-green.txt`）。CSV 最小实例比较五个原始 float 的 %a bits 及 D，独立 numeric primitive 验证边界与相等正例。

扩大相关回归 **489 passed、5 warnings、155.81 秒**（`native-did-numeric-input-final-green.txt`），含原模型 R/Stata 对照、数据操作、来源格式、reader options、owner/index、原 host LMM 只读导出及族名守卫。tsc、git diff --check、devline verify 通过。

边界复查另发现最大有限 double 在原 R reader 中先成为 Inf；新增 1 RED（`native-did-numeric-max-red.txt`），再把合法 decimal token 都从原文本解析，显式 Inf/−Inf/NA 保持原值。补充 **70 passed、103 deselected、25.68 秒**（`native-did-numeric-max-green.txt`），没有重复无关已通过套件。

最后六个 CSV 边界的期望改为从真实 Workbench `_read_frame` 后再 normalize，**6 passed、70 deselected、2.80 秒**（`native-did-numeric-production-reader-green.txt`），不是仅与手写 frame 比较。其他通过项未再次运行。独立新冻结复验及新公共产物验收待结论。第三轮报告的 133PASS/7FAIL（5harness）、15PASS/3RED、阈值 1PASS/1RED 记录各自真实命令，不混加宣称全面通过。

## 状态边界

页面旧 refusal 在设置改变后清除的限定修复已提交 `bfc6c305`，组件 3 RED 后 7 PASS、tsc 通过；此版本的真实页面跟进验收仍需记录。本修复不替代正式 E、真机 17 族、全量 live/chaos、两次 Claude 总审或宿主 gate。LMM 宿主 3 passed 已关闭；三项候选合入批准和 VIX omega GAP 仍未关闭。
