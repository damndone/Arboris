"""The model-visible request prefix must not depend on the process's string-hash seed.

Iterating a frozenset of operation ids reordered the chain protocol and the step
vocabulary in every new process (found 2026-11-03), so no two sessions shared a
cacheable prompt prefix.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

_PROBE = """
import hashlib, json
from workbench.agent.operations import OperationRegistry
from workbench.agent.protocol import chain_agent_protocol
registry = OperationRegistry()
parts = [chain_agent_protocol(registry), json.dumps(registry.capabilities(), sort_keys=True, default=str)]
print(hashlib.sha256("\\0".join(parts).encode()).hexdigest())
"""


def _digest(seed: str) -> str:
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(root / "backend")}
    result = subprocess.run([sys.executable, "-c", _PROBE], env=environment, capture_output=True, text=True,
                            check=True, cwd=root)
    return result.stdout.strip().splitlines()[-1]


def test_protocol_and_operation_registry_are_identical_under_different_hash_seeds():
    digests = {_digest(seed) for seed in ("1", "2", "3")}
    assert len(digests) == 1
    assert all(len(value) == len(hashlib.sha256().hexdigest()) for value in digests)
