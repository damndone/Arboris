# Retrospective — v1-8-6-predictive-research-foundation

## Goal

# Workbench v1.8.6 Predictive Research Foundation 实施计划  状态：设计范围已由接手说明确认；本计划是唯一中央实施计划。生产改动必须在正式 FMS 开发线建立后进行，并遵守每阶段先红后绿。  ## Objective  从 \`origin/main=7e257f2e4fc7ac3b75d68dd270c33021dffad530\` 建立 v1.8.6 正式线，在不修改 v1.8.5 release、main 本地证据或历史 artifact 的前提下，为通用表格回归建立可复现且 fail-closed 的 Predictive Research 正确性基础：持久化 typed SampleSpec（含抽样权重、 结构、可得性、FeatureRecipe）、显式 SplitPlan 与 fold 隔离预处理，可信 OOS prediction、 baseline、permutation/noise controls、最小 payload schema gate，并把证据投影到 Graph、 Table、Report、Compare、Agent；另以不重叠的 statistical_tests.py slice 提供统一统计 证据。不得把 temporal/panel/完整 PIT/Quant/自动调参/任意 code.execute 或实盘能力伪装为 本版交付。  ## 固定基线与约束  - 工作树：\`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.6\` - 分支：\`workbench-v1.8.6\` - 基线：\`origin/main\`、\`v1.8.5\` 与工作树创建点均为 \`7e257f2e4fc7ac3b75d68dd270c33021dffad530\` - 正式线：只用 \`PYTHONPATH=backend python3 scripts/devline_control.py start\` - 依赖：复用链接的 \`.venv\` 与 \`frontend/node_modules\`；不安装依赖、不访问网络、不暴露密钥 - 核心原则：TDD；先观察真实失败，再实现；未知结构、权重语义、recipe、schema、可得性   或 split profile 均不得静默降级；旧 prediction 只读兼容且与新结果不可比 - 禁止：push、PR、merge、tag、修改 main/v1.8.5、重写历史证据、删除 durable worktree、   任意 Python/SQL/code.execute、Quant/PIT/交易、深度学习、超参数平台、数据 reshape/merge  ## 交付阶段  ### 1. Contracts and schema gate  新增共享 contract 内核，定义 SampleSpec/SamplingSpec/StructureSpec/AvailabilitySpec、 FeatureRecipe、SplitPlan 与新 packet 的 \`payload_schema/schema_version\` envelope。扩展 artifact registry 校验，使 producer 在 index 更新前验证，consumer 对未知版本保留身份但 拒绝解释。sampling_weight、analysis_weight、frequency_weight 必须分别表达；不支持时 fail-closed，不能转换或忽略。  红测：缺字段/类型/非有限数/未知版本、未知结构、权重冲突、缺可得性 reservation、未知 recipe 和重复运行 hash 不变量。  ### 2. Split and fold preprocessing  实现随机/分组声明与可复用 SplitPlan；持久化 random/grouped/temporal 参数（含 group/time/ entity、ratio、fold、seed、shuffle、gap、embargo 和来源）。IID/Grouped 可执行；unknown 阻塞；temporal/panel 仅校验并拒绝随机执行。共享 fold kernel 保证 imputation/MICE/均值中位数 填补、scaling、feature select、PCA、target encoding 等 fit-state 只在当前训练 fold 拟合。 保留 \`stateless\` 与 \`date_local\` 语义，不把后者当作 period fit。  红测：global scaling、test-fold imputation、先 fit 后 split、group 泄漏、final holdout 进入 CV，以及 temporal/panel 误走 random。  ### 3. Prediction, baseline, controls and legacy boundary  在既有 prediction 入口接入协议，不新增 fixed test_size/alpha/cv 常量。所有候选与 mean baseline 共享同一 SplitPlan；新 PredictionPacket/EvaluationPacket 记录 assumptions、fit folds、各 partition n、row predictions、OOS metrics、baseline、controls、limits。实现 seeded permutation target、seeded noise feature 和 future-shift conformance；legacy artifact 不 生成伪 SplitPlan、不回写、不与新结果 Compare。  红测：final holdout 隔离、同 seed 可复现、置换/噪声退化、future-shift 在 estimator.fit 前 拒绝且不产生 packet、legacy/new Compare 稳定拒绝。  ### 4. FeatureRecipe  注册 deterministic derived variable、recode、interaction、log、ratio；记录输入/输出/类型/ 参数/version/fit scope/source artifact/parent/missing/outlier/reproducibility。零值、负值、 缺失、异常值策略必须显式；未知操作、动态表达式、dataset/exercise 分支和默认 code.execute 拒绝。recipe 输出绑定 SampleSpec/TaskSpec，消费者不临时重算。  ### 5. Independent statistical slice  只修改 \`backend/workbench/statistical_tests.py\` 及对应测试/证据投影。新增 posthoc ANOVA、 Tukey/Bonferroni、Cohen d、eta/omega squared、one-sample t、paired t、Wilcoxon signed-rank、 Levene/Bartlett、Shapiro-Wilk；统一输出 assumptions、warnings、effect size、CI（适用时）、 校正范围和 finite/degenerate 状态。保持既有检验/FDR/估计器行为，不自动参与 prediction model selection。  ### 6. Consumers, UI and release evidence  让 Graph/Table/Report/Compare/Agent 只读取已验证、版本匹配的 packet，引用同一 Sample/Split/ Evaluation/Control lineage。更新预测 UI 以显示结构确认、实际 SplitPlan 参数、OOS/baseline/ control/limits；未知结构提供可执行下一步。最后分别记录自动化测试、native browser（未做前 均为 \`NOT VERIFIED\`）和 \`bash scripts/gate.sh\` full gate；不把其中任一证据替代另一项。  ## 验证顺序  每个阶段均执行：  1. 新增或改写测试并确认修复前真实失败； 2. 实现最小改动； 3. 运行阶段 targeted pytest/TypeScript/Vitest（不直接 TypeScript \`| tail\`）； 4. \`git diff --check\`、allowlist 检查、FMS event append/verify； 5. 记录 changed files、红证据、绿证据、能力、gap、风险和是否 scope expansion。  收尾前运行相关 targeted gate、\`bash scripts/gate.sh --quick\`，最后在允许的本机服务状态下 运行 full gate；browser interaction、性能、containment、release/merge/tag 分别记账。任何 网络/依赖/沙箱能力问题单独记录，不得 skip/xfail 冒充产品通过。  ## Allowlist / protected boundary  Allowlist 由正式 Context Pack 固定，覆盖本计划、既有 v1.8.6 design、 \`backend/workbench/predictive_research\`、预测/artifact/domain/engine/agent/report 相关现有 文件、\`statistical_tests.py\`、预测 UI 和对应 tests。统计独立阶段不能扩展到预测主链路。  Protected：\`.agent/devlines\` 中既有线、\`.worktrees/workbench-v1.8.5\`、v1.8.5 release notes/ handoff/design、main 本地证据 \`7e011cb/82dab81\` 所涉及文件、backup branch、所有未列入 allowlist 的 estimator/consumer/test 文件。冻结范围若确需扩展，只能通过 \`scripts/devline_control.py rescope-context --line ... --affected-path ... --allow-path ...\`， 并先记录 RESCOPE/STATE_CHANGE 事件。  ## 完成定义  完成必须同时满足修订设计文件第 13、14、15、17 节验收：新协议 evidence 可复现、可追溯、 可比较且 fail-closed；legacy 可读但明确未验证；统计 slice 独立且不改变既有估计器； Graph/Table/Report/Compare/Agent/UI 从同一证据读取；自动化、browser、full gate、FMS 验证 分别有证据。未 push/PR/merge/tag，除非用户另行明确授权。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 22/28 (78.6%; 78.6 per 100 events)
- Repeat rate: 0/22 (0.0%)
- Recurrence rate: 0/22 (0.0%)
- MTTR: median=0 ms (sample=9; unresolved=13)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- #2 2026-08-02T15:36:33.100Z `start_objective_size_exceeded`; cause_status: `known`; cause: The first formal start supplied the full design document as the objective, and the CLI rejected it because objective input is capped at 16 KiB.; resolution: `resolved`; lesson: Use a bounded central implementation objective while keeping the full design as the scope authority.
- #4 2026-08-02T15:38:12.000Z `tdd_red_contract_kernel_absent`; cause_status: `known`; cause: The new Phase 1 contract tests import the planned predictive_research package, which does not exist at the v1.8.5 baseline.; resolution: `open`; lesson: Establish shared contract and payload registry tests before adding prediction consumers or model branches.
- #5 2026-08-02T15:40:02.000Z `tdd_red_artifact_schema_gate_absent`; cause_status: `known`; cause: The legacy register_artifact helper has no payload_contract boundary, so new packet producers cannot validate payloads before updating artifacts_index.json.; resolution: `open`; lesson: Keep legacy artifact registration compatible while requiring explicit schema validation for new packet producers.
- #8 2026-08-02T15:45:05.000Z `tdd_red_split_kernel_absent`; cause_status: `known`; cause: The new SplitPlan and fold preprocessing tests import the planned shared kernel, which is not present at the v1.8.5 baseline.; resolution: `open`; lesson: Build a shared split and preprocessing kernel before wiring model-specific prediction code.
- #9 2026-08-02T15:47:14.000Z `tdd_red_prediction_protocol_absent`; cause_status: `known`; cause: The new OOS protocol tests import the planned prediction_protocol module, which is not present at the release baseline.; resolution: `open`; lesson: Create the OOS protocol around one persisted SplitPlan before wiring existing prediction UI or model branches.
- #10 2026-08-02T15:49:20.000Z `tdd_red_controls_absent`; cause_status: `known`; cause: The new permutation and seeded-noise control tests import the planned controls module, which is not present at the release baseline.; resolution: `open`; lesson: Make negative controls first-class receipts instead of prose-only warnings or hidden random branches.
- #11 2026-08-02T15:51:40.000Z `tdd_red_statistical_slice_absent`; cause_status: `known`; cause: The independent v1.8.6 statistics tests import effect-size, posthoc, paired, signed-rank, variance, and normality functions that do not exist in the legacy statistical_tests.py.; resolution: `open`; lesson: Add statistical evidence functions with a unified result schema and independent oracle before consumer projection.
- #12 2026-08-02T15:53:12.000Z `tdd_red_feature_recipe_executor_absent`; cause_status: `known`; cause: The typed FeatureRecipe tests import the planned deterministic executor, which is not present at the release baseline.; resolution: `open`; lesson: Keep FeatureRecipe execution server-owned and deterministic; do not introduce an expression evaluator as a shortcut.
- #13 2026-08-02T15:55:26.000Z `tdd_red_prediction_entrypoint_absent`; cause_status: `known`; cause: The existing prediction module has only the legacy random-split entrypoint and no v1.8.6 protocol boundary.; resolution: `open`; lesson: Expose a separate typed v1.8.6 entrypoint first, then preserve legacy calls until consumer migration is verified.
- #14 2026-08-02T15:57:41.000Z `tdd_red_control_receipts_missing`; cause_status: `known`; cause: The typed prediction entrypoint currently returns an empty controls list and does not persist permutation/noise receipts.; resolution: `open`; lesson: Persist negative-control receipts alongside prediction and evaluation packets, not as transient test-only data.
- #15 2026-08-02T15:59:44.000Z `tdd_consumer_projection_absent`; cause_status: `known`; cause: The shared versioned consumer projection is not present, so Agent/Report/Table/Compare would still need to read prediction payloads independently.; resolution: `open`; lesson: Use one server-owned projection for all consumers and reject unknown versions before exposing numeric evidence.
- #16 2026-08-02T16:02:18.000Z `tdd_agent_evidence_reader_absent`; cause_status: `known`; cause: The Agent context tools have no v1.8.6 reader that verifies artifact SHA and payload contract before projecting prediction evidence.; resolution: `open`; lesson: The Agent reader must verify registered hash and schema before exposing any prediction numeric evidence.
- #17 2026-08-02T16:07:00.000Z `tdd_red_prediction_ui_structure_declaration_absent`; cause_status: `known`; cause: The prediction control rendered no data-structure declaration or grouped key selector.; resolution: `open`; lesson: Lock the user-visible structure declaration before connecting the typed prediction protocol.
- #18 2026-08-02T16:08:40.000Z `tdd_red_run_params_prediction_contract_not_forwarded`; cause_status: `known`; cause: POST /runs did not forward the new typed prediction structure fields into the background workflow.; resolution: `resolved`; lesson: Add a request-parameter forwarding test before dispatch wiring.
- #19 2026-08-02T16:09:10.000Z `tdd_red_temporal_split_profile_unimplemented`; cause_status: `known`; cause: The temporal split test hit the placeholder unsupported-profile branch.; resolution: `resolved`; lesson: Do not claim the generic split contract is complete while temporal execution remains a placeholder.
- #22 2026-08-02T16:24:30.000Z `tdd_red_existing_genesis_prediction_contract`; cause_status: `known`; cause: GenesisWizard now correctly blocks prediction until data structure is declared, so the existing persistence test stopped before its expected patch.; resolution: `resolved`; lesson: When a shared UI contract becomes fail-closed, update every existing route test with the explicit user declaration and persisted fields.

