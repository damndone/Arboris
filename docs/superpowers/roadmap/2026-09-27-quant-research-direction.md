# Quant 方向：AI 驱动、可验证的量化研究工作台（2026-09-27）

> 来源：用户设计笔记 Obsidian `workbench开发/路线图/Quant设计`（2026-07-22）。本文件把它与 v1.8.9 的
> 实际代码和 `followups/BACKLOG.md` §0.2 对齐；原笔记为准，这里只记录落地顺序与前置依赖。

## 定位

不是“一句话生成回测”，而是**一个能证明回测为什么可信、以及在哪些条件下不可信的研究工作台**。
通用统计工具仍是主线；Quant 是建立在同一套地基上的垂直方向（Quant Research Pack），不改变产品定位。

三条原则与 Workbench 现有原则一致，直接沿用：

1. 确定性引擎先行，Agent 负责理解、选择、编排、解释；收益、交易日历、复权、数据可用时点、成交、
   前视偏差判断一律由后端给出事实（对应现有的数字核对、确认边界、只读策略）。
2. 记录全部研究过程：测试了多少因子、多少参数、淘汰了哪些、为什么（对应现有的分析台账与报告披露）。
3. 多重检验与过拟合是一等问题（对应现有的反 p-hacking 规则、每会话检验预算）。

## 与现有资产的对应（v1.8.9 已有 / 缺）

| Quant 需要 | 现状 |
|---|---|
| 研究路径与分支、rerun、compare | ✅ 血缘图、rerun、Compare |
| 实验记录与选择性报告防护 | ✅ 分析台账 + 报告披露（需扩展到 trial / 参数搜索计数） |
| Agent 不自己算数 | ✅ 数字核对 + `calculate` |
| 面板与时间序列模型 | ✅ Panel OLS、ARIMA/VAR/VECM/GARCH |
| Newey–West（HAC）稳健标准误 | ❌ 未实现 —— 通用计量同样需要 |
| 统一结果信封（→ FactorEvaluationPacket / BacktestResult / Strategy Validation Packet 的底座） | ❌ `V189-RESULT-ENVELOPE` |
| 分组分别执行（分行业 / 分市值 / 分市场状态） | ❌ `V189-BY-GROUP` |
| ML 组合（Lasso/EN、树、排序学习）与时间感知验证（walk-forward、purged CV、embargo） | ❌ `V189-CLASSIFICATION-ML` 需把时间切分纳入同一验证契约 |
| 受限表达式引擎（因子公式） | ❌ 现为封闭比较运算符；需安全 parser / AST / 类型检查 |
| 图的可扩展：分层图、集合节点、ParameterSweep、trial 晋升、有界投影 API | ❌ `GET /graph` 一次返回全项目森林，无分页与上限 |
| 列式数据平面（Parquet 已用；Arrow/Polars/DuckDB） | 🟡 Parquet 已用；1M 行性能达标 |
| point-in-time 数据语义、交易日历、股票池历史成分、成本模型 | ❌ Quant Pack 专属 |

## 建议顺序（嵌入现有版本计划）

**v1.8.10 扩展地基**（通用主线，Quant 直接复用）：`V189-RESULT-ENVELOPE`、`V189-POSTEST-REGISTRY`、
`V189-MODEL-ACCEPTANCE-KIT`，并加入 **HAC/Newey–West** 与 **`V189-BY-GROUP`**。

**图的可扩展（Quant 笔记列为“现在就做”，影响持久化模型）**：集合节点（ExperimentSet / FactorSet /
ParameterSweep）、Trial ≠ Graph Branch 的晋升制、有界投影 API（overview / neighbors / group children 分页、
单视图节点与边上限、`VIEW_TOO_LARGE`）、折叠与聚焦视图。建议作为 v1.8.10 或 v1.8.11 的独立一条线，
先于任何大规模参数搜索功能；它同样服务通用场景（稳健性组、分组执行、多模型比较）。

**v1.8.11 预测与 ML 核心**：按 Codex 分类计划精简，验证契约从一开始就包含时间切分（walk-forward、purged、
embargo）；实验与参数搜索计入台账。

**v1.9.x Quant Research Pack — Level 1「因子研究最小闭环」**：交易日历、PointInTimePolicy、UniverseDefinition、
FactorDefinition（受限表达式）、去极值 / 标准化 / 行业与市值中性化、IC / RankIC / ICIR、分组收益与单调性、
衰减、换手、交易成本、与已有因子相关性、Strategy Validation Packet；Deflated Sharpe、PBO 等过拟合评估。

**之后**：Level 2 组合构建与回测、风险归因、容量；Level 3 有实验预算的自动研究 Agent；Level 4 模拟交易。
Level 5 自动实盘不作为目标。

**语言**：不整体重写。Python 控制平面 + Arrow/Parquet/Polars/DuckDB；只有经 profiling 证明的稳定热点
（滚动窗口、横截面 rank、成交模拟、表达式执行）才用 Rust。

## 开工前需要用户确认

- 市场与数据源（A 股 / 美股；Tushare、AkShare、Wind、聚宽等），以及是否有 point-in-time 财务与历史成分数据的授权。
- Level 1 的目标用户（个人研究者 / 团队），决定是否需要多用户与数据权限。
