from __future__ import annotations

from dataclasses import replace
from dataclasses import FrozenInstanceError

import pytest


def _candidate():
    from workbench.capability_factory.candidate_store import CapabilityCandidate

    return CapabilityCandidate(
        candidate_id="candidate.alpha",
        capability_kind="model",
        source_kind="authored_implementation",
        implementation_ref="a" * 64,
        source_ref="b" * 64,
        author_lineage_ref="c" * 64,
        risk_level="high",
    )


def test_candidate_stores_refs_and_risk_without_code_payload():
    from workbench.capability_factory.candidate_store import CandidateStore

    candidate = _candidate()
    reference = CandidateStore().put(candidate)

    assert reference == candidate.content_digest
    assert candidate.source_ref == "b" * 64
    assert not hasattr(candidate, "source_code")


def test_candidate_store_is_append_only_and_rejects_duplicate_identity():
    from workbench.capability_factory.candidate_store import CandidateStore, CandidateStoreError

    store = CandidateStore()
    candidate = _candidate()
    store.put(candidate)
    with pytest.raises(CandidateStoreError, match="already"):
        store.put(replace(candidate, source_ref="d" * 64))


def test_candidate_is_immutable():
    candidate = _candidate()
    with pytest.raises(FrozenInstanceError):
        candidate.risk_level = "low"
