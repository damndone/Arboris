"""Frozen VIX acceptance profiles and repository VIX-input locator.

The v1.8 specification (section 23) treats VIX only as a *frozen configuration
regression sample*. No VIX rule may leak into the generic pack. These profiles
are therefore plain data: the exact frozen analysis contract that a real VIX CSV
would be replayed through, plus the generic auto-discovery contract used to prove
the generic flow contains no VIX special-casing.

If, and only if, a genuine VIX CSV is later committed to the repository, the
locator below self-activates and the replication acceptance test stops skipping.
The locator never fabricates data and never reaches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import csv


# Deterministic skip contract when no real external VIX input is present.
MISSING_VIX_INPUT_REASON = "missing_external_acceptance_input"

# The original Stata Do-file estimates a joint model; Workbench uses a sequential
# two-stage ARMA(1,1)-GARCH(1,1). We therefore only ever assert directional /
# workflow parity, never exact per-parameter equality.
REFERENCE_SEMANTICS = "directional_or_workflow_regression"


# Frozen manual replication contract (section 23.A). Column names are filled in
# from the located CSV header; every other field is frozen here.
VIX_REPLICATION_PROFILE: dict[str, object] = {
    "profile_id": "vix_replication_profile",
    "reference_semantics": REFERENCE_SEMANTICS,
    "contract_template": {
        "time_index_semantics": "business_or_trading_observations",
        "transform": "log_return_pct",
        "transform_confirmed": True,
        # The reference Do-file drops non-trading rows (`drop if missing(vix)`)
        # before indexing by trading day. Excluding non-observations is confirmed
        # explicitly; nothing is filled, interpolated, or aggregated.
        "missing_value_policy": "drop_missing_confirmed",
        "selection_mode": "manual",
        "arma": {"p": 1, "q": 1, "constant_mode": "exclude"},
        "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
        "estimation_strategy": "sequential",
        "innovation_distribution": "normal",
        "validation": {"validation_n": 250, "refit_every": 1},
        "forecast": {"horizon": 1, "interval_level": 0.95, "lower_quantile": 0.05},
        "random_seed": 0,
    },
    "asserts": (
        "column_mapping",
        "date_ordering",
        "trading_observation_index",
        "transform",
        "effective_sample",
        "manual_arma11_garch11",
        "conditional_series",
        "diagnostics",
        "rolling_forecast",
        "charts",
        "artifacts",
        "lineage",
    ),
}


# Frozen generic auto-discovery contract (section 23.B). No VIX-specific rule.
VIX_GENERIC_AUTO_PROFILE: dict[str, object] = {
    "profile_id": "vix_generic_auto_profile",
    "contract_template": {
        "time_index_semantics": "business_or_trading_observations",
        "transform": "log_return_pct",
        "transform_confirmed": True,
        "missing_value_policy": "drop_missing_confirmed",
        "selection_mode": "auto",
        "arma": {
            "p": None,
            "q": None,
            "constant_mode": "auto",
            "auto_max_p": 2,
            "auto_max_q": 2,
            "auto_max_total_order": 2,
        },
        "variance": {
            "model": "auto",
            "auto_arch_max_p": 3,
            "include_garch_1_1": True,
        },
        "estimation_strategy": "auto",
        "innovation_distribution": "normal",
        "validation": {"validation_n": 60, "refit_every": 1},
        "random_seed": 0,
    },
    "asserts": (
        "identifies_time_and_value_columns",
        "produces_transform_recommendation",
        "runs_bounded_search",
        "recommends_reasonable_candidate",
        "produces_explanation",
        "contains_no_vix_special_casing",
    ),
}


@dataclass(frozen=True)
class LocatedVixInput:
    path: Path
    time_column: str
    value_column: str
    row_count: int


def _repository_root() -> Path:
    # tests/fixtures/models/arma_garch/vix_profiles.py -> repository root.
    return Path(__file__).resolve().parents[4]


def _looks_like_vix_header(header: list[str]) -> tuple[str, str] | None:
    lowered = [name.strip().lower() for name in header]
    time_candidates = ("date", "trade_date", "observation_date", "time")
    value_candidates = ("vix", "vixcls", "close", "vix_close", "adj close")
    time_column = next(
        (header[i] for i, name in enumerate(lowered) if name in time_candidates),
        None,
    )
    value_column = next(
        (
            header[i]
            for i, name in enumerate(lowered)
            if "vix" in name or name in value_candidates
        ),
        None,
    )
    if time_column is None or value_column is None or time_column == value_column:
        return None
    return time_column, value_column


def locate_repository_vix_csv() -> LocatedVixInput | None:
    """Search the repository for a genuine VIX CSV.

    Returns the located input, or ``None`` when the repository contains no real
    VIX data. Never downloads and never fabricates. A CSV qualifies only when its
    filename mentions VIX and it exposes a plausible time column plus a VIX value
    column.
    """

    root = _repository_root()
    skip_dirs = {"node_modules", ".venv", "__pycache__", ".git", "dist"}
    for candidate in sorted(root.rglob("*.csv")):
        if any(part in skip_dirs for part in candidate.parts):
            continue
        if "vix" not in candidate.name.lower():
            continue
        try:
            with candidate.open(newline="", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                header = next(reader, None)
                if header is None:
                    continue
                mapping = _looks_like_vix_header(header)
                if mapping is None:
                    continue
                row_count = sum(1 for _ in reader)
        except (OSError, UnicodeDecodeError, csv.Error):
            continue
        if row_count < 200:
            continue
        return LocatedVixInput(
            path=candidate,
            time_column=mapping[0],
            value_column=mapping[1],
            row_count=row_count,
        )
    return None


__all__ = [
    "LocatedVixInput",
    "MISSING_VIX_INPUT_REASON",
    "REFERENCE_SEMANTICS",
    "VIX_GENERIC_AUTO_PROFILE",
    "VIX_REPLICATION_PROFILE",
    "locate_repository_vix_csv",
]
