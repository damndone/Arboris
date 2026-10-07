# v1.8.11 Agent live harness 生产报告

冻结基线：485ce4fcd20a9b20d15d6916d8510754b7b74834。工作树 codex-v1811-live-harness。

本报告与新增 fixture 下的证据仅代表离线实现验证；真实 provider、宿主 LMM canary、17 族 live 准入均 NOT VERIFIED，由 Root 运行。

## 已批准设计的实施步骤

- 先在新 tests/test_agent_live_eval_v1811_harness.py 证明未知/空/重复 selection、非正 repeat、FAIL 退出码、逐例持久化与禁止覆盖会失败；只 stub provider 和 seed，不作真实 LLM 调用。
- 修 scripts/agent_live_eval.py 的输入验证和逐例落盘：验证必须在 config/project/provider 前；已有 out 拒绝；异常变成失败记录继续；全部唯一预期结果通过才返回 0。
- 追加17族案例与 scripts/agent_live_eval_fixtures_v1811.json，绑定既有 CSV SHA、完整参数、原生 oracle 路径/字段/原容差；原37项保持逐项一致。
- 使用真实公开 proposal revision/fingerprint 确认、operation reconcile/terminal、run completed 与登记 SHA 验证；在结果 run 新 session 追问，原生数字从真实资产比较。
- 跑限定 pytest、tsc、diff/scope 检查，提交 owned 文件；独立复审与真实 provider 运行由 Root 完成。

## 当前结论与范围

新 harness 离线候选已实现并验证：46 PASS（25.10s），tsc exit 0。其中16族的真实 public `/runs` seed完成、执行输入/模型与 kernel owner/登记 SHA/原生字段对照已核验；LMM 节点测试验证了真实 HTTP 422 `LMM_FROZEN_CONTAINMENT_REQUIRED` 的诚实拒绝，**不是 LMM 数值或 live PASS**。真实确认/reconcile节点通过（current revision/fingerprint、completed child run/session、run_inputs proposal lineage），无 LLM。

原37 case JSON对象逐项不变，追加17后总54。新17协议明确采用“public family seed → Agent精确 model.rerun → 实际完成 → 结果run新session追问”。初始 seed不是Agent执行通过；genesis/multi-step不在新增17候选覆盖，原37继续保留原案例协议。真实 DeepSeek live、Agent回答语义质量、宿主 LMM可执行性、浏览器、全量/gate与准入登记均 NOT VERIFIED；只由Root在真实运行后认定。

每例按00fixture/seed、01source、02proposal turn、03full parameter validation、04execution、05result、06native diffs、07result answer逐阶段独占创建JSON。exception、blocked、timeout、未确认、错target/family/alpha、额外transform/options、关联到外部completed run、错登记SHA与无真实结果证据都失败。`executed`来自完成的durable operation/绑定完成结果，不读工具文本 `executed=true`。追问回答使用结果session，仅tool角色证据必须含实际run与model/artifact，并须出现要求的native数字；完整自然语言语义仍由真实live审查判定。

输入验证在provider config/project之前：empty/unknown/mixed unknown/duplicate selection或repeat≤0退出2，空catalog无provider访问退出1；已有out（含dangling link）拒绝，禁止覆盖。逐例异常持久化后继续；结果missing/duplicate/zero或任一FAIL退出1，只有全部期望唯一 `(case_id,attempt)`通过退出0。

## 逐族原生对照范围（均不是provider live认证）

