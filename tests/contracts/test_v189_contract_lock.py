from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from workbench.contracts.common.contract_ref import (
    CONTRACT_DIGEST_MISMATCH,
    CONTRACT_DUPLICATE,
    CONTRACT_MAJOR_INCOMPATIBLE,
    CONTRACT_REF_INVALID,
    CONTRACT_UNRESOLVED,
    CONTRACT_VERSION_INVALID,
    ContractRefError,
    ContractRefResolverV1,
    ContractRefV1,
    canonical_contract_digest,
    parse_semantic_version,
)


def _ref(
    *,
    kind: str = "result",
    logical_id: str = "model.ols",
    semantic_version: str = "1.0",
    payload: object | None = None,
) -> ContractRefV1:
    contract_payload = (
        {"kind": kind, "logical_id": logical_id, "version": semantic_version}
        if payload is None
        else payload
    )
    return ContractRefV1(
        kind=kind,
        logical_id=logical_id,
        semantic_version=semantic_version,
        contract_digest=canonical_contract_digest(contract_payload),
    )


def test_contract_ref_requires_kind_id_semver_and_digest() -> None:
    ref = _ref()

    assert [field.name for field in fields(ref)] == [
        "kind",
        "logical_id",
        "semantic_version",
        "contract_digest",
    ]
    assert ContractRefV1.from_dict(ref.to_dict()) == ref
    with pytest.raises(FrozenInstanceError):
        ref.kind = "changed"  # type: ignore[misc]

    valid = ref.to_dict()
    for field_name in valid:
        missing = dict(valid)
        missing.pop(field_name)
        with pytest.raises(ContractRefError) as exc_info:
            ContractRefV1.from_dict(missing)
        assert exc_info.value.code == CONTRACT_REF_INVALID

    with pytest.raises(ContractRefError) as exc_info:
        ContractRefV1.from_dict({**valid, "unknown": "rejected"})
    assert exc_info.value.code == CONTRACT_REF_INVALID

    for field_name, invalid_value in (
        ("kind", " result"),
        ("kind", "result\x00"),
        ("logical_id", ""),
        ("logical_id", 7),
    ):
        with pytest.raises(ContractRefError) as exc_info:
            ContractRefV1.from_dict({**valid, field_name: invalid_value})
        assert exc_info.value.code == CONTRACT_REF_INVALID


def test_contract_ref_rejects_non_semver_and_non_sha256_digest() -> None:
    assert parse_semantic_version("1.0") == (1, 0)
    digest = canonical_contract_digest({"b": 2, "a": 1})
    assert digest == canonical_contract_digest({"a": 1, "b": 2})
    assert len(digest) == 64
    assert digest == digest.lower()

    for invalid_version in (
        "v1.0",
        "1",
        "1.0.0",
        "1.0-rc1",
        "01.0",
        "1.00",
        " 1.0",
        "1.0 ",
        1.0,
    ):
        with pytest.raises(ContractRefError) as exc_info:
            ContractRefV1(
                kind="result",
                logical_id="model.ols",
                semantic_version=invalid_version,  # type: ignore[arg-type]
                contract_digest=digest,
            )
        assert exc_info.value.code == CONTRACT_VERSION_INVALID

    for invalid_digest in ("sha256:" + digest, digest.upper(), "0" * 63, 123):
        with pytest.raises(ContractRefError) as exc_info:
            ContractRefV1(
                kind="result",
                logical_id="model.ols",
                semantic_version="1.0",
                contract_digest=invalid_digest,  # type: ignore[arg-type]
            )
        assert exc_info.value.code == CONTRACT_REF_INVALID


def test_resolver_rejects_duplicate_and_unresolved_refs() -> None:
    available = _ref()

    with pytest.raises(ContractRefError) as exc_info:
        ContractRefResolverV1((available, available))
    assert exc_info.value.code == CONTRACT_DUPLICATE

    resolver = ContractRefResolverV1((available,))
    assert resolver.resolve(available) == available

    for unresolved in (
        _ref(logical_id="model.logit"),
        _ref(semantic_version="1.1"),
    ):
        with pytest.raises(ContractRefError) as exc_info:
            resolver.resolve(unresolved)
        assert exc_info.value.code == CONTRACT_UNRESOLVED

    wrong_digest = _ref(payload={"different": True})
    with pytest.raises(ContractRefError) as exc_info:
        resolver.resolve(wrong_digest)
    assert exc_info.value.code == CONTRACT_DIGEST_MISMATCH


def test_major_version_mismatch_is_not_silently_coerced() -> None:
    resolver = ContractRefResolverV1((_ref(semantic_version="1.0"),))

    with pytest.raises(ContractRefError) as exc_info:
        resolver.resolve(_ref(semantic_version="2.0"))

    assert exc_info.value.code == CONTRACT_MAJOR_INCOMPATIBLE
