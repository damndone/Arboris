# Retrospective — local-contained-execution

## Goal

# Local Contained Development Mode — design  ## Status and decision  **Approved for planning; not implemented yet.**  The target macOS host has now demonstrated that Seatbelt is usable from its native Terminal: \`sandbox-exec\` launched successfully, the sandbox and \`code.execute\` suite passed (33 tests), and the native full gate reported \`GATE PASSED\`.  The earlier \`sandbox_apply: Operation not permitted\` result describes the nested Codex-managed environment, not the user's Mac.  The product therefore gains an explicitly selected local-development profile: \`local_contained\`.  It is not a relaxed or unsandboxed mode.  It enables the locally useful LMM flow, keeps \`code.execute\` behind the existing OS sandbox, and requires a fresh local canary before high-risk execution is admitted. It does **not** create C2 candidate-evaluation evidence or weaken C2's frozen exact-Git, trusted-runtime, hostile-ingestion, and independent-verdict rules.  ## Goals  1. A normal start remains fail-closed for LMM execution, exactly as today. 2. Each local-development start must opt in explicitly to    \`local_contained\`; no configuration file, prior run, or browser state may    silently re-enable it. 3. Under \`local_contained\`, the registered LMM pack may execute in the local    Workbench process after its existing sealed-input and persistence admission    checks.  It is labelled local-development execution, never C2 execution. 4. \`code.execute\` remains a separately sandboxed, typed high-risk operation.    \`local_contained\` requires an actual Seatbelt/Bubblewrap canary before it    may be used; a discovered binary, unit-test fake, or environment variable    alone is insufficient. 5. Every run records the selected profile and the resulting UI/API state makes    the active profile visible.  Records from this profile cannot satisfy C2 or    release-evaluation gates.  ## Explicit startup contract  The supported local entry point is a checked-in launcher:  \`\`\`bash ./scripts/run-local-contained.sh \`\`\`  It exports \`WORKBENCH_EXECUTION_PROFILE=local_contained\` only to the launched Workbench process.  The server parses this value through a closed enum:  | Value | Meaning | | --- | --- | | unset or \`default\` | LMM remains rejected with \`LMM_FROZEN_CONTAINMENT_REQUIRED\`; no local capability is active. | | \`local_contained\` | Startup runs the local containment canary.  A passed receipt admits local LMM and enables the existing sandboxed \`code.execute\` path. | | any other value | Startup fails with a structured invalid-profile error. |  The launcher must never write a persistent shell profile or an application settings file.  Closing the process ends the opt-in.  Direct users of Uvicorn may set the same variable deliberately, but receive the same startup canary; the environment value alone is not an admission capability.  ## Components and data flow  \`\`\`mermaid flowchart LR     Start["Explicit local launcher"] --> Profile["ExecutionProfile\nclosed enum"]     Profile --> Canary["OS sandbox canary\nreal Seatbelt/Bubblewrap"]     Canary -->|pass| Local["local_contained capability\nprocess-local"]     Canary -->|fail| Stop["Startup rejects\nno high-risk admission"]     Local --> LMM["LMM fixed model pack\nsealed input + pinned persistence"]     Local --> Code["code.execute\nexisting OS sandbox"]     Profile -->|default| Reject["LMM remains fail-closed"]     LMM --> Record["run manifest\nexecution_profile=local_contained"]     Record -. "never C2 evidence" .-> C2["future release C2\nfrozen snapshots + independent verdict"] \`\`\`  ### Execution-profile service  Add a small backend-owned \`ExecutionProfile\` service.  It owns parsing, startup admission, immutable process-local status, profile-specific structured errors, and a serializable safe status view for \`/health\`.  It must not accept request parameters, browser input, or a per-run override.  Its only active capability is constructed after the canary returns a passed receipt.  The service publishes only these safe facts: \`profile\`, \`lmm_admitted\`, \`high_risk_code_admitted\`, and \`canary_status\`.  It never exposes a rendered sandbox profile, host paths, child environment, or internal capability token.  ### Local containment canary  The canary is separate from C2 and intentionally narrower.  It exercises the same \`run_python_sandboxed\` production path that \`code.execute\` uses and must prove all of the following on this process start:  * a fixed harmless script runs successfully; * a write outside its declared output directory is denied; * network access is denied; and * its declared output directory is writable.  Missing backend, profile-application failure, malformed output, timeout, or any failed assertion yields \`LOCAL_CONTAINMENT_CANARY_FAILED\`.  The server does not start with \`local_contained\` active in that case.  Existing \`code.execute\` still independently fails closed if its own sandbox invocation later fails.  ### LMM admission  Replace the unconditional LMM rejection at both shared entry boundaries (\`run_service\` and direct synchronous orchestrator invocation) with one profile-owned \`require_lmm_local_or_c2_admission\` decision:  * default profile retains \`LMM_FROZEN_CONTAINMENT_REQUIRED\` before upload or   run creation; * passed \`local_contained\` permits the existing fixed LMM pack to continue   through its sealed-input, model-options binding, and pinned-persistence   state machine; and * a future C2 integration adds a third admission source without changing the   local profile's truth claim.  The local LMM path does not execute caller-provided Python, shell commands, or untrusted package paths.  It invokes the already registered, fixed \`linear_mixed_effects\` pack using the Workbench interpreter.  This is adequate for local development, but is explicitly not the separate hostile-candidate evaluator promised by C2.  ### Provenance and presentation  Each admitted local LMM run writes an immutable manifest fact:  \`\`\`json {   "execution_profile": "local_contained",   "containment_evidence": "local_startup_canary",   "release_evaluation_eligible": false } \`\`\`  The health response exposes the profile status.  The frontend shows a persistent non-dismissable local-development banner when the profile is active, explaining that LMM is locally enabled and the run is not C2/release evidence.  It shows no banner in the default profile.  ## Errors and safety invariants  * \`LMM_FROZEN_CONTAINMENT_REQUIRED\` remains the default-profile error for   compatibility with existing clients and tests. * \`LOCAL_CONTAINMENT_PROFILE_INVALID\` is a startup configuration error. * \`LOCAL_CONTAINMENT_CANARY_FAILED\` contains a bounded reason but no host path,   profile text, or secret-bearing environment detail. * A failed canary cannot fall back to host Python, disable the existing   \`code.execute\` sandbox, or create an LMM run. * A local receipt is process-local and dies with the server.  It cannot be   serialized, replayed, supplied by a client, or copied into C2 evidence. * C2 policy code is not modified to accept user-owned virtualenvs or this   local profile.  C2 remains independently fail-closed until its exact-host   policy and fresh canary requirements are met.  ## Test and acceptance plan  1. Unit tests prove closed parsing, default rejection, invalid profile refusal,    canary failure refusal, and successful local admission only after a passed    canary. 2. Integration tests prove both LMM entry boundaries retain the pre-materialize    rejection by default and permit the sealed LMM lifecycle only under an    injected passed local profile. 3. Sandbox tests run the real canary assertion harness where Seatbelt is    available; deterministic fakes cover non-native CI paths without claiming    host acceptance. 4. HTTP tests prove health exposes safe status and local LMM manifests carry    non-release provenance. 5. Frontend tests prove the banner appears only for active local mode. 6. On the native Mac, run targeted profile/LMM/code-execute tests, then    \`WORKBENCH_PYTHON=/Users/jiayuanren/项目规划/.venv/bin/python bash scripts/gate.sh --full\`.    Record the exact result in the release ledger and the formal FMS event    stream.  Browser acceptance must submit an LMM run in this explicit mode    and inspect its result/provenance; it may not call the result C2 evidence.  ## Non-goals  * No relaxed \`local_trusted\` or unsandboxed \`code.execute\` switch. * No persistent opt-in, browser-side opt-in, or request-side override. * No generic arbitrary-package execution. * No assertion that local LMM output, the local canary, or the full local gate   is a C2 verdict or release sign-off. * No change to the C2 trusted-runtime ownership rules.