| 族 | 对照来源、已核字段 | 原容差 | 未认证字段/限制 |
|---|---|---|---|
| iv_2sls | admission/iv_2sls R HC0：x1、xe estimate/SE | abs1e-8/1e-6 | 单内生；不代替双内生用例；其余输出未比 |
| glm:binomial | admission/glm_binomial R：x1、x2 estimate/SE，固定logit link | abs1e-8/1e-6 | 其余输出未比；不传unsupported link选项 |
| glm:poisson | admission/glm_poisson R：x1、x2 estimate/SE，固定log link | abs1e-8/1e-6 | 其余输出未比 |
| glm:negative_binomial | integration-strict-v1811 epsilon16 R：x1、x2 estimate/SE，alpha1/log/final EIM scale1 | abs1e-8/1e-6 | 不使用旧admission低精度oracle；其余字段未比 |
| panel_ols | panel_cluster Stata：x1、x2 estimate/SE，entity cluster | abs1e-9/rel1e-8 | 其余输出未比 |
| did | staggered.csv + panel_cluster Stata：_did_D、x1 estimate/SE | abs1e-9/rel1e-8 | cohort/cluster保持；其余输出未比 |
| linear_mixed_effects | R lme4的x estimate/SE packet保留 | 原abs1e-8/1e-4 | **真实containment阻断；所有数值/live未认证**；方差未比 |
| probit | postestimation R：x1、x2、x3 estimate | rel1e-6 | SE/CI/p未比 |
| poisson | postestimation R：x1、x2、x3 estimate | rel1e-6 | SE/CI/p、margins未比 |
| negative_binomial | 原严格NB2 R：x1、x2、x3 estimate、alpha estimate/SE，估alpha | abs1e-6、alpha rel1e-4 | 辅助CI/lnalphaSE/LR未纳入本packet对照 |
| ordinal_logit | v186 R polr：x1、x2、grp estimate；low/mid/high顺序 | abs1e-4 | 阈值、SE/CI/p未比 |
| multinomial_logit | v186 R multinom：b/c的x1、x2、grp estimate；base a | abs1e-4 | 截距、SE/CI/p未比 |
| quantile_regression | v186 R rq：tau .25/.5/.75各x1、x2、grp estimate；bootstrap0 | abs1e-5 | SE/CI/p未比；追问须出现三个tau的x1值 |
| survival_cox | v186 R coxph：x1、x2、grp estimate/SE；**Efron** | rel1e-10 | hazard ratio/CI/p/LL未比 |
| cs_did | R aggte DR/simple overall ATT/SE；x=[x1]、never/varying/anticipation0 | abs1e-6 | 其它aggregation、CI/p未比 |
| sa_did | R fixest balanced att_overall point estimate | abs1e-6（原SA点估计口径） | SE/CI/p未比 |
| dcdh | R DIDmultiplegtDYN：真实登记dcdh.json Effect_1..3与各点态SE | abs1e-6/1e-9 | **overall ATT与Av_tot_eff不同estimand，不认证相等** |

**dCDH明确known limitation**：public `coefficients.ATT`=0.7960170222577605，native `Av_tot_eff`=0.8428415529788059；runner明确前者为experimental switcher-weighted horizon mean。新增packet保留该差异及not_native_verified_fields，followup也必须说明该限定。动态三期同原生数字，不掩盖overall差异、不改生产定义/旧oracle/容差。

## RED与修复证据

- selection-red：10 FAIL → selection-green：10 PASS；原FAIL输出保留。
- protocol-red：7 FAIL/10 PASS → protocol-green：17 PASS（text伪执行、target/family/alpha/继承、binding）。
- packets-red：新增17资产缺失FAIL；public-fixtures-first 6 FAIL/12 PASS，修正自身GLM unsupported link、CS wire整数归一、dCDH比较错estimand；public-fixtures-recheck 2 FAIL/15 PASS，仅剩GLM executed owner归一和LMM真实阻断识别。
- complete-first：37 PASS；后来完整final-focused新增真实confirm时1 FAIL/40 PASS。public-confirm-recheck失败body是`AGENT_CHAIN_NOT_MANAGED`：旧dev seeder只注册in-memory Chain。测试走真实 `/agent/sessions`初始化durable activehead（生产 `_run_case`原本就走该入口）后public-confirm-initialized：1 PASS（14.06s）；未改旧seeder/center。
- edge-red：dangling out/empty catalog 2 FAIL，lineage-red：3 FAIL。最终final-green：46 PASS/4 warnings，25.10s。warning为既有Starlette httpx弃用和statsmodels BIC提示。
- 所有numeric/pytest/tsc经共享run_exclusive，保留所有pytest目录，不删除历史证据。第一次manifest收集因包括pytest alias未命中16唯一记录；改为排除alias后按真实目录收集，未改变测试结果或清理目录。

## 命令与证据

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest tests/test_agent_live_eval_v1811_harness.py -q
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py frontend/node_modules/.bin/tsc --noEmit -p frontend/tsconfig.json
```

完整命令、exit、输出SHA、candidate文件SHA与24个原CSV/oracle基线SHA见 `tests/fixtures/agent_live_eval_v1811/manifest.json`；24原资产与485ce4fc逐字节一致。`public-native-summary.json`保留16真实run的owner/参数/SHA/原生differences，以及独立LMM blocker；对应完整run/confirmation证据在pytest-859，路径/hash写进manifest。

Root真实运行须先余额检查、独立review/批准、真实宿主环境。以下只是**待运行命令**，本Lane未调用：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python scripts/agent_live_eval.py --cases scripts/agent_live_eval_cases.json --confirm --repeat 1 --out /private/tmp/v1811-live-eval-UNIQUE-FRESH --only v1811_iv_2sls,v1811_glm_binomial,v1811_glm_poisson,v1811_glm_negative_binomial,v1811_panel_ols,v1811_did,v1811_linear_mixed_effects,v1811_probit,v1811_poisson,v1811_negative_binomial,v1811_ordinal_logit,v1811_multinomial_logit,v1811_quantile_regression,v1811_survival_cox,v1811_cs_did,v1811_sa_did,v1811_dcdh
```

