# Retrospective — v1-8-9-p1-classification-ml-core

## Goal

# v1.8.9 P1 Classification ML Core Objective  Implement a model-agnostic classification contract and prove it with Logistic and Random Forest adapters. Enforce explicit class mapping, information-set availability, safe split profiles, fold-local preprocessing, isolated final holdout, baselines and negative controls, calibrated metrics, bounded tuning, explanation caveats and DecisionPolicy separation. Publish package-local provider and renderer contributions without central Agent/Notebook/UI cutover.  ## Formal baseline and scope  - Plan Lock: \`f3836408cf15c3e7380823e5c1b303b4467c7aec\` - C0 wave lock: \`c9f3c4ed3e07faf6f57f795a5e35fa6f8042c749\` - Formal line: \`v1-8-9-p1-classification-ml-core\` - Worktree: \`/Users/jiayuanren/项目规划/.worktrees/workbench-v1.8.9-wave-a\` - Branch: \`workbench-v1.8.9-wave-a\`  This line owns only the classification package, additive prediction entrypoint, package-local provider and unmounted renderer contribution listed in its Work Order. Existing Data Consumer Core changes in the same Wave A worktree are protected and remain untouched.  ## Explicit non-goals  - No central Agent/Notebook routing, Context Compiler, workflow runtime,   evidence core, report mount, canonical section registry or Data Consumer Core   changes. - No arbitrary provider execution, raw dict model selection, silent fallback,   holdout exploration, browser acceptance, external provider benchmark,   dependency installation, full release gate, commit, merge, push or tag. - Only Logistic Regression and Random Forest are completion adapters; additional   model support remains an extension seam fixture, not a completion claim.

## Final status

COMPLETED

## Metrics