## All errors

- #3 2026-08-02T15:36:33.200Z `start_tag_not_normalized`; cause_status: `known`; cause: The second formal start used the display release tag with dots, but the FMS CLI accepts normalized identifier tags only.; resolution: `resolved`; lesson: Normalize display versions before passing them as formal development-line tags.
- #20 2026-08-02T16:14:20.000Z `fd_writer_index_payload_type_bug`; cause_status: `known`; cause: The new FD writer passed the decoded index object to a byte-oriented atomic writer, producing a slicing KeyError.; resolution: `resolved`; lesson: Keep serialization at the FD writer boundary and test index append after packet persistence.
- #21 2026-08-02T16:20:30.000Z `frontend_build_script_missing`; cause_status: `known`; cause: The frontend package has no build script; the attempted npm run build command was rejected by npm.; resolution: `resolved`; lesson: Use the checked-in frontend verification surface (npm run typecheck and npm test) instead of assuming a build script exists.
- #28 2026-08-03T19:03:01.000Z `prediction_agent_assertion_wiring`; cause_status: `known`; cause: The new prediction Agent evidence assertions initially referenced the run result without retaining the run_prediction_model_v186 return value.; resolution: `resolved`; lesson: When adding consumer parity assertions, retain the producer return object and compare every projected field to that same persisted source.

