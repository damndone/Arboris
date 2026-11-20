"""Frozen workflow specification sets and source-verified descriptive curves."""
from __future__ import annotations

import json
from pathlib import Path

from ..artifacts import read_json, register_artifact, write_json
from ..canonical import sha256_canonical
from .completion import _Products, source_receipt, _number
from .workflow import WorkflowStateStore, WorkflowExecutionError, _fingerprint


def freeze_workflow(root, draft, *, resumed):
    path = Path(root) / 'workbench/workflows' / f'{draft.workflow_id}.plan.json'
    if path.exists():
        if read_json(path)['draft'] != draft.to_dict():
            raise WorkflowExecutionError('frozen workflow specification set changed')
    elif not resumed:
        write_json(path, {'draft': draft.to_dict(), 'source': source_receipt(root, draft.target)})
    # Old executions with no pre-execution snapshot remain unverified. Never
    # manufacture a before-results declaration during their resume.


def _estimation_step(step):
    from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
    contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(step['operation_id'])
    return (contract is not None and contract.produces_model_branches
            or step['operation_id'] in {'time_series.arima', 'model.time_series.arma_garch'})


def read_curve_snapshot(root, target, options):
    """Read the frozen set and verify its identity without projecting curve rows."""
    workflow_id = options['workflow_id']
    if Path(workflow_id).name != workflow_id:
        raise WorkflowExecutionError('specification workflow_id must be path-safe')
    path = Path(root) / 'workbench/workflows' / f'{workflow_id}.plan.json'
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise WorkflowExecutionError('no bounded pre-execution specification snapshot exists')
    frozen = read_json(path)
    draft = frozen['draft']
    state = WorkflowStateStore(root, workflow_id, create=False).current()
    expected = _fingerprint({k: draft[k] for k in ['schema_version', 'workflow_template', 'target', 'steps']})
    if (state is None or draft['workflow_id'] != workflow_id or state.plan_fingerprint != expected
            or draft['plan_fingerprint'] != expected
            or any(draft['target'][k] != target[k] for k in ['run_id', 'artifact_id'])
            or frozen['source'] is None or source_receipt(root, draft['target']) != frozen['source']):
        raise WorkflowExecutionError('specification set, state or registered source changed')
    if not any(_estimation_step(step) for step in draft['steps']):
        raise WorkflowExecutionError('the frozen set contains no supported model specifications')
    return frozen, state


def _model_refs(step, state, run_id):
    if state.model_branches:
        return [(b['branch_id'], {'run_id': b['run_id'], 'artifact_id': b['model_id']}, b['branch_spec'])
                for b in state.model_branches if b.get('model_id')]
    return [('', {'run_id': a.split(':', 1)[0], 'artifact_id': a.split(':', 1)[1]} if ':' in a
                 else {'run_id': run_id, 'artifact_id': a}, step['spec']) for a in state.artifact_ids]


def collect_curve(root, target, options):
    frozen, state = read_curve_snapshot(root, target, options)
    products = _Products(root)
    rows, steps = [], {}
    term, source = options['term'], frozen['source']
    for step in frozen['draft']['steps']:
        if not _estimation_step(step):
            continue
        saved = state.steps[step['step_id']]
        steps[step['step_id']] = {'status': saved.status, 'artifact_ids': [
            a if ':' in a else f"{target['run_id']}:{a}" for a in saved.artifact_ids]}
        base = {'step_id': step['step_id'], 'operation_id': step['operation_id'],
            'specification': step['spec'], 'status': saved.status, 'reason': saved.error,
            'estimate': None, 'std_error': None, 'ci_lower': None, 'ci_upper': None,
            'interval_status': 'not_reported', 'nobs': None, 'model_type': None}
        found = []
        if saved.status == 'completed':
            for branch, ref, spec in _model_refs(step, saved, target['run_id']):
                artifact = products.load(ref)
                model = products.model(ref, artifact)
                if model is None:
                    continue
                row = model['coefficients'].get(term)
                bound = any(a.sha256 == source['sha256'] for a in products.ancestors(ref))
                value = {**base, 'branch_id': branch, 'model_type': model['model_type'],
                    'nobs': model['nobs'], 'result_ref': {**ref, 'sha256': artifact.sha256},
                    'point_estimation_fingerprint': model.get('point_estimation_fingerprint'),
                    'analysis_sample_fingerprint': model.get('analysis_sample_fingerprint')}
                if not bound or not row or not _number(row.get('estimate')):
                    value.update(status='unverified', reason='registered source or focal coefficient unavailable')
                else:
                    value.update(status='estimated', estimate=row['estimate'], std_error=row.get('std_error'))
                    if all(_number(row.get(k)) for k in ['ci_lower', 'ci_upper']):
                        value.update(ci_lower=row['ci_lower'], ci_upper=row['ci_upper'], interval_status='native_reported')
                    outcome = spec.get('outcome') or (spec.get('column_bindings') or {}).get('value')
                    model_options = spec.get('options') or {}
                    transform = model.get('frozen_spec', {}).get('transform') or [model_options.get('order', [0,0,0])[1], model_options.get('seasonal_order', [0,0,0,0])[1:4:2]]
                    value['comparison_group'] = sha256_canonical([model['model_type'], outcome, transform, term, step['spec'].get('source')])[:12]
                    value['comparison_label'] = f"{model['model_type']}: {outcome}, transform={transform}"
                found.append(value)
        if not found:
            declared = step['spec'].get('branches') or [{'branch_id': ''}]
            found = [{**base, 'branch_id': b['branch_id'],
                **({'status': 'unverified', 'reason': 'native model output unavailable'} if saved.status == 'completed' else {})}
                for b in declared]
        rows.extend(found)
    seen = {}
    for row in rows:
        fingerprint = row.get('point_estimation_fingerprint')
        if row['status'] == 'estimated' and fingerprint:
            row['duplicate_of'] = seen.get(fingerprint)
            seen.setdefault(fingerprint, row['step_id'] + ':' + row['branch_id'])
    groups = {r['comparison_group'] for r in rows if r['status'] == 'estimated'}
    samples = {r.get('analysis_sample_fingerprint') for r in rows if r['status'] == 'estimated'}
    return {'schema_version': 'workflow-report-collection.v1', 'contract': 'specification-curve/v1',
        'status': 'completed', 'workflow_id': options['workflow_id'], 'steps': steps,
        'workflow_plan_fingerprint': state.plan_fingerprint, 'source': source,
        'frozen_snapshot_sha256': sha256_canonical(frozen), 'set_fixed_before_its_execution': True,
        'preregistration_verified': False, 'term': term, 'declared_estimand': options['estimand'],
        'rows': rows, 'comparison_group_count': len(groups), 'distinct_point_estimation_count': len(seen),
        'comparison_groups': {r['comparison_group']: r['comparison_label'] for r in rows if r['status'] == 'estimated'},
        'changed_or_unverified_samples': len(samples) > 1 or None in samples,
        'limitations': ['Descriptive specification curve, not simultaneous confidence intervals or model selection.',
            'Declared estimand and scientific comparability are not certified. Conditional coefficients can change meaning across control sets.',
            'Different result families, outcomes or transformations are separated; changed samples remain visible.',
            'Missing intervals are not reconstructed from standard errors. Failed and unattempted specifications are retained.']}


