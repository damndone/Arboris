# Retrospective — v1-8-9-p1-classification-central-consumer

## Goal

# Workbench v1.8.9 P1 Classification Central Consumer Objective  ## Objective  接通已经持久化并通过分类生产契约校验的 classification evidence，使中央 Agent、Notebook、Report 都从同一个 server-owned classification projection 入口读取结果。此线只负责消费层和 catalog/admission 接线，不重新拟合模型、 不重新计算指标、不降低已有的 artifact/receipt/C0 校验强度。  ## Required behavior  - 中央服务必须先解析 server-bound project/run identity，再从 indexed   classification artifact、receipt 和 server identity 读取结果。 - Agent、Notebook、Report 使用同一个 provider-owned projection adapter；   只在 consumer presentation 上有差异。 - classification projection 必须保留 \`validated\`、\`degraded\`、   \`unavailable\` 和阻断原因；缺失、过期、篡改、foreign run、错误 artifact   identity 必须 fail closed。 - Report 的 classification evidence authority 必须明确为 server-owned，   不能继续把已经校验过的 classification wrapper 标成 non-authoritative。 - Agent/Notebook 的中央读取入口不得接受 caller-supplied packet、registry、   provider、model 或 filesystem path；只能接受 server-issued run capability   或由中央服务解析出的 run identity。 - 本条线只建立共享 central reader；精确 projection-ref 的 catalog coverage   adapter join 作为后续 C2 单独实现，不能在本条线用 generic consumer   projection 冒充完成。 - 不能修改分类 estimator、split/CV/holdout/calibration/threshold/SHAP   语义；不能通过 raw JSON fallback 让未验证结果显示为有效结果。  ## Explicit non-goals  - 不新增分类模型族。 - 不实现浏览器、真实 provider、跨进程 authority 或发布流程。 - 不修改 central compiler、workflow runtime 或 Notebook planner。 - 不修改 provider catalog declaration 或前端 renderer registry；这些属于   后续 C2 接线。  ## Acceptance evidence  - TDD RED probes first cover central route authority, shared adapter identity,   stale/tampered/foreign artifact rejection and no in-memory bypass. - Central backend tests prove one reader/adapter is used for Agent/Notebook/Report   and unavailable states remain typed. Catalog coverage remains an explicit   follow-up gate rather than being counted as complete here. - Existing package classification production/consumer suites remain green. - \`compileall\`, \`git diff --check\` and formal devline verification/retrospective   pass. Browser/provider/full/release remain separate claims.

## Final status

COMPLETED

## Metrics

- Failure frequency: 1/5 (20.0%; 20.0 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: N/A (sample=0; unresolved=1)
- Review churn: changes_required=1; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #2 2026-08-20T20:46:26.559Z `integration_cherry_pick_blocked`; cause_status: `external`; cause: The managed sandbox rejected creation of normal Git worktree sequencer metadata during cherry-pick; the reviewed patch was integrated explicitly instead.; resolution: `accepted`; lesson: Keep a reviewed patch-based integration fallback when managed Git metadata is read-only; preserve unrelated dirty paths.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `managed-git-metadata-boundary`: occurrences=1; cause_status: `external`; root cause: The managed sandbox rejected creation of normal Git worktree sequencer metadata during cherry-pick; the reviewed patch was integrated explicitly instead.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `managed-git-metadata-boundary`: line experience occurrence(s)=1

## Future guidance

- Keep a reviewed patch-based integration fallback when managed Git metadata is read-only; preserve unrelated dirty paths.
- Review the actual authority and snapshot boundary before accepting a central evidence facade.

## Event index

- #1: `1938f086-22e5-4272-b92e-7bc380d9f260` | 2026-08-20T19:55:33.744Z | STATE_CHANGE/line_started | incident=`727b7a04-b0c2-4d3f-8b01-0c7e14fc0fa6` | lesson_key=`frozen-context-before-start` | event_sha256=`8ab3523a1ac6e944da5624ccc73b3dd666c04285130bb00d150e2eeb8f606e76`
- #2: `e1f2a3b4-c5d6-4789-ef01-4567890123aa` | 2026-08-20T20:46:26.559Z | ERROR/integration_cherry_pick_blocked | incident=`f2a3b4c5-d6e7-4890-f012-5678901234aa` | lesson_key=`managed-git-metadata-boundary` | event_sha256=`1a3099918b4144a56e81eba89ca075e505f30eff6e1750b84658a706a05eb237`
- #3: `e1f2a3b4-c5d6-4789-ef01-4567890123ab` | 2026-08-20T20:46:43.224Z | REVIEW/changes_required | incident=`f2a3b4c5-d6e7-4890-f012-5678901234ab` | lesson_key=`central-evidence-authority-review` | event_sha256=`7e0c024a4d11b927e38343f9ec10912487c4c1ced48808c14cbec7f389a65a60`
- #4: `e1f2a3b4-c5d6-4789-ef01-4567890123ac` | 2026-08-20T20:46:59.079Z | GATE/classification_central_consumer_focused_green | incident=`f2a3b4c5-d6e7-4890-f012-5678901234ac` | lesson_key=`classification-central-consumer-focused-gate` | event_sha256=`8d4c67538d446aece955c3591bb616a0638faebbc8450d755443a60231cb3c54`
- #5: `e1f2a3b4-c5d6-4789-ef01-4567890123ad` | 2026-08-20T20:47:15.711Z | STATE_CHANGE/line_completed | incident=`f2a3b4c5-d6e7-4890-f012-5678901234ad` | lesson_key=`bounded-line-completion-boundary` | event_sha256=`2b894b4ec1baee8f0065f5fea888842aa0dc759309faa473ad1000c9a7f19f89`
