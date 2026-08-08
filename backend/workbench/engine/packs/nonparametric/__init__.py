"""Standalone nonparametric and robust descriptive inference kernels."""

from .rank_tests import (
    run_friedman,
    run_kendall,
    run_kruskal_wallis,
    run_mann_whitney,
    run_spearman,
    run_wilcoxon_signed_rank,
)
from .robust import run_robust_summary

__all__ = [
    "run_friedman",
    "run_kendall",
    "run_kruskal_wallis",
    "run_mann_whitney",
    "run_robust_summary",
    "run_spearman",
    "run_wilcoxon_signed_rank",
]
