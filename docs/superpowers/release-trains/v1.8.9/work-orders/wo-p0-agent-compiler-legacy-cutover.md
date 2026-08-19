# Work Order — Agent Compiler C0 Legacy Authority Cutover

## Scope

Migrate only the Agent Compiler downstream callers in `plan_compiler.py`,
`planning_contracts.py`, and the compiler replay seam. Do not modify contract
lock files, Workflow Truth, Evidence Core, frontend, or other lanes.

## Sequence

1. Add red tests proving the production compiler has no retired issuer
   dependency, `planning_contracts` does not export it, and unavailable or
   malformed host compiler results fail closed.
2. Define the narrow typed host compiler port/result boundary in the agent
   package, with no local authority implementation.
3. Remove the `ServerCompilationRecordIssuerV1` import/instance/stage calls from
   `PlanCompiler`; route compilation through the injected port or return the
   typed integration-required failure.
4. Keep replay-store validation strict and update compiler fixtures to use a
   test-only adapter without widening the production authority surface.
5. Run the frozen focused tests, compileall, and `git diff --check`; record
   production host integration as `NOT VERIFIED`.

## Exit condition

No production source in the affected compiler lane directly constructs,
invokes, or re-exports the retired issuer. Tests prove the fail-closed seam and
all requested local gates pass. No commit, merge, push, or tag.
