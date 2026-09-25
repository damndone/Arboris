# Retrospective — v1-8-9-p0-central-evidence-projection-closure

## Goal

# v1.8.9 Central Evidence Consumer Mount Objective  ## Objective  Mount the already-persisted, typed v1.8.9 evidence into the real central Agent, Notebook, and Report consumer paths. The central surfaces must read a server-owned evidence envelope and its receipt, project only the consumer contract, and return \`UNAVAILABLE\`/\`DEGRADED\` when the evidence is missing, stale, foreign, or unverifiable. They must never reconstruct statistical results from raw model-result JSON or infer a result from labels.  ## Required behavior  1. A central run-detail request is bound to server-observed actor, project,    session, run, model-run, and confirmation identity before it reads a    projection. 2. Agent and Notebook result tools use the same typed persisted-evidence    source and the same projection registry. A natural-language request may    choose the consumer surface, but cannot choose a filesystem path, raw    result packet, provider callable, or alternate model result. 3. Report view-model and export routes consume only the owner-admitted typed    projection and receipt. If the artifact hash, receipt, registry, or scope    is invalid, the response is an explicit unavailable/degraded packet rather    than a guessed table or recalculated statistic. 4. Existing compatibility fields remain visibly non-authoritative until they    are backed by the typed evidence projection. No second capability table or    consumer-specific statistical calculation is introduced. 5. Tests cover the same path for Agent, Notebook, and Report, including    missing/stale/foreign evidence, forged identity, malformed digest, raw    model-result fallback, and positive persisted-evidence rendering.  ## Non-goals  - No new estimator/model family or statistical formula. - No native \`.sav/.zsav/.dta\` dependency work. - No browser/provider/cross-process/full-gate/release claim unless separately   executed on the candidate SHA. - No migration of the legacy \`prediction.py\` classification entrypoint in   this line; that is a separate typed host-port production migration.  ## Acceptance boundary  Focused central consumer tests may prove the server route/service/view-model join. Browser-visible acceptance, real provider startup, cross-process authority persistence, full repository gate, and release readiness remain \`NOT VERIFIED\` until explicitly run.

## Final status

COMPLETED

## Metrics

- Failure frequency: 2/15 (13.3%; 13.3 per 100 events)
- Repeat rate: 0/2 (0.0%)
- Recurrence rate: 0/2 (0.0%)
- MTTR: median=0 ms (sample=1; unresolved=1)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: 0/4 (0.0%)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- #3 2026-08-21T18:56:29.481Z `scoped_suite_socket_permission`; cause_status: `external`; cause: The first exact scoped-suite invocation could not bind the repository authority harness Unix socket in the sandbox and reported Operation not permitted; the same suite was rerun with the required temporary-socket permission.; resolution: `mitigated`; lesson: Treat sandbox authority-socket failures as environment evidence and rerun the exact gate with the required permission before judging the implementation.
- #10 2026-08-21T19:36:19.112Z `report_envelope_contract_repair`; cause_status: `known`; cause: The first production envelope adapter used reason-code strings and an invalid blocked validation/completeness combination; EvidenceEnvelopeV1 rejected those states before the final fail-closed mapping was repaired.; resolution: `resolved`; lesson: Derive every persisted envelope field through the existing EvidenceEnvelope contract, including reason objects, empty fact validation summary, and blocked completeness.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- `report-envelope-status-must-follow-contract`: occurrences=1; cause_status: `known`; root cause: The first production envelope adapter used reason-code strings and an invalid blocked validation/completeness combination; EvidenceEnvelopeV1 rejected those states before the final fail-closed mapping was repaired.; solution: `resolved`
- `scoped-authority-socket-environment-gate`: occurrences=1; cause_status: `external`; root cause: The first exact scoped-suite invocation could not bind the repository authority harness Unix socket in the sandbox and reported Operation not permitted; the same suite was rerun with the required temporary-socket permission.; solution: `mitigated`

## Added tests

- No test evidence recorded.

## New rules

- `report-envelope-status-must-follow-contract`: line experience occurrence(s)=1
- `scoped-authority-socket-environment-gate`: line experience occurrence(s)=1

## Future guidance

- A consumer may render only server-issued typed facts with exact actor, project, session, scope, run, model, artifact, and projection bindings.
- Derive every persisted envelope field through the existing EvidenceEnvelope contract, including reason objects, empty fact validation summary, and blocked completeness.
- Treat sandbox authority-socket failures as environment evidence and rerun the exact gate with the required permission before judging the implementation.

## Event index