- Failure frequency: 21/28 (75.0%; 75.0 per 100 events)
- Repeat rate: 0/21 (0.0%)
- Recurrence rate: 0/21 (0.0%)
- MTTR: median=0 ms (sample=6; unresolved=14)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/4 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-16T06:14:23.000Z `task1_contracts_tdd_red`; cause_status: `known`; cause: The Task 1 classification contract test was collected before the new classification_contracts module existed.; resolution: `accepted`; lesson: Write strict classification contract tests before implementing the public API and preserve the fail-closed information-set boundary.
- #3 2026-08-16T06:18:02.000Z `classification_tasks_tdd_red_collection`; cause_status: `known`; cause: Task 2 through Task 9 RED tests were collected before their new package-local modules and split/preprocessing seams existed.; resolution: `accepted`; lesson: Keep split, preprocessing, adapter, metric, protocol, explanation and projection tests ahead of their implementations.
- #6 2026-08-16T06:27:00.000Z `classification_focused_suite_first_assertion_failures`; cause_status: `known`; cause: The first full focused run exposed three implementation mismatches: sklearn 1.9 Brier uses y_proba, panel_new_entity validates period support before the required entity-overlap invariant, and classification artifact persistence writes the payload under a fixed key instead of preserving artifact names.; resolution: `accepted`; lesson: Run the complete focused suite after each TDD slice and preserve environment-specific numerical API contracts, invariant ordering, and artifact identity.
- #7 2026-08-16T06:30:00.000Z `classification_undefined_metric_reason_followup`; cause_status: `known`; cause: After the Brier API compatibility fix, ROC AUC on a single-class sample returned a non-finite value and the generic metric wrapper emitted only 'non-finite metric' instead of a class-support reason.; resolution: `accepted`; lesson: Undefined metrics need precondition-specific reasons and must not be normalized into a generic numeric failure.
- #8 2026-08-16T06:34:00.000Z `classification_renderer_label_assertion`; cause_status: `known`; cause: The new renderer exposed serialized metric keys verbatim, so 'accuracy' was rendered instead of the contract-facing label 'Accuracy'.; resolution: `resolved`; lesson: Typed consumer renderers should preserve values while applying stable human-readable labels at the presentation boundary.
- #11 2026-08-16T06:39:00.000Z `classification_task8_task9_red_collection`; cause_status: `known`; cause: The new typed consumer, clarification and additive-entrypoint tests were collected before the corresponding owned entrypoint and contract helper existed.; resolution: `accepted`; lesson: Add Task 8-9 contract tests before implementing package-local registry, clarification and additive prediction seams.
- #13 2026-08-16T06:46:00.000Z `classification_leakage_purge_adversarial_red`; cause_status: `known`; cause: The classification split kernel recorded cross-partition label-window overlaps and embargo declarations but did not mutate affected development assignments to a non-training purged partition.; resolution: `accepted`; lesson: Purge and embargo contracts must change executable partition membership, not only describe a receipt after the split is built.
- #14 2026-08-16T06:50:00.000Z `classification_protocol_evidence_negative_red`; cause_status: `known`; cause: Adversarial protocol tests exposed that HoldoutSealGuard accepted an unknown metric release request and the protocol did not yet emit development OOF calibration or negative-control receipts.; resolution: `accepted`; lesson: Seal release plans must be closed over known metrics, and model outputs need explicit OOF calibration/control evidence before they are projected.
- #15 2026-08-16T06:54:00.000Z `classification_control_fold_support`; cause_status: `known`; cause: The first negative-control implementation globally permuted development labels, which could remove a class from a CV training complement even though the original split manifest was stratified.; resolution: `accepted`; lesson: Negative controls must preserve the declared exchangeability unit and executable fold support; never weaken adapter training invariants to force a control through.
- #19 2026-08-16T07:05:00.000Z `classification_control_blocked_model_recording_red`; cause_status: `known`; cause: When a deterministic within-fold label derangement was impossible, the protocol appended the typed BLOCKED control receipt but skipped the base model evidence record; later holdout selection indexed a missing model entry and raised KeyError.; resolution: `accepted`; lesson: Record validated model OOF/selection evidence independently of optional negative-control computation; a blocked control must not erase the primary model record.
- #20 2026-08-16T07:07:00.000Z `classification_blocked_control_test_hash_assertion_red`; cause_status: `known`; cause: The new blocked-control test assumed ClassificationSplitManifestV1.to_dict exposed content_hash, but the hash is a computed property and is intentionally only placed in the protocol/control receipt.; resolution: `accepted`; lesson: Assert computed manifest identity through the public receipt contract rather than an absent serialized field.
- #21 2026-08-16T07:12:00.000Z `classification_provider_catalog_order_regression`; cause_status: `known`; cause: Adding the package-local classification provider changed built-in catalog provider_ids order so it no longer satisfied the existing sorted deterministic catalog contract.; resolution: `accepted`; lesson: Package-local provider declarations must preserve the loader's deterministic provider ordering contract without changing central routing.

## All errors

- #4 2026-08-16T06:18:15.000Z `frontend_test_wrong_workdir`; cause_status: `known`; cause: The first frontend test command was run from the repository root rather than the frontend package directory.; resolution: `resolved`; lesson: Run frontend gates from the frontend package directory exactly as declared in the Work Order.
- #5 2026-08-16T06:21:30.000Z `classification_graph_projection_collection_error`; cause_status: `known`; cause: The focused classification consumer test imports classification_graph_nodes before the required owned-path graph projection helper exists.; resolution: `resolved`; lesson: Keep the Graph projection typed and package-local before running the consumer evidence suite.
- #9 2026-08-16T06:36:00.000Z `classification_renderer_typecheck_es2020_api`; cause_status: `known`; cause: The renderer used String.replaceAll and an unannotated replacement callback while the frontend TypeScript lib is ES2020 with strict checking.; resolution: `resolved`; lesson: Keep package-local renderer code within the repository's declared ES2020 and strict TypeScript surface.
- #12 2026-08-16T06:42:00.000Z `classification_provider_catalog_wrong_interpreter_path`; cause_status: `known`; cause: The provider catalog smoke command was launched from backend with .venv/bin/python instead of the repository interpreter path ../.venv/bin/python.; resolution: `resolved`; lesson: Use the declared repository interpreter and PYTHONPATH from the active package directory for every backend gate.
- #16 2026-08-16T07:00:00.000Z `classification_test_interpreter_path_error`; cause_status: `known`; cause: The focused test command used a stale ../.venv/bin/python path from the worktree and the fallback python alias is unavailable; the test process did not start.; resolution: `accepted`; lesson: Run repository verification with the resolved worktree-local interpreter and record path failures before retrying.
- #17 2026-08-16T07:02:00.000Z `classification_test_path_worktree_layout_error`; cause_status: `known`; cause: The focused test command used ../tests from the worktree root, but this linked worktree is nested two levels below the repository root and the test suite is at ../../tests.; resolution: `accepted`; lesson: Resolve test paths relative to the active worktree layout before running verification.
- #18 2026-08-16T07:03:00.000Z `classification_test_path_second_layout_error`; cause_status: `known`; cause: The next retry assumed the tests were two levels above the active worktree, but this worktree contains its own tests directory and the requested file is at ./tests.; resolution: `accepted`; lesson: Use the active worktree's own owned tests path when it exists; do not infer a shared-root test location from another execution context.

