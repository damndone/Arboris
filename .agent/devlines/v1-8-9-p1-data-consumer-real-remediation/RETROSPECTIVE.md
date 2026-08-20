# Retrospective — v1-8-9-p1-data-consumer-real-remediation

## Goal

# Workbench v1.8.9 P1 Data Consumer real remediation objective  修复独立规格复审确认的真实 P1 缺口，不以 formal closeout 替代产品 验证。本 line 从当前 Data Consumer worktree 精确 HEAD \`dff7c6d9f0dcdc8f243a83a6f0f048e90ba3c4bb\` 开始；产品实现历史基线 \`73a09151aa3ab4eb1cdb2e3c94fca2df93df92b3\` 只作为上下文引用。旧的 \`v1-8-9-p1-data-consumer\` 与 \`v1-8-9-p1-data-consumer-formal-closeout\` formal lines 保持不变。  ## Required remediation  - 给 CSV/XLSX/Parquet 建立真实 writer/read-back interchange contract：能力声明   必须与可用 optional dependency 一致；缺失 \`pyarrow\`/\`fastparquet\` 时返回稳定的   typed \`optional_dependency\`/\`unavailable\`，不能假装支持；\`.sav\`/\`.zsav\`/\`.dta\`   在缺失 \`pyreadstat\` 时继续 typed unavailable；metadata loss 与 schema/dtype   边界必须可解释。 - 将已有 \`DataOperationsSection\` 接入 canonical   \`frontend/src/workbench/registry/sectionRegistry.ts\`。用户路径必须从服务端   manifest 的 typed descriptor 生成 preview，并且 confirm 只能携带服务端 preview   fingerprint/descriptor ref；不得在前端重算结果或绕过服务端 confirmation。 - 维持 package-local 边界。Agent/Notebook/Report central integration、provider、   host、browser、full gate、merge/release 均不在本 line 内，不得被测试或文档写成已完成。  ## Boundary  - formal files are generated or updated only through \`scripts/devline_control.py\`; - product scope is limited to interchange capability/writer/read-back and the   canonical Data Operations UI adapter plus their focused tests; - no dependency installation and no changes to central Agent/Notebook/Report   integration, provider catalog, host gate, release scripts, or old formal lines; - all optional dependency outcomes and unverified gates remain explicit.  ## Verification  - focused backend interchange/ingestion tests; - focused frontend Data Operations/registry tests; - \`PYTHONPATH=backend .venv/bin/python -m compileall -q backend\`; - \`git diff --check\`; - formal \`verify\` and regenerated \`RETROSPECTIVE.md\` through the CLI.  ## Known gates  \`agent-central-integration-not-verified\`, \`notebook-central-integration-not-verified\`, \`report-central-integration-not-verified\`, \`browser-acceptance-not-verified\`, \`provider-full-gate-not-verified\`, \`host-full-gate-not-verified\`, \`full-gate-not-verified\`, \`merge-not-authorized\`, \`release-not-verified\`.

## Final status

COMPLETED

## Metrics

- Failure frequency: 3/14 (21.4%; 21.4 per 100 events)
- Repeat rate: 0/3 (0.0%)
- Recurrence rate: 0/3 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-19T00:00:00.000Z `interchange_red`; cause_status: `known`; cause: The package exposed round-trip test behavior without a public typed writer capability or schema result.; resolution: `resolved`; lesson: TDD must cover public capability and typed dependency boundaries, not only a private helper.
- #3 2026-08-19T00:01:00.000Z `canonical_editor_red`; cause_status: `known`; cause: The canonical registry still mounted the read-only evidence projection and had no typed data-operation editor adapter.; resolution: `resolved`; lesson: A standalone typed editor is incomplete until the canonical section registry mounts it.
- #8 2026-08-19T00:02:00.000Z `bounded_parquet_unavailable_red`; cause_status: `known`; cause: Bounded Parquet ingestion converted a missing pyarrow dependency into an untyped ValueError.; resolution: `resolved`; lesson: Optional dependency failures must preserve a typed capability boundary at every exposed interchange seam.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `canonical-editor-registration`: occurrences=1; cause_status: `known`; root cause: The canonical registry still mounted the read-only evidence projection and had no typed data-operation editor adapter.; solution: `resolved`
- `public-interchange-capability`: occurrences=1; cause_status: `known`; root cause: The package exposed round-trip test behavior without a public typed writer capability or schema result.; solution: `resolved`
- `typed-ingestion-unavailable`: occurrences=1; cause_status: `known`; root cause: Bounded Parquet ingestion converted a missing pyarrow dependency into an untyped ValueError.; solution: `resolved`

## Added tests

- `frontend/src/workbench/registry/sectionRegistry.v189.test.ts`
- `tests/test_ingestion_metadata.py`
- `tests/test_v189_data_interchange.py`

## New rules

- `canonical-editor-registration`: line experience occurrence(s)=1
- `public-interchange-capability`: line experience occurrence(s)=1
- `typed-ingestion-unavailable`: line experience occurrence(s)=1

## Future guidance

- A standalone typed editor is incomplete until the canonical section registry mounts it.
- Do not convert package-local green tests into central, browser, provider, or release claims.
- Optional dependency failures must preserve a typed capability boundary at every exposed interchange seam.
- TDD must cover public capability and typed dependency boundaries, not only a private helper.

## Event index

