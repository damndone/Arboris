# Work Order: v1.8.9 P1 Survey authority remediation

## Scope

Remediate the reviewed Survey central-source authority and unsupported-family
projection boundary. This is a security/evidence correction to the preceding
Survey source line, not a new Survey estimator.

## Owned paths

- `backend/workbench/evidence/survey_projection_adapter.py`
- `backend/workbench/services/survey_consumer_service.py`
- `tests/test_v189_survey_central_consumer.py`
- `tests/test_v189_survey_authority_remediation.py`
- this objective/work-order and the formal handoff

## Protected paths

- `backend/workbench/predictive_research/**`
- `backend/workbench/survey/**`
- `backend/workbench/providers/**`
- `backend/workbench/agent/context_tools.py`
- `backend/workbench/agent/notebook/evidence.py`
- `frontend/src/**`
- prior Survey formal records

## Acceptance

- TDD RED probes reproduce caller-side capability/receipt minting and metadata
  loss for unsupported families;
- TDD GREEN closes both paths without raw fallback or estimator changes;
- existing supported OLS/Logit and catalog/coverage tests remain green;
- independent security and code-quality review finds no P0/P1 issue;
- formal events, verify, and retrospective are generated through the CLI.

## Known gates

Report/HTTP/frontend mounting, browser, real provider, cross-process issuer,
full host gate, merge, tag, and release remain `NOT VERIFIED`.
