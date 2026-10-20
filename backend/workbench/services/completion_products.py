"""Registered analysis-input readers shared by native completion products."""
from __future__ import annotations

import hashlib
import io
import pandas as pd

def source_binding(pinned, frame, *, artifact_id=None, csv_sha256=None):
    """Match the actual frame to one registered, content-verified data snapshot."""
    source = pinned.read_lmm_analysis_source(artifact_id=artifact_id, sha256=csv_sha256)
    if source is None:
        return None
    record, raw = source
    registered = read_analysis_frame(record, raw)
    if registered is None:
        return None
    # DataHandle may hold a named/nonunique index; positions below refer to the
    # original data order, never its pandas labels. CSV has no dtype authority.
    try:
        pd.testing.assert_frame_equal(frame.reset_index(drop=True), registered.reset_index(drop=True),
                                      check_dtype=False, check_exact=True, check_categorical=False)
    except AssertionError:
        return None
    return {'artifact_id': record['artifact_id'], 'sha256': hashlib.sha256(raw).hexdigest(),
            'row_count': len(frame)}


def read_analysis_frame(record, raw):
    """Decode supported registered analysis inputs without guessing a format."""
    suffix = str(record['path']).rsplit('.', 1)[-1].lower()
    if suffix == 'parquet':
        return pd.read_parquet(io.BytesIO(raw))
    if suffix == 'csv':
        return pd.read_csv(io.BytesIO(raw), float_precision='round_trip')
    return None


