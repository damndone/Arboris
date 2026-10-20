"""Native panel residual evidence: descriptive checks, not iid OLS tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..canonical import sha256_canonical
from ..checks.fit_checks import CLUSTER_COUNT


def panel_evidence(fitted, primary, frame, *, y, x, entity, time, cluster=None):
    native = fitted.model
    covariance = primary.get('covariance_evidence') or {}
    positions = np.arange(len(frame))
    if covariance.get('covariance') == 'clustered':
        fields = list(dict.fromkeys([y, *x, cluster or entity]))
        positions = positions[frame[fields].notna().all(axis=1)]
    if len(positions) != len(native.not_null):
        return {'status': 'unavailable', 'reason': 'retained_row_mapping_unverified'}, [], {}
    positions = positions[native.not_null]
    actual_y = pd.to_numeric(frame.iloc[positions][y], errors='coerce').to_numpy()
    if not np.array_equal(actual_y, native.dependent.values2d[:, 0]):
        return {'status': 'unavailable', 'reason': 'retained_row_mapping_unverified'}, [], {}
    residual = fitted.resids.to_numpy(dtype=float)
    entity_ids = native.dependent.entity_ids[:, 0]
    time_values = native.dependent.index.get_level_values(1)
    table = pd.DataFrame({'entity': entity_ids, 'time': time_values, 'residual': residual})
    groups, left, right = [], [], []
    for key, group in table.groupby('entity', sort=True):
        values = group.sort_values('time', kind='stable').residual.to_numpy()
        groups.append({'entity_code': int(key), 'n': len(values), 'mean': float(values.mean()),
                       'rms': float(np.sqrt(np.mean(values**2))), 'max_abs': float(np.max(np.abs(values)))})
        if time is not None and entity is not None:
            left.extend(values[:-1].tolist())
            right.extend(values[1:].tolist())
    correlation = None
    if len(left) > 1 and np.std(left) > 0 and np.std(right) > 0:
        correlation = float(np.corrcoef(left, right)[0, 1])
    clusters = covariance.get('cluster_count')
    cluster_assessment = ('not_applicable' if clusters is None else
        'severe' if clusters < CLUSTER_COUNT.threshold('severe_below') else
        'caution' if clusters < CLUSTER_COUNT.threshold('caution_below') else 'many_cluster_reference')
    result = {'status': 'computed', 'method': 'panel_within_residual_descriptive_v1',
        'residual_definition': 'y minus fitted slopes and all fitted fixed effects',
        'nobs': len(residual), 'n_entities': len(groups), 'n_times': int(table.time.nunique()),
        'total_parameter_rank': int(fitted.df_model), 'slope_parameter_count': len(fitted.params),
        'absorbed_parameter_rank': int(fitted.df_model)-len(fitted.params),
        'residual_df': int(fitted.df_resid), 'covariance': covariance.get('covariance'),
        'cluster_count': covariance.get('cluster_count'), 'inference': covariance,
        'cluster_count_assessment': cluster_assessment,
        'pairing': 'adjacent_observed_times_within_entity' if time is not None and entity is not None else 'unavailable_without_declared_entity_and_time',
        'adjacent_pairs': len(left),
        'adjacent_residual_correlation': correlation, 'serial_dependence_test': 'not_performed',
        'description': 'Observed-time neighbors can have gaps. Pairing requires declared entity and time fields. Correlation is descriptive, not an independence test.',
        'groups': groups, 'residuals': residual.tolist(), 'scientific_validity': 'not_certified'}
    definition = {'family': primary['model_type'], 'entity_effects': native.entity_effects,
        'time_effects': native.time_effects, 'outcome': native.dependent.vars,
        'design': native.exog.vars, 'actual_design_sha256': sha256_canonical({
            'y': native.dependent.values2d.tolist(), 'x': native.exog.values2d.tolist(),
            'entity_partition': native.dependent.entity_ids.tolist(),
            'time_partition': native.dependent.time_ids.tolist()})}
    return result, positions.tolist(), definition
