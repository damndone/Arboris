# Retrospective — v1-8-9-p1-data-operation-route-contract-migration

## Goal

# Workbench v1.8.9 P1 Data Operation Route Contract Migration  Align legacy code-execute and reshape route tests with the current typed preview/operation-result contracts, or repair a demonstrated production regression. Preserve preview-first confirmation, sandbox/determinism evidence, typed unavailable/blocked reasons, and child-node lineage.  Scope: backend/workbench/data_operations.py, backend/workbench/api.py, tests/test_code_execute_routes.py, tests/test_data_operation_routes_v186.py.  Acceptance: focused route tests pass without weakening safety, raw code execution, or provenance checks; any production change has a minimal regression test.

## Final status

COMPLETED

## Metrics

- Failure frequency: 5/13 (38.5%; 38.5 per 100 events)
- Repeat rate: 0/5 (0.0%)
- Recurrence rate: 0/5 (0.0%)
- MTTR: median=0 ms (sample=3; unresolved=2)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/1 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- #2 2026-08-21T07:22:05.586Z `route_contract_red`; cause_status: `known`; cause: The scoped route suite is green for blocked preview and bounded reshape contracts, but the successful code.execute child-node readback still returns 404.; resolution: `open`; lesson: Keep successful child-node readback as a production regression and do not turn a real 404 into a test-only compatibility expectation.

## All errors

- #4 2026-08-21T07:22:33.581Z `formal_cli_import_path`; cause_status: `known`; cause: The first formal CLI invocation inherited a linked-worktree module path and imported the unrelated workbench-v1.8.6 backend; the explicit worktree backend PYTHONPATH restored the supported command surface.; resolution: `resolved`; lesson: Run formal CLI operations with the current worktree backend first when linked virtual environments expose another workbench module.
- #11 2026-08-21T07:27:09.695Z `formal_event_schema_rejected`; cause_status: `known`; cause: The first GREEN gate event used the unsupported preventability value not_applicable and was rejected before append; the event was corrected to the controlled not_preventable value.; resolution: `resolved`; lesson: Validate formal event vocabulary against the live schema before appending a gate record.
- #13 2026-08-21T07:29:29.224Z `git_index_permission`; cause_status: `external`; cause: Default workspace permissions denied git add while creating the linked worktree index lock; the required commit operation must use the approved elevated environment.; resolution: `resolved`; lesson: Use the authorized elevated environment for git index operations when the shared worktree metadata is outside the default write sandbox.

## All gaps

- #3 2026-08-21T07:22:19.651Z `code_execute_child_lookup_allowlist`; cause_status: `known`; cause: The confirmed server effect carries typed child, artifact, and recipe bindings, but the by-child lookup filters through a live manifest that excludes code.execute.; resolution: `open`; lesson: Align a typed child-node lookup allowlist with every server-owned effect that the route is contractually required to resolve; preserve bounded projection and lineage checks.

## All waste

- None recorded.

## Root causes and solutions

- `child-node-readback-regression`: occurrences=1; cause_status: `known`; root cause: The scoped route suite is green for blocked preview and bounded reshape contracts, but the successful code.execute child-node readback still returns 404.; solution: `open`
- `formal-cli-worktree-import`: occurrences=1; cause_status: `known`; root cause: The first formal CLI invocation inherited a linked-worktree module path and imported the unrelated workbench-v1.8.6 backend; the explicit worktree backend PYTHONPATH restored the supported command surface.; solution: `resolved`
- `formal-event-vocabulary`: occurrences=1; cause_status: `known`; root cause: The first GREEN gate event used the unsupported preventability value not_applicable and was rejected before append; the event was corrected to the controlled not_preventable value.; solution: `resolved`
- `git-worktree-index-permission`: occurrences=1; cause_status: `external`; root cause: Default workspace permissions denied git add while creating the linked worktree index lock; the required commit operation must use the approved elevated environment.; solution: `resolved`
- `typed-child-lookup-allowlist`: occurrences=1; cause_status: `known`; root cause: The confirmed server effect carries typed child, artifact, and recipe bindings, but the by-child lookup filters through a live manifest that excludes code.execute.; solution: `open`

## Added tests

- No test evidence recorded.

## New rules

- `child-node-readback-regression`: line experience occurrence(s)=1
- `formal-cli-worktree-import`: line experience occurrence(s)=1
- `formal-event-vocabulary`: line experience occurrence(s)=1
- `git-worktree-index-permission`: line experience occurrence(s)=1
- `typed-child-lookup-allowlist`: line experience occurrence(s)=1

## Future guidance

- Align a typed child-node lookup allowlist with every server-owned effect that the route is contractually required to resolve; preserve bounded projection and lineage checks.
- Keep successful child-node readback as a production regression and do not turn a real 404 into a test-only compatibility expectation.
- Run formal CLI operations with the current worktree backend first when linked virtual environments expose another workbench module.
- Use the authorized elevated environment for git index operations when the shared worktree metadata is outside the default write sandbox.
- Validate formal event vocabulary against the live schema before appending a gate record.
- When a dedicated high-risk operation produces a server-owned typed data effect, add only that explicit operation to the lineage readback allowlist.

## Event index

