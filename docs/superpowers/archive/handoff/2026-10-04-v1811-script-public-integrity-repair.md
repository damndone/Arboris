# 脚本公共导出完整性修复与类型转换接续

基线 `99ef4a4a`。S 候选 `8102b5a7` 已按用户批准通过 `b3fdfd40` 合入；本交付继续完成 C3/C4 集成，不代表整个第 7 步验收完成。

## 已实现与依据

- 原始 Excel 容器保持完整字节时，权限检查覆盖所有工作表的列，包含未读取页；受限列在 ZIP 写入前拒绝。只检查分析页不足以授权整个工作簿。
- 导出存储沿已准入项目的目录 FD 打开 runs、owner、exports、scripts，持有 owner 文件锁直至 ZIP 与索引发布完毕。叶文件为 NOFOLLOW / O_EXCL，索引通过 owner FD 原子替换；同时核对目录 inode。相同目标幂等，不同语言保留两份登记。失败文件、临时文件和移名目录保留，没有清理或删除。
- 模型主结果与 kernel 的 model id、nobs、系数和标准误交叉核对。`econometrics/normalize.py` 和 `econometrics/runner.py` 保留系数与 SE 的完整 float，而非六位显示数。系数精确相等；重建 SE 仅允许 `16 * math.ulp(1.0)` 相对浮点舍入、绝对容差为零。这是持久化记录一致性检查；没有修改任何原生统计 oracle / ScriptStep 容差。
- 已完成 feature recipe 重新执行，并按原生产者的 CSV 序列化逐字节核对实际 output；防止 recipe 与 graph 同改但数据仍为原算式。CSV 读取再回写的二进制浮点差不能作为新的统计容差来源。
- 新后估计产物保留 compiled request，重算 durable plan 与各依赖 step 的内容指纹；统计复算使用原请求 spec。旧后估计缺少这份请求时，明确要求重新运行检验才能导出；不改写旧 owner、不从当前结果猜原假设。
- 单列/多列 cast 读取正式类型转换合同及完成记录，明确快照接续。只有实际 numeric 输入的 feature 才声称原生算术；文本转换保留完成数据快照。真实 cast→feature→OLS 三语言执行自检。
- 负二项旧 workflow 测试仍期待旧错误句子，现改为检查已有 `NB_COUNTS_INVALID` 错误码。仍检查拟合前拒绝负数/非整数，生产统计行为未改。

## RED / GREEN 与证据

独立原审查：`.worktrees/codex-v1811-script-public-review/docs/superpowers/handoffs/2026-10-04-v1811-script-export-public-independent-review.md`，冻结 `485ce4fc..2c76cd0e`，六项发现、七个失败探针；原生产/参考/容差未变。本主线复现副本先保留 `local/v1811-coordination/script-public-integrity-red.txt`（6 FAIL / 5 PASS）。独立审查树的原始 RED 文件未覆盖。

本地完整输出均保留在 ignored `local/v1811-coordination/`：

- `script-public-integrity-green2.txt`：68 PASS /31.02s，原 11 完整性探针、39 公共 lineage 路径及18实际参数检查。
- `script-kernel-precision-red2.txt`：1 FAIL /1 PASS，证明 1e-7 参数替换不能用显示精度放行；之后改为全精度核对。首轮同名证据碰撞留在 `script-kernel-precision-red.txt`，不算生产 RED。
- `script-public-security-related2.txt`：186 PASS /1 FAIL，唯一失败是负二项旧文案期望；有关 workflow、resume、Agent、GLM-NB 后估计、export、egress 与声明检查均通过。
- `script-public-final-integrity.txt`：113 PASS /1 FAIL /77.11s；包含15种原生后估计、12种原生权重/GLM、3种 cast 接续、50节点预算，以及修正后的负二项错误码。唯一失败是目录探针仍引用迁走的 service.os，已改为实际 storage.os；这是测试入口变化，原独立探针仍原样保留。
- `script-public-security-tsc.txt`：TypeScript exit 0。
- `script-public-integrity-final-green.txt`：修正入口后的14项完整性测试全部 PASS /13.87s，包括小量参数替换、真实 FD 已打开后的目录替换及不同语言并发登记。

目录替换的新探针在 scripts 的真实 FD 已打开后才替换 ancestor，要求 outside 无新文件、原有 ZIP 字节不变、另一个新 ZIP 只留在受控移名目录中。与旧全局 os.open patch 可能触发早期平台守卫的探针分开记录。

50节点路径由原始 dta、46个真实子集及完成 OLS 组成，完整公开打包（连快照写盘）实测 **0.35274495894555秒**、**1251579 bytes**；小于不含快照写盘的1秒预算。不是空 plan 微基准。

## 当前边界

此次不改模型估计、统计默认值或原生容差。FPC/GLM-NB 新统计导出 adapter 仍等待其单独合入批准。其余族实际协方差/特殊参数、最终数字断言覆盖、完整浏览器、自然语言 Agent 导出、17族 provider live、评估线 E、宿主 gate 及发版仍未完成。修复已经进入独立复验，未将作者测试算作独立通过。
