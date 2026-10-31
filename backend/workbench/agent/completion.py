"""Versioned, source-bound delivery requirements, not a statistical oracle.

Only registered products count. Step labels, model prose and a tool's success
receipt cannot replace a fitted model, diagnostics or an actual comparison.
"""
from __future__ import annotations

import math
import json
import re
from pathlib import Path
from typing import Any

from ..canonical import sha256_canonical
from .context_compiler import read_completion_artifact, read_completion_dataset_source, read_arima_completion_product, read_garch_completion_product, completion_candidate_refs, registered_model_completion_ref
from .completion_sensitivity import INFLUENCE_DISCLOSURE, MAX_OPTIONS, SENSITIVITY_NEXT_STEP, influence_option, specification_options
from .completion_profiles import NATIVE_COMPANIONS, companion_model, iv_ar_wrapper, native_diagnostics, native_findings, verified_iv_ar, with_iv_ar
from .completion_targets import TARGET_SCHEMA, computed_result, matches_target, requested_targets
from .plan_criteria import REQUIREMENTS_SCHEMA, PROOFS_SCHEMA

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
    'scope': {'type': 'string', 'enum': ['analysis', 'question']},
    'requirements': REQUIREMENTS_SCHEMA,
    'target': TARGET_SCHEMA,
    'playbooks': {'type': 'array', 'maxItems': 8, 'uniqueItems': True,
                 'items': {'type': 'string', 'enum': list(PLAYBOOKS)}},
    'source': {**_REF, 'required': ['run_id', 'artifact_id', 'sha256'], 'properties': {
        **_REF['properties'], 'sha256': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'}}}}, 'additionalProperties': False,
    'if': {'required': ['scope'], 'properties': {'scope': {'const': 'question'}}},
    'then': {'properties': {'playbooks': {'maxItems': 0}}},
    'else': {'properties': {'playbooks': {'minItems': 1}}}}
#: The Agent names the source; the Workbench binds its sha256 from the registered artifact
#: (a weaker model miscopied one hex digit and retried a refused plan to the end of its
#: nudges, free-route no-thinking round, panel_fe, 2026-10-22).
AGENT_CONTRACT_SCHEMA = {**CONTRACT_SCHEMA, 'properties': {**CONTRACT_SCHEMA['properties'], 'source': {
    **CONTRACT_SCHEMA['properties']['source'], 'required': ['run_id', 'artifact_id'],
    'description': 'run_id and artifact_id of the registered dataset; the Workbench binds its sha256.'}}}
# A source may carry the sha256 the Agent read before; the Workbench returns the verified one.
INSPECT_SCHEMA = {"type": "object", "properties": {"source": {**_REF, "properties": {
    **_REF["properties"], "sha256": {"type": "string", "maxLength": 128}}}}, "additionalProperties": False}
EVIDENCE_SCHEMA = {'type': 'object', 'properties': {
    'requirements': PROOFS_SCHEMA,
    **{key: {'type': 'array', 'maxItems': 24, 'items': _REF} for key in ('models', 'diagnostics', 'sensitivity', 'results')},
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
        self.native_models = {}
        self.native_diagnostics = {}

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
        if artifact is not None and (artifact.artifact_type in {'p7_analysis', 'workflow_capability_result'}
                or (artifact.payload or {}).get('model_type') == 'time_series.arma_garch'):
            key = (ref['run_id'], ref['artifact_id'])
            if key not in self.native_models:
                reader = read_arima_completion_product if artifact.artifact_type == 'p7_analysis' else read_garch_completion_product
                projected = reader(self.runs / ref['run_id'], artifact)
                self.native_models[key] = projected[0] if projected else None
                if projected:
                    self.native_diagnostics[key] = projected[1]
            return self.native_models[key]
        model = _model(artifact)
        return companion_model(self, ref, artifact, model) if model is not None else None

    def diagnostic(self, ref, artifact):
        return self.native_diagnostics.get((ref['run_id'], ref['artifact_id']), artifact.payload if artifact else None)

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
            if value.artifact_type == 'report_collection' and value.payload and 'result_sources' in value.payload:
                pins = value.payload['result_sources']
                if (not isinstance(pins, list) or len(pins) > 24
                        or any(not isinstance(pin, dict) or not isinstance(pin.get('sha256'), str)
                            or (owned := self.load(pin)) is None or owned.sha256 != pin['sha256'] for pin in pins)):
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
                    review = collection.get('research_review')
                    if isinstance(review, dict):
                        pending.extend(ref for ref in review.get('result_refs', [])
                            if isinstance(ref, dict) and all(isinstance(ref.get(key), str)
                                for key in ['run_id', 'artifact_id']))
                    pending.extend({'run_id': pin['run_id'], 'artifact_id': pin['artifact_id']}
                                   for pin in collection.get('result_sources', []))
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


class CompletionEvidenceError(ValueError):
    def __init__(self, message, *, corrections=()):
        super().__init__(message)
        self.code = 'COMPLETION_EVIDENCE_UNRESOLVED'
        self.corrections = list(corrections)


def _source_bound(products, source, ref):
    return source is not None and any(item.sha256 == source.sha256 for item in products.ancestors(ref))


def report_missing_sources(products, report_ref, selected_refs):
    """Shared provenance coverage for playbooks and approved report requirements."""
    ancestors = products.ancestors(report_ref)
    return [ref for ref in selected_refs if (value := products.load(ref)) is None
            or not any(item.sha256 == value.sha256 for item in ancestors)]


def _registered_alias_replacement(products, source, ref):
    """Suggest a unique verified model identity; never rewrite submitted refs."""
    if not isinstance(ref, dict) or not isinstance(ref.get('run_id'), str):
        return None
    alias = ref.get('artifact_id')
    if not isinstance(alias, str) or not alias.startswith('model_results:'):
        return None
    root = (products.runs / ref['run_id']).resolve()
    if root.parent != products.runs:
        return None
    model_id = alias[len('model_results:'):]
    registered = registered_model_completion_ref(root, {'model_id': model_id})
    if registered is None:
        return None
    candidate = {'run_id': registered['run_id'], 'artifact_id': registered['artifact_id']}
    artifact = products.load(candidate)
    model = products.model(candidate, artifact)
    return (candidate if model is not None and model.get('model_id') == model_id
            and _source_bound(products, source, candidate) else None)


def _evidence_binding_errors(products, source, evidence):
    errors, corrections = [], []
    for slot in ('models', 'diagnostics', 'sensitivity', 'results', 'report'):
        values = evidence.get(slot, [])
        values = [values] if slot == 'report' and values else values
        if not isinstance(values, list):
            errors.append(f'{slot}: references must be a list')
            continue
        for index, ref in enumerate(values):
            numeric_alias = (isinstance(ref, dict) and isinstance(ref.get('artifact_id'), str)
                             and ref['artifact_id'].startswith('model_results:'))
            # A plan can record pending delivery work. Diagnostics, comparisons
            # and report collections keep their existing family-specific gate;
            # a uniform ancestry rule here must not block a verified primary's
            # progress because its report has not been composed yet.
            if slot not in ('models', 'results') and not numeric_alias:
                continue
            artifact = products.load(ref)
            valid = not numeric_alias and artifact is not None and _source_bound(products, source, ref)
            if valid and slot == 'results':
                valid = computed_result(products, ref, artifact)
            if valid and slot == 'models':
                valid = products.model(ref, artifact) is not None
            if valid:
                continue
            field = f'{slot}[{index}]'
            errors.append(field + ': no verified source-bound registered artifact')
            if (slot == 'results' and iv_ar_wrapper(artifact) is not None
                    and _source_bound(products, source, ref)):
                errors.append('This iv.ar_confidence artifact belongs in completion_evidence.diagnostics: '
                    + json.dumps(ref, ensure_ascii=False)
                    + '. Nothing was saved or moved; this role hint does not certify its model, source or AR proof')
            replacement = (_registered_alias_replacement(products, source, ref)
                           if slot in ('models', 'results') else None)
            if replacement is not None:
                corrections.append({'field': field, 'rejected_ref': dict(ref),
                                    'replacement_ref': replacement})
    return errors, corrections


def validate_completion_evidence(project_root, contract, evidence):
    """Check concrete answer bindings; pending delivery refs stay gate-owned."""
    products = _Products(project_root)
    source = products.load(contract.get('source')) if isinstance(contract, dict) else None
    if (source is None or source.artifact_type not in _DATA_TYPES
            or source.sha256 != contract.get('source', {}).get('sha256')):
        raise CompletionEvidenceError('Completion evidence needs a verified completion source first.')
    if not isinstance(evidence, dict):
        raise CompletionEvidenceError('Completion evidence must be an object of registered references.')
    errors, corrections = _evidence_binding_errors(products, source, evidence)
    if errors:
        raise CompletionEvidenceError('; '.join(errors[:4]) +
            '. Numeric result_ref aliases are not artifact_id values. Inspect existing registered receipts; '
            'use the explicit replacement refs when provided, without rerunning or weakening completion.',
            corrections=corrections[:8])
    return evidence


def source_receipt(project_root, ref):
    """Discover a registered dataset identity without exposing rows or paths."""
    value = _Products(project_root).load(ref)
    if value is None or value.artifact_type not in _DATA_TYPES:
        return None
    return {'run_id': ref['run_id'], 'artifact_id': ref['artifact_id'], 'sha256': value.sha256}


def evaluate(project_root, contract, evidence, *, suggest=False, options=False, _products=None):
    """Recheck actual products on every final answer, including after restart.

    Missing or unsupported evidence stays partial. There is no model-call path,
    no result creation, and no permission decision inside this read-only gate.
    """
    missing = []
    products = _products if _products is not None else _Products(project_root)
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
              for key in ('models', 'diagnostics', 'sensitivity', 'results')}
    repairs = []
    sensitivity_options = []
    disclosures = []

    def bound(ref):
        return source is not None and any(a.sha256 == source.sha256 for a in products.ancestors(ref))

    target = contract.get('target')
    if target and not any(bound(ref) and matches_target(target, products.load(ref), contract['source']['sha256'])
                          for ref in evidence.get('results', [])):
        missing.append('target:computed_estimand_not_bound')
    if contract.get('scope') == 'question':
        results = [(ref, products.load(ref)) for ref in evidence.get('results', [])]
        if not results or any(not bound(ref) or not computed_result(products, ref, artifact) for ref, artifact in results):
            missing.append('question:computed_source_bound_result')
        result = {**_result(missing, products, target=target), 'scope': 'question'}
        if missing and (suggest or options):
            errors, corrections = _evidence_binding_errors(products, source, evidence)
            if errors:
                result['repair_steps'] = corrections or [{'reason': 'unverified_result_binding'}]
                refs = [item['replacement_ref'] for item in corrections[:4]]
                result['next_step'] = (
                    'Call update_plan with completion_evidence.results using these verified registered references: '
                    + json.dumps(refs, ensure_ascii=False)
                    + '. This repairs identity only; the gate must recheck the source and result. Keep existing computed results; do not refit just to repair a reference.'
                    if refs else 'Inspect completed operation receipts and copy their canonical completion_ref into '
                    'update_plan completion_evidence.results. The submitted result is unverified; do not invent IDs, '
                    'claim completion, or rerun merely to create plan history.')
                # The repair catalog has verified real products too. Expose
                # their exact references while retaining the original missing
                # state; discovering a replacement never accepts the alias.
                result.update(_result(missing, products, target=target))
        return result

    for family in families:
        names = PLAYBOOKS[family]
        matches = [(ref, model) for ref, artifact in groups['models']
                   if (model := products.model(ref, artifact)) is not None and model.get('model_type') in names and bound(ref)]
        if len(matches) != 1:
            missing.append(f'{family}:model:{MODEL_NAMES[family]}')
            if suggest:
                repairs.append({'family': family, 'reason': 'ambiguous_primary' if matches else 'no_eligible_primary',
                    'candidates': [ref for ref, _ in matches],
                    'action': 'Bind exactly one eligible source-bound primary model. Use the fixed specification and research question, never significance, to choose; put other fitted specifications in sensitivity. Summary artifacts are not model results.'})
        main_ref, main = matches[0] if len(matches) == 1 else (None, None)
        diagnostic_values = [value for ref, artifact in groups['diagnostics']
                             if artifact is not None and artifact.artifact_type in {'model_diagnostic', 'lmm_analysis_evidence', 'analysis_completion_evidence', 'p7_analysis', 'workflow_capability_result', 'model_result'}
                             and bound(ref) and main_ref and ref['run_id'] == main_ref['run_id']
                             and (value := products.diagnostic(ref, artifact)) and value.get('model_id') == main.get('model_id')
                             and (family != 'lmm' or artifact.artifact_type == 'lmm_analysis_evidence')
                             and (main.get('model_type') not in NATIVE_COMPANIONS
                                  or ref['artifact_id'] == main['model_id'] + '.completion')]
        if family == 'iv' and main_ref:
            diagnostic_values = with_iv_ar(products, main_ref, main, diagnostic_values,
                [(ref, artifact) for ref, artifact in groups['diagnostics'] if artifact and bound(ref)])
            if (suggest or options) and any(((v.get('diagnostics') or {}).get('iv', {}).get('weak_instruments') or {}).get('anderson_rubin_95', {}).get('kind') == 'not_computed' for v in diagnostic_values):
                repairs.append({'family': 'iv', 'reason': 'ar_not_requested',
                    'operation': {'operation_id': 'iv.ar_confidence',
                                  'spec': {'model_run_id': main_ref['run_id'], 'model_ref': main['model_id']}},
                    'action': 'Explicitly propose this fixed-model AR operation under the original permissions; do not change its specification or covariance. Include the resulting evidence in diagnostics and in a newly composed report.'})
        if not _diagnostics(family, diagnostic_values):
            reason = 'computed_and_model_bound' if family in {'ols', 'lmm', 'survival', 'iv', 'panel', 'did'} else 'native_profile_unverified'
            missing.append(f'{family}:diagnostics:{reason}')
        missing.extend(native_findings(family, diagnostic_values))
        alternates = [model for ref, artifact in groups['sensitivity']
                      if (model := products.model(ref, artifact)) is not None and model.get('model_type') in names and bound(ref)]
        comparisons = [alternate for alternate in alternates if main and _different_estimation(main, alternate)]
        if not comparisons:
            missing.append(f'{family}:sensitivity:distinct_point_estimation')
        influential = [v['cooks_distance'] for v in diagnostic_values if (v.get('cooks_distance') or {}).get('n_high', 0) > 0]
        influence_missing = False
        offered = []
        if family == 'ols' and influential:
            sample = main.get('analysis_sample_fingerprint')
            if not sample or not any(a.get('analysis_sample_fingerprint') and a['analysis_sample_fingerprint'] != sample for a in comparisons):
                option = influence_option(project_root, main_ref, main, influential[0].get('threshold')) if main_ref else None
                if option and 'unavailable' in option:
                    # The data rules the refit out: the report states why instead of the gate looping.
                    disclosures.append({'requirement': 'ols:sensitivity:influence_sample_comparison',
                                        'reason': option['unavailable'], 'action': INFLUENCE_DISCLOSURE})
                else:
                    missing.append('ols:sensitivity:influence_sample_comparison')
                    influence_missing = True
                    offered = [option]
        if (suggest or options) and main_ref and (influence_missing or not comparisons):
            if not comparisons:
                offered += specification_options(project_root, main_ref, main)
            sensitivity_options.extend(option for option in offered if option)
            if suggest:
                repairs.append({'family': family, 'reason': 'no_distinct_sensitivity_fit', 'action': SENSITIVITY_NEXT_STEP})
    report_ref = evidence.get('report')
    report = products.load(report_ref)
    json_report = report is not None and report.payload and report.payload.get('sections')
    native_report = report is not None and report.suffix in {'.html', '.pdf', '.md'} and report.size_bytes > 0
    if report is None or report.artifact_type != 'report' or not (json_report or native_report):
        missing.append('report:registered_nonempty')
        if suggest:
            repairs.append({'reason': 'unregistered_or_empty_report',
                'action': 'Use an exact registered report reference from the catalog or completed-operation receipt, including its actual format suffix. Never invent or append an ID. Compose a report if no verified report covers the required results.'})
    elif not bound(report_ref) or report_missing_sources(products, report_ref,
            [ref for ref, _ in groups['models'] + groups['diagnostics'] + groups['sensitivity'] + groups['results']]):
        missing.append('report:result_sources')
        if suggest:
            repairs.append({'reason': 'report_does_not_cover_selected_evidence',
                'action': 'Compose a report using the exact selected primary, diagnostics, sensitivity and AR references. An earlier report cannot cover evidence produced after it; do not relabel or reuse it as complete.'})
    catalog = _evidence_catalog(products, source, contract, evidence, bound, groups) if suggest else None
    result = _result(missing, products, target=target)
    if suggest:
        result['evidence_catalog'] = catalog
    if suggest or repairs:
        result['repair_steps'] = repairs
    if sensitivity_options:
        result['sensitivity_options'] = sensitivity_options[:MAX_OPTIONS]
    if disclosures:
        result['disclosures'] = disclosures
    return result


def _evidence_catalog(products, source, contract, evidence, bound, groups):
    """Explicit inspection only: exact verified references, no automatic selection."""
    catalog = {'models': [], 'reports': [], 'run_limit': 4, 'references_per_run_limit': 48,
               'model_limit': 8, 'report_limit': 4, 'omitted_model_count': 0, 'omitted_report_count': 0}
    if source is None:
        return catalog
    refs = [contract['source'], *evidence.get('models', []), *evidence.get('diagnostics', []),
            *evidence.get('sensitivity', []), *([evidence['report']] if evidence.get('report') else [])]
    runs = list(dict.fromkeys(ref['run_id'] for ref in refs))
    catalog['omitted_run_count'] = max(0, len(runs) - 4)
    candidates = []
    for run in runs[:4]:
        root = (products.runs / run).resolve()
        if root.parent == products.runs:
            candidates.extend((ref, products.load(ref)) for ref in completion_candidate_refs(root))
    candidates = [(ref, artifact) for ref, artifact in candidates if artifact is not None and bound(ref)]
    for ref, artifact in candidates:
        model = products.model(ref, artifact)
        if model is not None:
            for family in contract['playbooks']:
                if model.get('model_type') not in PLAYBOOKS[family]:
                    continue
                diagnostics = [(dref, products.diagnostic(dref, diagnostic)) for dref, diagnostic in candidates
                    if dref['run_id'] == ref['run_id']
                    and (diagnostic.artifact_type in {'model_diagnostic', 'lmm_analysis_evidence', 'analysis_completion_evidence'}
                         or (family in {'time_series', 'garch'} and dref == ref))
                    and (model.get('model_type') not in NATIVE_COMPANIONS
                         or dref['artifact_id'] == model['model_id'] + '.completion')
                    and (value := products.diagnostic(dref, diagnostic)) and value.get('model_id') == model['model_id']
                    and (family != 'lmm' or diagnostic.artifact_type == 'lmm_analysis_evidence')]
                if len(catalog['models']) < 8:
                    eligible = [dref for dref, _ in diagnostics]
                    values = [value for _, value in diagnostics]
                    if family == 'iv':
                        supplements = [(dref, d) for dref, d in candidates
                            if verified_iv_ar(products, ref, model, dref, d) is not None]
                        eligible.extend(dref for dref, _ in supplements)
                        values = with_iv_ar(products, ref, model, values, supplements)
                    catalog['models'].append({'family': family, 'ref': ref, 'model_id': model['model_id'],
                        'diagnostics': eligible[:2], 'omitted_diagnostic_count': max(0, len(eligible)-2),
                        'diagnostics_meet_requirements': _diagnostics(family, values) and not native_findings(family, values),
                        'diagnostic_findings': native_findings(family, values)})
                else:
                    catalog['omitted_model_count'] += 1
        elif artifact.artifact_type == 'report' and (
                (artifact.payload and artifact.payload.get('sections'))
                or (artifact.suffix in {'.html', '.pdf', '.md'} and artifact.size_bytes > 0)):
            ancestors = products.ancestors(ref)
            covers = all(value and any(a.sha256 == value.sha256 for a in ancestors)
                         for _, value in groups['models'] + groups['diagnostics'] + groups['sensitivity'])
            if len(catalog['reports']) < 4:
                catalog['reports'].append({'ref': ref, 'covers_submitted_evidence': bool(covers)})
            else:
                catalog['omitted_report_count'] += 1
    return catalog


def _result(missing, products, *, target=None):
    verified = [{'run_id': run, 'artifact_id': key, 'sha256': value.sha256}
                for (run, key), value in products.cache.items() if value is not None]
    return {**({'target': target} if target else {}), 'version': VERSION, 'status': 'partial' if missing else 'requirements_met',
            'missing': missing, 'scientific_validity': 'not_certified', 'verified_artifacts': verified[:8],
            'verified_artifact_count': len(verified), 'omitted_verified_artifacts': max(0, len(verified) - 8),
            'verified_lineage': list(products.verified_lineage.values())[:8],
            'verified_lineage_count': len(products.verified_lineage),
            'verified_manifest_sha256': sha256_canonical({'artifacts': verified, 'lineage': products.verified_lineage}),
            'limitations': ['Delivery requirements do not certify method choice, identification, inference validity, report fidelity or export rendering quality.']}


_CLAIM = re.compile(
    r'分析(?:已|已经|全部|现已|已全部|现已全部)?完成|(?:已|已经)完成(?:全部|所有)?(?:分析|研究)'
    r'|(?:analysis|analyses|research)\s+(?:(?:is|are|has been|have been)\s+)?(?:now\s+)?(?:complete[d]?|finished)'
    r'|(?:finished|completed)\s+(?:the\s+)?(?:analysis|analyses|research)'
    r'|(?:本|当前|这项|该)?问题(?:导向)?(?:已|已经|现已)?完成(?=$|[\s。！？.!?（(，,；;])'
    r'|(?:本|当前|该)?问题(?:的)?(?:全部|所有)(?:要求)?(?:已|均已)?满足(?=$|[\s。！？.!?（(，,；;])'
    r'|(?:^|\n)[ \t✅✓*#-]*(?:判断标准)?全部满足(?=$|[\s。！？.!?（(，,；;：:])'
    r'|(?:focused\s+)?question\s+(?:(?:is|has been)\s+)?complete[d]?\b'
    r'|(?:focused\s+)?question\s+requirements\s+(?:are\s+)?satisfied\b(?!\s+(?:(?:only\s+)?partially|in\s+part)\b)', re.I)
_GENERIC_CLAIM = re.compile(r'全部完成|everything\s+is\s+(?:done|complete)', re.I)
_FULL_REQUEST = re.compile(r'完整分析|全部分析|全面分析|(?:full|complete|entire|end.to.end)\s+analysis', re.I)


def enforce_request_scope(result, request_text):
    requested = requested_targets(request_text)
    if requested and requested != {(result.get('target') or {}).get('estimand')}:
        result = {**result, 'status': 'partial',
                  'missing': list(dict.fromkeys([*result['missing'], 'target:requested_estimand_unbound']))}
    if result.get('scope') == 'question' and _FULL_REQUEST.search(request_text or ''):
        return {**result, 'status': 'partial',
                'missing': list(dict.fromkeys([*result['missing'], 'task_scope:full_analysis_required']))}
    return result


def claims_completion(content, request_text=None):
    return bool(_CLAIM.search(content) or (_GENERIC_CLAIM.search(content)
                and (request_text is None or _FULL_REQUEST.search(request_text))))


def _missing_label(code, language):
    family, _, requirement = code.partition(':')
    special = {
        'plan:approved_criteria_unverified': (
            'The approved criteria or expected outputs are not fully verified. Keep existing findings; '
            'bind the original confirmed requests and registered artifacts, or retain partial completion for human takeover. '
            'Do not rerun completed work or remove commitments to obtain a pass.',
            '已批准的判据或预期产物尚未全部核验。保留已有结果，绑定原始已确认请求和注册产物；'
            '无法核验时保持部分完成并交由用户接管，不要重复执行或删去承诺来取得通过。'),
        'task_requirements:unverified': (
            'The original user task requirements are unverified. Restore the user-message evidence or explicitly revise the plan as a person before certifying completion.',
            '原始用户任务要求尚未核验。需恢复真实用户消息证据，或由用户明确修订计划后才能确认完成。'),
        'target:requested_estimand_unbound': (
            'Fix the requested causal target in completion.target; do not substitute a regression coefficient.',
            '需固定请求的因果目标估计量，不能用普通回归系数替代。'),
        'target:computed_estimand_not_bound': (
            'No verified result matches the target estimand and variable bindings. Estimate that target with an applicable method, or report it as unverified and keep a takeover state; do not relabel ATT as ATC/ATE.',
            '没有已核验产物匹配目标估计量与变量绑定。需用适用方法计算，或明确未验证并保留可接管状态，不能将 ATT 改称 ATC／ATE。'),
        'question:computed_source_bound_result': (
            'Bind a successful computed answer artifact to the verified dataset source.',
            '缺少与已核验数据来源绑定、成功计算的回答产物。'),
        'task_scope:full_analysis_required': (
            'The request requires a full analysis; a focused-question contract cannot satisfy it.',
            '用户要求完整分析，单项问题合同不能替代完整分析验收。'),
        'garch:diagnostics:invalid_variance_parameters': (
            'Production variance parameters fail their native constraints.',
            '生产方差参数未通过原生约束，需修正模型。'),
        'garch:diagnostics:inadmissible_mean_roots': (
            'Production mean roots are inadmissible; revise the specification.',
            '生产均值模型的根不满足平稳或可逆条件，需修正设定。'),
        'garch:diagnostics:calendar_gaps_unverified': (
            'Regular-calendar gaps remain; revise the time interpretation.',
            '规则日历存在间隙，需修正时间解释，不能自动填补。'),
        'garch:diagnostics:stationarity_unresolved': (
            'Stationarity remains unresolved for the transformed GARCH input.',
            'GARCH 实际转换序列的平稳性仍未解决。'),
        'garch:diagnostics:mean_correlation_requires_revision': (
            'Production standardized innovations retain mean correlation.',
            '生产标准化创新仍有均值自相关，需修正均值设定。'),
        'garch:diagnostics:remaining_arch_requires_revision': (
            'Production standardized innovations retain ARCH.',
            '生产标准化创新仍有 ARCH，需修正方差设定。'),
        'time_series:diagnostics:irregular_sampling_unverified': (
            'Observed times are irregular; an equal-spacing interpretation needs revision.',
            '观测时间不规则；需修正等间距解释，不能自动填补。'),
        'time_series:diagnostics:inadmissible_arima_roots': (
            'ARIMA roots are inadmissible; revise the frozen model specification.',
            'ARIMA 根不满足平稳或可逆条件，需修正模型设定。'),
        'time_series:diagnostics:stationarity_unresolved': (
            'Stationarity remains unresolved by the fixed ADF/KPSS diagnostics; revise or explain the transformation.',
            '固定 ADF／KPSS 诊断尚未解决平稳性问题；需修正或解释转换设定。'),
        'time_series:diagnostics:residual_correlation_requires_revision': (
            'Residual autocorrelation remains; revise the mean specification.',
            '残差仍有自相关，需修正均值设定。'),
        'time_series:diagnostics:conditional_variance_requires_revision': (
            'Residual ARCH remains; assess an applicable variance model.',
            '残差仍有 ARCH，需评估适用的条件方差模型。'),
        'survival:diagnostics:ph_rejected_requires_model_revision': (
            'Cox PH was rejected; the time-varying effect requires an explicit model revision.',
            'Cox 比例风险检验拒绝：时变效应尚未用适用模型处理，需明确修订方案。'),
        'panel:diagnostics:within_dependence_inference_unverified': (
            'Inference allowing within-unit dependence has not been validated for this panel fit.',
            '该面板拟合的组内相关推断尚未核验；不能用逐行 HC 当作固定 T 的聚类推断。'),
        'did:diagnostics:within_dependence_inference_unverified': (
            'Inference allowing within-unit dependence has not been validated for this DID fit.',
            '该 DID 拟合的组内相关推断尚未核验。'),
        'panel:diagnostics:few_clusters_inference_unverified': (
            'There are fewer than 10 clusters; small-cluster inference remains unverified.',
            '聚类少于 10 个，少聚类推断仍未验证，不能声称分析完成。'),
        'did:diagnostics:few_clusters_inference_unverified': (
            'There are fewer than 10 clusters; DID inference remains unverified.',
            '聚类少于 10 个，DID 的少聚类推断仍未验证。'),
        'did:diagnostics:pretrends_unavailable': (
            'There are no estimable pre-period leads to test; the design needs additional evidence.',
            '没有可估计的前导项，无法检验预趋势；需补充识别证据或明确修订方案。'),
        'did:diagnostics:pretrends_partly_unidentified': (
            'Some declared pre-period leads are unidentified; a test of the remainder is insufficient.',
            '部分前导项未识别，仅检验其余项不足以完成预趋势诊断。'),
        'did:diagnostics:pretrends_rejected_requires_revision': (
            'Zero pre-period coefficients were rejected; review and revise the identifying design.',
            '前导项为零的检验被拒绝，需复核并明确修订识别方案。'),
        'did:diagnostics:staggered_interpretation_requires_revision': (
            'Staggered TWFE is not a generic ATT; an appropriate estimator/estimand revision is required.',
            '交错实施 TWFE 不能直接解释为一般 ATT；需采用适用估计器并明确目标量。'),
        'iv:diagnostics:ar_unavailable': (
            'The global AR confidence set is unavailable or uncertified; weak-instrument inference remains incomplete.',
            'AR 全局置信集合不可用或未认证，弱工具推断仍未完成；需按不可用原因修订方案。'),
        'iv:diagnostics:ar_empty_requires_model_revision': (
            'The AR set is empty: the joint model restrictions require review, not a precise effect claim.',
            'AR 集合为空：需复核联合模型限制，不能据此声称效应已精确估计。'),
        'iv:diagnostics:overidentification_rejected_requires_model_revision': (
            'The joint over-identifying restrictions were rejected; revise and justify the model.',
            '过度识别联合限制被拒绝，需明确修订模型并给出理由。'),
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


def _verification_scope(result, language):
    """What the check covered, in the Workbench's words: Agents have widened "the sources
    verified" into "every step and conclusion verified" (Leverage Ask, 2026-10-31)."""
    question = result.get('scope') == 'question'
    if language == 'zh':
        return ('\n\nWorkbench 核验范围：只核对了结果的来源绑定和交付项'
                + ('（按单一问题交付，计划里未执行的步骤不在其中）' if question else '')
                + '，不认证方法选择、识别假设、推断有效性或科学结论。')
    return ('\n\nWorkbench verification scope: result provenance and delivery items only'
            + (' (delivered as a focused question; plan steps that did not run are not covered)' if question else '')
            + '. Method choice, identification, inference validity and scientific conclusions are not certified.')


def publication(content: str, result: dict, language: str, *, final=True, request_text=""):
    """Publish the machine state; a rejected completion claim is not a result."""
    result = enforce_request_scope(result, request_text)
    active = result['missing'] != ['completion_contract:select_playbooks_and_source']
    claim = claims_completion(content, request_text) or bool(active and _GENERIC_CLAIM.search(content))
    if result['status'] == 'requirements_met':
        return content + _verification_scope(result, language) if claim else content
    if not claim and not _PARTIAL_NOTICE.search(content) and (
            not final or result['missing'] == ['completion_contract:select_playbooks_and_source']):
        return content
    notice = partial_notice(result, language)
    # Keep useful findings rather than replacing an entire answer because its
    # closing sentence claimed completion. The remaining prose is still a draft,
    # not newly certified evidence; final answers retain the numeric check below
    # this publication boundary in the turn loop.
    content = content.removeprefix(notice).strip()
    content = _PARTIAL_NOTICE.sub('', content).strip()
    if claim:
        # Keep a claim spanning newlines together. Splitting it first would
        # leave two unmatched fragments that join back into a completion claim.
        # A regex's leading line anchor/newline is not part of its visible claim.
        spans = [match.span() for pattern in (_CLAIM, _GENERIC_CLAIM)
                 for match in pattern.finditer(content)]
        boundaries = [0]
        for match in re.finditer(r'(?<=\n)|(?<=[。！？])|(?<=[.!?])(?=\s|$)', content):
            position = match.start()
            if not any(start < position < end and content[start:position].strip()
                       and content[position:end].strip() for start, end in spans):
                boundaries.append(position)
        boundaries.append(len(content))
        sentences = [content[start:end] for start, end in zip(boundaries, boundaries[1:])]
        content = ''.join(sentence for sentence in sentences
                          if not claims_completion(sentence, request_text)
                          and not _GENERIC_CLAIM.search(sentence)).strip()
    draft_heading = '阶段性说明（仍需核验）' if language == 'zh' else 'Interim findings (still require verification)'
    content = content.removeprefix(draft_heading).strip()
    return notice if not content else notice + '\n\n' + draft_heading + '\n\n' + content


_PARTIAL_BOUNDARIES = {
    'zh': '当前仍为部分交付；阶段性说明与最终核验结论须分开阅读。',
    'en': 'The full analysis is not complete; interim prose and final verification are separate.',
}
_PARTIAL_NOTICE = re.compile(
    r'(?:部分完成：以下必需证据尚未核验。|Partially complete: required evidence remains unverified\.)'
    r'(?:[\s\S]*?(?:' + '|'.join(re.escape(text) for text in _PARTIAL_BOUNDARIES.values())
    + r')\n\n---\n*|[ \t]*(?:\n[ \t]*- [^\n]*)*\n*)')


def partial_notice(result, language):
    heading = '部分完成：以下必需证据尚未核验。' if language == 'zh' else 'Partially complete: required evidence remains unverified.'
    missing = list(dict.fromkeys(_missing_label(item, language) for item in result['missing']))
    notice = heading + '\n' + '\n'.join('- ' + item for item in missing[:32])
    # These are the completion check's actual registered artifacts, never model
    # prose or a claim that merely having a file certifies the analysis.
    refs = [f"{item['run_id']}/{item['artifact_id']}" for item in result.get('verified_artifacts', [])[:4]]
    if refs:
        title = '已核验的产物引用（不代表整项分析已通过）' if language == 'zh' else 'Verified artifact references (not whole-analysis certification)'
        notice += '\n\n' + title + '\n' + '\n'.join('- ' + ref for ref in refs)
    if language == 'zh':
        advice = ('由 Agent 先保存与当前问题匹配的分析计划并绑定数据来源；已有结果保留，'
                  '不要为补计划重复计算。然后绑定已执行结果，重新检查缺项。'
                  if 'completion_contract:select_playbooks_and_source' in result['missing'] else
                  '先补齐上列缺项，再重新核验；缺报告时应引用已有的已核验结果，避免重复拟合。'
                  '若需要额外数据、权限或预算，明确列出并等待接管。')
        if result.get('next_step'):
            advice += '\n' + str(result['next_step'])[:4000]
        return notice + '\n\n下一步建议\n' + advice + '\n\n' + _PARTIAL_BOUNDARIES['zh'] + '\n\n---'
    advice = ('Save a plan matching the question and bind its dataset source. Keep existing results; '
              'do not rerun computations just to create plan history. Bind the executed evidence and recheck.'
              if 'completion_contract:select_playbooks_and_source' in result['missing'] else
              'Address the missing evidence, then recheck. Compose missing reports from verified results rather '
              'than refitting. State any additional data, permission or budget needed and pause for takeover.')
    if result.get('next_step'):
        advice += '\n' + str(result['next_step'])[:4000]
    return notice + '\n\nRecommended next steps\n' + advice + '\n\n' + _PARTIAL_BOUNDARIES['en'] + '\n\n---'


_DIAGNOSTIC_TYPES = frozenset({'model_diagnostic', 'lmm_analysis_evidence', 'analysis_completion_evidence'})
#: Newest runs scanned for a source's products; each run lists at most 48.
DERIVE_RUN_LIMIT = 12


def derive_evidence(project_root, contract, evidence, *, _products=None):
    """Normalize the Agent's evidence and bind, from this source's own products, what it left out.

    In the paid v1.9.1 round (candidate-small-20261021) every Ask task stalled
    here although the fits and their diagnostics existed (panel estimate 0.514
    for a true 0.5): the gate needed exact run/artifact ids for one primary,
    its companion diagnostics, the alternative fits and a report composed after
    them, and the Agent wrote ids that did not exist, listed workflow artifacts
    and several fits as "models", or named a report collection as the report.

    The Agent keeps the scientific choices: the analysis families (the
    contract) and which eligible fit is primary. Of the eligible fits it names,
    the first is primary and the others are alternatives; with none named, a
    family with a single distinct specification binds it, while several stay
    the Agent's choice and are listed. Everything else follows from verified,
    source-bound products: references that do not resolve to the right kind
    are dropped (and named), the primary's own diagnostics are added, the other
    fits become alternatives when the Agent named none, and the newest report
    whose ancestry covers them is used, or a ready ``report.compose`` is given.
    ``evaluate`` then applies every check unchanged.
    """
    given = dict(evidence or {})
    notes = {'bound_by_workbench': [], 'dropped': [], 'primary_candidates': {}}
    if not contract or contract.get('scope') == 'question':
        return given, notes
    products = _products if _products is not None else _Products(project_root)
    source = products.load(contract['source'])
    if source is None or source.sha256 != contract['source'].get('sha256'):
        return given, notes

    def bound(ref):
        return any(a.sha256 == source.sha256 for a in products.ancestors(ref))

    def plain(ref):
        return {'run_id': ref['run_id'], 'artifact_id': ref['artifact_id']}

    def fitted_on_source(ref):
        artifact = products.load(ref)
        return artifact is not None and any(
            (data := products.load({'run_id': ref['run_id'], 'artifact_id': item})) is not None
            and data.artifact_type in _DATA_TYPES and data.sha256 == source.sha256 for item in artifact.inputs)

    runs = sorted((path.name for path in products.runs.iterdir()
                   if path.is_dir() and not path.name.startswith(('_', '.'))), reverse=True)[:DERIVE_RUN_LIMIT]
    models, diagnostics, reports, post_estimation = [], [], [], []
    for run in runs:
        for ref in completion_candidate_refs(products.runs / run):
            artifact = products.load(ref)
            if artifact is None:
                continue
            if artifact.artifact_type in _DIAGNOSTIC_TYPES:
                diagnostics.append(ref)
            elif artifact.artifact_type == 'post_estimation':
                post_estimation.append((ref, artifact))
            elif artifact.artifact_type == 'report':
                reports.append((ref, artifact))
            elif (model := products.model(ref, artifact)) is not None and bound(ref):
                models.append((ref, model))

    def usable_report(ref):
        artifact = products.load(ref)
        return (artifact is not None and artifact.artifact_type == 'report'
                and ((artifact.payload and artifact.payload.get('sections'))
                     or (artifact.suffix in {'.html', '.pdf', '.md'} and artifact.size_bytes > 0)))

    named = [plain(ref) for ref in given.get('models') or [] if isinstance(ref, dict)]
    eligible = {(ref['run_id'], ref['artifact_id']) for ref, _ in models}
    notes['dropped'] += [{'models': ref} for ref in named if (ref['run_id'], ref['artifact_id']) not in eligible]
    primaries, alternates = [], []
    for family in contract['playbooks']:
        family_models = [(ref, model) for ref, model in models if model.get('model_type') in PLAYBOOKS[family]]
        family_keys = {(ref['run_id'], ref['artifact_id']) for ref, _ in family_models}
        chosen = [ref for ref in named if (ref['run_id'], ref['artifact_id']) in family_keys]
        if chosen:
            primaries.append(chosen[0])
            alternates += chosen[1:]
            continue
        # Re-running one specification gives the same point estimates: not a choice.
        distinct = {}
        for ref, model in family_models:
            distinct.setdefault(model.get('point_estimation_fingerprint') or (ref['run_id'], ref['artifact_id']), (ref, model))
        # A fit on data derived from the source (a refit without influential rows) is a
        # variant of the fit on the source itself, not a rival primary (offline replay of off3 leverage).
        on_source = [entry for entry in distinct.values() if fitted_on_source(entry[0])]
        if len(distinct) == 1 or len(on_source) == 1:
            primaries.append(plain((on_source if len(distinct) > 1 else list(distinct.values()))[0][0]))
            notes['bound_by_workbench'].append(f'{family}:primary')
        elif distinct:
            notes['primary_candidates'][family] = [
                {'run_id': ref['run_id'], 'artifact_id': ref['artifact_id'], 'model_type': model.get('model_type'),
                 'nobs': model.get('nobs'), 'terms': list(model.get('coefficients') or {})[:8]}
                for ref, model in list(distinct.values())[:6]]
    if not primaries:
        return {**given, 'models': named}, notes
    result = {'models': primaries, **({'results': given['results']} if 'results' in given else {})}
    primary_keys = {(ref['run_id'], ref['artifact_id']) for ref in primaries}
    given_alternates = [plain(ref) for ref in given.get('sensitivity') or [] if isinstance(ref, dict)
                        and (ref['run_id'], ref['artifact_id']) in eligible - primary_keys]
    notes['dropped'] += [{'sensitivity': ref} for ref in given.get('sensitivity') or []
                         if isinstance(ref, dict) and plain(ref) not in given_alternates]
    alternates += given_alternates
    if not alternates:
        alternates = [plain(ref) for ref, model in models if (ref['run_id'], ref['artifact_id']) not in primary_keys
                      and any(model.get('model_type') in PLAYBOOKS[f] for f in contract['playbooks'])]
        if alternates:
            notes['bound_by_workbench'].append('sensitivity')
    result['sensitivity'] = list({(r['run_id'], r['artifact_id']): r for r in alternates}.values())[:24]
    given_diagnostics = [plain(ref) for ref in given.get('diagnostics') or []
                         if isinstance(ref, dict) and products.load(ref) is not None]
    notes['dropped'] += [{'diagnostics': ref} for ref in given.get('diagnostics') or []
                         if isinstance(ref, dict) and plain(ref) not in given_diagnostics]
    # Native models require their exact companion. Another same-run result
    # cannot replace it; other models retain the existing diagnostic selection.
    own = []
    for primary in primaries:
        model = next(model for ref, model in models if plain(ref) == primary)
        companion = {'run_id': primary['run_id'], 'artifact_id': model['model_id'] + '.completion'}
        if (companion in given_diagnostics if model.get('model_type') in NATIVE_COMPANIONS
                else any(ref['run_id'] == primary['run_id'] for ref in given_diagnostics)):
            continue
        if companion in [plain(ref) for ref in diagnostics]:
            own.append(companion)
        else:
            own += [plain(ref) for ref in diagnostics if ref['run_id'] == primary['run_id']
                    and (products.diagnostic(ref, products.load(ref)) or {}).get('model_id') == model['model_id']]
    # An IV primary's AR set: the gate accepts exactly one verified result for the
    # model, and re-running the same request is not a choice, so the newest is
    # used and any others are left out (paid fix3 round: two identical AR runs,
    # stored as post_estimation, were never bound and the task could not finish).
    ar_refs = set()
    for primary in primaries:
        model = next(model for ref, model in models if plain(ref) == primary)
        if model.get('model_type') not in PLAYBOOKS['iv']:
            continue
        matches = [plain(ref) for ref, artifact in post_estimation
                   if verified_iv_ar(products, primary, model, ref, artifact) is not None]
        if matches:
            newest_run = matches[0]['run_id']  # runs are scanned newest first
            chosen = [ref for ref in matches if ref['run_id'] == newest_run][-1]
            ar_refs.update((ref['run_id'], ref['artifact_id']) for ref in matches)
            own.append(chosen)
            ar_refs.discard((chosen['run_id'], chosen['artifact_id']))
    given_diagnostics = [ref for ref in given_diagnostics if (ref['run_id'], ref['artifact_id']) not in ar_refs]
    result['diagnostics'] = list({(r['run_id'], r['artifact_id']): r for r in given_diagnostics + own}.values())[:24]
    if own:
        notes['bound_by_workbench'].append('diagnostics')
    report = given.get('report')
    selected_refs = [ref for key in ('models', 'diagnostics', 'sensitivity', 'results') for ref in result.get(key, [])]
    selected = [products.load(ref) for ref in selected_refs]

    def uncovered(ref):
        return report_missing_sources(products, ref, selected_refs)

    # A named report counts only if it covers the selected results; otherwise it is returned
    # with what it lacks and the ready-made compose_report below. Accepting any usable report
    # left a weaker model with 'report:result_sources' and no way to learn which results were
    # missing (free-route no-thinking round, iv_weak, 2026-10-22: 8 nudges).
    lacking = uncovered(report) if isinstance(report, dict) and usable_report(report) else None
    if lacking == []:
        result['report'] = plain(report)
    else:
        if report is not None:
            notes['dropped'].append({'report': report, **({'does_not_cover': lacking[:12]} if lacking else {})})
        for ref, artifact in reports:
            if usable_report(ref) and bound(ref) and not uncovered(ref):
                result['report'] = plain(ref)
                notes['bound_by_workbench'].append('report')
                break
        else:
            notes['compose_report'] = {'operation_id': 'report.compose', 'spec': {'result_refs': (
                [{**ref, 'role': 'primary'} for ref in result['models']]
                + [{**ref, 'role': 'diagnostic'} for ref in result['diagnostics']]
                + [{**ref, 'role': 'sensitivity'} for ref in result['sensitivity']]
                + [{**ref, 'role': 'diagnostic'} for ref in result.get('results', [])])[:24]}}
    return result, notes
