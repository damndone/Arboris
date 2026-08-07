"""The complex-survey design declaration, stated once.

Four consumers need to know which fields make up a design: the capability
projection publishes them, the rerun operation contract decides which overrides
are legal from them, the Agent's proposal validator accepts them, and the form
renders them.  Four copies would drift, and the drift is silent in the worst
direction -- an Agent emitting a field the executor drops still reports success,
and the run comes back without the design it was asked for.

`kind` and `role` follow the vocabulary already used by
``engine/capabilities.py`` so these entries can be appended to a model family's
``params`` without translation.
"""

from __future__ import annotations

from typing import Any

from .design import LONELY_PSU_POLICIES, REPLICATE_TYPES

#: Ordered so the published params read the way the form asks for them.
DESIGN_FIELD_SPECS: tuple[dict[str, Any], ...] = (
    {
        "key": "survey_strata_col",
        "kind": "text",
        "label": "Survey strata column",
        "required": False,
        "role": "survey_strata",
    },
    {
        "key": "survey_psu_col",
        "kind": "text",
        "label": "Survey PSU column",
        "required": False,
        "role": "survey_psu",
    },
    {
        "key": "survey_fpc_col",
        "kind": "text",
        "label": "Finite population correction column",
        "required": False,
        "role": "survey_fpc",
    },
    {
        "key": "survey_replicate_weights",
        "kind": "columns",
        "label": "Replicate weight columns",
        "required": False,
        "role": "survey_replicate_weights",
    },
    {
        "key": "survey_replicate_type",
        "kind": "select",
        "label": "Replicate method",
        "required": False,
        "options": list(REPLICATE_TYPES),
        "role": "survey_replicate_type",
    },
    {
        "key": "survey_lonely_psu",
        "kind": "select",
        "label": "Single-PSU stratum policy",
        "required": False,
        "options": list(LONELY_PSU_POLICIES),
        "role": "survey_lonely_psu",
    },
    {
        "key": "survey_weight_frame",
        "kind": "select",
        "label": "Panel weight frame",
        "required": False,
        "options": ["cross_sectional", "longitudinal"],
        "role": "survey_weight_frame",
    },
    {
        "key": "survey_subpop",
        "kind": "text",
        "label": "Subpopulation condition",
        "required": False,
        "role": "survey_subpop",
    },
)

#: The field names alone, derived rather than restated.
DESIGN_FIELDS: tuple[str, ...] = tuple(spec["key"] for spec in DESIGN_FIELD_SPECS)


def design_params() -> list[dict[str, Any]]:
    """Fresh copies, so a consumer mutating its params cannot corrupt the source."""
    return [dict(spec) for spec in DESIGN_FIELD_SPECS]
