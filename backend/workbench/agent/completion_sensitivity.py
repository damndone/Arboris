"""Copyable sensitivity fits, derived from the primary model's own specification.

Free-route no-thinking round off3 (2026-10-22): iv_weak.goal reported
``iv:sensitivity:distinct_point_estimation`` 28 times with no repair step, and
leverage.goal never refitted without its high-influence rows; both ended on the
nudge budget. The Workbench knows the primary's specification, its input
dataset and its influence diagnostic, so it offers the mechanical alternatives
as an exact workflow target and steps. Each is validated as a model.genesis step
before it is offered. Which one answers the question -- or a specification of
the Agent's own -- stays the Agent's choice.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
from pandas.api.types import is_integer_dtype, is_string_dtype

MAX_OPTIONS = 4
#: Form fields that carry no specification beyond what the options copy.
_PASSIVE_FORM_FIELDS = frozenset({'mode', 'model_type', 'y', 'x', 'covariance', 'model_options', 'labels',
                                  'sheet_name', 'transpose', 'focal_x', 'model_options_binding'})
SENSITIVITY_NEXT_STEP = (
    'A fit that changes the point estimate is missing, and a report composed before it cannot cover it. Propose '
    'the sensitivity_options entry that best answers the research question -- run_operation, operation.multi_step, '
    'with its workflow target and steps exactly as given -- or a specification of your own that the question calls '
    'for; never drop the variable the question is about. '
    'The Workbench binds the new fit as sensitivity; compose the report after it.')
#: Above this many rows the influence refit is not computed inside the completion check.
MAX_INFLUENCE_ROWS = 200_000


def _unset(value: Any) -> bool:
    # The run form writes its defaults as strings ('[]', '0', 'false').
    return value in (None, {}, []) or (isinstance(value, str) and value.strip().lower() in {'', '[]', '0', 'false', 'none'})


def _names(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if not isinstance(value, str) or not value.strip():
        return []
    text = value.strip()
    if text.startswith('['):
        try:
            return _names(json.loads(text))
        except json.JSONDecodeError:
            return []
    return [part.strip() for part in text.split(',') if part.strip()]


def primary_specification(project_root: Path | str, run_id: str) -> tuple[dict[str, Any], list[str]] | None:
    """``(model.genesis spec, focal predictors)`` reproducing the run's model, or ``None`` if it cannot be copied exactly."""

    from ..contracts.model.family import MODEL_FAMILY_CONTRACTS
    from .workflow_contract_parts.validation import validate_model_genesis_spec

    try:
        form = json.loads((Path(project_root) / 'runs' / run_id / 'run_inputs.json').read_text(encoding='utf-8'))['form']
    except (OSError, KeyError, TypeError, ValueError):
        return None
    contract = MODEL_FAMILY_CONTRACTS.get(form.get('model_type')) if isinstance(form, dict) else None
    if contract is None:
        return None
    fields = set(contract.context_spec_fields)
    if any(not _unset(value) for key, value in form.items() if key not in _PASSIVE_FORM_FIELDS | fields):
        return None
    predictors = _names(form.get('x'))
    if not isinstance(form.get('y'), str) or not form['y'] or not predictors:
        return None
    spec: dict[str, Any] = {'model_family': form['model_type'],
                            'branches': [{'branch_id': 'primary', 'outcome': form['y'], 'predictors': predictors}]}
    if isinstance(form.get('covariance'), str) and form['covariance']:
        spec['covariance'] = form['covariance']
    for field in sorted(fields):
        value = form.get(field)
        if _unset(value):
            continue
        listed = _names(value)
        spec[field] = listed if isinstance(value, list) or str(value).strip().startswith('[') else value
    options = {key: value for key, value in (form.get('model_options') or {}).items() if key != 'covariance'}
    if options:
        spec['model_options'] = options
    try:
        validate_model_genesis_spec(spec)
    except Exception:
        return None
    return spec, _names(form.get('focal_x'))


