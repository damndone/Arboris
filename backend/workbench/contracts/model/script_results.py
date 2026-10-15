"""Family-owned completed-export layouts, distinct from inference capability."""
from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from collections.abc import Callable,Mapping


def ets_packet(packet,kernel,model_id,run_id,legacy=None):
    from .ets import ETSResultContract
    result=ETSResultContract.from_dict(packet['result'])
    if (result.model_type!=kernel['model_type'] or result.convergence_code!='converged'
            or kernel['param_names'] or kernel['nobs'] is not None):
        raise ValueError('Completed forecast and unavailable inference kernel disagree')
    return {'model_id':model_id,'model_type':result.model_type,'nobs':None,'coefficients':{}}


def ets_completed_input(packet,kernel,frame,form,y,x,options):
    from .ets import ETSResultContract
    from workbench.engine.packs.ets.input import ETSModelOptions, prepare_ets_input
    from workbench.engine.packs.ets.estimation import FIT_METHOD, _result_identity
    result=ETSResultContract.from_dict(packet['result'])
    prepared=prepare_ets_input(frame,ETSModelOptions.from_dict(options))
    audit=prepared.audit
    if (result.endog!=prepared.options.value_column
            or result.specification!=prepared.options.specification
            or result.n_obs!=audit.n_obs or result.n_excluded!=audit.n_excluded
            or dict(result.exclusion_reasons)!=dict(audit.exclusion_reasons)
            or result.time_index_semantics!=audit.time_index_semantics
            or packet['sample_fingerprint']!=prepared.sample_fingerprint
            or result.fit_method!=FIT_METHOD
            or result.result_identity!=_result_identity(prepared=prepared,params=dict(result.params))):
        raise ValueError('Completed forecast differs from the executed specification or sample')


def quantile_completed_input(packet,kernel,frame,form,y,x,options):
    from .quantile_regression import QuantileRegressionRequest
    from .v186_model_families import QuantileRegressionResultContract
    result=QuantileRegressionResultContract.from_dict(packet)
    quantiles=sorted(QuantileRegressionRequest.from_mapping(options).quantiles)
    keys={str(q) for q in quantiles}
    reference=min(quantiles,key=lambda q:abs(q-0.5))
    if (result.quantiles!=quantiles or result.reference_quantile!=reference
            or set(result.fits)!=keys or set(result.confidence_intervals)!=keys):
        raise ValueError('Completed quantiles differ from the executed request')
    for quantile in quantiles:
        fit=result.fits[str(quantile)]
        coefficients=fit['coefficients']
        if (fit['quantile']!=quantile or set(coefficients)!=set(kernel['param_names'])
                or result.confidence_intervals[str(quantile)]!={
                    name:[entry['ci_lower'],entry['ci_upper']] for name,entry in coefficients.items()}):
            raise ValueError('Completed quantile labels, terms or confidence intervals disagree')
    if result.coefficients!=result.fits[str(reference)]['coefficients']:
        raise ValueError('Reference quantile differs from the completed primary coefficients')


def aggregate_completed_document(packet,documents):
    effect=documents['evidence']['aggregations']['simple']
    coefficient=packet['coefficients']['ATT']
    if (effect['overall']!=coefficient['estimate']
            or effect['overall_se']!=coefficient['std_error']
            or effect['overall_pointwise_ci']!=[coefficient['ci_lower'],coefficient['ci_upper']]):
        raise ValueError('Completed primary aggregate differs from its coefficient projection')


def switcher_completed_document(packet,documents):
    effect=documents['evidence']['overall_att']
    coefficient=packet['coefficients']['ATT']
    if effect['estimate']!=coefficient['estimate'] or effect['se']!=coefficient['std_error']:
        raise ValueError('Completed primary effect differs from its coefficient projection')


def lmm_packet(packet,kernel,model_id,run_id,legacy=None):
    from workbench.services.lmm_result_adapter import parse_lmm_result_payload_v1
    from workbench.contracts.common.envelope import PacketEnvelope
    envelope=PacketEnvelope.from_dict(packet)
    if envelope.contract != 'linear_mixed_effects.result' or envelope.contract_version != '1.0':
        raise ValueError('Unknown completed result envelope contract')
    payload=parse_lmm_result_payload_v1(envelope.to_dict()['payload'])
    if (payload['model_id']!=model_id or payload['model_type']!=kernel['model_type']
            or payload['nobs']!=kernel['nobs'] or payload['execution_binding']['run_id']!=run_id
            or payload['status']!='complete' or payload['converged'] is not True):
        raise ValueError('Typed completed result differs from its executed owner')
    return dict(payload)


