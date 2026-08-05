# Frozen Context Pack

Line: `v1-8-7-a0-release-doc-truth`
Baseline SHA: `9d5e94717f9f06dbc92955aa8cf3ca26dda37f71`

## Objective
# v1.8.7 A0 发布文档事实修正 Objective

v1.8.7 块 0，起手即做，纯文档，不触碰任何产品代码。

已发布的 v1.8.6 release notes 内部自相矛盾：头部称「已发布（tag：`v1.8.6`）」，
而第 79 行与第 96 行仍称「未 push、未建 PR、未 merge、未 tag」。发布时只改了头部。
实际状态为 `origin/main` = tag `v1.8.6` = `9d5e947`，PR 已 merge。

同时 `followups/BACKLOG.md` 的 §0 / §0.1 / §1 仍停在 v1.8.0–v1.8.1 时期，
§1 表最新只到 `V1.8.5-TYPED-MEMORY`，v1.8.6 一条未进，
违反 `docs/superpowers/README.md`「唯一 live 滚动欠账清单」的约定。

这是已发布文档里的事实错误，不拖成长期欠账。

## 必须完成

1. 修正 `docs/releases/v1.8.6-release-notes.md` 第 79 行：删除「版本整合以及明确的
   push/merge/tag 授权仍未执行」一句，保留同段其余的浏览器验收记录（那部分属实）。
2. 修正同文件第 96 行：「未 push、未建 PR、未 merge、未 tag」改为实际发布事实
   （已 push、PR 已 merge、tag `v1.8.6` = `9d5e947` = `origin/main`）。
3. 除上述两处外，release notes 其余内容**一字不改**——尤其不得改动验证等级章节
   与本地验证摘要中的任何数字。
4. `followups/BACKLOG.md` 补齐 v1.8.6：§0 / §0.1 版本状态更新到 v1.8.6 已发布，
   §1 表补入 v1.8.6 产生的开放欠账，恢复「唯一 live 滚动清单」性质。

## 明确不做

- 不改 v1.8.6 的任何技术结论、验证等级或实测数字。
- 不归档任何文档（版本收尾仪式不属本 objective）。
- 不触碰产品代码、测试或 fixture。
- 不 push / 不建 PR / 不 merge / 不 tag。

## 可证伪验收

- `docs/releases/v1.8.6-release-notes.md` 全文再无与实际发布状态冲突的表述；
  用 `grep -n "未 push\|未建 PR\|未 merge\|未 tag\|授权仍未执行"` 对该文件应无命中。
- 该文件相对 `9d5e947` 的 diff **仅限**第 79 行与第 96 行所在的两处，
  `git diff --stat` 显示改动局限于这一个文件，且验证等级章节与本地验证摘要
  逐字节不变。
- `followups/BACKLOG.md` 中出现 v1.8.6 条目，且 §0.1 版本状态含 v1.8.6 已发布。
- `git diff --check` 干净。
- 全量 gate 不受影响（纯文档改动，后端/前端测试数与 golden 均不变）。

## Boundary
- Affected paths: `docs/releases/v1.8.6-release-notes.md`, `docs/superpowers/followups/BACKLOG.md`
- Allowed paths: `docs/releases/v1.8.6-release-notes.md`, `docs/superpowers/followups/BACKLOG.md`
- Protected paths: `backend`, `frontend`, `tests`, `scripts/gate.sh`
- Dependencies: none
- Tests: `git diff --stat`, `git diff --check`
- Known gates: `pure-docs line: backend/frontend/tests must stay untouched`

## Rules
```json
{"candidate_rules":[],"candidate_rules_sha256":"4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945","global_rules":{"rules":[],"schema_version":1},"global_rules_sha256":"994a863c694e05021d65d0f8b862f24a28da461080286b7b35d1695ee0775fdc","rules_sha256":"c43d07b614106c511776da60664c80b2b1d5f27cc62ddece26aa4e6761474c5c"}
```

## Selected historical lessons
### v1-8-4-reopened-incident-truth (2026-07-31T08:10:00.000Z)

Completed formal devline v1-8-4-reopened-incident-truth; final_state=COMPLETED; failure_lesson_keys=full-gate-requires-non-nested-seatbelt, gate-requires-non-nested-sandbox

### v1-8-4-open-incidents-remediation (2026-07-31T04:08:00.000Z)

Completed formal devline v1-8-4-open-incidents-remediation; final_state=COMPLETED; failure_lesson_keys=closing-evidence-must-postdate-the-work
