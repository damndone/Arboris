# Retrospective — v1-8-6-consumer-entries

## Goal

# v1.8.6 Consumer Entries Objective  在已验证的 v1.8.6 模型族提交 \`b2c8018\` 上，补齐统计消费链路的两个用户入口边界：  1. 普通 \`Run\` UI 能配置四个 v1.8.6 模型族的 \`model_options\`，并将其送入现有 API； 2. 用户可通过 POST \`/runs\` 的声明字段提供变量/值标签，标签持久化并贯通 Table 1、报告、    XLSX 与图形轴；未声明时继续使用列名 fallback，并显式记录 fallback 来源。  不改变既有估计器数值、统计检验算法、FeatureRecipe 语义或发布状态。  ## 可证伪验收  - 普通 Run UI 选择 ordinal/multinomial/survival/quantile 时显示对应配置，提交的   \`FormData\` 含 \`model_options\`；生存模型缺 event 列在服务端结构化拒绝。 - \`/runs\` 接收严格 JSON \`labels\`，错误结构拒绝；成功运行的 \`run_inputs\`、Table 1、   HTML/XLSX 报告和至少一张图形的轴/标题读取同一声明标签。 - 未声明标签的报告仍可生成，且 \`label_source=column_name_fallback\`。 - 既有前端 API/Run/报告/回归测试、编译和 \`git diff --check\` 通过；Formal FMS verify 通过。  ## 边界  - 不解析 Stata/R 外部标签文件；本线只交付显式 JSON 声明。 - 不把标签用于模型列名、Graph identity 或数值计算。 - 不 push、PR、merge、tag 或发布。

## Final status

CONTEXT_RESCOPED

## Metrics

- Failure frequency: 1/28 (3.6%; 3.6 per 100 events)
- Repeat rate: 0/1 (0.0%)
- Recurrence rate: 0/1 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/2 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #6 2026-08-03T11:37:48.000Z `consumer_entry_contract_red`; cause_status: `known`; cause: The new labels acceptance tests correctly failed because run_workflow had no labels transport, reports did not expose label source/value mappings, and figure axes did not yet use declared labels.; resolution: `resolved`; lesson: For labels, test the same declaration through transport, report/table export, and visualization metadata before claiming user reachability.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `labels-consumer-boundary-before-claim`: occurrences=1; cause_status: `known`; root cause: The new labels acceptance tests correctly failed because run_workflow had no labels transport, reports did not expose label source/value mappings, and figure axes did not yet use declared labels.; solution: `resolved`

## Added tests

- No test evidence recorded.

## New rules

- `labels-consumer-boundary-before-claim`: line experience occurrence(s)=1

## Future guidance

- For labels, test the same declaration through transport, report/table export, and visualization metadata before claiming user reachability.

## Event index