- #1: `9307d4ea-04ad-4184-bcaf-50366d056096` | 2026-08-21T07:06:47.718Z | STATE_CHANGE/line_started | incident=`c7c3923d-2bb2-437f-a203-a991a53bd15b` | lesson_key=`frozen-context-before-start` | event_sha256=`79ff08b70a5f5676350d0e61e7c9c8f36bb7c9ac6458b816698e6f74a3b5f318`
- #2: `b424373b-312c-4b8b-a5c5-2e1e8c35a1c5` | 2026-08-21T07:22:05.586Z | FAILURE/route_contract_red | incident=`49c38d31-8c8d-4a77-90db-4c10c1656d38` | lesson_key=`child-node-readback-regression` | event_sha256=`e7b50433dddbc72b516129cb86ef283a9cc6bf44aa5feb3430892b2913ca0e20`
- #3: `c1c705c7-63b3-4ddf-b41d-5bff4f6fead2` | 2026-08-21T07:22:19.651Z | GAP/code_execute_child_lookup_allowlist | incident=`cfd210e9-30a7-46f5-9e6f-598944f7a4c3` | lesson_key=`typed-child-lookup-allowlist` | event_sha256=`f68493f2fe5ece9bbfd6b02e772e9c03bb097deab5aee6e89bf670dee563dec3`
- #4: `dc01b65e-35c7-4411-8d51-4fb667c0e2d7` | 2026-08-21T07:22:33.581Z | ERROR/formal_cli_import_path | incident=`b48ca8e5-5a0e-4f6c-bd1e-82ebc47d04bf` | lesson_key=`formal-cli-worktree-import` | event_sha256=`547781498cb9f087c3dbfc180c2b6b93960ef9be6b4ddb63c1742b0f1668fbc5`
- #5: `6c728823-2e4f-4dc7-86c9-7a7b17c7a918` | 2026-08-21T07:24:04.590Z | STATE_CHANGE/context_rescope_required | incident=`f781d753-de00-4456-9fcc-39df584877a6` | lesson_key=`context-pack-rescope` | event_sha256=`d1e761f95446384fc17bd3a23adda6238d3ea379292f4c32767155fdb3716f17`
- #6: `a7d7f16b-cb38-4837-a14d-d7ce2047c3ed` | 2026-08-21T07:24:04.594Z | STATE_CHANGE/context_rescoped | incident=`3203cabc-5664-4155-a270-ec6f11e26a77` | lesson_key=`context-pack-rescope` | event_sha256=`0759d6c19d36975a729bff1d1cb7d1ba9b00f341cd98f63698eb31d9b1c0680c`
- #7: `cd697df5-7c05-47e4-8f51-a52df7831ed5` | 2026-08-21T07:24:45.972Z | STATE_CHANGE/context_rescope_required | incident=`a6809693-6ede-4855-8cc1-0877d275ab6c` | lesson_key=`context-pack-rescope` | event_sha256=`53e8dd931283c78a8856f7aa71926e1196857b6405fdaf780de7ba179a02e197`
- #8: `ec778a2c-4d36-48c5-89ad-0404584cf157` | 2026-08-21T07:24:45.977Z | STATE_CHANGE/context_rescoped | incident=`78adcee9-c0fc-4f53-9dd9-2e446daed45b` | lesson_key=`context-pack-rescope` | event_sha256=`22fc2aab612d97faf4f8630ee21f72ecb4f0e923413598d5c1cd1feea1d8bae9`
- #9: `31cb5b9e-9bc6-4b19-a28a-0a664198f3db` | 2026-08-21T07:26:47.587Z | GATE/scoped_route_suite_green | incident=`77f82653-887d-4c76-991a-29c7b915b8b6` | lesson_key=`scoped-route-gate-green` | event_sha256=`af71e7bff9f6fb96cd2168cee8c65207ddfc3ed3ae13c936a57d66eaf4e9f2b1`
- #10: `e50cbe8e-04f1-4c52-b1a0-2a736a01271f` | 2026-08-21T07:26:51.013Z | REVIEW/typed_child_allowlist_fix | incident=`c1e15f74-c0d2-4536-bdae-eb0bc6808bec` | lesson_key=`explicit-lineage-operation-allowlist` | event_sha256=`ea934516fa0cabfa4fac8380ae219e61369fe454ed59214dd13eff1c415c3f89`
- #11: `c0c10492-df9f-4c5f-8f89-592ce22b83f4` | 2026-08-21T07:27:09.695Z | ERROR/formal_event_schema_rejected | incident=`b9b1fe1d-6b56-4cb8-8d6b-2bb6d75fe9cc` | lesson_key=`formal-event-vocabulary` | event_sha256=`b2736ab90dfca7d9348ce361ff91cb59e201f103c5e28cf8b5c8e0ee99e4cb52`
- #12: `f0458878-e066-4c7d-bc1d-f0fd19e44a95` | 2026-08-21T07:27:58.009Z | STATE_CHANGE/line_completed | incident=`ba1caad2-2d72-46a9-a813-cbb9e7e78a92` | lesson_key=`line-completion-evidence` | event_sha256=`d5eab51b60cde4081dfe8b35a8a89376f31bf062eacf06aabfe4d4958821373f`
- #13: `4b6e7588-78b0-4fab-a858-f39e7e7db0ed` | 2026-08-21T07:29:29.224Z | ERROR/git_index_permission | incident=`e51bd0c0-b4f1-4b2b-a9c2-a76f4d7d1db2` | lesson_key=`git-worktree-index-permission` | event_sha256=`2d05affdc2853b82fcd1b5caf043c6720be0ff64c91b5010962296f1ef8ef0c4`
