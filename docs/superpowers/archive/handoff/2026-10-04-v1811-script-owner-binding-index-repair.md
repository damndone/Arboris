# 脚本实际模型输入、原请求绑定与共享索引修复

基线 `9dfcb907`。S `8102b5a7` 已经按用户批准通过 `b3fdfd40` 合入，本次没有再次合入 S，也没有 push、tag、发版或删除文件。

## 本次交付

- IV 的内生变量与工具变量从完成 owner 的实际输入读取，通过合同声明映射为导出参数；面板模型保留实际聚类列。实际方差、聚类数、参考分布及自由度与 kernel、结果包交叉核对。共享 builder 不以模型族名字分支。
- 原生自检增加每个参数的最终 t/z、p 值与自由度。直接按完成 kernel 的系数、方差及参考分布计算，没有更改估计方法、默认值或原生 oracle 容差。
- 独立复审 `95c77e49` 的第一项 P2：kernel 中每个参数必须有主结果系数行与 SE，缺失时拒绝；重命名参数不能跳过核对。
- 第二项 P2：compiled request 的模型绑定使用工作流执行器的同一解析规则。直接引用及 `step:<producer>:<branch>` 均核对真实 owner；动态引用必须有指纹相符的 completed producer 和保留的 branch binding。LR 的受限模型也同样核对。不能换成另一真实模型，再重算检验掩盖原请求不符。
- 第三项 P2：脚本导出、普通 register_artifact、报告校验和刷新、predictive 持久化及 LMM 两个持久化登记入口共用 owner 目录 FD 文件锁。读改写整个事务锁住；同一 admission 的多个线程通过重新打开 `.` 获得独立 file description。普通索引写入也以 FD 原子替换，避免完成的后估计登记被导出的旧索引覆盖。原 LMM live admission 与 canary 不变。

## 证据

独立原 RED、旧生产字节及原 native 参考均保留在 `.worktrees/codex-v1811-script-integrity-recheck`；本次没有重写独立 `r01..r05` 输出。

主线真实 RED：`local/v1811-coordination/script-kernel-complete-binding-red.txt`（缺主结果行）、`script-original-request-owner-red.txt`（原请求不变但换用实际 unadjusted owner）、`script-shared-index-red.txt`（真实 lincom 已完成但登记被覆盖）。新的并发正测试允许登记等待事务锁，而不是要求它在锁持有期间完成。

- `script-owner-final-statistics-green.txt`：85 PASS /35.80s，含实际 IV/panel、权重/GLM、15 种原生后估计、类型转换接续与完整性探针。
- `script-shared-index-related-final-r02.txt`：104 PASS /42.65s，含 LMM pinned persistence、predictive schema、普通登记、实际参数、公共 lineage 与三项完整性修复。首次命令 `script-shared-index-related-final.txt` 引用了不存在的测试名，exit 4，未执行任何测试；该输出保留，不计通过。
- `script-fitted-owner-native-final.txt`：4 PASS /7.64s，真实工作流两次拟合→LR→Stata/R/Python 导出执行，验证动态 owner 引用可正常接续。
- `script-shared-index-final-tsc.txt`：TypeScript exit 0；`git diff --check` exit 0。
- `script-shared-index-fifty-final.txt`：真实 50 节点完整 ZIP 导出 **0.346350708976388 秒**、**1251924 bytes**，预算 1 秒。原始 dta→46 个真实子集→完成 OLS，含快照写盘，非空 plan 基准。

作者验证不代替独立复验。本提交冻结后，独立代理重新验证三项 P2、全部索引写入入口及 native 回归。

## 尚未完成

复杂模型结果快照、DID 内部估计列接续、FPC/GLM-NB adapter 的另行批准与集成、浏览器与自然语言 Agent 导出、17族 provider live、评估线 E、宿主 gate、发版仍需继续推进。当前没有宣称整个脚本导出或 v1.8.11 已通过。