- #1: `2a695580-e41a-4368-8936-13d7433bf0aa` | 2026-08-03T11:28:27.642Z | STATE_CHANGE/line_started | incident=`c047e391-adb9-4580-896a-f371e36803d3` | lesson_key=`frozen-context-before-start` | event_sha256=`19c7c0fbc2164bb38a03f80302ac57feafe1cd29ab11dc78a83e9fa88de04308`
- #2: `f834330b-a3ca-4358-986d-c2396694d849` | 2026-08-03T11:32:30.660Z | STATE_CHANGE/context_rescope_required | incident=`6e991f25-ec42-4242-a02f-5baa2d69a509` | lesson_key=`context-pack-rescope` | event_sha256=`22fd287250ea24dd59d1862ea97c3794bef12d60e1daec6935ec7fcb0da7df82`
- #3: `7feca425-e06a-466d-9dae-8019e9b5ecba` | 2026-08-03T11:32:30.662Z | STATE_CHANGE/context_rescoped | incident=`f552dcc8-c5ee-44b5-90c2-c6653a68ec87` | lesson_key=`context-pack-rescope` | event_sha256=`d71f7070125b30212da8da7a28070b580684e65923607702ca518aaeacfc827d`
- #4: `33ec884f-8b31-4e11-90b7-71e7c40a8545` | 2026-08-03T11:34:11.770Z | STATE_CHANGE/context_rescope_required | incident=`393083f3-a49c-4ff7-8fba-f5c8432b3973` | lesson_key=`context-pack-rescope` | event_sha256=`6b3d3ca531817690635a56a3dd31d6f45146942f77fcf06f32dada3cc1d4816f`
- #5: `febbea38-44ef-4508-b52b-6175f7aa9f15` | 2026-08-03T11:34:11.773Z | STATE_CHANGE/context_rescoped | incident=`ff3fe456-d9c0-47cf-a913-5dff75a21b87` | lesson_key=`context-pack-rescope` | event_sha256=`27afa8a925f210111e0f5786b98417704191a8e96c1b2c06d8a9d596d8eab625`
- #6: `0c38a2bd-70c2-45ed-8d82-87f35acbca7d` | 2026-08-03T11:37:48.000Z | FAILURE/consumer_entry_contract_red | incident=`7bbf5591-5fa1-4f7b-a7cb-64b14a2c4d75` | lesson_key=`labels-consumer-boundary-before-claim` | event_sha256=`9f1dbdc4e8bb326e5a39f3450ab84107effe73f6820082d7166051619fb29682`
- #7: `d2e446d6-eb57-4ab3-9ff4-da7b05b52ed5` | 2026-08-03T11:41:31.025Z | STATE_CHANGE/context_rescope_required | incident=`1c097d75-2247-4f48-8871-8063bd46e898` | lesson_key=`context-pack-rescope` | event_sha256=`2c7f41b5d6f0c3d2bc9eaf4131da341b0e693f495e88b778786b4df3fe70ef3f`
- #8: `0966fce3-11dc-445a-b412-edd84b068b17` | 2026-08-03T11:41:31.030Z | STATE_CHANGE/context_rescoped | incident=`ee2fcf1b-1357-4b7c-bf14-e9a5342d5562` | lesson_key=`context-pack-rescope` | event_sha256=`9e7ccd735ae81267f6bfaa1d1117ec699f6df2c9fdeba893fac61a044b10a151`
- #9: `3cf2ba68-4f29-484d-9808-a324ca976598` | 2026-08-03T11:58:16.799Z | STATE_CHANGE/context_rescope_required | incident=`26ea4ec3-8a80-4303-80a0-3589c345107a` | lesson_key=`context-pack-rescope` | event_sha256=`20dac5f79f53b8b17391fd61b97d58dde4f8e005239d21f393e708ce63739ddd`
- #10: `a85ca2e4-8367-4cdb-b846-5581cef59278` | 2026-08-03T11:58:16.804Z | STATE_CHANGE/context_rescoped | incident=`54174244-e6be-4d8a-b06d-d035c9bb6567` | lesson_key=`context-pack-rescope` | event_sha256=`802f40ea90a32b248800d320cb071f8eb0de709890f1fcfda3a96fbd36a8efe5`
- #11: `9bc62688-0f3c-40d5-b199-e21e6827e494` | 2026-08-03T11:58:16.953Z | STATE_CHANGE/context_rescope_required | incident=`b5b0db66-fe22-467f-ac80-de3f8f565ba4` | lesson_key=`context-pack-rescope` | event_sha256=`c24dfb3b4cd192939f630fa72c7a20d37624f1f8c716c2c7d956190cfe091dbd`
- #12: `dff4eba2-9f95-4356-bed3-7eb8e5a7e308` | 2026-08-03T11:58:16.959Z | STATE_CHANGE/context_rescoped | incident=`c56fe10f-71f8-420a-ae25-a813972349ca` | lesson_key=`context-pack-rescope` | event_sha256=`952dfb7dd81b4f0fef21f23e0259ad33844f6befc42a98a3fe902b5c21672422`
- #13: `2f1b9d07-ab2d-4eea-9159-2f0884d17395` | 2026-08-03T11:58:17.087Z | STATE_CHANGE/context_rescope_required | incident=`323d2f3d-c153-4abe-9a7d-a1a513a8f8c7` | lesson_key=`context-pack-rescope` | event_sha256=`9183b99dd22b74350eb6f2962dd4e3b0afab88ca061d78dcf8789ec229bc6386`
- #14: `241ee71a-5012-4377-bf03-edd2bfe62448` | 2026-08-03T11:58:17.094Z | STATE_CHANGE/context_rescoped | incident=`f163c42a-e31c-4dde-ba93-670618761a4f` | lesson_key=`context-pack-rescope` | event_sha256=`8decc7859c8de05231ef6e6e87265282ecf2522b0fd27d0302b8aa91bf8444f6`
- #15: `5627288d-685f-4eef-894e-380c18c951bf` | 2026-08-03T11:58:17.228Z | STATE_CHANGE/context_rescope_required | incident=`e1c746a2-9f07-4f47-823b-cae57b2e6e8f` | lesson_key=`context-pack-rescope` | event_sha256=`180237df6e7d2ed0191fea73381f4d8aee577a580ab4360c4e8d8521be6d19d7`
- #16: `6cfed3a4-40ed-4f0e-b382-c1dbcd914380` | 2026-08-03T11:58:17.236Z | STATE_CHANGE/context_rescoped | incident=`d0795432-1b7e-469e-b34f-30fc5db710b0` | lesson_key=`context-pack-rescope` | event_sha256=`5543922c5c22a6144a7441a478222fb60e7c3d111bc0cdf1e71b5bd82858fd41`
- #17: `4d1311e7-301d-4942-9309-b9af4f91c217` | 2026-08-03T11:58:17.382Z | STATE_CHANGE/context_rescope_required | incident=`aa53a85d-a2ca-46b7-8e5c-b8259ac3cc65` | lesson_key=`context-pack-rescope` | event_sha256=`9ee08179f36cd1fa8376fef1ce4a9c30d0e683c68765123f6f329acc010e9df1`
- #18: `3d326d47-8be0-4f20-83d4-799d1b043c87` | 2026-08-03T11:58:17.389Z | STATE_CHANGE/context_rescoped | incident=`c9cb60a9-eb74-4db5-968f-62482c5d9aee` | lesson_key=`context-pack-rescope` | event_sha256=`d19e64c7db57d09a81dedcd250f10de7bb439030868196173c9b0091fc7bdc85`
- #19: `0a26111b-fd30-4170-b85b-5bb30cc62062` | 2026-08-03T11:58:17.522Z | STATE_CHANGE/context_rescope_required | incident=`cb37caf5-3796-4773-a8a2-a35829222918` | lesson_key=`context-pack-rescope` | event_sha256=`33fd7585adc3c7198efb0ccbe165db19125de2f205d72f133026cd5988538549`
- #20: `914b23aa-521d-4987-a351-945a762804dc` | 2026-08-03T11:58:17.530Z | STATE_CHANGE/context_rescoped | incident=`4e3d11f7-2e06-4e3d-800b-1265f3fa02a9` | lesson_key=`context-pack-rescope` | event_sha256=`3ceb0c29d31e9f6ad21fefa9c3a81f6e81e0fc5d4ab65d95ebd97d12ca03c8a2`
- #21: `b8871514-f583-436c-acc0-e4afe4cc93c2` | 2026-08-03T11:58:17.667Z | STATE_CHANGE/context_rescope_required | incident=`90814270-eec5-4b6f-8ade-f9e1e53603e3` | lesson_key=`context-pack-rescope` | event_sha256=`95954d5f46b4c2bc1b83a37fd7a48caf52cbe072e62c0d790b77a6f67e48a5d3`
- #22: `8d17298f-f611-4f03-8dc7-70a00476d46e` | 2026-08-03T11:58:17.676Z | STATE_CHANGE/context_rescoped | incident=`16f0eba6-8ca5-4c11-9ff8-de0ddf9d3816` | lesson_key=`context-pack-rescope` | event_sha256=`452e2f5d190ab1780c57f6ae824953fc0877d4f10768f390156947ad71ed3d1d`
- #23: `952ada19-f4a1-443a-9977-0602bcaf9d21` | 2026-08-03T11:58:17.817Z | STATE_CHANGE/context_rescope_required | incident=`0cb22277-97e8-41bd-9a10-40fd839486fb` | lesson_key=`context-pack-rescope` | event_sha256=`346c8e2e9cb7ac8456eca9c475af985130eaa006e5cc9bd991e590018637ba62`
- #24: `2af15c4d-df3c-4e7c-9d5f-374698f83971` | 2026-08-03T11:58:17.827Z | STATE_CHANGE/context_rescoped | incident=`be2c9507-f140-469b-85f6-62e7010b914e` | lesson_key=`context-pack-rescope` | event_sha256=`ab59f7cfd18a8c8dd5015d9597de0c02d6e2a989cda6dd8ef14d20f934e0fa77`
- #25: `724c4e73-d445-40a9-bcdc-70003f3c47e5` | 2026-08-03T12:02:51.946Z | STATE_CHANGE/context_rescope_required | incident=`0f1c098f-0201-40da-8d5f-d29e71e9a334` | lesson_key=`context-pack-rescope` | event_sha256=`6bbd213cba16948fee6a8ea18f0039c9edffcab8f5874c17e8ef01ad6e6cf7ed`
- #26: `6345333e-a4f6-4786-b506-6115d5fab8df` | 2026-08-03T12:02:51.957Z | STATE_CHANGE/context_rescoped | incident=`c3141b20-5e25-4bbb-983b-8fb29645ccf5` | lesson_key=`context-pack-rescope` | event_sha256=`a6415b4b1429702eaeadeb18e584f7a15ddf00517d2b804a4717d54c3e5bdab6`
- #27: `c3d4c1f1-3dd5-4ced-b9a6-1bcbd1cb5f4c` | 2026-08-03T12:03:23.000Z | GATE/full_backend_gate_host_sandbox | incident=`f7a6242a-aac8-4fd8-a73e-97a0ec0301d0` | lesson_key=`host-sandbox-gate-separation` | event_sha256=`c68b84590bb95820cbe4f68253d2a7606627976f453a17cac22fc98ac0020fa3`
- #28: `5a0e101a-8b2c-4d75-9855-653247c5f6c4` | 2026-08-03T12:05:12.000Z | GATE/focused_consumer_gate_passed | incident=`d75647a7-3700-4429-b773-58aa94a9df3b` | lesson_key=`consumer-vocabulary-completeness` | event_sha256=`95daf61fc4e6c3bff3b42dbef05d8d14fe7f7997d5dc5cf423a2ea475293a2e4`