## All gaps

- #24 2026-08-02T17:17:51.000Z `allowlist_scope_gap`; cause_status: `known`; cause: The inherited implementation changed shared API, service, Genesis, Table, and request-test paths that were not included in the frozen formal allowlist.; resolution: `resolved`; lesson: Record the complete shared-consumer and request wiring surface before implementation and use one formal rescope for all required paths.
- #25 2026-08-02T17:22:22.000Z `rescope_blocked_by_legacy_three_segment_path`; cause_status: `known`; cause: The rescope validator rejects backend allow paths with fewer than four path components, while this frozen v1.8.6 line already contains required three-segment backend files and directories.; resolution: `open`; lesson: When a frozen formal line cannot retain its inherited backend allowlist during rescope, preserve the line and continue from a clean checkpoint in a dependent formal line.

## All waste

- #23 2026-08-02T16:24:35.000Z `backend_verification_wrong_test_path`; cause_status: `known`; cause: A combined backend verification command referenced a non-existent root test path and collected zero tests before its failure was masked by a shell fallback.; resolution: `resolved`; lesson: Use exact repository test paths and never treat a zero-test command as a passing gate.

## Root causes and solutions

- `agent-reader-verifies-hash-and-schema`: occurrences=1; cause_status: `known`; root cause: The Agent context tools have no v1.8.6 reader that verifies artifact SHA and payload contract before projecting prediction evidence.; solution: `open`
- `bounded-formal-objective`: occurrences=1; cause_status: `known`; root cause: The first formal start supplied the full design document as the objective, and the CLI rejected it because objective input is capped at 16 KiB.; solution: `resolved`
- `contract-tests-before-prediction-integration`: occurrences=1; cause_status: `known`; root cause: The new Phase 1 contract tests import the planned predictive_research package, which does not exist at the v1.8.5 baseline.; solution: `open`
- `control-receipts-persist-with-prediction-evidence`: occurrences=1; cause_status: `known`; root cause: The typed prediction entrypoint currently returns an empty controls list and does not persist permutation/noise receipts.; solution: `open`
- `dependent-line-after-rescope-validator-conflict`: occurrences=1; cause_status: `known`; root cause: The rescope validator rejects backend allow paths with fewer than four path components, while this frozen v1.8.6 line already contains required three-segment backend files and directories.; solution: `open`
- `fd-writer-serializes-before-atomic-write`: occurrences=1; cause_status: `known`; root cause: The new FD writer passed the decoded index object to a byte-oriented atomic writer, producing a slicing KeyError.; solution: `resolved`
- `legacy-artifact-writer-compatible-schema-gate`: occurrences=1; cause_status: `known`; root cause: The legacy register_artifact helper has no payload_contract boundary, so new packet producers cannot validate payloads before updating artifacts_index.json.; solution: `open`
- `negative-controls-first-class-receipts`: occurrences=1; cause_status: `known`; root cause: The new permutation and seeded-noise control tests import the planned controls module, which is not present at the release baseline.; solution: `open`
- `normalized-fms-tag-before-start`: occurrences=1; cause_status: `known`; root cause: The second formal start used the display release tag with dots, but the FMS CLI accepts normalized identifier tags only.; solution: `resolved`
- `one-versioned-projection-for-all-consumers`: occurrences=1; cause_status: `known`; root cause: The shared versioned consumer projection is not present, so Agent/Report/Table/Compare would still need to read prediction payloads independently.; solution: `open`
- `oos-protocol-before-legacy-prediction-wiring`: occurrences=1; cause_status: `known`; root cause: The new OOS protocol tests import the planned prediction_protocol module, which is not present at the release baseline.; solution: `open`
- `prediction-agent-parity-test`: occurrences=1; cause_status: `known`; root cause: The new prediction Agent evidence assertions initially referenced the run result without retaining the run_prediction_model_v186 return value.; solution: `resolved`
- `prediction-request-forwarding-contract`: occurrences=1; cause_status: `known`; root cause: POST /runs did not forward the new typed prediction structure fields into the background workflow.; solution: `resolved`
- `prediction-ui-structure-before-dispatch`: occurrences=1; cause_status: `known`; root cause: The prediction control rendered no data-structure declaration or grouped key selector.; solution: `open`
- `rescope-complete-shared-consumer-surface`: occurrences=1; cause_status: `known`; root cause: The inherited implementation changed shared API, service, Genesis, Table, and request-test paths that were not included in the frozen formal allowlist.; solution: `resolved`
- `split-kernel-before-prediction-wiring`: occurrences=1; cause_status: `known`; root cause: The new SplitPlan and fold preprocessing tests import the planned shared kernel, which is not present at the v1.8.5 baseline.; solution: `open`
- `statistical-evidence-schema-before-projection`: occurrences=1; cause_status: `known`; root cause: The independent v1.8.6 statistics tests import effect-size, posthoc, paired, signed-rank, variance, and normality functions that do not exist in the legacy statistical_tests.py.; solution: `open`
- `temporal-split-is-executable-scope`: occurrences=1; cause_status: `known`; root cause: The temporal split test hit the placeholder unsupported-profile branch.; solution: `resolved`
- `typed-feature-recipe-before-expression-evaluator`: occurrences=1; cause_status: `known`; root cause: The typed FeatureRecipe tests import the planned deterministic executor, which is not present at the release baseline.; solution: `open`
- `typed-prediction-entrypoint-before-legacy-migration`: occurrences=1; cause_status: `known`; root cause: The existing prediction module has only the legacy random-split entrypoint and no v1.8.6 protocol boundary.; solution: `open`
- `update-existing-ui-contract-tests`: occurrences=1; cause_status: `known`; root cause: GenesisWizard now correctly blocks prediction until data structure is declared, so the existing persistence test stopped before its expected patch.; solution: `resolved`
- `verify-checked-in-frontend-scripts`: occurrences=1; cause_status: `known`; root cause: The frontend package has no build script; the attempted npm run build command was rejected by npm.; solution: `resolved`
- `zero-test-command-is-not-evidence`: occurrences=1; cause_status: `known`; root cause: A combined backend verification command referenced a non-existent root test path and collected zero tests before its failure was masked by a shell fallback.; solution: `resolved`

