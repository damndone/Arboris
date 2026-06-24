"""Feature flags for the v1.6.1 lineage-incremental work. All default OFF so the
shipped behavior is byte-identical to v1.6.0 until a flag is explicitly enabled
(ship-dark). Flags are read from the environment as "1" (on) / anything else (off),
so they can be flipped per-process for tests and bisection without code changes.

- WORKBENCH_INCREMENTAL_CACHE : enable the node-level Merkle cache wrapper.
- WORKBENCH_FORCE_FULL_RECOMPUTE : even with the cache on, never skip (debug bisection).
- WORKBENCH_GRAPH_HEADSET : GET /graph returns the new head-set shape (else legacy).
"""
from __future__ import annotations

import os


def _flag(name: str) -> bool:
    return os.environ.get(name, "0") == "1"


def incremental_cache() -> bool:
    return _flag("WORKBENCH_INCREMENTAL_CACHE")


def force_full_recompute() -> bool:
    return _flag("WORKBENCH_FORCE_FULL_RECOMPUTE")


def graph_headset() -> bool:
    return _flag("WORKBENCH_GRAPH_HEADSET")
