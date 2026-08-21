# Work Order: P0 truth-regression closure

## Objective

Close stale P0 workflow-truth fixtures after the v1.8.9 typed report and
canonical artifact-index cutovers.

## Allowed change

Only `tests/test_v189_workflow_truth.py` and the formal objective/work-order
records for this line may change.

## Verification

```bash
PYTHONPATH=backend:tests .venv/bin/pytest tests/test_v189_workflow_truth.py -q --disable-warnings
```

## Known not-verified gates

Production host injection, browser acceptance, real external provider,
cross-process deployment, full repository gate, and release integration remain
outside this line.
