# 原生脚本数值输入：独立复验与最新浏览器验收

结论：冻结生产 `1797e231dbd1d863316263b53587fb49f5557142` 的限定修复通过。第三轮两项 P2 已关闭；本报告补充最新浏览器实际公共 ZIP 验收，不覆盖旧报告，也不宣称 v1.8.11 已可发版。

## 独立复验

独立报告提交 `876f524f8fc3e395672084c0062b74d45a154d47`，工作树 `/Users/jiayuanren/项目规划/.worktrees/codex-v1811-native-did-r4-review`：`docs/superpowers/handoffs/2026-10-05-v1811-native-numeric-independent-recheck.md`。该提交仅在独立树本地保存，没有合入主线。

59 个不同后端节点、7 个组件节点与 tsc 全部通过，零 RED、零 harness 失败。原 r3 numeric threshold、equal-time、极端 float 与合法 JSON 大整数均通过；7 个真实 Workbench CSV reader 场景包括最大有限 double 和小数阈值。普通三模式三语言、R reader options、完整旧程序字节迁移检查通过。36 项 completed-owner 最终数字最大差 8.526512829121202e-14；这是已完成 owner 的再现，不冒称新独立统计 oracle。

保护核验：5283 tracked 文件、2010 旧审查 owned 文件、142 旧 DID owner 文件、49 旧 finite-public 文件、40 LMM host 文件、38 underscore-owner 文件 before/after SHA 全部不变。独立报告不认证下列浏览器动作。

## 最新可见页面与实际产物

使用上述冻结树服务 `http://127.0.0.1:5201` / `http://127.0.0.1:8042`，保留旧服务和页签。实际源是仓库合成 DID CSV，480 行；将第一个正 cohort 从 3 改为 `nextafter(3,+inf)`，原始 float hex `0x1.8000000000001p+1`。通过真实 `/runs` 服务拟合 owner `20261005_041740_098338_d976465b`，浏览器选中已完成模型并勾选 Require all steps to run natively，三语言依次显示 All steps run natively 和实际下载链接。R 显示 jsonlite 依赖。

浏览器生成的 ZIP 经本地公共 HTTP artifact 接口取回；这是 HTTP retrieval，不声称浏览器 download event 成功。保存原 ZIP 字节，在隔离副本加数值记录后执行原末尾断言，未删改参考或容差。Stata、R、Python 均为本机已有运行时，未安装软件。

| 实际 owner / language | Artifact ID | 原数值自检 | 最大绝对差 |
| --- | --- | --- | --- |
| 新 threshold / Stata | `script_export_stata_d02ad63d20f76be96d7c5ccf` | 18 PASS | 3.197442310920451e-14 |
| 新 threshold / R | `script_export_r_0b8dcd023dbd4e716de58c29` | 18 PASS | 3.197442310920451e-14 |
| 新 threshold / Python | `script_export_python_6fe2614872c64f97bdd9b506` | 18 PASS | 3.552713678800501e-15 |
| 旧 finite 1e308 owner / 最新 R compiler | `script_export_r_95172b60a59b8417809349e7` | 18 PASS | 8.526512829121202e-14 |

四份共 72 项，退出码全部 0。最后一份 owner `20261005_040108_747469_ec50b5cb` 未重新拟合；只由最新 compiler 生成新产物。旧 Stata 无法保持该有限 cohort 的保守拒绝仍保留，不能算为 Stata 执行通过。

原 ZIP、执行副本、数值记录及全部 SHA 在本机忽略目录 `local/v1811-script-browser/native-numeric-public-artifacts-1797e231/summary.json`。命令：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python local/v1811-coordination/run_exclusive.py .venv/bin/python local/v1811-coordination/native_numeric_browser_execute.py
```

真实截图均留在 `local/v1811-script-browser/`：`native-numeric-threshold-stata-1797e231.jpg`、`native-numeric-threshold-r-1797e231.jpg`、`native-numeric-threshold-python-1797e231.jpg`、`native-numeric-extreme-r-1797e231.jpg`。不是把旧冻结证据沿用到新代码。

## 旧错误清除

同一最新页面上，对极端 owner 生成 Stata 拒绝；改变 require-native checkbox 时错误立即清除。重新生成拒绝后切换 R，旧错误也立即清除，R 再生成成功。截图 `native-numeric-refusal-cleared-1797e231.jpg`。Analysis path 控件没有可选的另一条路径，浏览器不冒称验证该控件切换；三个控件的独立组件检查已通过。

## 状态边界

最新 LMM 宿主 owner `20261005_024643_550779_dbe309ee` 的真实 canary / 3 passed 已关闭，无需重跑，原证据只读保持。三个候选合入批准、VIX omega 原参数 GAP、正式 E、17 族真机、全量 live/chaos、Claude 两次总审、宿主 full gate 与发版批准仍未关闭。无 push、merge、tag、发版、删除或统计默认改变。

正式 REVIEW 的草稿两次被现有秘密识别器误识别科学解析术语；未改事件流或放宽保护，改写说明后通过正式 CLI。原草稿仅在本机忽略目录保留，最终正式事件使用不含歧义的措辞。
