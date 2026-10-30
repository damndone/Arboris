"""Native companion bindings and family-specific delivery requirements."""
from __future__ import annotations

from ..canonical import sha256_canonical

NATIVE_COMPANIONS = {'survival_cox', 'iv_2sls', 'panel_ols', 'did'}


def iv_ar_wrapper(artifact):
    """Recognize this producer's wrapper; recognition alone certifies no result."""
    if artifact is None or artifact.artifact_type != 'post_estimation':
        return None
    wrapper = artifact.payload or {}
    return (wrapper if wrapper.get('schema_version') == 'workbench.workflow.post-estimation/v1'
            and isinstance(wrapper.get('result'), dict)
            and wrapper['result'].get('contract') == 'iv-ar.evidence.v1' else None)


def verified_iv_ar(products, main_ref, main, ref, artifact):
    wrapper = iv_ar_wrapper(artifact)
    if wrapper is None:
        return None
    value = wrapper.get('result') or {}
    source = wrapper.get('source') or {}
    model = products.load(main_ref)
    companion = products.load({**main_ref, 'artifact_id': main['model_id'] + '.completion'})
    if (model is None or companion is None
            or source.get('model_run_id') != main_ref['run_id']
            or source.get('model_artifact_id') != main['model_id']
            or value.get('model_run_id') != main_ref['run_id'] or value.get('model_id') != main['model_id']
            or value.get('model_sha256') != model.sha256 or value.get('completion_sha256') != companion.sha256
            or value.get('point_estimation_fingerprint') != main.get('point_estimation_fingerprint')
            or value.get('analysis_sample_fingerprint') != main.get('analysis_sample_fingerprint')
            or value.get('confidence_level') != .95
            or value.get('covariance') != companion.payload['diagnostics']['iv']['weak_instruments']['covariance']):
        return None
    return value.get('anderson_rubin_95')


def with_iv_ar(products, main_ref, main, values, supplements):
    """Only explicitly supplied, unique native-bound AR evidence enriches diagnostics."""
    from copy import deepcopy
    matches = [ar for ref, artifact in supplements
               if (ar := verified_iv_ar(products, main_ref, main, ref, artifact)) is not None]
    if len(matches) != 1:
        return values
    augmented = deepcopy(values)
    for value in augmented:
        value['diagnostics']['iv']['weak_instruments']['anderson_rubin_95'] = matches[0]
    return augmented


def companion_model(products, ref, artifact, model):
    if model.get('model_type') not in NATIVE_COMPANIONS:
        return model
    companion = products.load({'run_id': ref['run_id'], 'artifact_id': model['model_id'] + '.completion'})
    if companion is None or companion.artifact_type != 'analysis_completion_evidence':
        return None
    value = companion.payload or {}
    if (value.get('contract') not in {'analysis-completion.evidence.v1', 'analysis-completion.evidence.v2'} or value.get('status') != 'complete'
            or value.get('model_payload_sha256') != sha256_canonical(artifact.payload)
            or value.get('model_id') != model['model_id'] or value.get('model_type') != model['model_type']
            or value.get('nobs') != model['nobs']):
        return None
    source = value.get('source')
    if not isinstance(source, dict):
        return None
    registered = products.load({'run_id': ref['run_id'], 'artifact_id': source.get('artifact_id')})
    if registered is None or registered.sha256 != source.get('sha256'):
        return None
    if value['contract'] == 'analysis-completion.evidence.v1':
        positions = value.get('retained_positions')
        if (not isinstance(positions, list) or len(positions) != model['nobs']
                or any(type(p) is not int or p < 0 or p >= source['row_count'] for p in positions)
                or positions != sorted(set(positions))
                or sha256_canonical(positions) != value.get('analysis_sample_fingerprint')):
            return None
    else:
        sample = value.get('sample') or {}
        if (sample.get('retained_count') != model['nobs']
                or sample.get('missing_count') != source['row_count']-model['nobs']
                or sample.get('fingerprint_version') != 'numpy-bytes.v1'
                or sample.get('positions_sha256') != value.get('analysis_sample_fingerprint')
                or len(str(sample.get('positions_sha256', ''))) != 64):
            return None
    if any(item not in companion.inputs for item in [model['model_id'], source['artifact_id']]):
        return None
    for artifact_id in value.get('diagnostic_artifact_ids', []):
        diagnostic = products.load({'run_id': ref['run_id'], 'artifact_id': artifact_id})
        if diagnostic is None or diagnostic.sha256 != value.get('diagnostic_artifact_sha256', {}).get(artifact_id):
            return None
    return {**model, **({'point_definition': value.get('point_definition')}
                       if model['model_type'] == 'iv_2sls' else {}),
            'point_estimation_fingerprint': value['point_estimation_fingerprint'],
            'analysis_sample_fingerprint': value['analysis_sample_fingerprint']}


