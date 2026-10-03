"""One declaration per model family of what its result exposes, and from where.

Before v1.8.10 three places each kept their own table of which file holds a
family's evidence and which fields matter: the Agent's projection, the report
stage, and the run-detail route. Each new family had to be added to all three,
and a family missing from one was simply invisible there -- Callaway-Sant'Anna,
Sun-Abraham and dCDH were never readable by the Agent at all.

Declarations here are data. A field states where it comes from and what kind of
value it is; each consumer decides how to present that kind. The Agent bounds
it (an unbounded probability table would be a data-export channel); the report
shows it in full. Nothing in this module or in its consumers branches on a
family name.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any

#: What a field holds. Consumers map each kind to a presentation; adding a kind
#: means adding it to every consumer, which a test enforces.
EVIDENCE_KINDS = frozenset(
    {
        "label",
        "labels",
        "positive_int",
        "numeric_list",
        "numeric_map",
        "numeric_fields",
        "anova_rows",
        "ordinal_marginal_effects",
        "ordinal_probabilities",
        "parallel_lines",
        "multinomial_marginal_effects",
        "probability_map",
        "survival_rows",
        "schoenfeld",
        "quantile_fits",
        "quantile_intervals",
        "bootstrap",
        "cross_quantile_comparisons",
        "effect_aggregate",
        "effect_series",
        "effect_point",
        "honest_did",
    }
)


def _frozen(options: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(options or {}))


@dataclass(frozen=True)
class EvidenceField:
    """One exposed value: its public name, where it is read, and its kind."""

    key: str
    source_key: str
    kind: str
    options: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    sidecar: str | None = None
    nested_key: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError(f"evidence field {self.key!r} has unknown kind {self.kind!r}")


@dataclass(frozen=True)
class ResultEnvelopeDeclaration:
    """What one family's result exposes beyond the shared envelope.

    ``evidence_document`` is a run-relative path when the family keeps its full
    result outside the packet (the DID estimators, survival); ``None`` means the
    result packet itself. ``report_document`` is what the report shows as the
    family's evidence; when it is ``None`` the report builds it from
    ``report_packet_keys`` of the packet.
    """

    family: str
    result_shape: str
    contract: str | None = None
    packet_model_types: tuple[str, ...] = ()
    evidence_document: str | None = None
    sidecars: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    fields: tuple[EvidenceField, ...] = ()
    report_document: str | None = None
    report_packet_keys: tuple[str, ...] = ()
    #: How the linear predictor maps to the predicted mean, for predictions and
    #: marginal effects: "identity", "logit", "probit" or "log". None when the
    #: family's prediction needs more than the coefficients and the regressors
    #: (an exposure, thresholds, several equations) and is not declared yet.
    inverse_link: str | None = None
    #: What the estimator is (§3.1 of the v1.8.10 design): its outcome, its
    #: estimation method and its design. Checks, post-estimation and
    #: combinators match on these, never on the family's name.
    traits: frozenset[str] = frozenset()

    @property
    def model_types(self) -> tuple[str, ...]:
        return (self.family, *self.packet_model_types)


def _field(key: str, kind: str, *, source_key: str | None = None, sidecar: str | None = None,
           nested_key: str | None = None, **options: Any) -> EvidenceField:
    return EvidenceField(
        key=key, source_key=source_key or key, kind=kind, options=_frozen(options),
        sidecar=sidecar, nested_key=nested_key,
    )


def _core(
    family: str, result_shape: str = "coefficient_intervals", *aliases: str, inverse_link: str | None = None
) -> ResultEnvelopeDeclaration:
    """A family whose result is fully described by the shared envelope."""
    return ResultEnvelopeDeclaration(
        family=family, result_shape=result_shape, packet_model_types=aliases, inverse_link=inverse_link
    )


def _aggregated_effects(family: str) -> ResultEnvelopeDeclaration:
    """Group-time ATT estimators share one result document layout."""
    return ResultEnvelopeDeclaration(
        family=family,
        result_shape="effect_estimate_bundle",
        evidence_document=f"{family}.json",
        fields=(
            _field("overall", "effect_aggregate", source_key="aggregations", nested_key="simple"),
            _field("event_study", "effect_series", source_key="aggregations", nested_key="dynamic"),
            _field("by_cohort", "effect_series", source_key="aggregations", nested_key="group"),
            _field("by_period", "effect_series", source_key="aggregations", nested_key="calendar"),
            _field("honest_did", "honest_did"),
            _field(
                "sample_spec", "numeric_fields", source_key="diagnostics", nested_key="sample_spec",
                string_fields=("control_group", "est_method", "base_period", "estimator", "cluster_var"),
                fields=("anticipation",),
            ),
        ),
        report_document=f"{family}.json",
    )


_ORDINAL_DIAGNOSTICS = "model_results/diagnostics_ordinal_logit_1.json"
_MULTINOMIAL_DIAGNOSTICS = "model_results/diagnostics_multinomial_logit_1.json"

_DECLARATIONS: tuple[ResultEnvelopeDeclaration, ...] = (
    _core("ols", "coefficient_intervals", "ols_robust", "ols_clustered", inverse_link="identity"),
    _core("logit", inverse_link="logit"),
    _core("probit", inverse_link="probit"),
    _core("poisson", inverse_link="log"),
    # A rate model predicts with its exposure, which the coefficients alone do
    # not carry; its prediction is not declared until the exposure is.
    _core("poisson_rate"),
    _core("negative_binomial"),
    _core("glm:binomial", "coefficient_intervals", "glm"),
    _core("glm:poisson"),
    _core("glm:negative_binomial"),
    _core("iv_2sls"),
    _core("panel_ols"),
    _core("did"),
    _core("linear_mixed_effects"),
    ResultEnvelopeDeclaration(
        family="anova",
        result_shape="anova_table",
        contract="workbench.anova.result.v1",
        fields=(
            # The type is not decoration: on an unbalanced design Type I and
            # Type III disagree (166.74 against 104.05 on the committed
            # fixture), so a table quoted without it is ambiguous.
            _field("sums_of_squares_type", "positive_int"),
            _field("anova_table", "anova_rows"),
            _field("partial_eta_squared", "numeric_map", fields=("partial_eta_squared",)),
            _field("posthoc", "anova_rows", limit=32),
        ),
    ),
    ResultEnvelopeDeclaration(
        family="ordinal_logit",
        result_shape="coefficient_intervals",
        contract="workbench.ordinal_logit.result.v1",
        sidecars=MappingProxyType({"diagnostic": _ORDINAL_DIAGNOSTICS}),
        fields=(
            _field("outcome_levels", "labels"),
            _field("odds_ratios", "numeric_map", fields=("odds_ratio", "ci_lower", "ci_upper")),
            _field("marginal_effects", "ordinal_marginal_effects"),
            _field("predicted_probabilities", "ordinal_probabilities"),
            _field("parallel_lines", "parallel_lines", sidecar="diagnostic"),
        ),
        report_document=_ORDINAL_DIAGNOSTICS,
    ),
    ResultEnvelopeDeclaration(
        family="multinomial_logit",
        result_shape="coefficient_intervals",
        contract="workbench.multinomial_logit.result.v1",
        sidecars=MappingProxyType({"diagnostic": _MULTINOMIAL_DIAGNOSTICS}),
        fields=(
            _field("outcome_levels", "labels"),
            _field("base_category", "label"),
            _field("relative_risk_ratios", "numeric_map", fields=("relative_risk_ratio", "ci_lower", "ci_upper")),
            _field("marginal_effects", "multinomial_marginal_effects"),
            _field("predicted_probabilities", "probability_map"),
        ),
        report_document=_MULTINOMIAL_DIAGNOSTICS,
    ),
    ResultEnvelopeDeclaration(
        family="survival_cox",
        result_shape="effect_estimate_bundle",
        evidence_document="survival/evidence.json",
        fields=(
            _field("duration_column", "label"),
            _field("event_column", "label"),
            _field("nobs", "positive_int"),
            _field("censoring", "numeric_fields", fields=("events", "censored")),
            _field("kaplan_meier", "survival_rows", limit=16),
            _field(
                "log_rank", "numeric_fields", fields=("statistic", "p_value"),
                string_fields=("status",), list_fields=("groups",),
            ),
            _field("risk_set", "survival_rows", limit=16),
            _field("schoenfeld", "schoenfeld"),
        ),
        report_document="survival/evidence.json",
    ),
    ResultEnvelopeDeclaration(
        family="quantile_regression",
        result_shape="coefficient_intervals",
        contract="workbench.quantile_regression.result.v1",
        fields=(
            _field("quantiles", "numeric_list", limit=7),
            _field("fits", "quantile_fits"),
            _field("confidence_intervals", "quantile_intervals"),
            _field("bootstrap", "bootstrap"),
            _field("cross_quantile_comparisons", "cross_quantile_comparisons"),
        ),
        report_packet_keys=("quantiles", "fits", "bootstrap", "cross_quantile_comparisons"),
    ),
    _aggregated_effects("cs_did"),
    _aggregated_effects("sa_did"),
    ResultEnvelopeDeclaration(
        family="dcdh",
        result_shape="event_study_bundle",
        evidence_document="dcdh.json",
        fields=(
            _field("overall", "effect_point", source_key="overall_att"),
            _field("event_study", "effect_series", source_key="event_study"),
            _field("interpretation_restrictions", "labels"),
        ),
        report_document="dcdh.json",
    ),
    _core("time_series.ets", "time_series_forecast"),
    _core("time_series.arma_garch", "time_series_forecast"),
)


#: The closed vocabulary of traits. A trait outside it is a typo, refused at
#: import rather than silently matching nothing.
TRAIT_VOCABULARY = frozenset({
    "outcome.continuous", "outcome.binary", "outcome.count", "outcome.ordinal",
    "outcome.categorical", "outcome.survival", "outcome.time_series", "outcome.effect",
    "method.least_squares", "method.maximum_likelihood", "method.instrumental_variables",
    "method.quantile", "method.partial_likelihood", "method.aggregation", "method.mixed",
    "design.linear_predictor", "design.instruments", "design.panel", "design.grouped",
    # The variance equals the mean (Poisson-type); overdispersion breaks it.
    "dispersion.fixed",
})

_LINEAR = "design.linear_predictor"
_LS = ("outcome.continuous", "method.least_squares", _LINEAR)
_ML = ("method.maximum_likelihood", _LINEAR)
FAMILY_TRAITS: Mapping[str, frozenset[str]] = MappingProxyType({
    family: frozenset(traits) for family, traits in {
        "ols": _LS,
        "anova": _LS,
        "panel_ols": (*_LS, "design.panel"),
        "did": (*_LS, "design.panel"),
        "logit": ("outcome.binary", *_ML),
        "probit": ("outcome.binary", *_ML),
        "glm:binomial": ("outcome.binary", *_ML),
        "poisson": ("outcome.count", "dispersion.fixed", *_ML),
        "poisson_rate": ("outcome.count", "dispersion.fixed", *_ML),
        "negative_binomial": ("outcome.count", *_ML),
        "glm:poisson": ("outcome.count", "dispersion.fixed", *_ML),
        "glm:negative_binomial": ("outcome.count", *_ML),
        "ordinal_logit": ("outcome.ordinal", *_ML),
        "multinomial_logit": ("outcome.categorical", *_ML),
        "iv_2sls": ("outcome.continuous", "method.instrumental_variables", _LINEAR, "design.instruments"),
        "linear_mixed_effects": ("outcome.continuous", "method.mixed", _LINEAR, "design.grouped"),
        "quantile_regression": ("outcome.continuous", "method.quantile", _LINEAR),
        "survival_cox": ("outcome.survival", "method.partial_likelihood", _LINEAR),
        "cs_did": ("outcome.effect", "method.aggregation", "design.panel"),
        "sa_did": ("outcome.effect", "method.aggregation", "design.panel"),
        "dcdh": ("outcome.effect", "method.aggregation", "design.panel"),
        "time_series.ets": ("outcome.time_series", "method.maximum_likelihood"),
        "time_series.arma_garch": ("outcome.time_series", "method.maximum_likelihood"),
    }.items()
})


def _index(declarations: tuple[ResultEnvelopeDeclaration, ...]) -> Mapping[str, ResultEnvelopeDeclaration]:
    index: dict[str, ResultEnvelopeDeclaration] = {}
    for declaration in declarations:
        traits = FAMILY_TRAITS.get(declaration.family)
        if traits is None:
            raise ValueError(f"family {declaration.family!r} declares no traits")
        unknown = traits - TRAIT_VOCABULARY
        if unknown:
            raise ValueError(f"family {declaration.family!r} declares unknown traits {sorted(unknown)}")
        declaration = replace(declaration, traits=traits)
        for model_type in declaration.model_types:
            if model_type in index:
                raise ValueError(f"model type {model_type!r} is declared twice")
            index[model_type] = declaration
    return MappingProxyType(index)


RESULT_ENVELOPE_DECLARATIONS: Mapping[str, ResultEnvelopeDeclaration] = _index(_DECLARATIONS)


def declaration_for(model_type: Any) -> ResultEnvelopeDeclaration | None:
    """The declaration for a family or for a model type its packets report."""
    return RESULT_ENVELOPE_DECLARATIONS.get(model_type) if isinstance(model_type, str) else None


def declared_families() -> frozenset[str]:
    return frozenset(declaration.family for declaration in _DECLARATIONS)
