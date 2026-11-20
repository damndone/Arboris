"""Standalone, fail-closed study-level meta-analysis kernels.

The code lives in sibling modules; this module keeps the import path.
"""

from __future__ import annotations

from .rows import (  # noqa: F401
    MAX_NUMERIC_INPUT,
    MAX_OUTPUT_ROWS,
    MAX_PM_ITERATIONS,
    MAX_STUDIES,
    MetaAnalysisPackError,
    PM_TOLERANCE,
    _binary_rows,
    _canonical_ci_method,
    _canonical_effect_measure,
    _canonical_method,
    _converted_rows,
    _count,
    _direct_alias_value,
    _direct_rows,
    _evidence_rows,
    _field,
    _finite_number,
    _mean_rows,
    _nonnegative_number,
    _positive_variance,
    _prepare_ids,
    _reject,
    _resolve_continuity_correction,
    _row_effect_measure,
    _rows,
    _safe_product,
    _safe_sqrt,
    _safe_sum,
    _sample_size,
    _standardized_mean_rows,
    _study_id,
    _validate_alpha,
    _validate_correction_applicability,
    _validate_evidence_correction,
)
from .combine import (  # noqa: F401
    _combine_core,
    _critical_value,
    _der_simonian_laird_tau2,
    _leave_one_out_evidence,
    _paule_mandel_tau2,
    _pm_q,
    _prepare_effects,
    _q_statistic,
    _source_payload,
    _source_rows,
    _weighted_mean,
    _weights,
    combine_effects,
    combine_meta_analysis,
    convert_effect_size,
    convert_meta_effect_size,
)

__all__ = [
    "MAX_NUMERIC_INPUT",
    "MAX_OUTPUT_ROWS",
    "MAX_STUDIES",
    "MetaAnalysisPackError",
    "combine_effects",
    "combine_meta_analysis",
    "convert_effect_size",
    "convert_meta_effect_size",
]
