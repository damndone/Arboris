"""Content-addressable NodeResult store keyed by node_hash.

Each cacheable unit's result is stored once, decoupled from any single run, so a
rerun can reference a prior node's result by hash instead of recomputing it. Layout:

    <project_root>/data/node_results/<node_hash>/meta.json          # NodeResult metadata
    <project_root>/data/node_results/<node_hash>/artifacts/<name>   # raw artifact bytes
    <project_root>/data/node_results/_refs.json                     # node_hash -> [run_id, ...]

The ref ledger maps each node_hash to the head run_ids that reference it; it exists so
a future GC pass can find unreferenced nodes. This loop only builds the ledger (no GC).

Concurrency note: `add_head_ref` does a non-atomic read-modify-write of `_refs.json`.
That is safe enough for the current single-run-slot orchestrator; if concurrent runs
ever share a project root, this needs a lock or atomic merge.
"""
from __future__ import annotations

from pathlib import Path

from ..artifacts import read_json, write_json


def _node_results_dir(project_root: Path) -> Path:
    return project_root / "data" / "node_results"


def _node_dir(project_root: Path, node_hash: str) -> Path:
    return _node_results_dir(project_root) / node_hash


def _meta_path(project_root: Path, node_hash: str) -> Path:
    return _node_dir(project_root, node_hash) / "meta.json"


def _artifacts_dir(project_root: Path, node_hash: str) -> Path:
    return _node_dir(project_root, node_hash) / "artifacts"


def _refs_path(project_root: Path) -> Path:
    return _node_results_dir(project_root) / "_refs.json"


def node_result_exists(project_root: Path, node_hash: str) -> bool:
    return _meta_path(project_root, node_hash).is_file()


def write_node_result(
    project_root: Path,
    node_hash: str,
    *,
    meta: dict,
    artifacts: dict[str, bytes],
) -> None:
    """Store a NodeResult content-addressably under `node_hash`. Idempotent: if the
    result already exists it is a no-op (identical content stores once)."""
    if node_result_exists(project_root, node_hash):
        return
    artifacts_dir = _artifacts_dir(project_root, node_hash)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for name, data in artifacts.items():
        (artifacts_dir / name).write_bytes(data)
    # Write meta.json last so its presence signals a complete result (see exists()).
    write_json(_meta_path(project_root, node_hash), meta)


def read_node_result(project_root: Path, node_hash: str) -> dict:
    """Return {"meta": <dict>, "artifacts": {name: bytes}} for a stored node_hash."""
    meta = read_json(_meta_path(project_root, node_hash))
    artifacts: dict[str, bytes] = {}
    artifacts_dir = _artifacts_dir(project_root, node_hash)
    if artifacts_dir.is_dir():
        for child in sorted(artifacts_dir.iterdir()):
            if child.is_file():
                artifacts[child.name] = child.read_bytes()
    return {"meta": meta, "artifacts": artifacts}


def heads_for_node(project_root: Path, node_hash: str) -> list[str]:
    refs_path = _refs_path(project_root)
    if not refs_path.is_file():
        return []
    refs = read_json(refs_path)
    return list(refs.get(node_hash, []))


def add_head_ref(
    project_root: Path,
    *,
    head_run_id: str,
    node_hash: str,
) -> None:
    """Append `head_run_id` to the ref ledger for `node_hash`. Idempotent: a run_id
    already present is not duplicated. Non-atomic read-modify-write (see module note)."""
    refs_path = _refs_path(project_root)
    refs_path.parent.mkdir(parents=True, exist_ok=True)
    refs = read_json(refs_path) if refs_path.is_file() else {}
    heads = refs.setdefault(node_hash, [])
    if head_run_id not in heads:
        heads.append(head_run_id)
        write_json(refs_path, refs)