## Final status

CLOSED

## Metrics

- Failure frequency: N/A (sample=0)
- Repeat rate: N/A (sample=0)
- Recurrence rate: N/A (sample=0)
- MTTR: N/A (sample=0; unresolved=0)
- Review churn: changes_required=0; average_review_round=N/A (sample=0); withdrawn=0
- Spec churn: N/A (sample=0)
- Plan churn: N/A (sample=0)
- Gate waste rate: N/A (sample=0)
- Same-state retry rate: N/A (sample=0)
- Token waste: N/A (sample=0)

## All failures

- None recorded.

## All errors

- None recorded.

## All gaps

- None recorded.

## All waste

- None recorded.

## Root causes and solutions

- None recorded.

## Added tests

- No test evidence recorded.

## New rules

- No rule candidate recorded.

## Future guidance

- No guidance recorded.

## Event index

- #1: `50f86f5a-c116-47f6-afae-489540795e0d` | 2026-07-20T05:02:45.927Z | STATE_CHANGE/line_started | incident=`45d254e3-312b-4b7b-b37a-eab9b7975ca6` | lesson_key=`frozen-context-before-start` | event_sha256=`4d46e382c77ea45dbcb1fb0244666243ce23e691909ca5fc15e5077c3229aa93`
- #2: `f6a0fd21-5731-4711-8da3-f12ca0e4c213` | 2026-07-20T05:20:43.176Z | STATE_CHANGE/context_rescope_required | incident=`64a05565-d530-4a82-86cf-641b5f7ef570` | lesson_key=`context-pack-rescope` | event_sha256=`9b07ae743358cf48247f6cf771c1661a1b6da599a59af408a3f498395ff5f8ba`
- #3: `4e4a6d59-08d5-463c-8151-ba8b7c2fc362` | 2026-07-20T05:20:43.180Z | STATE_CHANGE/context_rescoped | incident=`887ab071-8d4c-470b-a190-23692bbe78d5` | lesson_key=`context-pack-rescope` | event_sha256=`9a0b85683e52c8d8eb61cd1525af91e08257f435401337ef777f6be9815fbc3b`
- #4: `9044560d-603f-43a6-b71e-c324384fc89d` | 2026-07-20T17:44:54.000Z | STATE_CHANGE/local_contained_accepted | incident=`338e9e9f-551f-4de7-b26b-e95f775914a1` | lesson_key=`assembled-line-state-closeout` | event_sha256=`c90a51a694ac3364d649a8e7381c96d2b0240a6036213924459d2ff260ded7a2`
