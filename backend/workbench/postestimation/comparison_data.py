"""Verify the executed inputs before public likelihood-ratio comparisons.

Kernels deliberately describe inference, not arbitrary source data. Row labels
alone cannot certify the response and common regressors in two completed runs.
"""
from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Mapping
from pathlib import Path

import numpy as np
import pandas as pd

from ..artifacts import read_json
from ..contracts.model.inference_kernel import estimation_rows_fingerprint, kernel_relative_path
from ..contracts.model.result_envelope_registry import declaration_for
from .core import MODEL_BASED_COVARIANCES, PostestimationRefusal
from .estimation_data import _dataset_path


def _bound_bytes(root: Path, path: Path) -> bytes:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PostestimationRefusal('ESTIMATION_DATA_UNAVAILABLE', 'the estimation artifact is outside its owner run') from exc
    index = read_json(root / 'artifacts_index.json')
    matches = [item for item in index.get('artifacts', []) if item.get('path') == relative]
    if len(matches) != 1 or not isinstance(matches[0].get('sha256'), str):
        raise PostestimationRefusal('ESTIMATION_DATA_UNAVAILABLE', 'the estimation artifact has no unique recorded hash')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != matches[0]['sha256']:
        raise PostestimationRefusal('ESTIMATION_DATA_CHANGED', 'the recorded estimation artifact changed after fitting')
    return raw


def assert_completed_kernel(root: Path, kernel: Mapping) -> None:
    """Bind a kernel to an unchanged registered artifact of a completed run."""
    if read_json(root / 'run_manifest.json').get('status') != 'completed':
        raise PostestimationRefusal('MODEL_NOT_COMPLETED', 'post-estimation requires a completed owner run')
    recorded_kernel = json.loads(_bound_bytes(root, root / kernel_relative_path(kernel['model_id'])))
    if recorded_kernel != kernel:
        raise PostestimationRefusal('MODEL_BINDING_CHANGED', 'the inference kernel changed while resolving its owner')


def _executed_sample(root: Path, kernel: Mapping):
    assert_completed_kernel(root, kernel)
    packet = json.loads(_bound_bytes(root, root / 'model_results' / f"{kernel['model_id']}.json"))
    if packet.get('model_id') != kernel['model_id']:
        raise PostestimationRefusal('MODEL_BINDING_CHANGED', 'the result artifact identity does not match the inference kernel')
    identity = json.loads(_bound_bytes(root, root / 'diagnostic_summary.json')).get('model_identity', {})
    predictors = identity.get('x_variables')
    if not isinstance(predictors, list) or not all(isinstance(name, str) for name in predictors):
        raise PostestimationRefusal('ESTIMATION_DATA_UNAVAILABLE', 'the actual model inputs cannot be verified for LR')
    outcome = identity.get('y_variable')
    if not isinstance(outcome, str) or not outcome:
        raise PostestimationRefusal('ESTIMATION_DATA_UNAVAILABLE', 'the actual response cannot be verified for LR')
    frame = pd.read_parquet(io.BytesIO(_bound_bytes(root, _dataset_path(root))))
    columns = list(dict.fromkeys([outcome, *predictors]))
    weights = packet.get('weights')
    if isinstance(weights, Mapping) and kernel.get('weights') != 'none':
        column = weights.get('column')
        if not isinstance(column, str) or not column:
            raise PostestimationRefusal('ESTIMATION_DATA_UNAVAILABLE', 'the actual weight column cannot be verified for LR')
        columns.append(column)
    if any(column not in frame.columns for column in columns):
        raise PostestimationRefusal('ESTIMATION_DATA_UNAVAILABLE', 'the executed response or inputs are unavailable for LR')
    sample = frame[columns].dropna()
    if len(sample) != kernel['nobs'] or estimation_rows_fingerprint(list(sample.index)) != kernel.get('estimation_sample_fingerprint'):
        raise PostestimationRefusal('SAMPLE_UNVERIFIED', 'the actual estimation sample cannot be verified for LR')
    return outcome, sample, packet


def assert_lr_comparable(full_root: Path, full: Mapping, restricted_root: Path, restricted: Mapping) -> None:
    """Prove same response/data and owner-defined likelihood before consuming LR."""
    # Keep the primitive's original family/variance/weight refusal reasons.
    if full['model_type'] != restricted['model_type'] or any(
        kernel.get('covariance_estimator') not in MODEL_BASED_COVARIANCES
        or kernel.get('weights') == 'sampling' for kernel in (full, restricted)
    ):
        return
    try:
        full_y, full_data, full_packet = _executed_sample(full_root, full)
        restricted_y, restricted_data, restricted_packet = _executed_sample(restricted_root, restricted)
    except (OSError, ValueError, KeyError) as exc:
        if isinstance(exc, PostestimationRefusal):
            raise
        raise PostestimationRefusal('ESTIMATION_DATA_UNAVAILABLE', 'the completed models lack verifiable estimation inputs for LR') from exc
    if full_y != restricted_y:
        raise PostestimationRefusal('DIFFERENT_RESPONSES', 'the models have different response variables and are not comparable nested models')
    if not full_data.index.equals(restricted_data.index):
        raise PostestimationRefusal('DIFFERENT_SAMPLES', 'the models use different actual estimation rows')
    for column in set(full_data.columns).intersection(restricted_data.columns):
        if not np.array_equal(full_data[column].to_numpy(), restricted_data[column].to_numpy()):
            raise PostestimationRefusal('DIFFERENT_ESTIMATION_INPUTS', f'the models used different actual data for shared input {column}; LR is not comparable')
    owner = declaration_for(str(full['model_type']))
    for key in owner.likelihood_definition_fields if owner is not None else ():
        if key not in full_packet or key not in restricted_packet:
            raise PostestimationRefusal('LIKELIHOOD_UNVERIFIED', f'the fixed likelihood setting {key} is unavailable for LR')
        if full_packet[key] != restricted_packet[key]:
            raise PostestimationRefusal('DIFFERENT_LIKELIHOODS', f'the models use different fixed likelihood settings ({key}) and are not comparable')
