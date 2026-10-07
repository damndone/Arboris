# v1.8.11 正式 Lane E 评估报告

状态：正式E七项已完成。范围内未确认生产缺陷；最终累计47个pytest节点通过、1个Stata停止精度FAIL原样保留，该模型经一次真实R闭式量验证Workbench符合最优解。本报告不宣称48个pytest全绿，也不代替browser/provider/release准入。

worktree `/Users/jiayuanren/项目规划/.worktrees/codex-v1811-evaluation`；分支 `eval/v1811-codex`；生产冻结 baseline `5f8451b929ac51ba7ae9821e4a8a7f1adea642a8`。用户已批准正式 E 及并行，M1/M2/S、双内生IV参考、FPC/GLM-NB脚本统计adapter、17族harness已合入。主线随后0289b65e仅更改旧FPC测试/文档，生产与冻结相同；本E坚持5f生产与自身新增测试，不将过时FPC忽略/拒绝断言作为产品缺陷。

只新增 `tests/eval_v1811/lane_e_20261005/**`、`tests/fixtures/eval_v1811/lane_e_20261005/**` 及本报告。不改生产、旧测试、参考、容差、正式devline；不安装、删除、merge/push/tag、跑全量/gate/tsc、不访问Downloads/私有VIX、不调用provider/真实LLM、不创建服务。正式 E 与已有专项复审分开，旧RED证据保留。

按七项工单每项一个测试文件，最多30分钟。先跑本E七文件一次；PASS节点不复跑。若存在自身harness错误，只修具体入口并复跑受影响节点；生产失败原样保留，不第三轮、不改产品或放宽容差。所有数值与软件执行均通过主线 `local/v1811-coordination/run_exclusive.py` 共享锁，与真实53case live串行，锁排队等待不计数值运行时间。

| E项 | 当前结果 | owned测试文件 | 范围 |
|---|---|---|---|
| E1 | 4节点通过；边界SE限制 | test_e01_joint.py | 新ARMA(2,2)–GARCH(1,1)、AR .98、小β；真实Stata最终参数/SE/LL/IC与明确不收敛 |
| E2 | 6节点通过 | test_e02_count.py | 新NB2/NB1/fixed数据；真实Stata OIM与R最终EIM；固定alpha无LR、未认证边界/缺alpha拒绝 |
| E3 | 4节点通过 | test_e03_panel_did.py | 新panel/DID真实默认t/df/p/lincom/Wald；staggered事件研究F/df/p；小G与legacy只读标记 |
| E4 | 25节点通过 | test_e04_post.py | 三GLM五post和两种margins真实R；双内生IV真实Stata；LMM未验证与IV无LL明确拒绝 |
| E5 | 6节点通过 | test_e05_scripts.py | 实际HTTP .dta上传→subset→multiply→clusterOLS→持久Wald→三语言ZIP实跑；源SHA破坏；真实NB1快照接续与完全原生拒绝 |
| E6 | 1节点通过；1保留FAIL、R闭式正确 | test_e06_classical.py | 手动诊断警告/自动门槛/短lag unavailable；模拟classic全样本+prefix首origin真实Stata，未来尾值攻击 |
| E7 | 1节点通过 | test_e07_entries.py | 同一GLM-NB缺alpha组合的真实HTTP/CLI与确定性Agent编译拒绝一致性 |

LMM已有宿主dbe真实拟合3PASS，本E不重拟合、不撤销containment；post未验证，REML LR仍不得被开放。GLS(lme4)与fullOIM(statsmodels) covariance差异尚未关闭，不能用拟合通过认证post。VIX原omega失败报告保留；root另报告高精度R/nativeStata复验已通过原门槛，本E没有读取数据或独立验证该新私有验收，不能把旧失败或根新PASS冒充本E实测。

已有专项报告仅用于定位/历史来源；本报告最终只计本E实际节点及明示引用证据，不复查7000资产SHA。R/Stata直接读取公开模拟CSV/已有publicfixture，不从Workbench expected构造原生结果。所有原合同数值容差保持；已完成结果快照仅认证真实归档接续，不称目标软件重新拟合。

## 首轮实测与失败归因

