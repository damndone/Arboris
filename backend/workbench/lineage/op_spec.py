"""Per-stage op_spec extraction for the lineage op-layer (Loop 2A.3).

`op_spec_for_stage` returns the STABLE structural spec for one cacheable stage:
the subset of POST-/runs form params (plus, where relevant, the RNG seed) that
the stage actually consumes. This dict feeds `node_hash` (hashing.py), so it must
be deterministic and free of volatile fields (run_id, started_at, paths, times).

The critical invariant: `model_type` lives ONLY in `estimation` (and flows
downstream to `diagnostics`), so an upstream stage's op_spec is unaffected by a
model swap and stays cache-hittable.

This module is the extraction function + its partition only; it is NOT wired into
the orchestrator in this loop. The partition's completeness is byte-identical
validated in later loops (2A.5/2A.6).
"""
from __future__ import annotations

from typing import Any

# Per-stage consumed form keys. A stage absent from this map (or mapped to an
# empty list) consumes no form keys and gets a stable, model-independent op_spec.
# Add a future stage by adding one entry here; add to _SEED_CONSUMING_STAGES if it
# may consume RNG.
STAGE_FORM_KEYS: dict[str, list[str]] = {
    # Stages that consume NO form keys (stable, model_type-independent):
    "source": [],
    "cleaning": [],
    "profile": [],
    "validation": [],
    "pre_estimation_checks": [],
    "roles": [],
    "exposure": [],
    "statistical_tests": [],
    "report": [],
    # Stages with consumed form keys:
    "routing": ["entity_col", "time_col"],
    "ytype": ["y"],
    "imputation": ["imputation"],
    # Fork point: model_type lives HERE, not upstream.
    "estimation": [
        "model_type",
        "covariance",
        "iv_endog",
        "iv_instruments",
        "entity_col",
        "time_col",
        "y",
        "x",
        "model_options",
    ],
    "diagnostics": [
        "prediction_model_type",
        "prediction_cv_folds",
        "prediction_sampling_method",
    ],
}

# Per-stage consumed CONFIG keys (from the WorkbenchConfig, not the form). A stage
# that may consume RNG MUST include its seed; imputation also consumes the MICE
# hyper-params, which therefore MUST enter its node_hash (else a hyper-param change
# would stale-hit the materialized MICE cache — R1 cache poisoning).
_STAGE_CONFIG_KEYS: dict[str, list[str]] = {
    "imputation": [
        "random_seed", "imputation_method", "imputation_m",
        "imputation_max_iter", "max_missing_rate",
    ],
    "diagnostics": ["random_seed"],
}


def op_spec_for_stage(
    stage_name: str,
    *,
    form: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Return the stable structural op_spec for `stage_name`.

    Args:
        stage_name: pipeline stage identifier.
        form: flat dict of POST-/runs form params.
        config: dict containing at least ``random_seed``.

    Rules:
        - Only keys PRESENT in ``form`` are included (missing key -> omitted, never
          injected as None).
        - Seed-consuming stages additionally carry ``random_seed`` from ``config``.
        - Volatile fields (run_id, started_at, paths/times) are NEVER included.
        - Unknown ``stage_name`` -> ``{}`` (safe default).
    """
    consumed_keys = STAGE_FORM_KEYS.get(stage_name)
    if consumed_keys is None:
        return {}

    op_spec: dict[str, Any] = {
        key: form[key] for key in consumed_keys if key in form
    }

    for ckey in _STAGE_CONFIG_KEYS.get(stage_name, []):
        if ckey in config:
            op_spec[ckey] = config[ckey]

    return op_spec
