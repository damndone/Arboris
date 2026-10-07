# 完成结果导出集成：待独立复审

基线 `f623a4ee`。只按原 objective §7/C3 修复完整结果交付；原统计方法、默认值、R/Stata oracle 和容差未改，冻结 ScriptPlan 未改。

## 最终行为

- 族的 `ScriptResultLayout` 声明 envelope、artifact身份、实际系数投影、估计输入准备和完整数值文档角色；共享 builder 没有按族名字分支。
- 快照保留主结果、推断核心、diagnostic_summary、声明 evidence_document/sidecars，以及时间序列注册 JSON 文档。每份原始文档附本地裸文件名、真实artifact id、SHA；runtime 在任何数值自检前验证文档。optional documents 扩展不改变既有无扩展 v1 sidecar 的读取。
- QR 保留所有 quantile fit/interval/bootstrap/cross comparison；CS/SA 保留 simple/dynamic/group/calendar 及标签；dCDH 保留 event study 和不同总体estimand的限制说明。完整数值按文档角色的 JSON pointer 自检，保留 null、字符串标签和不适用说明的原文档。这里未创造新的推断、SE或分布。
- ETS 用原 typed result 的 n_obs/params/IC/LL，空 regression kernel 不补 SE。ARMA-GARCH 核对每个 artifact_ref 的实际registered角色/owner，保留训练/生产、参数、诊断、conditional/rolling/next forecast和acceptance状态，不把回顾指标改称独立验证。
- DID 复用封印角色字段与执行 normalize_did_input，单列 `data.estimation_input` 快照准备步骤及原因，之后三语言原生 DID 估计。当前准备步骤未声明为完全原生；require_native 明确列出该步骤并拒绝，不能宣称整个 DID 路径完全原生。
- LMM graph 指向 `.result` artifact，与模型/kernel id不同；显式suffix声明验证两者。typed public envelope只有primary interaction，完整5项固定效应保留在原推断核心。复用实际输入prepare/formula与producer interaction命名证明publicprimary的estimate/SE对应核内唯一项，不伪造缺少的完整系数行。保留随机效应/figure/diagnostics，快照数值含真实随机方差。

## RED → GREEN

独立 `1c701347` 七个真实完成owner缺口已保留。根新测试初稿的 GraphStore API/fixture文件路径/execute dataclass/PYTHONPATH 错误全部保留日志并纠正，不把这些harness错误记成产品RED。最终 `complete-result-red-r03.txt` 中七份文档完整性断言/typed packet拒绝是真实缺口；部分执行错误仍是错误的相对PYTHONPATH，之后已修正。`result-documents-red.txt` 的valid optional document读取1 RED/6 PASS是独立contract RED。

新的真实宿主owner `20261005_024643_550779_dbe309ee`，用户返回 **3 passed, 1 warning in 2.67s**。根只读复查真实canary、completed、26条完整index、1份strict public result、5项kernel/N=360。原R差：固定效应9.565332526051407e-9、SE7.9580113040989e-7、随机截距方差3.7404650424788244e-6、残差方差-4.73113604071429e-7。旧owner不改写/重新登记。导出首次3 RED定位`.result` artifact id不能作为kernel id；该LMM身份与primary-only布局修正后3语言通过，前后所有host文件SHA不变。

最终相关后端：**243 PASS /81.08s**，包含完整结果/现有lineage/真实public防篡改/原sidecar攻击/合同/族名ratchet，以及原CS、SA、dCDH、QR等R/Stata参考与ETS known truth。tsc exit0。完整8种owner三语言 **24脚本/7398数值自检全部exit0**；最大绝对差6.750155989720952e-14、最大原允许误差占比1.7644764749749906e-9。大部分是完成快照读取自检，不能把它们称为三软件独立重新估计全部族；DID本轮在真实软件里重新估计。

50节点实际public完整ZIP再测 **0.391903583秒 /1,280,581 bytes**，小于原1秒预算，1 PASS/14.42s包含准备工作。

本机证据：`local/v1811-coordination/complete-result-green-r02.txt`、`complete-result-native-summary.json`（pytest-951的24个execution/numeric_pairs路径）、`complete-result-50-node.txt`、`lmm-complete-export-red.txt`与green、`result-documents-red.txt`。Stata原输出和宿主结果只在本机留存。

## 未认证事项

独立完整结果复审待做；真实浏览器完整快照/拒绝/Agent导出、待批准原生FPC/GLM-NB adapter合入、17族真机/评估E/Claude两节点/full gate/发版未完成。VIX原omega绝对差超1e-4仍UNRESOLVED，不能用同目标更高LL或修改容差判通过。没有push/tag/release/删缓存或worktree。