## Added tests

- `pytest tests/predictive_research/test_agent_evidence_v186.py -q: ImportError for read_prediction_research_evidence`
- `pytest tests/predictive_research/test_artifact_schema_integration.py -q: two TypeError failures for missing payload_contract`
- `pytest tests/predictive_research/test_consumer_projection_v186.py -q: collection ModuleNotFoundError`
- `pytest tests/predictive_research/test_contracts_v186.py -q: ModuleNotFoundError for workbench.predictive_research`
- `pytest tests/predictive_research/test_controls_v186.py -q: collection ModuleNotFoundError`
- `pytest tests/predictive_research/test_feature_recipe_v186.py -q: collection ModuleNotFoundError`
- `pytest tests/predictive_research/test_prediction_entrypoint_v186.py -q: ImportError for run_prediction_model_v186`
- `pytest tests/predictive_research/test_prediction_entrypoint_v186.py -q: controls assertion failed`
- `pytest tests/predictive_research/test_prediction_protocol_v186.py -q: collection ModuleNotFoundError`
- `pytest tests/predictive_research/test_split_kernel_v186.py -q: collection ModuleNotFoundError`
- `pytest tests/test_statistical_tests_v186.py -q: ImportError for missing cohens_d`

## New rules

- `agent-reader-verifies-hash-and-schema`: line experience occurrence(s)=1
- `bounded-formal-objective`: line experience occurrence(s)=1
- `contract-tests-before-prediction-integration`: line experience occurrence(s)=1
- `control-receipts-persist-with-prediction-evidence`: line experience occurrence(s)=1
- `dependent-line-after-rescope-validator-conflict`: line experience occurrence(s)=1
- `fd-writer-serializes-before-atomic-write`: line experience occurrence(s)=1
- `legacy-artifact-writer-compatible-schema-gate`: line experience occurrence(s)=1
- `negative-controls-first-class-receipts`: line experience occurrence(s)=1
- `normalized-fms-tag-before-start`: line experience occurrence(s)=1
- `one-versioned-projection-for-all-consumers`: line experience occurrence(s)=1
- `oos-protocol-before-legacy-prediction-wiring`: line experience occurrence(s)=1
- `prediction-agent-parity-test`: line experience occurrence(s)=1
- `prediction-request-forwarding-contract`: line experience occurrence(s)=1
- `prediction-ui-structure-before-dispatch`: line experience occurrence(s)=1
- `rescope-complete-shared-consumer-surface`: line experience occurrence(s)=1
- `split-kernel-before-prediction-wiring`: line experience occurrence(s)=1
- `statistical-evidence-schema-before-projection`: line experience occurrence(s)=1
- `temporal-split-is-executable-scope`: line experience occurrence(s)=1
- `typed-feature-recipe-before-expression-evaluator`: line experience occurrence(s)=1
- `typed-prediction-entrypoint-before-legacy-migration`: line experience occurrence(s)=1
- `update-existing-ui-contract-tests`: line experience occurrence(s)=1
- `verify-checked-in-frontend-scripts`: line experience occurrence(s)=1
- `zero-test-command-is-not-evidence`: line experience occurrence(s)=1