def native_diagnostics(family, values):
    if family == 'garch':
        for value in values:
            diag = (value.get('diagnostics') or {}).get('garch') or {}
            if (value.get('contract') == 'garch.completion.v1'
                    and diag.get('method') == 'garch_production_standardized_innovations_v1'
                    and diag.get('status') == 'computed'
                    and (diag.get('squared_ljung_box') or {}).get('status') == 'computed'
                    and all(type((diag.get(test) or {}).get('p_value')) in {int, float}
                            and 0 <= diag[test]['p_value'] <= 1 for test in ['ljung_box', 'squared_ljung_box', 'arch_lm'])
                    and all((diag.get('stationarity') or {}).get(test, {}).get('status') == 'computed' for test in ['adf', 'kpss'])):
                return True
    if family == 'time_series':
        for value in values:
            ts = (value.get('diagnostics') or {}).get('time_series') or {}
            if (value.get('contract') == 'time-series.completion.v1'
                    and ts.get('method') == 'arima_native_innovations_v1' and ts.get('status') == 'computed'
                    and all((ts.get('stationarity') or {}).get(test, {}).get('status') == 'computed' for test in ['adf', 'kpss'])
                    and type((ts.get('ljung_box') or {}).get('p_value')) in {float, int}
                    and type((ts.get('arch_lm') or {}).get('p_value')) in {float, int}):
                return True
    if family in {'panel', 'did'}:
        for value in values:
            panel = (value.get('diagnostics') or {}).get('panel') or {}
            valid = (value.get('contract') in {'analysis-completion.evidence.v1', 'analysis-completion.evidence.v2'}
                and panel.get('status') == 'computed' and panel.get('method') == 'panel_within_residual_descriptive_v1'
                and panel.get('nobs') == value.get('nobs')
                and ((value['contract'] == 'analysis-completion.evidence.v1' and panel.get('groups')
                      and len(panel.get('residuals', [])) == value.get('nobs'))
                     or (value['contract'] == 'analysis-completion.evidence.v2' and panel.get('n_entities', 0) > 0
                         and (panel.get('residual_summary') or {}).get('count') == value.get('nobs')
                         and len(str(panel['residual_summary'].get('sha256', ''))) == 64))
                and panel.get('total_parameter_rank', 0) > 0 and panel.get('residual_df', 0) > 0)
            if family == 'did':
                did = (value.get('diagnostics') or {}).get('did') or {}
                trends = did.get('parallel_trends') or {}
                valid = (valid and trends.get('verdict') in {'not_rejected', 'rejected'}
                    and trends.get('n_pre_leads', 0) > 0
                    and type(trends.get('pvalue')) in {float, int} and 0 <= trends['pvalue'] <= 1)
            if valid:
                return True
    if family == 'iv':
        for value in values:
            diag = (value.get('diagnostics') or {}).get('iv') or {}
            weak = diag.get('weak_instruments') or {}
            ar = weak.get('anderson_rubin_95') or {}
            endogeneity = diag.get('endogeneity') or {}
            overid = diag.get('overidentification') or {}
            if (value.get('contract') in {'analysis-completion.evidence.v1', 'analysis-completion.evidence.v2'}
                    and weak.get('per_endogenous') and weak.get('reference_distribution')
                    and (ar.get('global_certification') or {}).get('status') == 'certified'
                    and ar.get('kind') in {'interval', 'singleton', 'whole_line', 'ray_below', 'ray_above', 'union_of_rays', 'disjoint', 'empty'}
                    and endogeneity.get('test') in {'wooldridge_regression', 'wu_hausman'}
                    and type(endogeneity.get('pvalue')) in {float, int} and 0 <= endogeneity['pvalue'] <= 1
                    and (diag.get('identification') == 'just' or (overid.get('applicable') is True
                         and overid.get('test') in {'wooldridge_overid', 'sargan'}
                         and type(overid.get('pvalue')) in {float, int} and 0 <= overid['pvalue'] <= 1))):
                return True
    if family == 'survival':
        for value in values:
            ph = (value.get('diagnostics') or {}).get('proportional_hazards') or {}
            if (value.get('contract') in {'analysis-completion.evidence.v1', 'analysis-completion.evidence.v2'}
                    and ph.get('status') == 'computed' and ph.get('method') == 'cox_log_time_interaction_score_v1'
                    and ph.get('transform') == 'log' and ph.get('ties') in {'breslow', 'efron'}
                    and type((ph.get('global') or {}).get('p_value')) in {float, int}
                    and 0 <= ph['global']['p_value'] <= 1):
                return True
    return False


