# Retrospective — v1-8-3-document-authority-consolidation

## Goal

# v1.8.3 文档权威收敛  ## 目标  把 v1.8.3 规格与计划恢复为仓库既有的扁平目录惯例，消除重复 scope、已完成使命的 objective、双重权威和失效引用，同时完整保留已批准的运行时、Capability Factory、领域记忆与执行边界。  ## 交付  - 三份扁平规格：custom capability runtime、Capability Factory、domain memory； - 三份扁平计划：execution control、Capability lane、Memory lane； - 零份保留 objective，零份重定向壳文件； - execution-control plan 是唯一开工入口； - 全部实时文档引用指向新权威路径； - 已冻结 \`.agent/devlines\` 历史证据保持不变。  ## 不做  - 不修改产品代码、测试代码、正式 FMS 历史记录或发布状态； - 不删除有独立语义职责的运行时、Capability Factory 或领域记忆契约； - 不新增设计功能、实现范围、review 文档或计划分片； - 不 push、PR、merge、tag 或 release。  ## 完成标准  - \`docs/superpowers/specs\` 和 \`docs/superpowers/plans\` 不再存在唯一的 v1.8.3 子目录例外； - v1.8.3 只保留三份规格与三份计划，文件名均含日期和版本； - objectives、重复 README 和旧实时引用清零； - 命名 gate、引用检查、diff check 与正式 FMS verify 通过。

## Final status

COMPLETED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0; coverage=0/1)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- #2 2026-07-26T03:27:00.000Z `fragmented_document_authority`; cause_status: `known`; cause: v1.8.3 was the only version using specs and plans subdirectories while also retaining scope maps and objectives that duplicated live authority.; resolution: `resolved`; lesson: Version documentation must follow the repository-wide flat dated naming convention and expose one execution entry without retaining frozen-input source files as live authority.

## Root causes and solutions

- `documentation-authority-follows-repository-convention`: occurrences=1; cause_status: `known`; root cause: v1.8.3 was the only version using specs and plans subdirectories while also retaining scope maps and objectives that duplicated live authority.; solution: `resolved`

## Added tests

- `tests/test_no_exercise_specific_naming.py`

## New rules

- `documentation-authority-follows-repository-convention`: line experience occurrence(s)=1

## Future guidance

- Minimize authority files without merging contracts that have independent producers, consumers, failure modes, and acceptance gates.
- Version documentation must follow the repository-wide flat dated naming convention and expose one execution entry without retaining frozen-input source files as live authority.

## Event index

- #1: `a71ec3ca-05ef-40fe-8625-faae15404dd3` | 2026-07-26T03:21:55.398Z | STATE_CHANGE/line_started | incident=`7bde7d7d-aa26-4a93-9b3c-88b309138b4b` | lesson_key=`frozen-context-before-start` | event_sha256=`9cfd61278d4ab6945b25e2e9b2ed452d2a6534578a6fde94ff1b2614836eeef5`
- #2: `ca0ca7f8-2448-4623-8c6f-ed9b588ff0ee` | 2026-07-26T03:27:00.000Z | WASTE/fragmented_document_authority | incident=`8f5dd945-2c89-4ce8-8891-3dcd09d8e8ac` | lesson_key=`documentation-authority-follows-repository-convention` | event_sha256=`3d17812a8336551bc4fd0e6274f664b36ddbeed00a741726fda790845d549870`
- #3: `a3eb78fd-d73f-4348-9233-31c0e5c44599` | 2026-07-26T03:28:00.000Z | REVIEW/flat_authority_map_accepted | incident=`bad74f22-c5de-4711-9b73-a6aad395c6a9` | lesson_key=`minimal-authority-preserves-contract-boundaries` | event_sha256=`be1a7a0d428c280b410051388f1763a55497924ce929f5e684a1968a0e85cc9e`
- #4: `50ff3e54-1465-4cd5-bf02-be72b786539c` | 2026-07-26T03:29:00.000Z | GATE/document_authority_gate_passed | incident=`840f4c2c-94dc-49b5-a199-966e1aafe1db` | lesson_key=`document-authority-needs-structural-gate` | event_sha256=`fc9cfc84c9bf185f4205ad6ee0a6fff86bc95205d7b317f098ac5a69db8ef6b4`
- #5: `c11214a1-c0b0-4b90-a114-87c7ed357e9e` | 2026-07-26T03:30:00.000Z | STATE_CHANGE/document_authority_consolidated | incident=`f95a635d-89af-4e9e-9ce7-1e854f247f5b` | lesson_key=`uniform-document-map-preserves-independent-contracts` | event_sha256=`5dd4b6e16b2429e960332435c8ffbee5831f7e8fe45e018f4f9dd4ba2136505d`
