"""Deterministic hashes for the lineage op-layer.

PIPELINE_VERSION is a declared constant bumped whenever the PIPELINE stage
structure changes; it participates in dag_hash so a pipeline change invalidates
any future hash-skip cache. Slice 1 reserves and populates these hashes but does
NOT implement caching."""
from __future__ import annotations

import hashlib
import json
from typing import Any

# Bump when orchestrator.PIPELINE stage structure changes.
PIPELINE_VERSION = "v1.6.0-pipeline-1"


def canonicalize(obj: Any) -> str:
    """Stable JSON string: sorted keys, compact separators."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def override_hash(op_overrides: dict) -> str:
    return _sha(canonicalize(op_overrides))


def dag_hash(upload_sha256: str, form_bag: dict) -> str:
    return _sha(canonicalize([upload_sha256, form_bag, PIPELINE_VERSION]))


def node_hash(parent_hashes: list[str], op_spec: dict, pipeline_version: str = PIPELINE_VERSION) -> str:
    """Merkle hash of a cacheable unit. Parent order-independent (sorted);
    op_spec is the unit's structural spec (volatile fields like run_id/started_at
    MUST be excluded by the caller in op_spec extraction, not here)."""
    return _sha(canonicalize([sorted(parent_hashes), op_spec, pipeline_version]))
