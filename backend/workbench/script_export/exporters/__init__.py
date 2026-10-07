"""Explicit export capabilities, checked against the live registries."""
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Callable, Mapping
from workbench.script_export.plan import LANGUAGES
from . import data, models, postestimation, survey
from ..syntax import refuse

@dataclass(frozen=True)
class LanguageExporter:
    renderer: Callable | None
    status: str
    note: str = ''
    packages: tuple[str,...] = ()

@dataclass(frozen=True)
class ExporterSpec:
    operation: str
    per_language: Mapping[str, LanguageExporter]
    capability: Callable | None = None

    def resolve(self, step, language):
        declared = self.per_language[language]
        reason = self.capability(step) if self.capability else None
        if isinstance(reason,Mapping):return reason[language]
        return LanguageExporter(None, 'snapshot', reason) if reason else declared


def native(operation, renderer, capability=None):
    return ExporterSpec(operation,{l:LanguageExporter(renderer,'native') for l in LANGUAGES},capability)


def survey_capability(step):
    weight = step.parameters.get('weights')
    if weight and weight.get('kind') == 'sampling':
        if not step.parameters.get('model_options',{}).get('survey_design'):
            refuse('Sampling weights require an explicit survey design','SURVEY_DESIGN_REQUIRED')
        return 'Survey-design estimation and its degrees of freedom are not validated for export in this release.'


def ols_capability(step):
    weight=step.parameters.get('weights')
    if weight and weight.get('kind')=='sampling':
        _,reason=survey.configuration(step)
        if reason:return reason
        return {l:LanguageExporter(survey.ols,'native_with_equivalence_note',
            'Full single-stage linearization design including supplied FPC and domain; Python uses the validated Workbench survey engine and executed t df.' if l=='python' else
            'Full single-stage linearization design including supplied FPC and domain; coefficient and joint-test df preserve the executed Workbench convention.') for l in LANGUAGES}


def generalized_capability(step):
    return survey_capability(step) or ('Weighted generalized estimation is not validated.' if step.parameters.get('weights') else None) or ('Generalized robust covariance is not validated.' if step.parameters.get('covariance') not in {None,'unadjusted'} else None)


def nb_capability(step):
    options = step.parameters.get('model_options',{})
    if options.get('dispersion','mean') != 'mean' or options.get('alpha') is not None:
        return 'Only estimated-dispersion NB2 is validated; NB1 and fixed-alpha inference require Workbench.'
    return generalized_capability(step)


def glm_capability(step):
    family=step.parameters.get('model_options',{}).get('family')
    if family not in {'binomial','poisson','negative_binomial'}:
        return 'This GLM family is not validated for native export.'
    if family=='negative_binomial':models.glm_nb_alpha(step)
    return generalized_capability(step)


def glm_nb_capability(step):
    models.glm_nb_alpha(step)
    return generalized_capability(step)


def iv_capability(step):
    p = step.parameters
    if p.get('weights') or p.get('categorical_x') or p.get('covariance','unadjusted') not in {'unadjusted','robust'}:
        return 'IV export currently validates unweighted continuous designs with model-based or HC0 covariance.'


def panel_capability(step):
    p = step.parameters
    if p.get('weights') or p.get('categorical_x') or p.get('covariance','clustered') != 'clustered':
        return 'Panel export currently validates unweighted continuous designs with C3 CR1 cluster covariance.'


def snapshot(operation, reason):
    return ExporterSpec(operation,{l:LanguageExporter(None,'snapshot',reason) for l in LANGUAGES})


SPECS = (
    native('data.subset',data.subset),native('data.recode',data.recode),native('data.rename',data.rename),
    native('data.fill_missing',data.fill_missing),native('data.dedupe',data.dedupe),native('data.merge',data.merge),
    native('data.append',data.append),native('data.aggregate',data.aggregate),native('data.reshape',data.reshape),
    native('data.lag',data.lag),native('data.tsset',data.tsset),
    native('model.ols',models.ols,ols_capability),native('model.logit',models.logit,generalized_capability),native('model.probit',models.probit,generalized_capability),
    native('model.poisson',models.poisson,generalized_capability),native('model.negative_binomial',models.negative_binomial,nb_capability),native('model.glm',models.glm,glm_capability),
    native('model.glm:binomial',models.glm_binomial,generalized_capability),native('model.glm:poisson',models.glm_poisson,generalized_capability),native('model.iv_2sls',models.iv_2sls,iv_capability),
    native('model.glm:negative_binomial',models.glm_negative_binomial,glm_nb_capability),
    native('model.panel_ols',models.panel_ols,panel_capability),native('model.did',models.did,panel_capability),
    native('postestimation.wald',postestimation.wald),native('postestimation.lincom',postestimation.lincom),ExporterSpec('postestimation.nlcom',{l:LanguageExporter(postestimation.nlcom,'native_with_equivalence_note','Delta-method estimate and covariance; inference uses the fitted residual or cluster df, including t inference after Stata nlcom.') for l in LANGUAGES}),
    native('postestimation.lr',postestimation.lr),native('postestimation.margins',postestimation.margins),
    snapshot('model.anova','ANOVA sums-of-squares and post-hoc export are not validated.'),
    snapshot('model.cs_did','Cohort ATT and bootstrap inference require the Workbench estimator.'),
    snapshot('model.sa_did','Interaction-weighted cohort aggregation and bootstrap inference require the Workbench estimator.'),
    snapshot('model.dcdh','Switching-treatment estimand and inference require the Workbench estimator.'),
    snapshot('model.ordinal_logit','Threshold parameterization export is not validated.'),
    snapshot('model.multinomial_logit','Outcome reference contrasts export is not validated.'),
    snapshot('model.survival_cox','Risk-set, ties and entry-time export are not validated.'),
    snapshot('model.linear_mixed_effects','REML covariance and containment-dependent estimator export are not validated.'),
    snapshot('model.quantile_regression','Quantile solver and covariance export are not validated.'),
    snapshot('model.arma_garch','Joint presample likelihood and covariance export require the Workbench estimator.'),
)
EXPORTERS = {spec.operation:spec for spec in SPECS}