- #1: `8a397208-9830-4483-aa46-0ebd11b32996` | 2026-08-20T00:10:35.347Z | STATE_CHANGE/line_started | incident=`600357cf-52cf-42fc-9d3f-adc4204a555c` | lesson_key=`frozen-context-before-start` | event_sha256=`d2b6905ffb46de5158467955b1460b06e71390bf6323457fd6f6a183f2d007f9`
- #2: `4a75e0d5-42c1-4b90-8a21-5a0c0b8771c9` | 2026-08-19T00:00:00.000Z | FAILURE/interchange_red | incident=`9b9e7ce5-3f3b-45f2-9ca4-03e8f1d9e7e1` | lesson_key=`public-interchange-capability` | event_sha256=`9611e2ce89e4639c0b3282da5c2a03af5aefaf9c4e2f8e8c4e7f16eae3ec5111`
- #3: `7ebf2cbb-a1f7-4c4f-8cf1-51d2e6b2e3e8` | 2026-08-19T00:01:00.000Z | FAILURE/canonical_editor_red | incident=`e6b85b61-7579-457e-9c6d-11c71dd8d1e8` | lesson_key=`canonical-editor-registration` | event_sha256=`20fde241c513ca57737539c2f43a51d57251e4ce420745a0afcfee1a0d7db2ba`
- #4: `716d58bf-cf38-4c46-8b4e-3143c2bb82de` | 2026-08-20T00:20:49.087Z | STATE_CHANGE/context_rescope_required | incident=`26ab1f18-6d1f-45ca-9ad8-41db3df93d91` | lesson_key=`context-pack-rescope` | event_sha256=`e0d16b07e45b97369b2109d9ce0ea5c669e3003c3d6b5753ab0c144a3a5455a6`
- #5: `e26c5cce-ddb2-4c7e-b74b-bb028d35b695` | 2026-08-20T00:20:49.090Z | STATE_CHANGE/context_rescoped | incident=`6fd4d926-8a3e-44d7-8ab6-38618a232265` | lesson_key=`context-pack-rescope` | event_sha256=`3f4ac4d5072ebd8f835dcf796c7f10200d2b8f517be3bb4538cab5ad091fd059`
- #6: `2c8393fd-1b38-4b91-b3d5-25a75dea4d8e` | 2026-08-20T00:21:39.905Z | STATE_CHANGE/context_rescope_required | incident=`718a05f5-0f91-4fa4-a2bf-25725f09cfe7` | lesson_key=`context-pack-rescope` | event_sha256=`48de73345f0251a723cc6ca659c501778997dc404690b68cc1da678aed13e54d`
- #7: `e521e97c-297b-477b-b163-8efc18976e2e` | 2026-08-20T00:21:39.909Z | STATE_CHANGE/context_rescoped | incident=`c0273e0a-13f2-4429-8806-a0b05d162844` | lesson_key=`context-pack-rescope` | event_sha256=`3cecdd125e5729d4192e8ce33da20ac8ca47af2921551de42115a62f0637c5eb`
- #8: `b0f2f4fb-73c6-4f5d-b7ca-9c5eab1afc26` | 2026-08-19T00:02:00.000Z | FAILURE/bounded_parquet_unavailable_red | incident=`2f5f8d73-c802-4f05-8645-104c05f86b64` | lesson_key=`typed-ingestion-unavailable` | event_sha256=`14cb8478bea984ee598319c5a277af52a89648e2141a80bf5bd006c73ae6f217`
- #9: `a5a4d8c1-2f6e-4bb6-9cc3-0b1a7b7e4d90` | 2026-08-20T00:25:00.000Z | GATE/package_local_green | incident=`d4fd05f1-4e42-4aa7-9f6e-42b1b18e8c3f` | lesson_key=`package-local-verification` | event_sha256=`facf7248f7017d0b3c72f82e6be63c2d594783f20eaf278eeca17d287da36998`
- #10: `3af845e9-9e95-4db4-a6e5-4b707f2f5e08` | 2026-08-20T00:26:00.000Z | REVIEW/scope_boundary_review | incident=`b6c0e3f5-3cb9-4b4a-86f0-7d5d8c78b4e1` | lesson_key=`unverified-gate-boundaries` | event_sha256=`184b0a407caaaa3520d480ce682eb85491ed4bc89587ccb5d97663c916b65154`
- #11: `b4c6e8f1-2a5d-4a71-9c3e-6f0b8d2e1a94` | 2026-08-20T00:27:00.000Z | STATE_CHANGE/remediation_completed | incident=`f6d1a8c4-7e39-4b2a-95f0-3c8e7d1b6a42` | lesson_key=`remediation-formal-closeout` | event_sha256=`fef2d5fd582ba0a5f553ee3edd7b4bf70d1136e91f664a090c4b2ca26f20dee5`
- #12: `7c38922e-a641-484f-a27f-980a6340e59d` | 2026-08-20T00:30:57.784Z | STATE_CHANGE/context_rescope_required | incident=`e2d9944d-3f68-4341-ad3b-358f4cb12b41` | lesson_key=`context-pack-rescope` | event_sha256=`9652961248b856f3668e90c96d03ea66ddd0d284661fa7803e67e4f611487c02`
- #13: `666c868f-d117-4576-a045-28926ab05ae3` | 2026-08-20T00:30:57.791Z | STATE_CHANGE/context_rescoped | incident=`aafe20e3-b163-4fb9-90ab-e2bdc3c75a1c` | lesson_key=`context-pack-rescope` | event_sha256=`e0ce599d8abc2c4d64534c9aee72cb27bba5eba59489e20adc41d336ab989c58`
- #14: `a9e4d2c7-5f31-4b68-8d0a-6c2e7f1b5d93` | 2026-08-20T00:31:00.000Z | STATE_CHANGE/remediation_rescoped_completed | incident=`c3f7a1e9-6d20-4b58-8e4c-0a2d9f7b5e61` | lesson_key=`complete-remediation-scope` | event_sha256=`0bcd829229e39ccfba8153e94ae7b0dbf0ece71e327ed64d3b51c0733102ab44`