`r01/pytest-output.txt`：48节点，44 PASS、4 FAIL，33.41秒。通过节点不再跑。`r01/run-manifest.json`记录每一实际node、耗时、outcome、冻结baseline、实际HEAD与模块导入路径；实际加载的是本树`backend`的joint_mle/count_models/builder，而非主线随后修复或其他旧工作树。

1. E1 `small_beta`：无约束Stata给出β=−0.006104257312327369，Workbench按C1的α/β非负约束落到β=0。原对照的μ差0.000113531569372104，超过1e−4，但它比较了不同约束域，不能定性产品数值缺陷。最终对照按真实Stata`constraint define 1 [ARCH]L.garch=0`对齐该边界，原参数/LL容差保持。约束Stata的covariance固定一维、IC rank减少，而Workbench仍有全部参数OPG；最终仅验证同域参数/LL与冻结C1全部参数k公式的IC，不将固定β的SE或rank5的IC冒充full-parameter推断等价。边界SE/CI没有在本E得到原生认证，必须保留该限制。
2. E3 `panel_ols`：生产同时用EntityEffects与TimeEffects（runner.py构建公式），首轮Stata仅有单位FE，漏了`i.time`，x1估计0.48385401548639123与0.4907132918351812的差是测试参考公式错误。最终补时间FE，其余输入/cluster/t/df/p/post与全部原容差不变。
3. E6：零均值ARMA(0,0)的Stata默认优化停点使variance=1.0839934372675566，Workbench=1.0841774164273454；LL分别−210.14630198833817与−210.1463009514371。最终仅收紧原生优化停止条件，不改统计模型、样本、Workbench或容差，再检查真实Stata最终点。
4. E7：HTTP正常异步返回200/running，两条实际HTTP/CLI owner最终都为failed，issues明确`GLM_NB_ALPHA_REQUIRED`，没有模型结果。CLI现有源码合同是stdout返回持久化run_id（注释明确长期shell契约），不是失败模型一律非零exit；首轮即时HTTP≥400/CLI非零断言是测试入口错误。最终检查HTTP终态、CLI返回run_id指向的真实failed owner、相同明确错误与没有静默alpha默认。Agent确定性编译已明确requires alpha。CLI退出0不作为本任务产品缺陷；也不将Agent编译拒绝称为provider执行验收。

公开完整路径E5首轮三语言各30条实际numeric self-check：Python最大绝对差1.4210854715202004e−13，R 7.105427357601002e−14，Stata 4.263256414560601e−14；均exit0。三份ZIP SHA、原生命令、plan、来源文件、schema、逐字段实际/expected/allowed均在owned r01中。篡改源bytes的三语言执行明确失败；源SHA不是只看JSON声明。NB1的三语言结果接续明确标为snapshot，require_native拒绝，不称重新拟合。

四个问题各只进行一次定向最终重放；完整r01输出、source与raw scratch均不覆盖，r02使用新输出/新scratch。最终r02只选择首轮4个失败节点：3 PASS、1 FAIL，14.53秒；没有重复任何首轮PASS、没有第三轮fit/pytest。`evaluation-summary.json`保留按node合并的47 PASS/1 FAIL，r01/r02是各自原始结果，不能称两轮全套或48 PASS。

## E6停止精度归因与结论

root明确授权一次纯原生R读取同一已执行CSV计算零均值Gaussian闭式MLE、LL与score；没有再次拟合、没有新统计口径/参数/容差。`native_classic_definition.R`与`e06-native-r-definition.json`显示R4.6.0：

| 点 | variance | Gaussian LL | variance score |
|---|---:|---:|---:|
| R闭式mean(y²) | 1.0841774164273452 | −210.14630095143715 | 1.42e−14 |
| Workbench最终值 | 1.0841774164273454 | −210.14630095143715 | 0 |
| tight Stata最终值 | 1.0841775206953714 | −210.1463009514375 | −6.386793145907177e−6 |

R闭式与Workbench差2.22e−16；prefix140观测也差2.22e−16、Workbench score=0，而Stata prefix残差score=−1.911263396436880e−6。Workbench在这一定义上符合最优解，保留的FAIL源于Stata有限停止精度未满足abs1e−8，而非已确认的Workbench生产统计错误。对Stata差异不放宽tol、不删除FAIL、不再拟合找更好参数。经典全样本/严格prefix与未来tail攻击未失配；本E的原生对照结论要带该参考精度例外。