## All gaps

- #10 2026-08-16T06:37:00.000Z `classification_renderer_source_missing`; cause_status: `known`; cause: The frontend classification contract test was created before its same-line ClassificationEvidence renderer source.; resolution: `resolved`; lesson: Keep package-local renderer source and contract tests in the same implementation slice before handing the path to another line.
- #22 2026-08-16T07:15:00.000Z `classification_catalog_order_parallel_line_gap`; cause_status: `known`; cause: The repository builtin catalog currently contains pre-existing consumer_projection and data_consumer manifests whose filename-derived provider order is already inconsistent with the contract-lock assertion; the classification manifest cannot repair that relative ordering without changing another line or central loader.; resolution: `accepted`; lesson: Keep cross-line provider catalog ordering gaps explicit and out of the classification owned path; do not modify parallel provider manifests or central routing to hide the mismatch.

## All waste

- None recorded.

## Root causes and solutions

- `classification-blocked-control-preserves-model-evidence`: occurrences=1; cause_status: `known`; root cause: When a deterministic within-fold label derangement was impossible, the protocol appended the typed BLOCKED control receipt but skipped the base model evidence record; later holdout selection indexed a missing model entry and raised KeyError.; solution: `accepted`
- `classification-control-preserve-fold-support`: occurrences=1; cause_status: `known`; root cause: The first negative-control implementation globally permuted development labels, which could remove a class from a CV training complement even though the original split manifest was stratified.; solution: `accepted`
- `classification-first-focused-suite-failures`: occurrences=1; cause_status: `known`; root cause: The first full focused run exposed three implementation mismatches: sklearn 1.9 Brier uses y_proba, panel_new_entity validates period support before the required entity-overlap invariant, and classification artifact persistence writes the payload under a fixed key instead of preserving artifact names.; solution: `accepted`
- `classification-graph-projection-before-consumer-suite`: occurrences=1; cause_status: `known`; root cause: The focused classification consumer test imports classification_graph_nodes before the required owned-path graph projection helper exists.; solution: `resolved`
- `classification-isolate-parallel-catalog-gap`: occurrences=1; cause_status: `known`; root cause: The repository builtin catalog currently contains pre-existing consumer_projection and data_consumer manifests whose filename-derived provider order is already inconsistent with the contract-lock assertion; the classification manifest cannot repair that relative ordering without changing another line or central loader.; solution: `accepted`
- `classification-package-red-first`: occurrences=1; cause_status: `known`; root cause: Task 2 through Task 9 RED tests were collected before their new package-local modules and split/preprocessing seams existed.; solution: `accepted`
- `classification-protocol-seal-evidence-completeness`: occurrences=1; cause_status: `known`; root cause: Adversarial protocol tests exposed that HoldoutSealGuard accepted an unknown metric release request and the protocol did not yet emit development OOF calibration or negative-control receipts.; solution: `accepted`
- `classification-provider-interpreter-path`: occurrences=1; cause_status: `known`; root cause: The provider catalog smoke command was launched from backend with .venv/bin/python instead of the repository interpreter path ../.venv/bin/python.; solution: `resolved`
- `classification-provider-preserve-catalog-order`: occurrences=1; cause_status: `known`; root cause: Adding the package-local classification provider changed built-in catalog provider_ids order so it no longer satisfied the existing sorted deterministic catalog contract.; solution: `accepted`
- `classification-purge-must-be-executable`: occurrences=1; cause_status: `known`; root cause: The classification split kernel recorded cross-partition label-window overlaps and embargo declarations but did not mutate affected development assignments to a non-training purged partition.; solution: `accepted`
- `classification-renderer-es2020-typecheck`: occurrences=1; cause_status: `known`; root cause: The renderer used String.replaceAll and an unannotated replacement callback while the frontend TypeScript lib is ES2020 with strict checking.; solution: `resolved`
- `classification-renderer-readable-metric-labels`: occurrences=1; cause_status: `known`; root cause: The new renderer exposed serialized metric keys verbatim, so 'accuracy' was rendered instead of the contract-facing label 'Accuracy'.; solution: `resolved`
- `classification-renderer-source-test-closure`: occurrences=1; cause_status: `known`; root cause: The frontend classification contract test was created before its same-line ClassificationEvidence renderer source.; solution: `resolved`
- `classification-resolve-worktree-test-path`: occurrences=1; cause_status: `known`; root cause: The focused test command used ../tests from the worktree root, but this linked worktree is nested two levels below the repository root and the test suite is at ../../tests.; solution: `accepted`
- `classification-task8-task9-red-first`: occurrences=1; cause_status: `known`; root cause: The new typed consumer, clarification and additive-entrypoint tests were collected before the corresponding owned entrypoint and contract helper existed.; solution: `accepted`
- `classification-test-public-split-hash-contract`: occurrences=1; cause_status: `known`; root cause: The new blocked-control test assumed ClassificationSplitManifestV1.to_dict exposed content_hash, but the hash is a computed property and is intentionally only placed in the protocol/control receipt.; solution: `accepted`
- `classification-undefined-metric-reason`: occurrences=1; cause_status: `known`; root cause: After the Brier API compatibility fix, ROC AUC on a single-class sample returned a non-finite value and the generic metric wrapper emitted only 'non-finite metric' instead of a class-support reason.; solution: `accepted`
- `classification-use-active-worktree-tests`: occurrences=1; cause_status: `known`; root cause: The next retry assumed the tests were two levels above the active worktree, but this worktree contains its own tests directory and the requested file is at ./tests.; solution: `accepted`
- `classification-use-resolved-interpreter`: occurrences=1; cause_status: `known`; root cause: The focused test command used a stale ../.venv/bin/python path from the worktree and the fallback python alias is unavailable; the test process did not start.; solution: `accepted`
- `frontend-gate-workdir`: occurrences=1; cause_status: `known`; root cause: The first frontend test command was run from the repository root rather than the frontend package directory.; solution: `resolved`
- `task1-classification-contracts-red`: occurrences=1; cause_status: `known`; root cause: The Task 1 classification contract test was collected before the new classification_contracts module existed.; solution: `accepted`