- #1: `c9f794f1-e288-4233-b91a-13748af6e0b9` | 2026-08-21T18:31:47.693Z | STATE_CHANGE/line_started | incident=`f4c06aa9-8e81-42b3-936f-bfa327badd63` | lesson_key=`frozen-context-before-start` | event_sha256=`415671942c0f5f82aba313512c3b8dc28361cd8648ca380a0d8d83f8a21a8b5a`
- #2: `52b3c9f5-6f4f-4b9d-9c65-74c5c2e19d7f` | 2026-08-21T18:56:07.650Z | GATE/tdd_red | incident=`9d2cc936-4d2a-4f85-94c1-a8d8c1b8fd4a` | lesson_key=`central-evidence-red-before-implementation` | event_sha256=`45da24e346624cbce477ed2e8a5b10e06948c99f64b0bc2442a1c1c25355817e`
- #3: `a40f37f1-9b4a-43f7-b8aa-3b9b0a4a6d4e` | 2026-08-21T18:56:29.481Z | ERROR/scoped_suite_socket_permission | incident=`f2f8d97b-bb2b-4d76-a951-4a8484cfa8ca` | lesson_key=`scoped-authority-socket-environment-gate` | event_sha256=`e56891dae2c1f4bb5f2e88b0eadd994895d37723fb5b1271854fcea09b9a3853`
- #4: `17a3b6c2-20be-4c75-a76a-93e1d9f33a0b` | 2026-08-21T18:58:19.093Z | GATE/scoped_suite_green | incident=`bd4f5d4d-d0c4-4c3a-8f7d-fba3b6d3e76d` | lesson_key=`central-evidence-scoped-green-boundary` | event_sha256=`eea236f3bcfea8bb5b86900984dc0313bbf083ae3d320bccdecc122b1ec67885`
- #5: `16a4bf84-f28f-4a85-a629-b0fc2b8caea4` | 2026-08-21T19:09:59.133Z | STATE_CHANGE/context_rescope_required | incident=`e0a9c12c-a028-4ddd-aa8f-c459c19ca84a` | lesson_key=`context-pack-rescope` | event_sha256=`8df11e9bbf2a611fd1de91bc202ac2a2d6c3edb900e13c32e6bb0a3a432c3a15`
- #6: `0ba9b1b4-1c4e-4e59-b63c-c2af83d1ba22` | 2026-08-21T19:09:59.138Z | STATE_CHANGE/context_rescoped | incident=`cb4e8d23-6785-430b-9da8-eac6367d6680` | lesson_key=`context-pack-rescope` | event_sha256=`d5c9930eca6d4b2c1034189f8b83705b8e56ef25581a2502fabcd8b0038b35a8`
- #7: `f8443fd7-ecc9-430c-9fb0-7bd7f8fa1915` | 2026-08-21T19:15:18.609Z | STATE_CHANGE/context_rescope_required | incident=`dd5c39dd-c41a-4a7a-b32c-caef3d82d04e` | lesson_key=`context-pack-rescope` | event_sha256=`0188106182e11798534fba43726bb82d52c325af0513798c3c6a85359dc30559`
- #8: `cf3febd2-dd4a-4a73-96d6-cea819871d6c` | 2026-08-21T19:15:18.616Z | STATE_CHANGE/context_rescoped | incident=`d13359c9-ae90-400f-910e-932ed43b7e41` | lesson_key=`context-pack-rescope` | event_sha256=`6d5cfb2189afd4b632d24315c101d62471368477a6085f2f6f1940d94fbbe218`
- #9: `f6b498ba-71e1-48a1-b0f2-ae3d87c3f2dd` | 2026-08-21T19:36:19.000Z | GATE/expanded_p0b_tdd_red | incident=`9f7164f6-08ee-4f37-90b7-e5cdd1122b70` | lesson_key=`expanded-central-evidence-red-before-implementation` | event_sha256=`2775f2e3aa74e099455bb477f40079d2ef155b3711ec24f8aa48094bb147a776`
- #10: `e7080f6b-bc23-4daa-a6ad-b09b6eaeec64` | 2026-08-21T19:36:19.112Z | ERROR/report_envelope_contract_repair | incident=`2feecf87-a819-4f1f-92a0-4b80de6db7c2` | lesson_key=`report-envelope-status-must-follow-contract` | event_sha256=`f207892cdb1ee2a8f0cdfc275a51de432fdc95ad25772b68df39cee940e905b9`
- #11: `c8b28c3e-08c2-4849-8e57-a77cdcdf23c0` | 2026-08-21T19:44:06.543Z | STATE_CHANGE/context_rescope_required | incident=`e9a88e0b-5ff5-4a1e-8806-eaa87792388f` | lesson_key=`context-pack-rescope` | event_sha256=`b4007fa2396b18148822f737bc6c5f99520a8986ebc0c08c7e57b61e93d55be2`
- #12: `5898822c-64af-4f10-8d5f-644bd708eabf` | 2026-08-21T19:44:06.551Z | STATE_CHANGE/context_rescoped | incident=`de86c3ea-4612-416d-b13c-4339ee76f60e` | lesson_key=`context-pack-rescope` | event_sha256=`82fe92a0e70ab4d42ee274c43bcc7abb614599a3e24917adef78f40290cc3bd1`
- #13: `a8e0af27-7a55-4a1e-95e7-3fe1f9c7b6a4` | 2026-08-21T20:40:34.038Z | REVIEW/p0_b_central_projection_review_green | incident=`6b9adf20-0c70-4ba1-a7f6-bb5db90a5d41` | lesson_key=`central-evidence-consumer-boundary` | event_sha256=`2689a95ca3de136008aa464349c1e418220a41adaa0e9e568ace1a0448ac638d`
- #14: `e8d7c6b5-a4f3-4210-9edc-b8a7f6e5d4c3` | 2026-08-21T20:41:29.390Z | GATE/p0_b_matrix_green | incident=`6b9adf20-0c70-4ba1-a7f6-bb5db90a5d41` | lesson_key=`p0-b-gate-evidence` | event_sha256=`1fb255efcd485535d112fc76bb7463c38a2ac234537d54c9d47b0326890d7073`
- #15: `b2c3d4e5-f6a7-4890-9123-4b5c6d7e8f90` | 2026-08-21T20:42:33.794Z | STATE_CHANGE/p0_b_completed | incident=`6b9adf20-0c70-4ba1-a7f6-bb5db90a5d41` | lesson_key=`p0-formal-closeout-boundary` | event_sha256=`af9ccd22414c2c017f68f7466c7e219784edd18fac07bf04448ca05e5f6c15cc`
