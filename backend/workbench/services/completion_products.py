"""Compact registered input identities; no source re-read during publication."""
from __future__ import annotations

import hashlib
import io
import json
import numpy as np
import pandas as pd


def array_fingerprint(values):
    """Versioned C-order bytes, including dtype and shape; never Python scalars."""
    array = np.asarray(values)
    if array.dtype.hasobject:
        raise TypeError('object arrays have no stable byte representation')
    header = {'version': 'numpy-bytes.v1', 'dtype': array.dtype.str, 'shape': list(array.shape)}
    digest = hashlib.sha256(json.dumps(header, sort_keys=True, separators=(',', ':')).encode() + b'\0')
    if array.dtype.kind in 'mM':
        # Dates and durations expose no buffer ("cannot include dtype 'M' in a
        # buffer" failed every panel, DID, IV, Cox or LMM fit on a frame with a
        # date column). Their int64 ticks are the value; the header keeps the unit.
        array = array.view(np.dtype('<i8') if array.dtype.byteorder in '<=|' else np.dtype('>i8'))
    if array.flags.c_contiguous:
        digest.update(memoryview(array).cast('B'))
    else:
        # Canonical C order without copying an entire Fortran/strided matrix.
        for block in np.nditer(array, flags=['external_loop', 'buffered'],
                               op_flags=['readonly'], order='C', buffersize=131072):
            digest.update(memoryview(np.ascontiguousarray(block)).cast('B'))
    return digest.hexdigest()


def frame_fingerprint(frame):
    # Column-wise hashing bounds temporary memory to one column and handles
    # strings/categoricals by value, never by Python object addresses.
    columns = []
    for name, series in frame.items():
        values = series.to_numpy(copy=False)
        encoding = 'numpy-bytes.v1'
        if values.dtype.hasobject:
            values = pd.util.hash_pandas_object(series, index=False).to_numpy()
            encoding = 'pandas-value-hash.v1'
        columns.append({'name': str(name), 'dtype': str(series.dtype), 'encoding': encoding,
                        'sha256': array_fingerprint(values)})
    return hashlib.sha256(json.dumps({'version': 'dataframe-columns.v1', 'columns': columns,
        'rows': len(frame)}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sample_metadata(positions, source_rows):
    positions = np.asarray(positions, dtype='<i8')
    return {'retained_count': int(positions.size), 'missing_count': int(source_rows-positions.size),
            'fingerprint_version': 'numpy-bytes.v1', 'positions_sha256': array_fingerprint(positions)}


def source_binding(pinned, frame, *, artifact_id=None, csv_sha256=None):
    """Bind import-time registration to the live frame without decoding a copy."""
    record = pinned.lmm_source_record(artifact_id=artifact_id, sha256=csv_sha256)
    if record is None:
        return None
    return {'artifact_id': record['artifact_id'], 'sha256': record['sha256'],
            'row_count': len(frame), 'frame_fingerprint': frame_fingerprint(frame),
            'frame_fingerprint_version': 'dataframe-columns.v1'}


def read_analysis_frame(record, raw):
    """Explicit artifact reads (not publication) decode registered snapshots."""
    suffix = str(record['path']).rsplit('.', 1)[-1].lower()
    if suffix == 'parquet':
        return pd.read_parquet(io.BytesIO(raw))
    if suffix == 'csv':
        return pd.read_csv(io.BytesIO(raw), float_precision='round_trip')
    return None