## Future guidance

- Add a request-parameter forwarding test before dispatch wiring.
- Add statistical evidence functions with a unified result schema and independent oracle before consumer projection.
- Build a shared split and preprocessing kernel before wiring model-specific prediction code.
- Create the OOS protocol around one persisted SplitPlan before wiring existing prediction UI or model branches.
- Do not claim the generic split contract is complete while temporal execution remains a placeholder.
- Establish shared contract and payload registry tests before adding prediction consumers or model branches.
- Expose a separate typed v1.8.6 entrypoint first, then preserve legacy calls until consumer migration is verified.
- Keep FeatureRecipe execution server-owned and deterministic; do not introduce an expression evaluator as a shortcut.
- Keep legacy artifact registration compatible while requiring explicit schema validation for new packet producers.
- Keep new predictive contracts in a shared kernel and preserve legacy artifact records unless a producer opts into a payload contract.
- Keep serialization at the FD writer boundary and test index append after packet persistence.
- Lock the user-visible structure declaration before connecting the typed prediction protocol.
- Make negative controls first-class receipts instead of prose-only warnings or hidden random branches.
- Normalize display versions before passing them as formal development-line tags.
- Persist negative-control receipts alongside prediction and evaluation packets, not as transient test-only data.
- Record the complete shared-consumer and request wiring surface before implementation and use one formal rescope for all required paths.
- The Agent reader must verify registered hash and schema before exposing any prediction numeric evidence.
- Use a bounded central implementation objective while keeping the full design as the scope authority.
- Use exact repository test paths and never treat a zero-test command as a passing gate.
- Use one server-owned projection for all consumers and reject unknown versions before exposing numeric evidence.
- Use the checked-in frontend verification surface (npm run typecheck and npm test) instead of assuming a build script exists.
- When a frozen formal line cannot retain its inherited backend allowlist during rescope, preserve the line and continue from a clean checkpoint in a dependent formal line.
- When a shared UI contract becomes fail-closed, update every existing route test with the explicit user declaration and persisted fields.
- When adding consumer parity assertions, retain the producer return object and compare every projected field to that same persisted source.

