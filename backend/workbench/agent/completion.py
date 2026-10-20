"""Versioned, source-bound delivery requirements, not a statistical oracle.

Only registered products count. Step labels, model prose and a tool's success
receipt cannot replace a fitted model, diagnostics or an actual comparison.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from ..canonical import sha256_canonical
from .context_compiler import read_completion_artifact, read_completion_dataset_source
from .completion_profiles import companion_model, native_diagnostics, native_findings

VERSION = 'analysis-completion/v1'
PLAYBOOKS = {
    'ols': ('ols', 'ols_robust', 'ols_clustered', 'ols_hac', 'wls'),
    'survival': ('survival_cox',),
    'panel': ('panel_ols',),
    'did': ('did', 'did_twfe', 'twfe_did'),
    'iv': ('iv_2sls',),
    'time_series': ('time_series', 'arima', 'sarima', 'var', 'vecm'),
    'lmm': ('linear_mixed_effects',),
    'garch': ('time_series.arma_garch',),
}
_DATA_TYPES = frozenset({'processed_data', 'raw_data', 'derived_data'})
MODEL_NAMES = {key: names[0] for key, names in PLAYBOOKS.items()}
MODEL_NAMES.update(panel='panel', garch='arma_garch')
_REF = {'type': 'object', 'required': ['run_id', 'artifact_id'], 'properties': {
    'run_id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
    'artifact_id': {'type': 'string', 'minLength': 1, 'maxLength': 200}}, 'additionalProperties': False}
CONTRACT_SCHEMA = {'type': 'object', 'required': ['playbooks', 'source'], 'properties': {
    'playbooks': {'type': 'array', 'minItems': 1, 'maxItems': 8, 'uniqueItems': True,
                 'items': {'type': 'string', 'enum': list(PLAYBOOKS)}},
    'source': {**_REF, 'required': ['run_id', 'artifact_id', 'sha256'], 'properties': {
        **_REF['properties'], 'sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}}}}, 'additionalProperties': False}
INSPECT_SCHEMA = {"type": "object", "properties": {"source": _REF}, "additionalProperties": False}
EVIDENCE_SCHEMA = {'type': 'object', 'properties': {
    **{key: {'type': 'array', 'maxItems': 24, 'items': _REF} for key in ('models', 'diagnostics', 'sensitivity')},
    'report': _REF}, 'additionalProperties': False}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _test(value):
    """A computed diagnostic, rather than an unavailable/empty placeholder."""
    return (isinstance(value, dict) and not value.get('error')
            and value.get('status') not in {'failed', 'unavailable', 'not_applicable'}
            and ('p_value' not in value or (_number(value['p_value']) and 0 <= value['p_value'] <= 1))
            and any(_number(value.get(key)) for key in ('p_value', 'statistic', 'max', 'first_stage_f')))


def _model(artifact):
    if artifact is None or artifact.artifact_type not in {'model_result', 'workflow_result', 'model_result_packet'}:
        return None
    value = artifact.payload or {}
    # These are the persisted workflow/envelope owners, not arbitrary recursive
    # searches for a model_type string somewhere in a document.
    for _ in range(3):
        if isinstance(value.get('result'), dict):
            value = value['result']
        elif isinstance(value.get('payload'), dict):
            value = value['payload']
        else:
            break
    if value.get('model_type') == 'linear_mixed_effects' and artifact.artifact_type != 'model_result_packet':
        return None
    if value.get('status') in {'failed', 'unavailable', 'not_applicable'} or value.get('converged') is False:
        return None
    if value.get('fit_scope') == 'training_only':
        return None
    coefficients = value.get('coefficients')
    if not isinstance(value.get('model_id'), str) or not value['model_id']:
        return None
    if (not _number(value.get('nobs')) or value['nobs'] <= 0 or not isinstance(coefficients, dict)
            or not any(isinstance(row, dict) and _number(row.get('estimate'))
                       and _number(row.get('std_error')) and row['std_error'] >= 0 for row in coefficients.values())):
        return None
    return value


def _different_estimation(main, alternate):
    left, right = main.get('point_estimation_fingerprint'), alternate.get('point_estimation_fingerprint')
    # Changed uncertainty alone is not a change to the fitted specification.
    return isinstance(left, str) and isinstance(right, str) and len(left) == len(right) == 64 and left != right


def _diagnostics(family, values):
    if family == 'ols':
        return any(_test(v.get('breusch_pagan')) and _test(v.get('cooks_distance')) for v in values)
    if family == 'lmm':
        return any(v.get('status') == 'complete' and v.get('summary') and v.get('residual_definitions') for v in values)
    if native_diagnostics(family, values):
        return True
    # Native time-series packets use distinct contracts, not these
    # legacy OLS diagnostic dictionaries. Keep their positive path closed
    # until calibrated against actual producer fixtures, rather than treating
    # generic p-value-shaped JSON as family-specific evidence.
    return False



class _Products:
    """One bounded verification pass, shared by source and dependency checks."""
    def __init__(self, project_root):
        self.runs = (Path(project_root) / 'runs').resolve()
        self.cache = {}
        self.lineage_cache = {}
        self.verified_lineage = {}

    def load(self, ref):
        if not isinstance(ref, dict):
            return None
        run_id, artifact_id = ref.get('run_id'), ref.get('artifact_id')
        if not isinstance(run_id, str) or not isinstance(artifact_id, str):
            return None
        root = (self.runs / run_id).resolve()
        if root.parent != self.runs:
            return None
        key = (run_id, artifact_id)
        if key not in self.cache:
            if len(self.cache) >= 256:
                return None
            self.cache[key] = read_completion_artifact(root, artifact_id)
        return self.cache[key]

    def model(self, ref, artifact):
        model = _model(artifact)
        return companion_model(self, ref, artifact, model) if model is not None else None

    def ancestors(self, ref):
        seen, pending, found = set(), [ref], []
        while pending and len(seen) < 256:
            current = pending.pop()
            key = (current['run_id'], current['artifact_id'])
            if key in seen:
                continue
            seen.add(key)
            value = self.load(current)
            if value is None:
                continue
            found.append(value)
            pending.extend({'run_id': current['run_id'], 'artifact_id': item} for item in value.inputs)
            if value.artifact_type == 'report_collection' and value.payload:
                collection = value.payload
                if (collection.get('schema_version') == 'workflow-report-collection.v1'
                        and collection.get('status') == 'completed' and isinstance(collection.get('steps'), dict)):
                    for step in collection['steps'].values():
                        if not isinstance(step, dict) or step.get('status') != 'completed':
                            continue
                        references = step.get('artifact_ids')
                        if not isinstance(references, list):
                            continue
                        for item in references:
                            if not isinstance(item, str):
                                continue
                            # Native workflow model outputs are run-qualified;
                            # statistical products in the target run are local.
                            run_id, artifact_id = item.split(':', 1) if ':' in item else (current['run_id'], item)
                            pending.append({'run_id': run_id, 'artifact_id': artifact_id})
            if value.artifact_type == 'raw_data':
                run_id = current['run_id']
                if run_id not in self.lineage_cache:
                    self.lineage_cache[run_id] = read_completion_dataset_source(self.runs / run_id)
                lineage = self.lineage_cache[run_id]
                if lineage is not None and value.sha256 == lineage['upload_sha256']:
                    parent = self.load(lineage['source'])
                    if (parent is not None and parent.artifact_type in _DATA_TYPES
                            and parent.sha256 == lineage['source']['sha256']):
                        self.verified_lineage[run_id] = {'run_id': run_id, 'sha256': lineage['sha256']}
                        pending.append(lineage['source'])
        return found


def source_receipt(project_root, ref):
    """Discover a registered dataset identity without exposing rows or paths."""
    value = _Products(project_root).load(ref)
    if value is None or value.artifact_type not in _DATA_TYPES:
        return None
    return {'run_id': ref['run_id'], 'artifact_id': ref['artifact_id'], 'sha256': value.sha256}


def evaluate(project_root, contract, evidence):
    """Recheck actual products on every final answer, including after restart.

    Missing or unsupported evidence stays partial. There is no model-call path,
    no result creation, and no permission decision inside this read-only gate.
    """
    missing = []
    products = _Products(project_root)
    evidence = evidence or {}
    if not contract:
        return _result(['completion_contract:select_playbooks_and_source'], products)
    else:
        families = contract['playbooks']
        source = products.load(contract['source'])
        if (source is None or source.sha256 != contract['source']['sha256']
                or source.artifact_type not in _DATA_TYPES):
            source = None
            missing.append('source:changed_or_unavailable')
    groups = {key: [(ref, products.load(ref)) for ref in evidence.get(key, [])]
              for key in ('models', 'diagnostics', 'sensitivity')}

    def bound(ref):
        return source is not None and any(a.sha256 == source.sha256 for a in products.ancestors(ref))

    for family in families:
        names = PLAYBOOKS[family]
        matches = [(ref, model) for ref, artifact in groups['models']
                   if (model := products.model(ref, artifact)) is not None and model.get('model_type') in names and bound(ref)]
        if len(matches) != 1:
            missing.append(f'{family}:model:{MODEL_NAMES[family]}')
        main_ref, main = matches[0] if len(matches) == 1 else (None, None)
        diagnostic_values = [artifact.payload for ref, artifact in groups['diagnostics']
                             if artifact is not None and artifact.artifact_type in {'model_diagnostic', 'lmm_analysis_evidence', 'analysis_completion_evidence'}
                             and bound(ref) and main_ref and ref['run_id'] == main_ref['run_id']
                             and artifact.payload and artifact.payload.get('model_id') == main.get('model_id')
                             and (family != 'lmm' or artifact.artifact_type == 'lmm_analysis_evidence')
                             and (main.get('model_type') not in {'survival_cox'}
                                  or ref['artifact_id'] == main['model_id'] + '.completion')]
        if not _diagnostics(family, diagnostic_values):
            reason = 'computed_and_model_bound' if family in {'ols', 'lmm', 'survival'} else 'native_profile_unverified'
            missing.append(f'{family}:diagnostics:{reason}')
        missing.extend(native_findings(family, diagnostic_values))
        alternates = [model for ref, artifact in groups['sensitivity']
                      if (model := products.model(ref, artifact)) is not None and model.get('model_type') in names and bound(ref)]
        comparisons = [alternate for alternate in alternates if main and _different_estimation(main, alternate)]
        if not comparisons:
            missing.append(f'{family}:sensitivity:distinct_point_estimation')
        if family == 'ols' and any((v.get('cooks_distance') or {}).get('n_high', 0) > 0 for v in diagnostic_values):
            sample = main.get('analysis_sample_fingerprint')
            if not sample or not any(a.get('analysis_sample_fingerprint') and a['analysis_sample_fingerprint'] != sample for a in comparisons):
                missing.append('ols:sensitivity:influence_sample_comparison')
    report_ref = evidence.get('report')
    report = products.load(report_ref)
    json_report = report is not None and report.payload and report.payload.get('sections')
    native_report = report is not None and report.suffix in {'.html', '.pdf', '.md'} and report.size_bytes > 0
    if report is None or report.artifact_type != 'report' or not (json_report or native_report):
        missing.append('report:registered_nonempty')
    elif not bound(report_ref) or not all(
        artifact and any(a.sha256 == artifact.sha256 for a in products.ancestors(report_ref))
        for _, artifact in groups['models'] + groups['diagnostics'] + groups['sensitivity']
    ):
        missing.append('report:result_sources')
    return _result(missing, products)


def _result(missing, products):
    verified = [{'run_id': run, 'artifact_id': key, 'sha256': value.sha256}
                for (run, key), value in products.cache.items() if value is not None]
    return {'version': VERSION, 'status': 'partial' if missing else 'requirements_met',
            'missing': missing, 'scientific_validity': 'not_certified', 'verified_artifacts': verified[:8],
            'verified_artifact_count': len(verified), 'omitted_verified_artifacts': max(0, len(verified) - 8),
            'verified_lineage': list(products.verified_lineage.values())[:8],
            'verified_lineage_count': len(products.verified_lineage),
            'verified_manifest_sha256': sha256_canonical({'artifacts': verified, 'lineage': products.verified_lineage}),
            'limitations': ['Delivery requirements do not certify method choice, identification, inference validity, report fidelity or export rendering quality.']}


_CLAIM = re.compile(
    r'分析(?:已|已经|全部|现已|已全部|现已全部)?完成|(?:已|已经)完成(?:全部|所有)?(?:分析|研究)'
    r'|(?:analysis|analyses|research)\s+(?:(?:is|are|has been|have been)\s+)?(?:now\s+)?(?:complete[d]?|finished)'
    r'|(?:finished|completed)\s+(?:the\s+)?(?:analysis|analyses|research)', re.I)
_GENERIC_CLAIM = re.compile(r'全部完成|everything\s+is\s+(?:done|complete)', re.I)
_FULL_REQUEST = re.compile(r'完整分析|全部分析|全面分析|(?:full|complete|entire|end.to.end)\s+analysis', re.I)


def claims_completion(content, request_text=None):
    return bool(_CLAIM.search(content) or (_GENERIC_CLAIM.search(content)
                and (request_text is None or _FULL_REQUEST.search(request_text))))


def _missing_label(code, language):
    family, _, requirement = code.partition(':')
    special = {
        'survival:diagnostics:ph_rejected_requires_model_revision': (
            'Cox PH was rejected; the time-varying effect requires an explicit model revision.',
            'Cox 比例风险检验拒绝：时变效应尚未用适用模型处理，需明确修订方案。'),
        'survival:diagnostics:delayed_entry_not_validated': (
            'The Cox PH test with delayed entry has not been validated.',
            '延迟入组情形的 Cox 比例风险检验尚未验证。')}
    if code in special:
        return special[code][1 if language == 'zh' else 0]

    if language != 'zh':
        labels = {'completion_contract': 'Select the analysis playbooks and verify the dataset source.',
                  'source': 'The dataset source changed or is unavailable.',
                  'report': 'A report with verified result sources is missing.'}
        if family in labels:
            return labels[family]
        label = {'ols': 'OLS', 'survival': 'Cox survival', 'panel': 'Panel', 'did': 'DID',
                 'iv': 'IV', 'time_series': 'Time series', 'lmm': 'LMM', 'garch': 'GARCH'}[family]
        return label + ': ' + ('native diagnostic evidence has not been validated.' if 'native_profile' in requirement
                               else 'a source-bound primary fit is missing.' if requirement.startswith('model:')
                               else 'computed, model-bound diagnostics are missing.' if requirement.startswith('diagnostics:')
                               else 'a fitted sensitivity comparison is missing.')
    labels = {'completion_contract': '尚未固定分析剧本和核验数据来源。',
              'source': '数据来源已改变或当前不可用。',
              'report': '缺少引用已核验结果的报告。'}
    if family in labels:
        return labels[family]
    label = {'ols': 'OLS', 'survival': 'Cox 生存分析', 'panel': '面板分析', 'did': 'DID',
             'iv': 'IV', 'time_series': '时间序列', 'lmm': 'LMM', 'garch': 'GARCH'}[family]
    if 'native_profile' in requirement:
        return label + '：原生诊断证据的完成规则尚未校准。'
    if requirement.startswith('model:'):
        return label + ' 主模型：缺少与数据来源一致的拟合结果。'
    if requirement.startswith('diagnostics:'):
        return label + '：缺少已计算且绑定主模型的诊断。'
    if 'influence_sample' in requirement:
        return label + '：缺少针对高影响观测、改变分析样本的敏感性对照。'
    return label + '：缺少真实拟合、改变点估计设定的敏感性对照。'


def publication(content: str, result: dict, language: str, *, final=True, request_text=""):
    """Publish the machine state; a rejected completion claim is not a result."""
    active = result['missing'] != ['completion_contract:select_playbooks_and_source']
    claim = claims_completion(content, request_text) or bool(active and _GENERIC_CLAIM.search(content))
    if (result['status'] == 'requirements_met'
            or (not claim and (not final or result['missing'] == ['completion_contract:select_playbooks_and_source']))):
        return content
    notice = partial_notice(result, language)
    # Preserve useful interim findings, but never republish a rejected claim.
    return notice if claim else notice + '\n\n' + content


def partial_notice(result, language):
    heading = '部分完成：以下必需证据尚未核验。' if language == 'zh' else 'Partially complete: required evidence remains unverified.'
    missing = list(dict.fromkeys(_missing_label(item, language) for item in result['missing']))
    return heading + '\n' + '\n'.join('- ' + item for item in missing[:32])