去掉--only保留全54例行为；每次选全新out。若LMM无法真实宿主准入，overall应exit1并保留BLOCKED，不登记17族全live通过。

## owned与交付门槛

只修改冻结design允许的scripts/agent_live_eval.py、cases追加、新fixture manifest、新tests、新tests/fixtures/agent_live_eval_v1811/**与本报告；无生产center、旧测试/oracle/tol、.agent、Downloads或依赖变更。代码、JSON和报告的限定 git diff --cached --check 通过；全路径检查会因保留的原始pytest RED日志自带trailing whitespace退出2，日志未清洗或覆盖。只本地提交，不merge/push/tag/delete；独立审查、Root真实provider/host LMM与用户合入批准仍待完成。正式v1-8-11事件由Root登记，未另开版本线。

Root的全族owner适配调研摘要另见 `tests/fixtures/agent_live_eval_v1811/owner-input-summary.json`：16真实project/run及repo测试CSV，actual run_inputs.executed_payload有无/原内容、qualified form/executable model_type和kernel协方差/权重字段；不猜默认，LMM没有completed owner。

## 独立审查三项 P2 修复候选（追加，先前证据保持原样）

原候选 `a41e21653fc058606986a08549ace030fd9c265d` 的 46 PASS 是历史离线结果，不能认证其答案字段与 owner 绑定。独立审查 `89e4d5c950df9993b78bd3fbd3f69cae8bf33d19` 证明了三个 P2：数字子串忽略字段与符号；run/model 子串接受其它 owner；completed operation 未核对本次确认身份。本节候选已完成限定修复验证，**仍待原独立审查人复验，不表示准入或 provider live 已通过**。

原审查四个实际调用用例在本 worktree 的原 a41 脚本重放为 4 FAIL，分别保存 `repair-original-red.txt` 与 `repair-original-red-records/`；未修改审查测试、旧 RED、旧 manifest、统计引擎或原生 oracle。最终同一审查测试加载修复脚本为 4 PASS（1.71s），另存 `repair-reviewed-final-green.txt` 与 `repair-reviewed-final-green-records/`。原自由文本攻击会因没有字段声明而拒绝；另有结构化的错字段、负号与合法答案控制，不能仅凭拒绝所有自由文本宣称语义修复。

修复位置：`scripts/agent_live_eval.py:303` 核对 operation 的 agent_session_id/proposal_id/proposal_revision/proposal_fingerprint/operation_id/完整 target，及持久化 confirmation 的相应 session/revision/fingerprint/target；不采用请求回显作为完成凭据。缺失或错绑定生成明确失败记录，停在 execution 阶段，不等待或读取冒用的结果。原 child bindings/outputs 一致性、真实 completed、源 run/proposal 血缘、登记 SHA 仍需同时通过。

`agent_live_eval.py:333` 只解析当前结果 session 中三种结果读取工具的结构化 tool-role 返回。run_id/model_id 或登记 artifact_id 必须在同一个对象及其 evidence_ref 中精确相等，冲突 ref、其它角色、跨对象拼接、`result_unrelated`/`poisson_10` 子串均不作凭据。`agent_live_eval.py:364` 按声明逐字段核对 actual：路径 token 的类型/值、artifact、有限有符号 value、字段数量/唯一性、精确 owner；重复 JSON key、NaN/Infinity、bool、错 term/字段/tau、缺失或额外字段均拒绝。正文额外数字拒绝，避免正确 JSON 配上错误有符号 prose 仍自动通过。

新 17 例的真实 followup 已明确要求唯一 JSON 块，runtime 再补入本次实际 owner 和字段骨架。协议如下（value 必须由真实工具读取，此处只是格式示例）：

```json
{"schema":"workbench-live-answer-v1","run_id":"ACTUAL_COMPLETED_RUN","model_id":"ACTUAL_MODEL","fields":[{"path":["coefficients","x1","estimate"],"artifact":null,"value":0.6}]}
```

每个字段须达到与 actual 相同的 12 位有效数字表示，并且其绝对差仍小于等于该字段**原 native comparison tolerance**；没有新增宽松舍入容差。12 位是明确的答案显示协议，不是统计定义或 oracle 修改。声明覆盖本族全部原 comparisons（共 70 个字段，其中 LMM 两字段仍受真实宿主阻断）；此前只检验首项/三个 QR 值的 answer indices 已扩成全部。实际值始终来自登记真实资产；expected/native 值仅作对照断言，不进入请求的 value。缺少工具可读字段、回答只给短舍入值、未遵守格式或无法核验，均保留 FAIL 供现场审查，不猜值或补算。新协议的自动检查不代替警告措辞、中文解释及 dCDH estimand 限定的人工审查。

原 37 case 对象、自由文本评分行为保持原样；新的中文语言检查仅针对新 family followup 的 JSON 块外正文。旧 37 的 free-text checks 不因本次修复而获得更强的逐字段认证。新增 17 的模型参数、CSV/oracle SHA、比较路径/统计口径/容差、dCDH Av_tot_eff known limitation 均保持原样；只改 followup 格式和答案核对覆盖字段。

TDD/最终验证：

- 原审查真实 public owner 四个 RED：4 FAIL → 最终 4 PASS；原文件原样保留。
- 新 confirmation/owner/field 契约初轮 27 FAIL（原脚本缺少新验证入口）→ 27 PASS；另有 path `False/0.0` 冒充索引 `0` 的两个功能 RED → GREEN。
- 真实 public Poisson 正控制及四个结构化反例：新建真实 public seed、真实提案/确认/reconcile、completed child、实际 run_inputs 血缘/owner/登记 SHA/原生差异，再仅替换 provider 答案 seam。合法完整声明 PASS；错字段、符号、工具 owner、confirmation 均 FAIL，错 confirmation 未写 05-result。该控制测试由 module fixture 每次新建真实 owner，不依赖历史临时目录；**无 LLM/provider**。
- 最终限定 `tests/test_agent_live_eval_v1811_harness.py`：84 PASS，29.27s；含原 46 节点和新增 38 节点。真实 public LMM 的阻断检查也算测试通过，仍不是 LMM 数值/live通过。仅有既有 Starlette 和 statsmodels BIC warnings。
- tsc exit 0。未跑全量/gate，未安装或删除，所有 pytest/numeric/tsc 经同一 run_exclusive 锁且保留临时目录。
- 24 个原 CSV/oracle、18 个原 owned fixture/evidence 文件逐字节不变，原37对象一致，17族全部非 answer-indices packet 字段不变。完整 SHA、受审脚本/审查测试身份、命令、退出码、fresh owner/positive-negative 控制记录路径见新 `tests/fixtures/agent_live_eval_v1811/repair-manifest.json`。旧 `manifest.json` 不覆盖。

最终复现（必须另选尚不存在的攻击输出目录；旧输出不得覆写或删除）：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest tests/test_agent_live_eval_v1811_harness.py -q
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend V1811_HARNESS_UNDER_REVIEW=/Users/jiayuanren/项目规划/.worktrees/codex-v1811-live-harness/scripts/agent_live_eval.py V1811_PUBLIC_CONFIRM_EVIDENCE=/Users/jiayuanren/项目规划/.worktrees/codex-v1811-live-harness-review/tests/fixtures/live_harness_independent_review_public/real-confirm-evidence.json V1811_REVIEW_ATTACK_OUT=/private/tmp/v1811-independent-review-FRESH .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest /Users/jiayuanren/项目规划/.worktrees/codex-v1811-live-harness-review/tests/eval_v1811/live_harness_review_actual_red.py -q
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py frontend/node_modules/.bin/tsc --noEmit -p frontend/tsconfig.json
```

交付仅为本地修复候选；最终提交 SHA 另在交接返回。原独立审查人复验、Root 真 provider 运行、宿主 LMM、17族现场准入、genesis/multi-step 与用户合入批准仍未完成。本次无 merge/push/tag/中心/FMS 文件变更。

## 残留 owner 数值来源 P2 再修复候选（追加，前述证据不覆盖）

独立审查 08882230056f72396a573c1c6167e8d256b020d5（重放接口增补 9cff0c76bb63d79c2201023c6b5556bc1997bf4c）证明 `2aab16400a2f4c0ec7037c4fe7aa940667dcdb58` 仍会把 current-owner 空 metadata 和 foreign-owner coefficient 数值分别认证。该 tip 的 84 PASS/原四项 GREEN 不能认证此残留场景；本轮在原脚本原样重放 `metadata_owner_only`，保留 `remaining-owner-original-red.txt` 的 **1 FAIL/32 PASS** 和独立真实 owner RED 记录。没有修改审查攻击、原生数值或先前任何 manifest/evidence。

`agent_live_eval.py:416` 新增逐字段来源门槛：每个请求的 path/artifact/value 必须能从同一个匹配 run/model 或实际登记 artifact 的 tool 对象中读取，值须匹配已登记 actual 的 12 位表示并满足原 native tolerance。`_answer_owner_evidence` 只收集身份候选，不再单凭非空候选列表认证数值。metadata-only 对象没有字段绑定，foreign 对象被排除；即使通用 numeric_grounding 从其它对象找到了相同数字，`result_answer_provenance` 仍失败。`answer_provenance.tool_field_evidence` 持久化每个字段的实际 source owner、value、actual、原容差和判定。

读取仅沿精确 path 和命名公共投影 result/model_family_evidence/family_evidence，不作任意递归数值搜索；bounded coefficients 按唯一精确 term 映射。路径经过的对象及其 evidence_ref 不能切换 run/model/artifact，主模型 result_ref 如有声明须匹配 model_results:model_id；重复 term、冲突 ref/投影、错字段/符号/舍入、相互矛盾的 current-owner 数值来源都拒绝。每个独立资产字段须有真实登记 artifact_id，不能以 model 空 metadata 或缺失映射代替。允许多个工具返回的完整 current-owner 对象分别支持不同请求字段，不能把 owner 元数据与 foreign 数值拼接。

另以单独 1 RED 证明旧 Unicode 边界漏掉中文紧邻的正确数字/错字段 prose，例如正确 JSON 配“x1的标准误为0.60”；已在新17协议的正文数字检查中修正为 ASCII 变量标识边界。缺失登记 artifact 映射另有 1 RED → GREEN。原37自由文本评分和协议不变。此轮 cases/fixture packet 均无改动，原生路径/统计定义/容差没有变化。

验证结果：新增来源绑定初轮 14 RED → GREEN；最终 producer 限定文件 **104 PASS/4既有 warnings，29.70s**，包含真实 public Poisson 重新执行和真实 `inspect_project_model_coefficients` bounded 系数列表的正控制，以及 raw/bounded/命名投影、同-owner 分批返回、QR多tau/ancillary、登记 artifact 正反控制。原独立完整33节点显式加载最终脚本 SHA `9aed19ef826381869555d2497e38cbc75ad6b00d9c9526659202ccb39c35a806` 为 **33 PASS，1.37s**；其中合法声明/24确认身份 mutants 保留，metadata_owner_only 的唯一来源门槛明确失败。tsc exit 0。全部 pytest/numeric/tsc 经共享独占 runner 保留临时目录。

完整命令与 SHA 见新增 `tests/fixtures/agent_live_eval_v1811/remaining-owner-manifest.json`。对照2aab：原44份 fixture/evidence 原字节一致，cases/packet 原字节一致，旧 owned test 原文件完整前缀保留，仅追加20节点；24个原CSV/oracle一致。本节只追加报告，不改前述结论证据。原独立重放入口已支持 V1811_RECHECK_SCRIPT/V1811_RECHECK_SCRIPT_SHA256/V1811_RECHECK_OUT，后者必须使用 fresh 目录；重放精确例：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend V1811_RECHECK_SCRIPT=/Users/jiayuanren/项目规划/.worktrees/codex-v1811-live-harness/scripts/agent_live_eval.py V1811_RECHECK_SCRIPT_SHA256=9aed19ef826381869555d2497e38cbc75ad6b00d9c9526659202ccb39c35a806 V1811_RECHECK_OUT=/private/tmp/v1811-owner-recheck-FRESH .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest /Users/jiayuanren/项目规划/.worktrees/codex-v1811-live-harness-review/tests/eval_v1811/live_harness_review_p2_recheck.py -q
```

本候选仍待原独立审查人读取最终 committed tip 复验。没有合法 owner/字段公共投影时会保留 FAIL，不从没有绑定的兄弟对象补来源；未实现或未现场核验的模型公共投影不得因此宣称live通过。中文说明/警告/estimand措辞仍需现场语义检查。无 provider、中心修改、全量/gate、安装/删除或合入；LMM宿主/17族真实 live/准入、用户合入批准继续 NOT VERIFIED。
