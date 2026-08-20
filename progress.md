# remediation-5 progress

## Baseline and RED

- Reused the existing remediation-5 objective/formal line; no second `start`
  was run. Exact baseline HEAD:
  `f82758736adabd80d3d9dcb03b317f86c221f27a1`; parent:
  `c59999695bd4af5d941f77ad2dd53841ae2641a1`.
- Forged Mapping view/render probes were RED on the baseline: the view was
  `available` and legacy rendering reached the writer seam. The default valid
  owner probe hit the known Unix authority socket permission boundary.

## GREEN and package-local gate

- `build_report_view_model` now admits only the owner-issued typed Report
  projection after C0 owner/proof/receipt/canonical evidence validation.
- Legacy HTML delegates through the owner-issued document writer; formal HTML
  revalidates ownership before template or filesystem IO.
- Forged Mapping/render and forged `object.__new__` HTML writer probes prove
  `write_bytes_durable` and `register_artifact` are not called. The controlled
  valid owner path renders successfully.
- Controlled backend Evidence/Report/event focused suite: `114 passed, 1
  warning`; strict event pair: `17 passed`.
- Frontend focused suite: `3 files, 50 passed`; frontend typecheck,
  compileall, and `git diff --check` passed. React `act(...)` warnings remain
  test-harness warnings; no test failed.

## Formal closeout

- Formal events include RED, GREEN, GATE, resolution of the RED incident, and
  `STATE_CHANGE STARTED -> COMPLETED`; retrospective/verify must report
  `unresolved=0`.

## Remaining gates

Browser, provider, central, production live-host, full repository gate,
release, merge, push, tag, deployment, and browser-visible acceptance remain
`NOT VERIFIED`.