## Event index

- #1: `aab00807-d544-436b-a371-6fc521eef3ad` | 2026-08-02T15:35:45.398Z | STATE_CHANGE/line_started | incident=`d0a233f2-7c9f-41c0-bf8f-a8062597a051` | lesson_key=`frozen-context-before-start` | event_sha256=`1d3a91b6c1bc174893df48bc01fd9c026730f2c46ad18d35b3ae6c64813c8234`
- #2: `f094279b-6d9c-494f-af08-0a2266b5d459` | 2026-08-02T15:36:33.100Z | FAILURE/start_objective_size_exceeded | incident=`4a1b2c3d-4e5f-4678-9012-abcdefabcdef` | lesson_key=`bounded-formal-objective` | event_sha256=`d0dbab9e41ff022225e16d36561c7954f2d0674b9746bccd3340511bddf92a5a`
- #3: `52258047-58c0-43cc-9078-591732968083` | 2026-08-02T15:36:33.200Z | ERROR/start_tag_not_normalized | incident=`5b6c7d8e-9f01-4234-8567-bcdefabcdeff` | lesson_key=`normalized-fms-tag-before-start` | event_sha256=`49c8a72afc6c79ee7b29a97f2d320af3aff0407cff965798806fcb63bb6b7d54`
- #4: `7e7c4d5b-8ab0-4d26-9f2b-2a7f7b9d7b31` | 2026-08-02T15:38:12.000Z | FAILURE/tdd_red_contract_kernel_absent | incident=`6a4b9d82-2fc9-4b5d-8c31-9d2e7f6b1a04` | lesson_key=`contract-tests-before-prediction-integration` | event_sha256=`4c8c26d1cb74974c7a5b2a0a71d731fbfbfcb5d71677172ad9dcb62aa464d314`
- #5: `c0f31d9e-4f3c-4b8e-a92d-1e7a2bb4d8f0` | 2026-08-02T15:40:02.000Z | FAILURE/tdd_red_artifact_schema_gate_absent | incident=`9d4b2a7c-7e31-4f8a-b0c2-1e6d3a9f5b42` | lesson_key=`legacy-artifact-writer-compatible-schema-gate` | event_sha256=`91d82f588772adad02b4f57f2c3e707a81025b6bedf8981407b59e0d8bced123`
- #6: `f6fefbe1-fd65-4a9c-a8df-06c5b4a9e2d1` | 2026-08-02T15:43:18.000Z | REVIEW/phase1_contract_schema_review | incident=`cb5e8d17-f8c6-4461-b0dd-6a3e1c9f2b74` | lesson_key=`contract-kernel-preserves-legacy-artifacts` | event_sha256=`fa2fdb95af587bc1e805792bacd90152df9e0456d99315f9cf881de4148e75f2`
- #7: `2bc0e1f8-5c74-4e99-90a1-7d3a6b2f8c41` | 2026-08-02T15:43:18.100Z | GATE/phase1_contract_schema_gate | incident=`3a7f5c9e-1d64-4b80-a2f6-8c3e5d9b7a21` | lesson_key=`focused-gate-separate-from-host-containment` | event_sha256=`1be90d75df7f65fc597252d7f6a371940f0150ef0973c97b8746e276ec580aa7`
- #8: `1f7a3c9e-6b2d-4e80-a5f1-9c8d2b7e4a63` | 2026-08-02T15:45:05.000Z | FAILURE/tdd_red_split_kernel_absent | incident=`8b4e1d7c-2a9f-46c5-90e3-7f1b5d8a2c64` | lesson_key=`split-kernel-before-prediction-wiring` | event_sha256=`82b5457ae8cf8729b36e68181f9f5413741660456287d3dde031c3e878d24b03`
- #9: `b8f2d1a7-4c6e-49b3-8d0f-2e5a7c9b1d64` | 2026-08-02T15:47:14.000Z | FAILURE/tdd_red_prediction_protocol_absent | incident=`2e7a4c9d-6b1f-43e8-a5d2-9c7b1e4f8a30` | lesson_key=`oos-protocol-before-legacy-prediction-wiring` | event_sha256=`a61e9e044511d5f3d5fe89301dee1ede8e27d403ca0c34f92516ff27504fc6ed`
- #10: `4a9e2d7c-1f63-48b5-90e2-6c7d3a8f5b21` | 2026-08-02T15:49:20.000Z | FAILURE/tdd_red_controls_absent | incident=`7c2e5a9d-4b81-46f3-a0d7-1e9b6c3f8a52` | lesson_key=`negative-controls-first-class-receipts` | event_sha256=`808f046a1058c2a085e62e29747accbebc5414322978bb63a9d346e5a8acd350`
- #11: `9f2c6b8a-4d71-45e0-b3a9-1c7f5d2e8b64` | 2026-08-02T15:51:40.000Z | FAILURE/tdd_red_statistical_slice_absent | incident=`6d4a9b1f-2e73-48c5-a0d8-7f1b3e9c5a62` | lesson_key=`statistical-evidence-schema-before-projection` | event_sha256=`7d685bc9d52ddc2f2d0e009ad1c57893b610a684e08edc87ff869cf87665737d`
- #12: `2d8a5c1f-7e43-49b0-b6d2-1a9f3c7e5b84` | 2026-08-02T15:53:12.000Z | FAILURE/tdd_red_feature_recipe_executor_absent | incident=`5f1c8a3d-9b27-46e0-a5d4-7c2f1e9b8a63` | lesson_key=`typed-feature-recipe-before-expression-evaluator` | event_sha256=`28d4f05541cc5c71600ef60c009d53bb9d4f09c8c8c2a1e607f4ce9f1a6c908c`
- #13: `7b3e1c9a-5d82-46f0-a4e7-2c8b6d1f9a53` | 2026-08-02T15:55:26.000Z | FAILURE/tdd_red_prediction_entrypoint_absent | incident=`4c7a2e9d-1f53-48b6-a0d8-6e2b9f5c1a74` | lesson_key=`typed-prediction-entrypoint-before-legacy-migration` | event_sha256=`b9088c3256a3a4981550a9b124c6621bc6f7f7a017c18e04478187e92880deb5`
- #14: `5c1e8a7d-3f92-46b0-a5d4-9c7e2b1f8a63` | 2026-08-02T15:57:41.000Z | FAILURE/tdd_red_control_receipts_missing | incident=`8d4a1f7c-2e93-46b5-a0d8-7c1f5e9b3a62` | lesson_key=`control-receipts-persist-with-prediction-evidence` | event_sha256=`0d21532e123af8dfd242d2eb1dad37f5b5db7a282f329f4bc045a2065aa22c32`
- #15: `6e2a9c1f-4b73-48d0-a5e7-3c8f1b9d6a42` | 2026-08-02T15:59:44.000Z | FAILURE/tdd_consumer_projection_absent | incident=`3f7a1c9e-5b62-48d0-a4e7-2c8f6b1d9a53` | lesson_key=`one-versioned-projection-for-all-consumers` | event_sha256=`f29841d6edb4975eafd9e8dc2e6b7374014b607fc2aa8329044b99f959e8561b`
- #16: `8a4e1c7d-2f93-46b0-b5d8-7c1e9a3f6b42` | 2026-08-02T16:02:18.000Z | FAILURE/tdd_agent_evidence_reader_absent | incident=`6f1a9c3e-4b72-48d0-a5e8-2c7f1d9b6a43` | lesson_key=`agent-reader-verifies-hash-and-schema` | event_sha256=`52507fe8b564efa20fb7deed7119e19c027c439ddcb1fb4d69ce2327fdf6a9b4`
- #17: `d2c0f4e5-1a2b-4c3d-8e9f-0123456789ab` | 2026-08-02T16:07:00.000Z | FAILURE/tdd_red_prediction_ui_structure_declaration_absent | incident=`e3d1a5f6-2b3c-4d4e-9f01-1234567890bc` | lesson_key=`prediction-ui-structure-before-dispatch` | event_sha256=`1fe33b7842d7e9b1357376bc55ce5ea88b39f1eb6eec597143aeab6c392b6c78`
- #18: `f4e2b6c7-3d4e-4f50-a123-2345678901cd` | 2026-08-02T16:08:40.000Z | FAILURE/tdd_red_run_params_prediction_contract_not_forwarded | incident=`a5f3c7d8-4e5f-4061-b234-3456789012de` | lesson_key=`prediction-request-forwarding-contract` | event_sha256=`1abe5b57dab3c92279e68331a40b9164582b16d76755fc94c3a0ad3043e871e7`
- #19: `b6f4d8e9-5f60-4172-c345-4567890123ef` | 2026-08-02T16:09:10.000Z | FAILURE/tdd_red_temporal_split_profile_unimplemented | incident=`c7a5e9f0-6071-4283-d456-5678901234f0` | lesson_key=`temporal-split-is-executable-scope` | event_sha256=`e6515d8d980627ff9458c2778d8cc4bd3f32b6908579acbd110308a4ea4819e8`
- #20: `d8b6f0a1-7182-4394-e567-6789012345a1` | 2026-08-02T16:14:20.000Z | ERROR/fd_writer_index_payload_type_bug | incident=`e9c7a1b2-8293-4405-f678-7890123456b2` | lesson_key=`fd-writer-serializes-before-atomic-write` | event_sha256=`b6daf42077a76788cd8709f04782605a29b393a623e08cc16407b1be92070f57`
- #21: `ea8c2b3d-9405-4516-a789-8901234567c3` | 2026-08-02T16:20:30.000Z | ERROR/frontend_build_script_missing | incident=`fb9d3c4e-a516-4627-b890-9012345678d4` | lesson_key=`verify-checked-in-frontend-scripts` | event_sha256=`5900db5498d40f708757c429ae86fc738e1b2c831532cf1ca1ab8d76e953b011`
- #22: `fc0a4e5f-b627-4738-c901-0123456789e5` | 2026-08-02T16:24:30.000Z | FAILURE/tdd_red_existing_genesis_prediction_contract | incident=`ad1b5f60-c738-4849-d012-1234567890f6` | lesson_key=`update-existing-ui-contract-tests` | event_sha256=`4da1b3ceec5065510cf1c3922288c76e423510c4a1f759f0d9dd7a7a20223e79`
- #23: `0b7d3f4a-8516-4962-b901-1234567890a7` | 2026-08-02T16:24:35.000Z | WASTE/backend_verification_wrong_test_path | incident=`1c8e4a5b-9627-4a73-c012-2345678901b8` | lesson_key=`zero-test-command-is-not-evidence` | event_sha256=`5ea818c985a40eceb83664b05a00605151a2f33b3191e85dd72b9fca4fce76a7`
- #24: `a2b3c4d5-e6f7-4890-a123-456789abcdef` | 2026-08-02T17:17:51.000Z | GAP/allowlist_scope_gap | incident=`b3c4d5e6-f7a8-4901-b234-56789abcdef0` | lesson_key=`rescope-complete-shared-consumer-surface` | event_sha256=`362ef52a73f5a3a10a434a10e0a7d4d84569a94155679111d346cd5251046878`
- #25: `c4d5e6f7-a8b9-4012-c345-6789abcdef01` | 2026-08-02T17:22:22.000Z | GAP/rescope_blocked_by_legacy_three_segment_path | incident=`d5e6f7a8-b9c0-4123-d456-789abcdef012` | lesson_key=`dependent-line-after-rescope-validator-conflict` | event_sha256=`260b6d3c8d161b7ce882bd09d3d433f1d705e333aa647ecfb27a5a96df758fb1`
- #26: `101e9bcf-ff2d-4b0e-8fcc-7d30ed9ec773` | 2026-08-03T15:49:28.984Z | STATE_CHANGE/context_rescope_required | incident=`87e501f7-cd5d-48c9-bbaf-f5f4186fa112` | lesson_key=`context-pack-rescope` | event_sha256=`7a32cf070f8aa1c8d8e7b7eae861cfd2f67eec69975c604d7ab7fd0dd8c9a25f`
- #27: `4b1e6696-bc55-480f-9589-b6678c10415f` | 2026-08-03T15:49:28.996Z | STATE_CHANGE/context_rescoped | incident=`2de53778-ff5e-4082-bd80-7a313573580c` | lesson_key=`context-pack-rescope` | event_sha256=`f8374a7ad1dba99017fc97be465f6530888301c016b04d00325ff9c96df3ec86`
- #28: `c2345678-9abc-4890-d123-456789abcdef` | 2026-08-03T19:03:01.000Z | ERROR/prediction_agent_assertion_wiring | incident=`d3456789-abcd-4901-e234-56789abcdef0` | lesson_key=`prediction-agent-parity-test` | event_sha256=`b7c067c0fbb9151033e3bd3457749497d6d6b75b1c141a9c23dec8931a202e57`
