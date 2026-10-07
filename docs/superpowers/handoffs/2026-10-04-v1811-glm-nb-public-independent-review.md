# GLM-NB 公共集成独立审查

结论：**PASS（`67088c98` 的限定公共后估计接线）**。独立新测试 **34 passed in17.67s**，真实同名协变量补验 **2 passed in13.54s**；另六个实际 HTTP kernel 的独立 R 审计通过。没有确认新的可复现 P 问题。不代替完整浏览器、真实 Agent/LLM live、全量 gate 或发布验收；`PLANNED.live_eval` 保留。

被审 tip `67088c983e0ed80c20b5ecb29a1a9f5d73140962`，parent baseline `824b2e0c40eeb962b739fe467821a22de91523e8`；获批原生资产 merge `8a05bbe22a9e12ba582e22d0e21e022a5edf0323`（候选5b82）。worktree `/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11`，开工 clean HEAD 与指定 tip 相同。审查期间 Root 更新独立脚本 builder/文档至 `eb9b34270f6a3ac93ba33608acb10bcf91d430fe`，被审 post/consumer 不变；其 data_operation_routes/runtime/new builder test dirty 保留。本审查只新增 `glm_nb_public_review_*` 与本报告，不改生产、旧测试、oracle 或容差。

| 独立攻击 | 实际结果 |
|---|---|
| 公共 alpha0.5/1/2 owner 与五操作 | 六个模型由真实 TestClient HTTP `/runs` 拟合并完成；每个 alpha 的 Agent compile/runtime 运行不同于作者的 Wald `x2+x3=0`、lincom `x2-.3*x3+.2`、nlcom `exp(x3)`、LR full/restricted 与 x3 margins average/means，共18节点对新真实 R通过 |
| 结果确实可消费 | 每个步骤的真实 artifact 已登记SHA、绑定 model_run_id/glm_1；HTTP `/runs/{id}` 的 post_estimation_results 与 Agent实际数值完全相同，来源 SHA 对应实际 owner 的 cleaned dataset。没有把调用成功当数值证据 |
| LR固定似然一致性 | 三个 same-alpha LR（含固定1.0）对真实 R通过；.5→1、1→2、2→.5 三种不同 alpha 公开执行均先按 `alpha_fixed_value` 拒绝，没有输出虚假嵌套 LR |
| 辅助参数准入 | 基础模型无 alpha/lnalpha 协变量时，二者在 Wald/lincom/nlcom/margins 共8路径明确拒绝，不能冒充 beta |
| 实际同名协变量 | 只修改原 CSV 的 x3 header 为 alpha 或 lnalpha，数值 body完全相同；固定 dispersion alpha2 与该真实 regressor并存，beta kernel保留它，四操作均对 R x3改名等价参考通过，没有按名称错误过滤真实协变量 |
| margins/kernel来源 | 另保留四个临时 owner副本，篡改 kernel bytes、processed x3、diagnostic bytes或completion；均在来源/owner层明确拒绝，不退回naive或更换数据，未还原覆盖攻击 bytes |
| capability自动推导 | registry五项、Agent vocabulary/dispatcher一致；独立替换进程内声明以移除该family后，生成的step summary也自动移除该family。admission指向已批准R资产，live evidence为空、PLANNED=v1.8.11；没有手工宣称live准入完成 |

新真实原生脚本 `glm_nb_public_review_native.R` 不导入 Workbench，以 MASS fixed-theta log GLM、car、lmtest、marginaleffects在原始未变 CSV上运行 alpha .5/1/2。每个 full/restricted fit 的 natural beta score/n均小于原1e-8门槛，最大 `6.171477660345201e-13`；最终 EIM scale1通过Cholesky，最小 eigenvalue在所有fit中均正。完整17位字段与环境写入独立 JSON，不从 expected常量或 WB结果生成。

六个 retained HTTP kernels 的 beta对该新 R最大绝差 `1.78207448797707e-12`，SE最大绝差 `1.4391265956703592e-14`；沿用原 owner测试 beta abs1e-8、SE abs1e-6。五操作使用原 rel1e-6/p及margins-SE rel1e-5，没有新容差或放宽。kernel SHA在公共执行前后相同。原获批 alpha1 R/Stata 与脱敏日志资产全部只读保留，当前审查没有重新写入原参考或访问旧私人日志。

Git审查：670仅新增 registry/admission参考接线与公共测试/说明；count producer、统计primitive、kernel schema/row fingerprint与真实数值实现相对parent baseline没有变化。主线新脚本工作不混入本报告认证范围。

数值均经过独占 runner，cwd如上，retention=all：

```sh
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py Rscript tests/eval_v1811/glm_nb_public_review_native.R tests/fixtures/postestimation/data.csv tests/eval_v1811/glm_nb_public_review_native.json
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest tests/eval_v1811/glm_nb_public_review_adversarial.py -q -s
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python -m pytest tests/eval_v1811/glm_nb_public_review_named_regressors.py -q -s
LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8 PYTHONPATH=backend .venv/bin/python /Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.11/local/v1811-coordination/run_exclusive.py .venv/bin/python tests/eval_v1811/glm_nb_public_review_kernel_audit.py
```

全输出、exact功能tip、baseline、source/reference/旧证据/新文件及retained真实run/攻击路径/hash在 `glm_nb_public_review_manifest.json`。首轮主探针33PASS/1失败为自己的异常类型要求过窄：processed被更早 source resolver以 `DataColumnCastValidationError` 明确拒绝；最终只接受该精确拒绝类型。真实同名协变量首轮2失败发生在自己的quoted CSV header解析、进入生产之前；已修自己的header处理，numeric body不变。两轮原source/output均保留，未删除或改旧测试伪造PASS。

共享锁已释放。本审查未重跑作者110测试/tsc，不宣称其为独立证据；无 full gate、网络LLM、安装、Downloads、删除、merge/push/tag。后续只限定提交 owned独立资产；用户批准前不执行外部发布动作。
