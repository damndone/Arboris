# OLS `model_options` contract implementation plan

## Goal

Make an OLS run eligible for Notebook run projection and typed `model.rerun`
proposals without weakening the existing OLS covariance semantics. The
canonical Agent patch is:

```json
{"model_options": {"covariance": "unadjusted"}}
```

The accepted values are `robust`, `clustered`, and `unadjusted`. `clustered`
still requires the existing OLS cluster field (`entity_col`) at execution;
the contract must fail closed if that field is absent.

## Boundaries

- Preserve the existing top-level `covariance` form field and its Draft/RunForm
  control for human users.
- Treat nested `model_options.covariance` as the Agent-owned patch channel.
- When both channels are present during execution, the validated nested OLS
  option is the effective Agent choice; persist the effective covariance in
  the legacy top-level execution metadata so no stale robust default can hide a
  changed option.
- Keep `model_options_binding` server-owned and retain the existing hash and
  owner checks.
- Do not implement `statistical.explore`, `operation.multi_step`, or the
  broader one-sentence assignment workflow in this slice. Those remain a
  follow-up development slice.

## Implementation steps

1. Add an OLS model-options contract module with a strict covariance validator,
   stable contract version, and an effective-covariance resolver.
2. Register the validator and `ModelOptionsContract` on the OLS handler.
3. Publish an OLS `model_options` capability entry and Agent option vocabulary;
   update Notebook planning validation/remediation so OLS is no longer
   hard-coded as unsupported.
4. Preserve nested OLS options through Genesis materialization and make the
   rerun/Genesis/orchestrator path derive the actual `_covariance` from the
   validated nested option. Ensure persisted run inputs and contract metadata
   reflect the effective choice.
5. Keep OLS covariance visible as the existing select in Draft/Operation UI;
   do not render the opaque Agent envelope as a second malformed control.

## Verification

- Backend tests cover accepted/rejected OLS options, binding ownership,
  capability/catalog eligibility, nested-to-execution covariance propagation,
  clustered fail-closed behavior, and Genesis materialization preservation.
- Frontend tests cover that an OLS Draft/Operation surface still renders the
  human covariance select without rendering a duplicate opaque envelope.
- Run the focused backend suites, frontend tests and TypeScript check. The full
  repository gate is run serially once after targeted checks; any environment
  limitation is recorded separately from product failures.
