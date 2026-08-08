"""Post-hoc multiple-comparisons inference packs."""

from .posthoc import (
    MAX_GROUPS,
    MAX_OBSERVATIONS,
    MultipleComparisonsPackError,
    run_games_howell,
    run_scheffe,
)

__all__ = [
    "MAX_GROUPS",
    "MAX_OBSERVATIONS",
    "MultipleComparisonsPackError",
    "run_games_howell",
    "run_scheffe",
]
