"""Verify native time-series products against their registered data snapshot.

This reader never fits a model or changes files. The Agent receives only the
projection; raw source bytes stay behind the compiler/service boundary.
"""
from __future__ import annotations

import io
import numpy as np
import pandas as pd

from workbench.canonical import sha256_canonical
from workbench.engine.packs.time_series.completion import input_fingerprint, ordered_positions
from workbench.engine.packs.time_series.input import prepare_time_series
from workbench.services.pinned_run_directory import open_pinned_run_directory, LmmPersistenceError, PinnedRunError


def read_arima_completion(run_root, artifact):
    if artifact.artifact_type != 'p7_analysis':
        return None
    payload = artifact.payload or {}
    if payload.get('schema_version') != 'workbench.workflow.p7-pack/v1':
        return None
    source, envelope = payload.get('source') or {}, payload.get('result') or {}
    if not isinstance(source, dict) or not isinstance(envelope, dict):
        return None
    if (source.get('run_id') != run_root.name or source.get('operation_id') != 'time_series.arima'
            or source.get('artifact_id') not in artifact.inputs
            or envelope.get('contract') != 'time_series.pack.result' or envelope.get('status') != 'completed'
            or envelope.get('operation_id') != 'time_series.arima'):
        return None
    result = envelope.get('result') or {}
    if not isinstance(result, dict):
        return None
    native, policy = result.get('analysis_evidence') or {}, result.get('policy') or {}
    if not isinstance(native, dict) or not isinstance(policy, dict):
        return None
    if native.get('contract') != 'time-series.completion.v1' or native.get('model_type') != 'arima':
        return None
    try:
        with open_pinned_run_directory(run_root.parent, run_root.name) as pinned:
            snapshot = pinned.read_lmm_analysis_source(artifact_id=source.get('artifact_id'))
        if snapshot is None or snapshot[0]['sha256'] != source.get('sha256'):
            return None
        record, raw = snapshot
        # Match the ordinary P7 source-reader's CSV decoding; no rounding or
        # approximate fingerprint comparison is introduced here.
        frame = pd.read_parquet(io.BytesIO(raw)) if record['path'].endswith('.parquet') else pd.read_csv(io.BytesIO(raw))
        prepared = prepare_time_series(frame, time_column=native['time_column'],
            value_columns=[result['value_column']], time_order=policy['time_order'])
        fingerprint = input_fingerprint(prepared)
        positions = ordered_positions(frame, prepared)
        definition = {'input': fingerprint, 'order': policy['order'], 'seasonal_order': policy['seasonal_order'], 'trend': policy['trend']}
        if (native.get('input_fingerprint') != fingerprint or native.get('ordered_positions') != positions
                or native.get('nobs') != prepared.n_observations or native['nobs'] != envelope['n_observations']
                or native.get('point_estimation_fingerprint') != sha256_canonical(definition)
                or native.get('analysis_sample_fingerprint') != sha256_canonical(positions)):
            return None
        coefficients = native['coefficients']
        if (not isinstance(coefficients, dict) or set(coefficients) != set(result['parameters']) or not all(
                isinstance(row, dict) and
                row['estimate'] == result['parameters'][term] and type(row.get('std_error')) in {float, int}
                and np.isfinite(row['std_error']) and row['std_error'] >= 0 for term, row in coefficients.items())):
            return None
    except (OSError, ValueError, KeyError, TypeError, LmmPersistenceError, PinnedRunError):
        return None
    if native.get('converged') is not True:
        return None
    model = {**native, 'model_id': artifact.artifact_id}
    diagnostic = {'contract': 'time-series.completion.v1', 'model_id': artifact.artifact_id,
                  'diagnostics': {'time_series': native['diagnostics']}}
    return model, diagnostic
