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


def read_garch_completion(run_root, artifact):
    """Verify the full-sample child, never promote the training-only parent."""
    from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
    from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input, ROW_ID_COLUMN
    from workbench.engine.packs.arma_garch.completion import input_fingerprint as garch_input, point_fingerprint, POINT_FIELDS
    from workbench.engine.packs.arma_garch.errors import ArmaGarchInputError
    import hashlib
    import json

    try:
        payload = artifact.payload or {}
        if artifact.artifact_type == 'workflow_capability_result':
            source, envelope = payload.get('source'), payload.get('result')
            if (payload.get('schema_version') != 'workbench.workflow.capability/v1'
                    or not isinstance(source, dict) or not isinstance(envelope, dict)
                    or source.get('run_id') != run_root.name or source.get('artifact_id') not in artifact.inputs
                    or source.get('operation_id') != 'model.time_series.arma_garch'
                    or envelope.get('operation_id') != 'model.time_series.arma_garch'
                    or envelope.get('status') != 'completed'
                    or hashlib.sha256(json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                        separators=(',', ':'), allow_nan=False).encode()).hexdigest() != payload.get('result_sha256')):
                return None
            result = envelope.get('result')
            source_ids = [source['artifact_id']]
        elif artifact.artifact_type == 'model_result':
            result, source, source_ids = payload, None, artifact.inputs
        else:
            return None
        if not isinstance(result, dict) or result.get('model_type') != 'time_series.arma_garch' or len(source_ids) != 1:
            return None
        child = result['production_child']
        native = child['analysis_evidence']
        summary = child['refit_summary']
        if not all(isinstance(v, dict) for v in [native, summary, native['diagnostics'], summary['analysis_evidence']]):
            return None
        if (native['contract'] != 'garch.completion.v1' or native['model_type'] != 'time_series.arma_garch'
                or child['result_role'] != 'production_final_child' or child['parent_result_id'] != result['model_id']
                or child['result_id'] != native['model_id']
                or child['fit_scope'] != 'all_available_observations' or native['fit_scope'] != child['fit_scope']
                or summary['fit_scope'] != child['fit_scope'] or summary['converged'] is not True
                or native['converged'] is not True or summary['finite_parameters'] is not True
                or summary['analysis_evidence']['coefficients'] != native['coefficients']
                or any(native['diagnostics'].get(k) != v for k,v in summary['analysis_evidence']['diagnostics'].items())):
            return None
        spec = child['next_forecast']['frozen_spec']
        if native['frozen_spec'] != spec or any(spec[k] != result['selected_specification'][k] for k in POINT_FIELDS):
            return None
        with open_pinned_run_directory(run_root.parent, run_root.name) as pinned:
            snapshot = pinned.read_lmm_analysis_source(artifact_id=source_ids[0])
        if snapshot is None or source and snapshot[0]['sha256'] != source.get('sha256'):
            return None
        record, raw = snapshot
        frame = pd.read_parquet(io.BytesIO(raw)) if record['path'].endswith('.parquet') else pd.read_csv(io.BytesIO(raw))
        contract = ArmaGarchAnalysisContract.from_dict(native['analysis_contract'])
        prepared = prepare_arma_garch_input(frame, contract)
        if (native['nobs'] != len(prepared.transformed_view) or native['nobs'] != summary['nobs']
                or native['input_fingerprint'] != garch_input(prepared)
                or native['point_estimation_fingerprint'] != point_fingerprint(prepared, spec)
                or native['analysis_sample_fingerprint'] != sha256_canonical(prepared.transformed_view[ROW_ID_COLUMN].tolist())):
            return None
        coefficients = native['coefficients']
        if (not isinstance(coefficients, dict) or not coefficients or not all(
                isinstance(row, dict) and all(type(row[k]) in {int, float} and np.isfinite(row[k])
                    for k in ['estimate', 'std_error']) and row['std_error'] >= 0 for row in coefficients.values())):
            return None
        if not isinstance(native['diagnostics'], dict):
            return None
    except (OSError, ValueError, KeyError, TypeError, LmmPersistenceError, PinnedRunError, ArmaGarchInputError):
        return None
    model = {**native, 'model_id': artifact.artifact_id + ':production-final'}
    diagnostic = {'contract': 'garch.completion.v1', 'model_id': model['model_id'],
                  'diagnostics': {'garch': native['diagnostics']}}
    return model, diagnostic
