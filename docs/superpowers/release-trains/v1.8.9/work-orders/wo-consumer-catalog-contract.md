# Work order: provider-owned consumer catalog declarations

## Goal

Close the provider/catalog schema gap discovered during the v1.8.9 consumer
projection review. The central registry may only consume policy, renderer,
fact-kind, identity and budget values that are declared by the owning provider
and bound to an exposure path.

## Allowed implementation

- Extend `backend/workbench/contracts/common/provider.py` with the immutable
  declaration contract and strict wire validation.
- Extend `backend/workbench/providers/catalog.py` and builtin manifests with
  declaration loading and identity checks.
- Update `backend/workbench/evidence/consumer_adapters.py` only at the catalog
  registry seam; do not change persistence authority or evidence math.
- Add focused tests under `tests/test_v189_consumer_catalog_contract.py`.

## Explicit non-goals

- Do not rewrite provider projection refs to make coverage green.
- Do not add package runtime adapters, browser acceptance, provider calls,
  report UI changes, or model-family logic in this work order.
