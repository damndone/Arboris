"""The envelope a combinator returns: one member per run of a capability.

A combinator runs one capability several times -- once per group, once per
imputed data set -- and its result is the collection of those runs. Every
member is either estimated, with a reference to its own result envelope, or
explicitly not estimable with the reason; a group that was too small is listed,
never silently dropped. Multiple imputation adds the pooled result and the
method that pooled it.

Members refer to results inside the same run; the collection never embeds
them, so each member keeps its own envelope and inference kernel.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from typing import Any

RESULT_COLLECTION_CONTRACT = "workbench.result_collection.v1"
MEMBER_STATUSES = ("estimated", "not_estimable")

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.:]{0,63}$")
_FIELDS = frozenset({"contract", "combinator", "capability", "parameters", "seed", "members", "pooled"})
_MEMBER_FIELDS = frozenset({"key", "status", "nobs", "result_ref", "reason"})


class ResultCollectionError(ValueError):
    """A collection a consumer could not rely on."""


def _relative_ref(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResultCollectionError(f"{name} must be a non-empty run-relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise ResultCollectionError(f"{name} must stay inside the run")
    return value


def _validate_member(member: Any) -> dict[str, Any]:
    if not isinstance(member, Mapping):
        raise ResultCollectionError("each member must be an object")
    unexpected = set(member) - _MEMBER_FIELDS
    if unexpected:
        raise ResultCollectionError(f"unexpected member fields {sorted(unexpected)}")
    key = member.get("key")
    if not isinstance(key, str) or not key:
        raise ResultCollectionError("member key must be a non-empty string")
    status = member.get("status")
    if status not in MEMBER_STATUSES:
        raise ResultCollectionError(f"member {key!r} has unknown status {status!r}")
    nobs = member.get("nobs")
    if nobs is not None and (not isinstance(nobs, int) or isinstance(nobs, bool) or nobs < 0):
        raise ResultCollectionError(f"member {key!r} nobs must be a non-negative integer")
    normalized: dict[str, Any] = {"key": key, "status": status, "nobs": nobs}
    if status == "estimated":
        normalized["result_ref"] = _relative_ref(member.get("result_ref"), f"member {key!r} result_ref")
        normalized["reason"] = None
    else:
        reason = member.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ResultCollectionError(f"member {key!r} is not estimable but gives no reason")
        normalized["result_ref"] = None
        normalized["reason"] = reason
    return normalized


def validate_result_collection(collection: Any) -> None:
    if not isinstance(collection, Mapping):
        raise ResultCollectionError("result collection must be an object")
    if set(collection) != _FIELDS:
        raise ResultCollectionError(
            f"result collection fields differ: missing {sorted(_FIELDS - set(collection))}, "
            f"unexpected {sorted(set(collection) - _FIELDS)}"
        )
    if collection["contract"] != RESULT_COLLECTION_CONTRACT:
        raise ResultCollectionError("result collection contract is not recognised")
    for name in ("combinator", "capability"):
        if not isinstance(collection[name], str) or not _IDENTIFIER.fullmatch(collection[name]):
            raise ResultCollectionError(f"{name} must be an identifier")
    if not isinstance(collection["parameters"], Mapping):
        raise ResultCollectionError("parameters must be an object")
    seed = collection["seed"]
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool) or seed < 0):
        raise ResultCollectionError("seed must be a non-negative integer or null")
    members = collection["members"]
    if not isinstance(members, Sequence) or isinstance(members, (str, bytes)) or not members:
        raise ResultCollectionError("a collection needs at least one member")
    keys = [_validate_member(member)["key"] for member in members]
    if len(set(keys)) != len(keys):
        raise ResultCollectionError("member keys must be unique")
    pooled = collection["pooled"]
    if pooled is not None:
        if not isinstance(pooled, Mapping) or set(pooled) != {"method", "result_ref"}:
            raise ResultCollectionError("pooled must name its method and its result_ref")
        if not isinstance(pooled["method"], str) or not _IDENTIFIER.fullmatch(pooled["method"]):
            raise ResultCollectionError("pooled method must be an identifier")
        _relative_ref(pooled["result_ref"], "pooled result_ref")


def build_result_collection(
    *,
    combinator: str,
    capability: str,
    parameters: Mapping[str, Any],
    members: Sequence[Mapping[str, Any]],
    seed: int | None = None,
    pooled: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    collection = {
        "contract": RESULT_COLLECTION_CONTRACT,
        "combinator": combinator,
        "capability": capability,
        "parameters": dict(parameters),
        "seed": seed,
        "members": [_validate_member(member) for member in members],
        "pooled": dict(pooled) if pooled is not None else None,
    }
    validate_result_collection(collection)
    return collection