def publish_curve(root, draft, options):
    curve = collect_curve(root, draft.target, options)
    run_root = Path(root) / 'runs' / draft.target['run_id']
    folder = run_root / 'artifacts/specification_curves'
    folder.mkdir(parents=True, exist_ok=True)
    artifact_id = f'workflow_specification_curve_{draft.workflow_id}'
    path = folder / f'{draft.workflow_id}.json'
    if path.exists() and read_json(path) != curve:
        raise WorkflowExecutionError('specification curve output path is occupied')
    write_json(path, curve)
    register_artifact(run_root, artifact_id, path, 'report_collection', 'report.compose', [draft.target['artifact_id']])
    panels = _render(curve, folder / draft.workflow_id)
    image_ids = []
    for suffix in ['svg', 'png']:
        image_id = artifact_id + '_' + suffix
        register_artifact(run_root, image_id, folder / f'{draft.workflow_id}.{suffix}',
                          'figure', 'report.compose', [artifact_id])
        image_ids.append(image_id)
    for i, panel in enumerate(panels):
        if panel.name != f'{draft.workflow_id}.png':
            image_id = artifact_id + f'_panel_{i}'
            register_artifact(run_root, image_id, panel, 'figure', 'report.compose', [artifact_id])
            image_ids.append(image_id)
    return {'artifact_id': artifact_id, 'figure_artifact_ids': image_ids, 'member_count': len(curve['rows']),
            'estimated_count': sum(r['status'] == 'estimated' for r in curve['rows']),
            'preregistration_verified': False, 'panel_files': [p.name for p in panels]}


def _render(curve, base):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    groups = sorted({r['comparison_group'] for r in curve['rows'] if r['status'] == 'estimated'})
    groups = groups or ['unavailable']
    fig, axes = plt.subplots(len(groups), 1, figsize=(max(8, min(20, len(curve['rows'])*.7)), 4*len(groups)), squeeze=False)
    def draw(ax, group):
        rows = [r for r in curve['rows'] if r.get('comparison_group') == group or r['status'] != 'estimated']
        ordered = sorted(rows, key=lambda r: (r['status'] != 'estimated', r['estimate'] if r['estimate'] is not None else 0))
        for x, row in enumerate(ordered):
            if row['status'] == 'estimated':
                ax.plot(x, row['estimate'], 'o', color='#286d9a')
                if row['interval_status'] == 'native_reported':
                    ax.vlines(x, row['ci_lower'], row['ci_upper'], color='#286d9a')
            else:
                ax.text(x, .03, row['status'], transform=ax.get_xaxis_transform(), rotation=90, color='#666666')
        ax.axhline(0, linewidth=.6, color='#999999')
        ax.set_xticks(range(len(ordered)), [r['step_id'] + (':' + r['branch_id'] if r['branch_id'] else '')
                                          + f"\nn={r['nobs'] if r['nobs'] is not None else 'NA'}" for r in ordered], rotation=35, ha='right')
        ax.set_title(f"{curve['term']} | {curve['comparison_groups'].get(group, 'No verified estimates')}")
        ax.set_ylabel('Native estimate / reported interval')
    for ax, group in zip(axes[:,0], groups, strict=True):
        draw(ax, group)
    fig.text(.01, .01, 'Frozen before this workflow ran; preregistration and scientific comparability unverified. Intervals are not simultaneous.', fontsize=8)
    fig.tight_layout(rect=[0,.05,1,1])
    fig.savefig(Path(str(base)+'.svg'))
    fig.savefig(Path(str(base)+'.png'), dpi=160)
    plt.close(fig)
    if len(groups) == 1:
        return [Path(str(base)+'.png')]
    panels = []
    for i, group in enumerate(groups):
        fig, ax = plt.subplots(figsize=(12, 4))
        draw(ax, group)
        fig.tight_layout()
        path = base.parent / f'{base.name}.panel-{i}.png'
        fig.savefig(path, dpi=160)
        plt.close(fig)
        panels.append(path)
    return panels
