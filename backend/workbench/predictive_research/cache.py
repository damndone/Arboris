"""Small identity-only cache seam backed by the existing NodeResult store.

This module records successful identity markers.  It does not skip model
execution or pretend to provide a prediction artifact cache; callers can use
the status to distinguish transform reuse from prediction reuse explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..lineage.node_store import node_result_exists, read_node_result, write_node_result
from .identity import PredictionIdentityV1


_CACHE_SCHEMA = "workbench.predictive.identity-cache"
_CACHE_VERSION = 2


@dataclass(frozen=True)
class PredictionCacheStatus:
    transformation_hit: bool
    prediction_hit: bool
    reuse: str = "identity_only"
    compute_skipped: bool = False

    def to_dict(self) -> dict[str, bool | str]:
        return {
            "transformation_hit": self.transformation_hit,
            "prediction_hit": self.prediction_hit,
            "reuse": self.reuse,
            "compute_skipped": self.compute_skipped,
        }


class PredictionIdentityCache:
    """Identity marker store using ``data/node_results`` as the real cache layer."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)

    def status(self, identity: PredictionIdentityV1) -> PredictionCacheStatus:
        return PredictionCacheStatus(
            transformation_hit=self._marker_matches(
                self._key("transformation", identity.transformation_identity_hash),
                layer="transformation",
                identity_hash=identity.transformation_identity_hash,
            ),
            prediction_hit=self._marker_matches(
                self._key("prediction", identity.prediction_identity_hash),
                layer="prediction",
                identity_hash=identity.prediction_identity_hash,
            ),
        )

    def record(self, identity: PredictionIdentityV1) -> None:
        self._record_marker(
            self._key("transformation", identity.transformation_identity_hash),
            layer="transformation",
            identity_hash=identity.transformation_identity_hash,
            sample_spec_hash=identity.sample_spec_hash,
        )
        self._record_marker(
            self._key("prediction", identity.prediction_identity_hash),
            layer="prediction",
            identity_hash=identity.prediction_identity_hash,
            run_identity_hash=identity.run_identity_hash,
            sample_spec_hash=identity.sample_spec_hash,
        )

    @staticmethod
    def _key(layer: str, identity_hash: str) -> str:
        return f"predictive-{layer}-{identity_hash}"

    def _record_marker(
        self,
        cache_key: str,
        *,
        layer: str,
        identity_hash: str,
        run_identity_hash: str | None = None,
        sample_spec_hash: str | None = None,
    ) -> None:
        meta: dict[str, str | int] = {
            "cache_schema": _CACHE_SCHEMA,
            "schema_version": _CACHE_VERSION,
            "layer": layer,
            "identity_hash": identity_hash,
        }
        if run_identity_hash is not None:
            meta["run_identity_hash"] = run_identity_hash
        if sample_spec_hash is not None:
            meta["sample_spec_hash"] = sample_spec_hash
        write_node_result(self.project_root, cache_key, meta=meta, artifacts={})

    def _marker_matches(self, cache_key: str, *, layer: str, identity_hash: str) -> bool:
        if not node_result_exists(self.project_root, cache_key):
            return False
        try:
            meta = read_node_result(self.project_root, cache_key).get("meta")
        except (OSError, TypeError, ValueError):
            return False
        return (
            isinstance(meta, dict)
            and meta.get("cache_schema") == _CACHE_SCHEMA
            and meta.get("schema_version") == _CACHE_VERSION
            and meta.get("layer") == layer
            and meta.get("identity_hash") == identity_hash
        )