## 实测覆盖和界限

E1新增ARMA(2,2)/AR=.98两组完整最终参数/OPG SE/LL/AIC/BIC符合C1；smallβ只证明对齐非负边界后的参数/LL与冻结k公式，SE/CI不能借固定β参考认证。失败max_iterations=1明确blocking、无部分数字或sequential降级。E2新NB2/NB1/Stata OIM与fixedalpha OIM、真实R fixedGLM EIM、边界未认证阻断、固定NB1和缺alpha拒绝全部通过；边界用恒定响应检查明确拒绝，并非新的完整Poisson-boundary ancillary原生认证。

E3真实panel/basicDID默认CR1 cluster/t/df/p及lincom/Wald；staggered事件研究原生F/df/p与系数/SE，小G/legacy标注均通过。E4三GLM各Wald、lincom、nlcom、LR及average/means margins（6组操作）有fresh真实R；双内生IV三操作有fresh真实Stata。固定GLM-NB LR只针对相同固定α=1.3的嵌套均值模型，不包含估计α、多软件默认α或α=0边界检验；E2固定α=.7同理。LMM五post的NOT_YET_VALIDATED、IV无LL拒绝及panel margins未验证均保持；不宣称七族全部post笛卡尔积本E重验或LMM post开放。

E5三语言actual HTTP .dta原始上传→实际清洗→subset→multiply→cluster OLS→Workflow执行confirm的持久Wald→真实ZIP→执行；30个比较均绑定实际plan步骤/字段且有原生结果。所有数据、标签与来源SHA在包内，tamper均拒绝。另NB1快照只认证已完成结果接续，不冒充原生模型重估。E7测试的是无provider的真实HTTP/CLI终态与Agent确定性编译拒绝，不是模型回答或真实LLM确认流程。

范围内无需生产修复；E6原生Stata点精度例外和E1边界推断限制须随集成保留。browser、真实provider/live53、Claude(a,b)、hostgate、fullchaos与release均不是本E认证；主线随后summary evidence_ref/selected-model评测差异没有加载进本E冻结包，应独立按差异审查。

## 证据与复现

生产冻结/实际执行HEAD均`5f8451b929ac51ba7ae9821e4a8a7f1adea642a8`。实际导入路径均为本worktree `/backend/workbench/{__init__.py,engine/packs/arma_garch/joint_mle.py,econometrics/count_models.py,script_export/builder.py}`，manifest逐路径SHA明确；本地审查提交只新增评估文件，不成为新的生产功能baseline。

- `tests/fixtures/eval_v1811/lane_e_20261005/r01`：原始48节点首轮输出/manifest、源代码快照、输入CSV、独立R/Stata命令及公开命令输出、actual owner路径、实际三语言脚本包/逐字段numeric_pairs。
- `r02`：仅四个修正参考/入口节点的最终输出/manifest/源代码快照和真实新owner，完整首轮失败仍保留。
- 两轮scratch在各自`scratch-path.txt`记录，目录均首次不存在，`--basetemp`直接指定；没有默认pytest历史清理。所有完整Stata raw logs留scratch且0600，tracked只取`. do <script>`后的公共输出，不含license字段。
- `e06-native-r-definition.json`、`e06-definition-check.json`：纯R和直接读同CSV的闭式归因，后者是数据/定义检查，不作为新原生拟合证据。
- `final-evidence-manifest.json`：baseline、模块paths/hashes、owned证据paths/hashes、精确commands、源码未改范围和结果分类。

所有命令在本worktree，`LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=<本tree>/backend`。两轮pytest另设`WB_LANE_E_OUT=<本tree>/tests/fixtures/eval_v1811/lane_e_20261005/r01或r02`，经主线`.venv/bin/python local/v1811-coordination/run_exclusive.py`执行本tree`.venv/bin/python -m pytest`；七文件首轮与四node最终选择、完整absolute backend `-o pythonpath=`及fresh `--basetemp`见manifest精确命令。纯R也经同一runner，未占用其他线的锁同时运行。