def _workflow(run_id: str, dataset: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {'target': {'run_id': run_id, 'node_ref': dataset}, 'steps': steps}


def _branch_id(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9_]+', '_', text).strip('_')[:60] or 'sensitivity'


def _dataset(project_root, run_id, model_id):
    from ..lineage.model_inputs import input_datasets

    lineage = input_datasets(project_root, run_id, f'model:{model_id}')
    return lineage[1][0] if lineage and len(lineage[1]) == 1 else None


def specification_options(project_root, main_ref, main) -> list[dict[str, Any]]:
    """One fit per dropped predictor, the rest of the primary's specification unchanged."""

    from .workflow_contract_parts.validation import validate_model_genesis_spec

    copied = primary_specification(project_root, main_ref['run_id'])
    dataset = _dataset(project_root, main_ref['run_id'], main.get('model_id'))
    if copied is None or dataset is None:
        return []
    spec, focal = copied
    predictors = spec['branches'][0]['predictors']
    options = []
    for name in predictors:
        if name in focal:
            continue
        branch = {**spec['branches'][0], 'branch_id': _branch_id(f'without_{name}'),
                  'predictors': [item for item in predictors if item != name]}
        alternative = {**spec, 'branches': [branch]}
        try:
            validate_model_genesis_spec(alternative)
        except Exception:
            continue
        options.append({'label': f'the primary specification without {name}',
                        'workflow': _workflow(main_ref['run_id'], dataset, [
                            {'step_id': 'sensitivity', 'operation_id': 'model.genesis', 'spec': alternative}])})
    return options[:MAX_OPTIONS]


def influence_option(project_root, main_ref, main, threshold) -> dict[str, Any] | None:
    """The primary refitted without the rows whose Cook's distance exceeds the diagnostic's own threshold.

    Rows are named by a column whose values identify them (unique, no missing),
    so the subset is reviewable; without one, nothing is offered.
    """

    from ..data_operations import _read_frame, resolve_data_column_cast_context

    copied = primary_specification(project_root, main_ref['run_id'])
    dataset = _dataset(project_root, main_ref['run_id'], main.get('model_id'))
    if copied is None or dataset is None or not isinstance(threshold, (int, float)):
        return None
    spec, _ = copied
    branch = spec['branches'][0]
    try:
        context = resolve_data_column_cast_context(project_root, source_run_id=main_ref['run_id'], source_node_id=dataset)
        frame = _read_frame(Path(project_root) / 'runs' / main_ref['run_id'] / context['source_artifact_path'])
    except Exception:
        return None
    used = [branch['outcome'], *branch['predictors']]
    if len(frame) > MAX_INFLUENCE_ROWS or any(column not in frame for column in used):
        return None
    sample = frame.dropna(subset=used)
    try:
        y = sample[branch['outcome']].to_numpy(dtype=float)
        x = np.column_stack([np.ones(len(sample)), sample[branch['predictors']].to_numpy(dtype=float)])
    except (TypeError, ValueError):
        return None
    n, k = x.shape
    if n <= k + 1:
        return None
    xtx_inv = np.linalg.pinv(x.T @ x)
    leverage = np.einsum('ij,jk,ik->i', x, xtx_inv, x)
    residuals = y - x @ (xtx_inv @ x.T @ y)
    scale = residuals @ residuals / (n - k)
    if scale <= 0 or np.any(leverage >= 1):
        return None
    cooks = residuals ** 2 / (k * scale) * leverage / (1 - leverage) ** 2
    flagged = sample.index[cooks > threshold]
    if len(flagged) == 0 or len(flagged) >= n - k - 1:
        return None
    identifier = next((column for column in frame.columns if column not in used
                       and frame[column].notna().all() and frame[column].is_unique
                       and (is_string_dtype(frame[column]) or is_integer_dtype(frame[column]))), None)
    if identifier is None:
        return None
    excluded = [value.item() if hasattr(value, 'item') else value for value in frame.loc[flagged, identifier]]
    refit = {**spec, 'branches': [{**branch, 'branch_id': 'without_high_influence'}],
             'source': {'from_step': 'drop_high_influence', 'output': 'produced_dataset'}}
    return {'label': f"the primary specification without the {len(excluded)} rows whose Cook's distance exceeds "
                     f"{threshold:g} ({identifier}: {', '.join(map(str, excluded[:12]))}"
                     f"{', ...' if len(excluded) > 12 else ''})",
            'workflow': _workflow(main_ref['run_id'], dataset, [
                {'step_id': 'drop_high_influence', 'operation_id': 'data.subset',
                 'spec': {'columns': [str(identifier), *used],
                          'filters': [{'column': identifier, 'op': 'not_in', 'value': excluded}]}},
                {'step_id': 'sensitivity', 'operation_id': 'model.genesis', 'depends_on': ['drop_high_influence'],
                 'spec': refit}])}
