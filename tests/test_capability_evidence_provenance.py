from __future__ import annotations

import pytest


def _node(node_id: str, kind: str, ref: str, *parents: str):
    from workbench.capability_factory.provenance import ProvenanceNode

    return ProvenanceNode(node_id=node_id, kind=kind, artifact_ref=ref, parent_refs=parents)


def test_independent_oracle_requires_disjoint_lineage():
    from workbench.capability_factory.provenance import EvidenceProvenance, ProvenanceError

    provenance = EvidenceProvenance(
        evidence_ref="e" * 64,
        author_root="author",
        oracle_root="oracle",
        nodes=(
            _node("author", "author", "a" * 64),
            _node("oracle", "oracle", "b" * 64),
        ),
    )
    assert provenance.independent_oracle is True

    with pytest.raises(ProvenanceError, match="independent"):
        EvidenceProvenance(
            evidence_ref="e" * 64,
            author_root="author",
            oracle_root="oracle",
            nodes=(
                _node("shared", "author", "a" * 64),
                _node("author", "author", "b" * 64, "shared"),
                _node("oracle", "oracle", "c" * 64, "shared"),
            ),
        )


def test_author_only_provenance_is_valid_but_not_independent():
    from workbench.capability_factory.provenance import EvidenceProvenance

    provenance = EvidenceProvenance(
        evidence_ref="e" * 64,
        author_root="author",
        oracle_root=None,
        nodes=(_node("author", "author", "a" * 64),),
    )
    assert provenance.independent_oracle is False
