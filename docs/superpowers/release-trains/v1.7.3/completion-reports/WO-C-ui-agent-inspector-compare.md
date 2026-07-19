# WO-C completion report — UI Agent Inspector / Compare

## Decision

**Local candidate approved.** This report records a WAVE-1 lane candidate only;
it authorizes neither cross-lane integration nor a remote/release action.

## Identity and contract

- Lane branch: `feat/v173-ui-agent-inspector-compare`
- C1.1 immutable start: `0251f0a30d984bdbb2cfab404e6c646deab60cae`
- Approved code candidate: `670b960a83696201b77212c8da5e15c7dce7ce6a`
- Contract receipt: `f25ffd119df91479aabfcebcb549a47a1153e227`
- Governed boundary: PacketEnvelope v1.0 with
  `contract`, `contract_version`, `producer_version`, and `payload`.

## Delivered lane behavior

- Packet-only repeated-measures view model for result, diagnostic/recovery, and
  comparison facts. The UI neither estimates statistics, selects a winner, nor
  executes a rerun.
- Strict fail-closed packet cloning: descriptor-only reads reject accessors,
  prototypes, symbols, sparse arrays, cycles, aliases, malformed envelopes,
  and unknown contracts.
- Resource limits: maximum depth 32, nodes 10,000, key 4 KiB, value string
  64 KiB, and total UTF-8 JSON serialization 512 KiB.
- Frozen trajectory `FigureContext` uses `time` and `groups`; unsupported
  `series` shapes are rejected. A group label is rendered once with `rowSpan`,
  so time rows cannot multiply server-controlled label output.
- Full result and four-layer Compare facts are rendered as server facts,
  including `schema_version` and `inference_method`.

## Evidence

- Independent quality and specification reviews approved exact candidate
  `670b960a83696201b77212c8da5e15c7dce7ce6a`; both audited C1 ancestry,
  protected files, packet bounds, canonical fixtures, and fail-closed paths.
- Fresh focused frontend verification passed:
  `8` Vitest files, `101` tests; `npm run typecheck`; and
  `git diff --check`.
- Fresh full frontend verification was intentionally recorded, not masked:
  `138/139` test files and `1249/1250` tests passed. The sole failure is
  outside WO-C in `src/runResult/FailureCard.test.tsx`: its assertion expects
  `{ model_type: "auto" }` but receives the existing
  `{ model_type: "auto", model_options: {} }` shape.
- Existing React `act(...)` warnings occurred during the focused suite; they
  did not fail a test and are not changed by this lane.

## Deliberate limits and integration prerequisites

- No central route/runtime wiring, cross-lane cherry-pick, merge, push, PR,
  tag, or release was performed.
- Browser acceptance has not been performed; packet fixtures and component
  tests are not a claim of live API/browser acceptance.
- WO-B remains blocked pending a governed, versioned public adapter from the
  LMM packet to legacy runtime consumers and a single frozen FigureContext
  producer/consumer shape. WO-C must not compensate for that mismatch.
- WO-D must evaluate an exact later integration candidate; this lane approval
  is not an evaluation acceptance for an integrated release.

## Rollback

Before any future integration, drop this lane candidate. After a future
authorized integration, revert the WO-C code range from
`ea11be0` through `670b960` as a single lane rollback, then rerun the focused
packet/UI checks above. This report commit is administrative evidence and is
not a runtime dependency.
