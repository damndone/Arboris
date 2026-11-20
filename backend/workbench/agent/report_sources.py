"""Verify and render explicitly selected existing report evidence, without refitting."""
from __future__ import annotations

from .completion import _Products
from .completion_outcome import CHECKS_ARTIFACT_TYPE
from .completion_targets import computed_result
from .workflow import WorkflowExecutionError

MAX_EVIDENCE_ROWS = 128
_OMIT = {'residuals', 'rows', 'values', 'retained_positions', 'ordered_positions',
         'innovations', 'conditional_series', 'root_isolation', 'polynomials'}


def validate_plan_report_sources(root, target, ordered_steps):
    """Check the existing or earlier workflow evidence a plan report can consume."""
    from ..analysis_ledger import step_category

    has_earlier_results = False
    for step in ordered_steps:
        operation_id = step["operation_id"]
        if operation_id != "report.compose":
            has_earlier_results |= step_category(operation_id) in {"model", "inferential", "descriptive", "data_change"}
            continue
        spec = step["spec"]
        refs = spec.get("result_refs")
        curve = spec.get("specification_curve")
        review = spec.get("research_review")
        if not (has_earlier_results or refs or curve or review):
            raise WorkflowExecutionError(
                f"Report step {step['step_id']} needs verified result_refs or earlier evidence-producing workflow steps."
            )
        if refs:
            collect_report_sources(root, target, refs)
        if curve:
            from .specification_curves import read_curve_snapshot

            read_curve_snapshot(root, target, curve)
        if review:
            from .report_reviews import read_review_receipts

            read_review_receipts(root, target, review)


def collect_report_sources(root, target, refs):
    products = _Products(root)
    source = products.load(target)
    if source is None or source.artifact_type not in {'raw_data', 'processed_data', 'derived_data'}:
        raise WorkflowExecutionError('Report source is unavailable or changed.')
    result = {'references': [], 'models': [], 'diagnostic_rows': [], 'omitted_diagnostic_fields': 0}
    evidence = []

    def scalars(value, path='', depth=0):
        if isinstance(value, dict) and depth < 7:
            for key, item in value.items():
                if key not in _OMIT:
                    yield from scalars(item, path + '.' + str(key) if path else str(key), depth+1)
        elif isinstance(value, list) and path.rsplit('.', 1)[-1] in {
                'components', 'defined_components', 'undefined_points', 'root_brackets', 'checks', 'thresholds'}:
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
            # A computed result the delivery gate binds (a descriptive exploration, a named test) must be
            # reportable, or the gate's own compose_report can never run (binary_logit.open.r1, b25d3a1b).
            if artifact.artifact_type not in {'model_diagnostic', 'analysis_completion_evidence',
                    'lmm_analysis_evidence', 'post_estimation', 'p7_analysis', 'workflow_capability_result',
                    CHECKS_ARTIFACT_TYPE} and not computed_result(products, ref, artifact):
                raise WorkflowExecutionError('A diagnostic report reference is not registered diagnostic evidence.')
            payload = artifact.payload or {}
            values = payload.get('diagnostics', payload.get('result', payload))
            evidence.append([{**identity, 'field': field, 'value': value if not isinstance(value, str) else value[:2000]}
                             for field, value in scalars(values)])
    shares = _shares([len(rows) for rows in evidence], MAX_EVIDENCE_ROWS)
    for rows, share in zip(evidence, shares):
        result['diagnostic_rows'].extend(rows[:share])
        result['omitted_diagnostic_fields'] += len(rows) - share
    return result


def _shares(sizes, total):
    """Each reference's row allowance: equal shares, a small reference's unused share passed on.

    A first-come cap gave one exploration and the fit checks all 128 rows and left the marginal
    effects, the question's answer, out of the report (binary_logit.open.r1, b25d3a1b)."""
    shares, left, pending = [0] * len(sizes), total, sorted(range(len(sizes)), key=lambda i: sizes[i])
    while pending:
        level = left // len(pending)
        index = pending.pop(0)
        shares[index] = min(sizes[index], level)
        left -= shares[index]
    return shares
