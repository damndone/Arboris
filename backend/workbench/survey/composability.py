"""Which combinations a sampling design refuses, and why it refuses them.

Two refusals that look alike and are not:

* **not wired yet** -- the family could take a design and nobody has declared
  one for it. A later version will.
* **incoherent** -- the two describe different objects, and no version will
  reconcile them. A sampling design says how units were drawn from a
  population; a time series is one realisation of a process observed over time,
  with no population of units behind it. Weighting the observations of a single
  series by "probability of selection" has no referent.

Telling a user "not supported yet" for the second kind promises a release that
cannot exist, and invites them to keep looking for the option.

Registrable rather than hard-coded so a future pack can state its own position
without editing this file, and so the reason travels with the declaration
instead of being reconstructed at the point of refusal.
"""

from __future__ import annotations

from .errors import SurveyEngineError

#: model_type -> why a sampling design cannot apply to it.
_INCOHERENT: dict[str, str] = {}


def declare_design_incoherent(model_type: str, reason: str) -> None:
    """State that a sampling design is meaningless for this family."""
    if not model_type or not reason:
        raise ValueError("declaring incoherence requires a model type and a reason")
    _INCOHERENT[model_type] = reason


def design_incoherence_reason(model_type: str) -> str | None:
    return _INCOHERENT.get(model_type)


class SurveyCompositionRefusal(SurveyEngineError):
    """A refusal that names its own error code for the failure taxonomy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_TIME_SERIES_REASON = (
    "A sampling design describes how units were drawn from a population. A time "
    "series is a single realisation observed over time, so there is no population "
    "of units to have sampled and no selection probability to weight by. These do "
    "not combine -- this is a property of the two ideas, not a gap in the engine."
)

declare_design_incoherent("time_series.arma_garch", _TIME_SERIES_REASON)
declare_design_incoherent("time_series.ets", _TIME_SERIES_REASON)


def check_design_composition(
    *,
    model_type: str,
    has_design: bool,
    has_sampling_weight: bool,
    entity_column: str | None,
    time_column: str | None,
    weight_frame: str | None,
) -> None:
    """Refuse the combinations that would produce a misread result.

    Both refusals here are about a run that would otherwise succeed and be
    quietly answering a different question than the user asked.
    """
    if not (has_design or has_sampling_weight):
        return

    reason = design_incoherence_reason(model_type)
    if reason is not None:
        raise SurveyCompositionRefusal("SURVEY_DESIGN_DOES_NOT_COMPOSE", reason)

    # Panel-shaped data, a sampling weight, and no statement of which frame the
    # weight is on. Cross-sectional weights make each wave represent the
    # population at that wave; longitudinal weights make the panel represent
    # those present throughout. Using one for the other's question estimates a
    # different population, and every diagnostic still looks healthy.
    if entity_column and time_column and has_sampling_weight and not weight_frame:
        raise SurveyCompositionRefusal(
            "SURVEY_WEIGHT_FRAME_REQUIRED",
            "This data has both an entity and a time column, so a sampling weight "
            "is ambiguous: declare survey_weight_frame as cross-sectional (each "
            "wave represents the population at that wave) or longitudinal (the "
            "panel represents units present throughout). The two estimate "
            "different populations and the output looks the same either way.",
        )