## Added tests

- No test evidence recorded.

## New rules

- `classification-blocked-control-preserves-model-evidence`: line experience occurrence(s)=1
- `classification-control-preserve-fold-support`: line experience occurrence(s)=1
- `classification-first-focused-suite-failures`: line experience occurrence(s)=1
- `classification-graph-projection-before-consumer-suite`: line experience occurrence(s)=1
- `classification-isolate-parallel-catalog-gap`: line experience occurrence(s)=1
- `classification-package-red-first`: line experience occurrence(s)=1
- `classification-protocol-seal-evidence-completeness`: line experience occurrence(s)=1
- `classification-provider-interpreter-path`: line experience occurrence(s)=1
- `classification-provider-preserve-catalog-order`: line experience occurrence(s)=1
- `classification-purge-must-be-executable`: line experience occurrence(s)=1
- `classification-renderer-es2020-typecheck`: line experience occurrence(s)=1
- `classification-renderer-readable-metric-labels`: line experience occurrence(s)=1
- `classification-renderer-source-test-closure`: line experience occurrence(s)=1
- `classification-resolve-worktree-test-path`: line experience occurrence(s)=1
- `classification-task8-task9-red-first`: line experience occurrence(s)=1
- `classification-test-public-split-hash-contract`: line experience occurrence(s)=1
- `classification-undefined-metric-reason`: line experience occurrence(s)=1
- `classification-use-active-worktree-tests`: line experience occurrence(s)=1
- `classification-use-resolved-interpreter`: line experience occurrence(s)=1
- `frontend-gate-workdir`: line experience occurrence(s)=1
- `task1-classification-contracts-red`: line experience occurrence(s)=1

