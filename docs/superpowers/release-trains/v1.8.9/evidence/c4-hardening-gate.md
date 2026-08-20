# Workbench v1.8.9 C4 hardening candidate evidence

## Decision

The exact product candidate is `43578a90a8f224649f27c9d1bc816439f6b21d3d`.
The candidate is suitable for the next controlled host/browser/provider gates,
but it is not a release candidate: candidate-bound acceptance is `BLOCKED`
because four required frontend acceptance files belong to the sidecar harness
and are not present in the product candidate. The backend candidate-bound
path passed.

## Serial integration

The integration worktree started from the exact C3 baseline
`05362b5697e10eb25fd219da003641f96eeec082` and retained the C0 contract lock
and C3 Agent/Notebook/Report foundation. The reviewed feature lines were
merged in this order:

1. P0 legacy/resume (`9270f7c0`, source tip `a2b51d5e2cad718795d2c739f10aee1c9fdca10f`)
2. P0 evidence/Report (`98d05a4f`, source tip `623ecfc0a8eed0e2d6665983584b9fdded38567f`)
3. P1 data consumer (`c735795e`, source tip `48964f575873fd8c73d0303c5c4dbab5e6bbec9d`)
4. P1 classification production (`f74ca125`, source tip `65233cc7a9b3b4c788a00c7488333675929bf5d2`)
5. P1 survey extension (`401e01c2`, source tip `c05b2df248656dac4dbb76d18cc90161ddee9834`)
6. integration-only legacy evidence download repair (`43578a90`)

The final repair preserves the strict artifact-index reader for normal listing
and accepts only the exact legacy classification-evidence index shape on the
download compatibility path. It does not read raw model results as a fallback.

## Product test evidence

Fresh tests on the exact candidate reported:

- classification contracts, split/leakage/protocol, production, consumer and
  evidence-report boundary: `240 passed, 5 warnings`;
- survey design/wiring/GLM/report visibility plus report view/export paths:
  `156 passed, 2 warnings`;
- Agent/Notebook cutover, artifact integrity, consumer projection, capability
  manifest, runtime bridge and classification production: `173 passed, 2 warnings`;
- frontend Report/Notebook evidence boundary and classification evidence:
  `4 files, 49 tests passed`;
- frontend TypeScript typecheck: passed;
- Python `compileall`: passed;
- `git diff --check`: passed.

These are package and integration tests. They are not browser, external
provider, host full-gate, or release evidence.

## Catalog and coverage

The live candidate catalog contains 7 providers and 15 declared consumer
coverage rows:

- catalog digest: `97cd7730bf1afefe8d9b33be17a81b434b3613b128e478fac3bf5d12ebb08420`;
- coverage digest: `771e983ae7172a0c467f04f4de69e3d9c00ec473ef03d1e0c8d54a7b872c3f9b`;
- 5 rows are covered by the registered consumer projection;
- 10 rows remain `BLOCKED` with `projection_ref_mismatch`.

The blocked rows are retained in the denominator. They are not silently
dropped and are not counted as supported Agent/Notebook/Report behavior.

## Candidate-bound acceptance

The sidecar harness tip is
`753f5405089aa8c88ee6f28cb16b2c47021e2618` and was loaded read-only against
the product candidate. The sidecar manifest is stored outside the product
worktree; its local run id is
`run-20260820T070540078025Z-d97915649ca1` and its SHA-256 is
`0eadd4bd575c0764b4b6d321fdb2e763310c6b77d6f66463d6d762cd973acc26`.

Observed result:

- candidate identity: exact SHA verified;
- backend acceptance: `PASS`;
- frontend acceptance: `BLOCKED` because these required sidecar files are not
  present in the candidate:
  `LineageRouteContainer.v189.test.tsx`, `NotebookRouteView.v189.test.tsx`,
  `ReportView.integration-v189.test.tsx`, and `evaluation/v189/status.test.ts`;
- matrix: 15 rows, 5 covered, 10 blocked, digest
  `21c9aadecdd05719669f3ef572f003e3e3b581df43349f68bb1310e495e1132a`;
- deterministic external provider: not requested, `provider_called=false`;
- browser: `NOT_VERIFIED`;
- host full gate: `NOT_VERIFIED`;
- release: `NOT_VERIFIED`.

The frontend product tests and typecheck pass independently, but they do not
substitute for the missing sidecar acceptance artifacts.

## Controlled host full gate

The release gate was run once on the exact candidate with:

```text
WORKBENCH_PYTHON=.venv/bin/python bash scripts/gate.sh --full
```

The gate did not pass. The frontend full suite completed with `197` files,
`1727` passed tests and `9` skipped tests; frontend typecheck also passed. The
backend full suite returned failures before the frontend stage. The first
reproducible failures were:

- ARMA–GARCH legacy tests passed an unbound report mapping to
  `render_html_report`, which now correctly requires a server-owned typed
  Report writer;
- a legacy consumer-projection test still monkeypatches the removed
  `_model_results` raw-result hook;
- analysis-loop lifecycle tests construct an orchestrator without the
  server-issued proposal-store capability, then access the intentionally
  unavailable public store;
- golden snapshots expect pre-cutover report artifacts and do not include the
  typed evidence-bound report failure state.

The last two categories are unchanged in the v1.8.8-to-candidate source diff;
the first, second and golden categories need owner-line test/consumer
migration. No raw-model-results fallback or unbound report writer was restored
to make the release gate green. Therefore the controlled host gate is recorded
as `FAILED`, and release remains blocked.

## Safety boundary

The candidate is not yet allowed to be described as “fully implemented” or
“released”. Historical Notebook routes and old workflow runtime paths still
need migration evidence; real provider and host identity configuration,
browser-visible acceptance, full host-gate, and release/tag evidence remain
separate follow-up gates.