def lmm_coefficient_records(packet,kernel,frame,form,y,x):
    from workbench.engine.packs.linear_mixed_effects.input import prepare_lmm_input
    from workbench.engine.packs.linear_mixed_effects.result import _interaction_term
    from workbench.econometrics.normalize import _public_term
    prepared=prepare_lmm_input(frame,outcome=y,controls=x,options=form['model_options'])
    payload=packet['payload']
    if (prepared.formula!=payload['fixed_effects_formula'] or len(prepared.frame)!=kernel['nobs']
            or prepared.input.fit_method!=payload['fit_method']
            or prepared.reference_group!=payload['reference_group']
            or prepared.comparison_group!=payload['comparison_group']):
        raise ValueError('Typed primary coefficient differs from the executed formula or input')
    name=_public_term(_interaction_term(prepared))
    if kernel['param_names'].count(name)!=1:
        raise ValueError('Primary public result has no unique full-kernel term')
    return {name:payload['coefficients'][prepared.primary_result_id]}


def did_frame(frame,form,y):
    from workbench.engine.did_spec import normalize_did_input
    return normalize_did_input(frame,mode=form.get('did_mode') or 'cohort',
        entity=form.get('entity_col') or None,time=form.get('time_col') or None,y=y,
        cohort=form.get('did_cohort_col') or None,treat=form.get('did_treat_col') or None,
        post=form.get('did_post_col') or None,status=form.get('did_status_col') or None).frame


def did_input_parameters(frame,form,y):
    from pandas.api.types import is_bool_dtype
    from workbench.engine.did_spec import _coerce_cohort_value
    import math
    roles=[form.get(key) for key in ('entity_col','time_col','did_cohort_col',
        'did_treat_col','did_post_col','did_status_col')]
    parameters={'preparation':{'kind':'absorbing_treatment_panel','version':1,
        'boolean_columns':[name for name in roles if name and is_bool_dtype(frame[name])],
        'mode':form.get('did_mode') or 'cohort','entity':form['entity_col'],
        'time':form['time_col'],'cohort':form.get('did_cohort_col') or None,
        'treat':form.get('did_treat_col') or None,'post':form.get('did_post_col') or None,
        'status':form.get('did_status_col') or None}}
    if parameters['preparation']['mode']=='cohort':
        values=[_coerce_cohort_value(value) for value in frame[form['did_cohort_col']].drop_duplicates()]
        values=[value for value in values if math.isfinite(value)]
        parameters['preparation']['cohort_range']=[min(values),max(values)] if values else None
    return parameters


@dataclass(frozen=True)
class ScriptResultLayout:
    intrinsic_covariance: str | None = None
    packet_adapter: Callable | None = None
    artifact_suffix: str = ""
    coefficient_records: Callable | None = None
    completed_input_validator: Callable | None = None
    completed_document_validator: Callable | None = None
    empty_coefficients: bool = False
    input_preparer: Callable | None = None
    input_parameters: Callable | None = None
    snapshot_numbers: bool = False
    reference_field: str | None = None
    numeric_document_roles: tuple[str,...] = ()


SCRIPT_RESULT_LAYOUTS=MappingProxyType({
    'did':ScriptResultLayout(input_preparer=did_frame,input_parameters=did_input_parameters),
    'linear_mixed_effects':ScriptResultLayout(packet_adapter=lmm_packet,
        intrinsic_covariance='lmm_gls_conditional',
        artifact_suffix='.result',coefficient_records=lmm_coefficient_records,snapshot_numbers=True,
        numeric_document_roles=('packet',)),
    'quantile_regression':ScriptResultLayout(snapshot_numbers=True,
        completed_input_validator=quantile_completed_input),
    'cs_did':ScriptResultLayout(snapshot_numbers=True,
        completed_document_validator=aggregate_completed_document),
    'sa_did':ScriptResultLayout(snapshot_numbers=True,
        completed_document_validator=aggregate_completed_document),
    'dcdh':ScriptResultLayout(snapshot_numbers=True,
        completed_document_validator=switcher_completed_document),
    'time_series.ets':ScriptResultLayout(packet_adapter=ets_packet,empty_coefficients=True,
        completed_input_validator=ets_completed_input,
        snapshot_numbers=True,numeric_document_roles=('packet',)),
    'time_series.arma_garch':ScriptResultLayout(empty_coefficients=True,snapshot_numbers=True,
        reference_field='artifact_refs',numeric_document_roles=('ts.parameters','ts.final_model',
            'ts.final_diagnostics','ts.forecast_metrics','ts.next_forecast')),
})
DEFAULT_SCRIPT_RESULT_LAYOUT=ScriptResultLayout()
