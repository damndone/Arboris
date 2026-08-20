# v1.8.9 P0 model-branch Resume implementation plan

Formal line: `v1-8-9-p0-model-branch-resume`

## Sequence

1. Read the frozen Context Pack, global rules and prior Resume/evidence
   retrospectives; map the actual `WorkflowStepResult` producer, state store,
   resume validator and model-genesis child-run path.
2. Add RED tests for canonical `output_bindings["model_branches"]` round-trip,
   canonical-first consumer selection, missing-binding migration/availability
   behavior, and branch-aware child idempotency.
3. Implement the smallest adapter over the existing typed state and evidence
   admission contracts. Preserve legacy aliases only behind an explicit
   compatibility path.
4. Run focused tests plus the existing Resume/authority suites, then inspect
   the complete diff for raw mapping/path/authority escapes.
5. Record exact test counts, remaining cross-process/central/browser gates,
   formal retrospective and verification in the handoff.

## Safety invariants

- No callback or client-supplied mapping can mint a branch, run, artifact or
  evidence reference.
- No missing branch binding is silently converted to `{}` for a completed
  model step.
- Resume reuses the server-owned branch execution key and does not rerun a
  completed child merely because the parent completion write was interrupted.
- Existing artifact digest, owner/process, compiler receipt and evidence
  admission checks remain mandatory.
