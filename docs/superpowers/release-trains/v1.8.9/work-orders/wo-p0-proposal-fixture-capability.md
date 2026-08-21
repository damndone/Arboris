# Work Order: v1.8.9 P0 proposal fixture capability migration

## Scope

Move only proposal-operation and dev-navigation fixtures from the retired
direct orchestrator mutation path to the existing server-issued capability.

## Owned paths

- `tests/test_agent_navigation_fixture.py`
- `tests/test_agent_operation_audit.py`
- `tests/test_agent_proposal_operations.py`
- `backend/workbench/dev_fixtures/agent_navigation.py`
- this objective and work order

## Protected boundaries

Do not weaken `WorkbenchOrchestrator` authority checks, change Agent/Notebook
HTTP contracts, change evidence or Report ownership, or alter model engines.

## Acceptance

- the three owned test files pass together;
- the fixture helper remains server-capability-backed;
- compile and diff checks pass and formal evidence records external gates.
