"""Verify and render explicitly selected existing report evidence, without refitting."""
from __future__ import annotations

from .completion import _Products
from .workflow import WorkflowExecutionError

_OMIT = {'residuals', 'rows', 'values', 'retained_positions', 'ordered_positions',
         'innovations', 'conditional_series', 'root_isolation', 'polynomials'}


def collect_report_sources(root, target, refs):
    products = _Products(root)
    source = products.load(target)
    if source is None or source.artifact_type not in {'raw_data', 'processed_data', 'derived_data'}:
        raise WorkflowExecutionError('Report source is unavailable or changed.')
    result = {'references': [], 'models': [], 'diagnostic_rows': [], 'omitted_diagnostic_fields': 0}

    def scalars(value, path='', depth=0):
        if isinstance(value, dict) and depth < 7:
            for key, item in value.items():
                if key not in _OMIT:
                    yield from scalars(item, path + '.' + str(key) if path else str(key), depth+1)
        elif isinstance(value, list) and path.rsplit('.', 1)[-1] in {
                'components', 'defined_components', 'undefined_points', 'root_brackets'}:
            # These are short set/endpoint metadata, never observation arrays.
            result['omitted_diagnostic_fields'] += max(0, len(value)-32)
            for i, item in enumerate(value[:32]):
                yield from scalars(item, f'{path}[{i}]', depth+1)
        elif value is None or type(value) in {bool, int, float, str}:
            yield path, value

    for ref in refs:
        artifact = products.load(ref)
        if artifact is None or not any(a.sha256 == source.sha256 for a in products.ancestors(ref)):
            raise WorkflowExecutionError('A selected report result is unavailable, changed, or bound to another source.')
        identity = {key: ref[key] for key in ['run_id', 'artifact_id', 'role']}
        result['references'].append({**identity, 'sha256': artifact.sha256})
        if ref['role'] in {'primary', 'sensitivity'}:
            model = products.model(ref, artifact)
            if model is None:
                raise WorkflowExecutionError('A primary/sensitivity report reference is not a verified fitted model.')
            result['models'].append((f"{ref['run_id']}:{ref['artifact_id']}", {
                **model, 'model_label': f"{ref['role']} — {model['model_type']} ({ref['run_id']})"}))
        else:
            if artifact.artifact_type not in {'model_diagnostic', 'analysis_completion_evidence',
                    'lmm_analysis_evidence', 'post_estimation', 'p7_analysis', 'workflow_capability_result'}:
                raise WorkflowExecutionError('A diagnostic report reference is not registered diagnostic evidence.')
            payload = artifact.payload or {}
            values = payload.get('diagnostics', payload.get('result', payload))
            for field, value in scalars(values):
                if len(result['diagnostic_rows']) == 128:
                    result['omitted_diagnostic_fields'] += 1
                    continue
                result['diagnostic_rows'].append({**identity, 'field': field,
                    'value': value if not isinstance(value, str) else value[:2000]})
    return result