## Future guidance

- Add Task 8-9 contract tests before implementing package-local registry, clarification and additive prediction seams.
- Assert computed manifest identity through the public receipt contract rather than an absent serialized field.
- Close the line with explicit disjoint-path evidence and retain unrelated cross-line gates as open rather than masking them.
- Keep cross-line provider catalog ordering gaps explicit and out of the classification owned path; do not modify parallel provider manifests or central routing to hide the mismatch.
- Keep package-local renderer code within the repository's declared ES2020 and strict TypeScript surface.
- Keep package-local renderer source and contract tests in the same implementation slice before handing the path to another line.
- Keep split, preprocessing, adapter, metric, protocol, explanation and projection tests ahead of their implementations.
- Keep the Graph projection typed and package-local before running the consumer evidence suite.
- Negative controls must preserve the declared exchangeability unit and executable fold support; never weaken adapter training invariants to force a control through.
- Package-local provider declarations must preserve the loader's deterministic provider ordering contract without changing central routing.
- Purge and embargo contracts must change executable partition membership, not only describe a receipt after the split is built.
- Record validated model OOF/selection evidence independently of optional negative-control computation; a blocked control must not erase the primary model record.
- Resolve test paths relative to the active worktree layout before running verification.
- Run frontend gates from the frontend package directory exactly as declared in the Work Order.
- Run repository verification with the resolved worktree-local interpreter and record path failures before retrying.
- Run the complete focused suite after each TDD slice and preserve environment-specific numerical API contracts, invariant ordering, and artifact identity.
- Seal release plans must be closed over known metrics, and model outputs need explicit OOF calibration/control evidence before they are projected.
- Typed consumer renderers should preserve values while applying stable human-readable labels at the presentation boundary.
- Undefined metrics need precondition-specific reasons and must not be normalized into a generic numeric failure.
- Use the active worktree's own owned tests path when it exists; do not infer a shared-root test location from another execution context.
- Use the declared repository interpreter and PYTHONPATH from the active package directory for every backend gate.
- Write strict classification contract tests before implementing the public API and preserve the fail-closed information-set boundary.

## Event index