def native_findings(family, values):
    if family == 'garch':
        findings = []
        for value in values:
            diag = (value.get('diagnostics') or {}).get('garch') or {}
            if not diag:
                continue
            if diag.get('mean_stationary') is False or diag.get('mean_invertible') is False:
                findings.append('garch:diagnostics:inadmissible_mean_roots')
            if not diag.get('variance_parameters_valid'):
                findings.append('garch:diagnostics:invalid_variance_parameters')
            if diag.get('time_index_semantics') == 'regular_calendar' and (not diag.get('stable_frequency') or diag.get('internal_gap_count')):
                findings.append('garch:diagnostics:calendar_gaps_unverified')
            unit = diag.get('stationarity') or {}
            if (unit.get('adf') or {}).get('p_value', 1) >= .05 or (unit.get('kpss') or {}).get('p_value', 0) < .05:
                findings.append('garch:diagnostics:stationarity_unresolved')
            if (diag.get('ljung_box') or {}).get('p_value', 1) < diag['significance_level']:
                findings.append('garch:diagnostics:mean_correlation_requires_revision')
            if any((diag.get(test) or {}).get('p_value', 1) < diag['significance_level'] for test in ['squared_ljung_box', 'arch_lm']):
                findings.append('garch:diagnostics:remaining_arch_requires_revision')
        return list(dict.fromkeys(findings))
    if family == 'time_series':
        findings = []
        for value in values:
            ts = (value.get('diagnostics') or {}).get('time_series') or {}
            if not ts:
                continue
            if not (ts.get('sampling') or {}).get('regular'):
                findings.append('time_series:diagnostics:irregular_sampling_unverified')
            if ts.get('ar_stationary') is False or ts.get('ma_invertible') is False:
                findings.append('time_series:diagnostics:inadmissible_arima_roots')
            unit = ts.get('stationarity') or {}
            if (unit.get('adf') or {}).get('p_value', 1) >= .05 or (unit.get('kpss') or {}).get('p_value', 0) < .05:
                findings.append('time_series:diagnostics:stationarity_unresolved')
            if (ts.get('ljung_box') or {}).get('p_value', 1) < .05:
                findings.append('time_series:diagnostics:residual_correlation_requires_revision')
            if (ts.get('arch_lm') or {}).get('p_value', 1) < .05:
                findings.append('time_series:diagnostics:conditional_variance_requires_revision')
        return list(dict.fromkeys(findings))
    if family in {'panel', 'did'}:
        from ..checks.fit_checks import CLUSTER_COUNT

        findings = []
        for value in values:
            panel = (value.get('diagnostics') or {}).get('panel') or {}
            if panel:
                if panel.get('covariance') != 'clustered':
                    findings.append(f'{family}:diagnostics:within_dependence_inference_unverified')
                elif (panel.get('cluster_count') or 0) < CLUSTER_COUNT.threshold('severe_below'):
                    findings.append(f'{family}:diagnostics:few_clusters_inference_unverified')
            if family == 'did':
                did = (value.get('diagnostics') or {}).get('did') or {}
                trends = did.get('parallel_trends') or {}
                if trends.get('verdict') == 'unavailable' or not trends.get('n_pre_leads'):
                    findings.append('did:diagnostics:pretrends_unavailable')
                if trends.get('omitted_pre_leads'):
                    findings.append('did:diagnostics:pretrends_partly_unidentified')
                if trends.get('verdict') == 'rejected':
                    findings.append('did:diagnostics:pretrends_rejected_requires_revision')
                if did.get('interpretation_restriction'):
                    findings.append('did:diagnostics:staggered_interpretation_requires_revision')
        return list(dict.fromkeys(findings))
    if family == 'iv':
        findings = []
        for value in values:
            diag = (value.get('diagnostics') or {}).get('iv') or {}
            ar = (diag.get('weak_instruments') or {}).get('anderson_rubin_95') or {}
            if ar.get('kind') == 'unavailable' or (ar.get('kind') and (ar.get('global_certification') or {}).get('status') != 'certified'):
                findings.append('iv:diagnostics:ar_unavailable')
            if ar.get('kind') == 'empty':
                findings.append('iv:diagnostics:ar_empty_requires_model_revision')
            if (diag.get('overidentification') or {}).get('pvalue', 1) < .05:
                findings.append('iv:diagnostics:overidentification_rejected_requires_model_revision')
        return list(dict.fromkeys(findings))
    if family == 'survival':
        for value in values:
            ph = (value.get('diagnostics') or {}).get('proportional_hazards') or {}
            if ph.get('status') == 'unverified':
                return ['survival:diagnostics:' + ph['reason']]
            if ph.get('status') == 'computed' and (ph.get('global') or {}).get('p_value', 1) < .05:
                return ['survival:diagnostics:ph_rejected_requires_model_revision']
    return []
