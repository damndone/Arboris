# GLM-NB 公共资产 P2 独立定向复审

结论：**PASS**，原许可证 header P2 已关闭。此次仅核验公开资产保护、完整原始证据保全及内容不变，不重新运行统计 oracle。

审查 producer tip：`06e3c798b4758a2c32fae2c30708641d54b15642`。修复前 tip（含首次独立审查）：`87f964311115117f08b790a6247645ad23e1ff80`；原统计候选 `64ec3d73121c7d8e792942e62d30d0b92c9d8907`；统一基线 `01fb0752bce129c8d8848c021eca776dadccb515`。本次审查提交只新增独立证据，不是功能 baseline，不代表合入、消费者准入或发版验收。

## 独立证据

起始 HEAD 精确匹配修复 tip，tracked clean；原四项 owned untracked 证据保持原状。没有修改作者资产、旧参考、生产或中心文件。

`tests/eval_v1811/glm_nb_review_p2_recheck.py` 独立读取 raw 副本、修复前 Git blob、当前 tracked 字节与 manifest，不调用 producer 脱敏实现。原私有字段值仅在进程内用于扫描，不打印、不写入 proof、报告或新提交。

| 核验 | 结果 |
|---|---|
| 四份完整 raw 副本 | 与修复前 Git blob 字节完全相同；Git ignored、未 tracked、mode `0600` |
| 四份 tracked 日志脱敏 | 恰好 8 行字段值改为 `[REDACTED]`，标签/缩进/行尾与其余每个字节不变 |
| 数字、命令、错误、警告 | header 外 payload 完全一致，不是重新生成或补造输出 |
| manifest 对应关系 | 原始 SHA、脱敏 SHA、payload SHA、确切行号逐项吻合；29 个当前资产 hash 全部匹配 |
| 当前新增 tracked 文本 | 独立扫描 50 个文本；原许可证字段值命中 0，未脱敏 header 命中 0 |
| 9 个冻结保护路径 | 与统一基线逐字节相同，hash 与 manifest 相同 |
| 19 个原统计资产 | 除四份日志及仅新增 guard 的测试文件外，原 manifest 全部资产 hash 不变 |
| 作者既有函数 | 所有既有函数含装饰器 AST 完全不变；没有修改统计断言或容差 |
| 原独立统计证据 | 首次独立 manifest 中全部 owned 文件 hash 不变；原 RED 记录保留 |

四份 raw 副本保存在 ignored `local/v1811-glm-nb-raw-logs/20261004-p2/`，包括三个 `native-stata*/oracle.log` 和 `native-output.txt`。当前 tracked 日志的三组第 14–15 行与一组第 185–186 行已脱敏。完整路径/hash/判据见 `tests/eval_v1811/glm_nb_review_p2_proof.json`；没有保存原字段值。

独立 5 项定向断言＋作者新增便携 payload guard：**6 passed in 1.34s**，共享独占 runner 退出 0。作者新 11PASS 原始输出保留在自己的资产中；本报告的 fresh 实测范围为上述 6 项。

首次审查的真实 R/Stata/owner **18PASS** 统计结论继续适用于字节不变的参考、模型代码与原测试函数，此次没有重新跑这些数值。scale=1 final EIM 与固定 alpha=1 的 LR 嵌套边界仍按首次独立报告解释；本次没有增加任何宽泛 GLM-NB 准入声明。

## 复现

工作树：`/Users/jiayuanren/项目规划/.worktrees/codex-v1811-final-oracles`。

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 .venv/bin/python tests/eval_v1811/glm_nb_review_p2_recheck.py > tests/eval_v1811/glm_nb_review_p2_capture_output.txt 2>&1
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest -q tests/eval_v1811/glm_nb_review_p2_test.py tests/test_glm_nb_v1811_reference.py::test_native_log_redaction_preserves_all_non_header_bytes > tests/eval_v1811/glm_nb_review_p2_test_output.txt 2>&1
```

采集脚本拒绝覆盖已有 proof；重新采集应使用新的独占输出文件。此次脚本只读既有文件，仅新建自己的 proof/输出/报告/manifest。没有删除、安装、改写历史、merge、push 或运行完整 gate。独立复审完成，Integration 可依用户授权继续后续流程。