- #1: `acc0046f-078e-4d96-8657-f32d4d374d32` | 2026-08-16T06:12:58.760Z | STATE_CHANGE/line_started | incident=`7d52f43c-c079-4aa9-a873-3f5b65fcae54` | lesson_key=`frozen-context-before-start` | event_sha256=`9de8a6c40acc6770f870da14bff44bcd9d461305c7062b4bdf8bd71f0fd48355`
- #2: `0e3adf6f-8a1c-4a8e-9c1a-3b1b0c2d4e5f` | 2026-08-16T06:14:23.000Z | FAILURE/task1_contracts_tdd_red | incident=`1f4bc2d3-5e6f-4789-8abc-def012345678` | lesson_key=`task1-classification-contracts-red` | event_sha256=`c65f8d3d7c5e2597427949c6760c28b0964f2b2f5cc9b5f97dc87d7c2a4e90cd`
- #3: `2a4b6c8d-0e1f-42a3-b4c5-d6e7f8091a2b` | 2026-08-16T06:18:02.000Z | FAILURE/classification_tasks_tdd_red_collection | incident=`3b5c7d9e-1f20-43a5-b6c7-d8e9f0012a3b` | lesson_key=`classification-package-red-first` | event_sha256=`723eca483490ce63bf6f447b3f58c5273d1221c23978cd41792c1d1fb46f4e63`
- #4: `4c6e8f0a-2b3d-45f6-a7b8-c9d0e1f20314` | 2026-08-16T06:18:15.000Z | ERROR/frontend_test_wrong_workdir | incident=`5d7f9a1b-3c4e-46a7-b8c9-d0e1f2031425` | lesson_key=`frontend-gate-workdir` | event_sha256=`1fd69bc3773559725875a6bfbed3950817de4f7e257f881f364bbfd0572a4362`
- #5: `5e6f7081-92a3-4b4c-8d5e-6f708192a3b4` | 2026-08-16T06:21:30.000Z | ERROR/classification_graph_projection_collection_error | incident=`6d7f8091-a2b3-4c5d-e6f7-8091a2b3c4d5` | lesson_key=`classification-graph-projection-before-consumer-suite` | event_sha256=`faf5a1dd7f6badd6761ccc0dc5fa2071383a91be8a1c293b63bd065780d5e996`
- #6: `6f708192-a3b4-4c5d-e6f7-8091a2b3c4d5` | 2026-08-16T06:27:00.000Z | FAILURE/classification_focused_suite_first_assertion_failures | incident=`7e8f9012-a3b4-4c5d-e6f7-8091a2b3c4d5` | lesson_key=`classification-first-focused-suite-failures` | event_sha256=`1c08f96666543f9e6ef62e0d596d5c2f7c1e6140d91be7654e4aebba4e2e08ef`
- #7: `91a2b3c4-d5e6-4f70-8192-a3b4c5d6e7f8` | 2026-08-16T06:30:00.000Z | FAILURE/classification_undefined_metric_reason_followup | incident=`8091a2b3-c4d5-4e6f-7081-92a3b4c5d6e7` | lesson_key=`classification-undefined-metric-reason` | event_sha256=`044041368878107ba5df8201ef79370edf6e1615169af46528251221277ab71e`
- #8: `b4c5d6e7-f809-41a2-b3c4-d5e6f708192a` | 2026-08-16T06:34:00.000Z | FAILURE/classification_renderer_label_assertion | incident=`a3b4c5d6-e7f8-4091-a2b3-c4d5e6f70819` | lesson_key=`classification-renderer-readable-metric-labels` | event_sha256=`7cd7ec55c337a918489e2b7cc16bd8ec587f76271a82a6cb2b4107d7c4b2c70b`
- #9: `d6e7f809-12a3-4b4c-d5e6-f708192a3b4c` | 2026-08-16T06:36:00.000Z | ERROR/classification_renderer_typecheck_es2020_api | incident=`c5d6e7f8-0912-4a3b-c4d5-e6f708192a3b` | lesson_key=`classification-renderer-es2020-typecheck` | event_sha256=`452d8eb34d7feacfafedf769b6e2c0646c9a465000f3e97d10661b9574361291`
- #10: `f80912a3-b4c5-4d6e-f708-192a3b4c5d6e` | 2026-08-16T06:37:00.000Z | GAP/classification_renderer_source_missing | incident=`e7f80912-a3b4-4c5d-e6f7-08192a3b4c5d` | lesson_key=`classification-renderer-source-test-closure` | event_sha256=`fef10244dadc35fc12cb3c0616e080c34e866cd1f90b166fd62dc6dbc25741b9`
- #11: `091a2b3c-4d5e-4f70-8192-a3b4c5d6e7f8` | 2026-08-16T06:39:00.000Z | FAILURE/classification_task8_task9_red_collection | incident=`f8091a2b-3c4d-4e5f-7081-92a3b4c5d6e7` | lesson_key=`classification-task8-task9-red-first` | event_sha256=`60d179f4af4f1f0e38fd4bffcd81cbab637bf293ccb429bc7f21999fa30cddeb`
- #12: `2b3c4d5e-6f70-4192-a3b4-c5d6e7f8091a` | 2026-08-16T06:42:00.000Z | ERROR/classification_provider_catalog_wrong_interpreter_path | incident=`1a2b3c4d-5e6f-4071-92a3-b4c5d6e7f809` | lesson_key=`classification-provider-interpreter-path` | event_sha256=`ad28a3bea42e8980a2b0788f8941d8b296543b6597c1693e7d816cc021fc9f05`
- #13: `4d5e6f70-8192-4a3b-c4d5-e6f708192a3b` | 2026-08-16T06:46:00.000Z | FAILURE/classification_leakage_purge_adversarial_red | incident=`3c4d5e6f-7081-492a-b3c4-d5e6f708192a` | lesson_key=`classification-purge-must-be-executable` | event_sha256=`052b075ccdc3f73891122e0ec29250a61ea6fb33799d30616a74b82799476dbd`
- #14: `6f708192-a3b4-4c5d-e6f7-08192a3b4c5d` | 2026-08-16T06:50:00.000Z | FAILURE/classification_protocol_evidence_negative_red | incident=`5e6f7081-92a3-4b4c-d5e6-f708192a3b4c` | lesson_key=`classification-protocol-seal-evidence-completeness` | event_sha256=`f8ded8b1274da33500b461937fb71225a20ab0cbd8d7bcf9256971b1c08f1189`
- #15: `8192a3b4-c5d6-4e7f-0819-2a3b4c5d6e7f` | 2026-08-16T06:54:00.000Z | FAILURE/classification_control_fold_support | incident=`708192a3-b4c5-4d6e-f708-192a3b4c5d6e` | lesson_key=`classification-control-preserve-fold-support` | event_sha256=`5da6ef8a121377cb2d2cd1c2a7f99e9c6b70799617ddac827ffce92499a4bdbf`
- #16: `a3b4c5d6-e7f8-4192-a3b4-c5d6e7f8091a` | 2026-08-16T07:00:00.000Z | ERROR/classification_test_interpreter_path_error | incident=`b4c5d6e7-f809-4a1b-2c3d-4e5f60718293` | lesson_key=`classification-use-resolved-interpreter` | event_sha256=`c72b3c744211c3511575bef447b6fe9e1fb06ea95e7a305b8466c5be672b52fa`
- #17: `c5d6e7f8-091a-4b2c-3d4e-5f60718293a4` | 2026-08-16T07:02:00.000Z | ERROR/classification_test_path_worktree_layout_error | incident=`d6e7f809-1a2b-4c3d-4e5f-60718293a4b5` | lesson_key=`classification-resolve-worktree-test-path` | event_sha256=`fd4d515b53ad2d18cdb3bf9f1257b0a2c6b45e6f4ad292f02a3dfb8bb6135574`
- #18: `e7f8091a-2b3c-4d5e-6f70-8192a3b4c5d6` | 2026-08-16T07:03:00.000Z | ERROR/classification_test_path_second_layout_error | incident=`f8091a2b-3c4d-5e6f-7081-92a3b4c5d6e7` | lesson_key=`classification-use-active-worktree-tests` | event_sha256=`8f92693f249a0c079939180470674ddf7c53e47e8e2bed031a6115ae02d27491`
- #19: `091a2b3c-4d5e-4f70-8192-a3b4c5d6e7f9` | 2026-08-16T07:05:00.000Z | FAILURE/classification_control_blocked_model_recording_red | incident=`1a2b3c4d-5e6f-7081-92a3-b4c5d6e7f809` | lesson_key=`classification-blocked-control-preserves-model-evidence` | event_sha256=`78708ab9ec4bbd75b63fef23aa0d5cf2ee46a6f1f46aa7ee794b6f0a9c82c137`
- #20: `1a2b3c4d-5e6f-7081-92a3-b4c5d6e7f80a` | 2026-08-16T07:07:00.000Z | FAILURE/classification_blocked_control_test_hash_assertion_red | incident=`2b3c4d5e-6f70-8192-a3b4-c5d6e7f8091a` | lesson_key=`classification-test-public-split-hash-contract` | event_sha256=`420f0e5c8ca8024dc5d739c1b8e7f372d4622623e492e8e2383c50d4843ea7be`
- #21: `2b3c4d5e-6f70-4192-a3b4-c5d6e7f8091b` | 2026-08-16T07:12:00.000Z | FAILURE/classification_provider_catalog_order_regression | incident=`3c4d5e6f-7081-492a-b3c4-d5e6f708192a` | lesson_key=`classification-provider-preserve-catalog-order` | event_sha256=`e3fc1a581da9e99198e278365d5a737e279e3f9f0714e240e386ab7145bfaff4`
- #22: `4d5e6f70-8192-4a3b-c4d5-e6f708192a3c` | 2026-08-16T07:15:00.000Z | GAP/classification_catalog_order_parallel_line_gap | incident=`5e6f7081-92a3-4b4c-8d5e-6f708192a3b5` | lesson_key=`classification-isolate-parallel-catalog-gap` | event_sha256=`e90a5d692888a26f73482002d93c88cf1b75718bdf7e2f7de8693a59c2234019`
- #23: `5e6f7081-92a3-4b4c-8d5e-6f708192a3b6` | 2026-08-16T07:20:00.000Z | GATE/classification_focused_backend_green | incident=`6f708192-a3b4-4c5d-e6f7-8091a2b3c4d6` | lesson_key=`classification-focused-backend-green` | event_sha256=`319c755404ddb94400a62ac217d60f491fe01bab873d7c1a0799898e9ddd9405`
- #24: `708192a3-b4c5-4d6e-f708-192a3b4c5d6f` | 2026-08-16T07:20:01.000Z | GATE/classification_mutation_negative_green | incident=`8192a3b4-c5d6-4e7f-0819-2a3b4c5d6e80` | lesson_key=`classification-negative-control-strict-support-green` | event_sha256=`0496235e31ba4b5f875e8cc536203c0d41c8f639da39dc9037198bbc7b48fcf9`
- #25: `92a3b4c5-d6e7-4f80-91a2-b3c4d5e6f708` | 2026-08-16T07:20:02.000Z | GATE/classification_renderer_frontend_green | incident=`a3b4c5d6-e7f8-4192-a3b4-c5d6e7f8091b` | lesson_key=`classification-unmounted-renderer-green` | event_sha256=`199c12b4b84fa1874bb03108214ce4d06a53b8e4cf9ad2ee9cb7ad75be69b90f`
- #26: `b4c5d6e7-f809-4a1b-2c3d-4e5f60718294` | 2026-08-16T07:20:03.000Z | GATE/classification_compile_diff_scope_green | incident=`c5d6e7f8-091a-4b2c-3d4e-5f60718293a5` | lesson_key=`classification-compile-diff-green` | event_sha256=`ae817f8824bc35e7516776fadac9a30428d8a18ad3c867ecc283675f6a4360e7`
- #27: `d6e7f809-1a2b-4c3d-4e5f-60718293a4b6` | 2026-08-16T07:20:04.000Z | REVIEW/classification_owned_scope_review | incident=`e7f8091a-2b3c-4d5e-6f70-8192a3b4c5d7` | lesson_key=`classification-disjoint-owned-scope-review` | event_sha256=`b55e2c22c0002b3f2f3df028c174983a8130f1c6010ec22c2bc8f4ef7a41d591`
- #28: `f8091a2b-3c4d-4e5f-7081-92a3b4c5d6e8` | 2026-08-16T07:22:00.000Z | STATE_CHANGE/classification_line_completed | incident=`091a2b3c-4d5e-4f70-8192-a3b4c5d6e810` | lesson_key=`classification-formal-closeout-boundaries` | event_sha256=`c5c310f8bac36a5fc46feef57dcc4bfcec1fd12e56706137ae8362baa77cec96`
