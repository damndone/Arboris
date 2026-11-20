"""Actual statistical producer integration, preparation and cancellation boundary."""
from itertools import combinations
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import pytest
from scipy import stats


def bits(value):return np.asarray(value,dtype=np.float64).tobytes()


@pytest.fixture
def api():
    from workbench import native_math
    return native_math


@pytest.fixture
def native(api):
    kernel=api._load_native()
    if kernel is None:pytest.skip('build native/spearman_ranks/build.py for actual native producer checks')
    return kernel


def test_default_actual_producer_uses_native_without_reference(api,native,monkeypatch):
    from workbench.statistical_tests import run_statistical_tests
    frame=pd.DataFrame({'x':np.arange(100,dtype=np.float64),'y':(np.arange(100,dtype=np.float64)*7)%100})
    reference=stats.spearmanr(frame.x,frame.y)
    def forbidden(*args,**kwargs):pytest.fail('default actual producer unexpectedly used reference Spearman')
    monkeypatch.setattr(api.stats,'spearmanr',forbidden)
    result=run_statistical_tests(frame,analysis_columns=['x','y'])
    row=next(r for r in result['rank_correlations']['results'] if r['test_type']=='spearman_correlation')
    assert row['computation']=={'engine':'native-average-rank','reason':None}
    assert bits(row['statistic'])==bits(reference.statistic) and bits(row['p_value'])==bits(reference.pvalue)


def test_pairwise_preparation_nobs_constants_nan_and_warning_lists(api,native):
    from workbench.statistical_test_pairs import _rank_correlations
    frame=pd.DataFrame({'x':[1.,np.nan,3.,4.,5.],'y':[5.,4.,np.nan,2.,1.]})
    expected=stats.spearmanr(frame[['x','y']].dropna().x,frame[['x','y']].dropna().y)
    spearman,kendall=_rank_correlations(frame,'x','y')
    assert spearman['nobs']==kendall['nobs']==3
    assert bits(spearman['statistic'])==bits(expected.statistic)
    assert bits(spearman['p_value'])==bits(expected.pvalue)
    assert spearman['warnings']==kendall['warnings']==[]
    assert spearman['warnings'] is not kendall['warnings']
    constant=_rank_correlations(pd.DataFrame({'x':[1.,1.,np.nan,1.],'y':[1.,2.,3.,4.]}),'x','y')
    assert len(constant)==2
    assert all(row['nobs']==3 and row['statistic'] is None and row['p_value'] is None for row in constant)
    assert all(row['warnings']==['CORRELATION_CONSTANT_INPUT'] for row in constant)
    assert constant[0]['warnings'] is not constant[1]['warnings']
    assert constant[0]['computation']=={'engine':'not-computed','reason':'constant-input'}
    assert _rank_correlations(frame.iloc[:2],'x','y')==[]


def test_precision_receipts_do_not_pollute_other_correlation_warnings(api,native):
    from workbench.statistical_test_pairs import _rank_correlations
    integers=np.array([1<<53,(1<<53)+1,(1<<53)+2,(1<<53)+3],dtype=np.int64)
    spearman,kendall=_rank_correlations(pd.DataFrame({'x':integers,'y':np.array([1,3,2,4],dtype=np.int64)}),'x','y')
    assert spearman['computation']['engine']=='native-average-rank'
    assert spearman['warnings']==[] and kendall['warnings']==['KENDALL_PUBLIC_INTEGER_PROMOTION']
    spearman,kendall=_rank_correlations(pd.DataFrame({'x':integers,'y':np.array([1.,3.,2.,4.])}),'x','y')
    assert spearman['computation']=={'engine':'scipy-public','reason':'public-integer-promotion-unsafe'}
    assert spearman['warnings']==[] and kendall['warnings']==['KENDALL_PUBLIC_INTEGER_PROMOTION']


def test_producer_explicit_cancel_preserves_original_during_native_and_stops_before_kendall(api,native,monkeypatch):
    from workbench import statistical_test_pairs
    original=RuntimeError('owner cancelled active native ranking')
    seen=[]
    def check():
        if native.workspace_info()['cpp_live_requested_bytes']:
            seen.append(True)
            raise original
    def forbidden(*args,**kwargs):pytest.fail('Kendall ran after cancelled Spearman')
    monkeypatch.setattr(statistical_test_pairs.native_kendall,'evaluate',forbidden)
    with pytest.raises(RuntimeError) as captured:
        statistical_test_pairs._rank_correlations(pd.DataFrame({'x':np.arange(100.),'y':(np.arange(100.)*7)%100}),
                                                  'x','y',check_cancel=check)
    assert captured.value is original and seen==[True]
    assert native.workspace_info()['cpp_live_requested_bytes']==0
    assert native.workspace_info()['python_output_live_in_kernel_bytes']==0


def test_actual_csv_all_ten_default_producer_pairs_keep_public_bits(api,native,record_property):
    from workbench.statistical_test_pairs import _rank_correlations
    source=Path(__file__).resolve().parents[1]/'local/perf-inputs/ols/wages.csv'
    if not source.exists():pytest.skip('fixed local 1M CSV unavailable')
    with source.open('rb') as stream:
        assert hashlib.file_digest(stream,'sha256').hexdigest()=='d7b25e65fa1875e205a31354feba22f5a9988a2647fb20fd232825ce2e9e595d'
    frame=pd.read_csv(source)
    raw=[]
    for left,right in combinations(['wage','education','experience','female','hours'],2):
        spearman,kendall=_rank_correlations(frame,left,right)
        pair=frame[[left,right]].dropna()
        expected=stats.spearmanr(pair[left],pair[right])
        assert spearman['computation']['engine']=='native-average-rank'
        assert bits(spearman['statistic'])==bits(expected.statistic)
        assert bits(spearman['p_value'])==bits(expected.pvalue)
        assert spearman['nobs']==kendall['nobs']==1_000_000
        assert spearman['warnings']==[]
        raw.append(bits(spearman['statistic'])+bits(spearman['p_value']))
    assert hashlib.sha256(b''.join(raw)).hexdigest()=='65b534fbdcd13ed10aa97d607c109b49f9a5fa4fd1723815adb65b5c9a31cda3'
    record_property('actual_producer_pairs',10)


def test_actual_producer_missing_binary_retains_public_values_and_audit(api,monkeypatch):
    from workbench.statistical_test_pairs import _rank_correlations
    monkeypatch.setattr(api,'_load_native',lambda:None)
    frame=pd.DataFrame({'x':[1.,4.,2.,3.],'y':[4.,2.,3.,1.]})
    expected=stats.spearmanr(frame.x,frame.y)
    row=_rank_correlations(frame,'x','y')[0]
    assert row['computation']=={'engine':'scipy-public','reason':'extension-not-built'}
    assert bits(row['statistic'])==bits(expected.statistic) and bits(row['p_value'])==bits(expected.pvalue)
    assert row['warnings']==[]


@pytest.mark.parametrize('reason',['extension-not-built','public-library-version-unverified',
                                  'dtype-outside-native64-envelope','public-integer-promotion-unsafe'])
def test_actual_producer_persists_reference_receipt_with_unchanged_numeric_bits(api,tmp_path,monkeypatch,reason):
    from workbench.statistical_tests import run_statistical_tests,write_statistical_test_artifacts
    from workbench.artifacts import initialize_artifact_index
    frame=pd.DataFrame({'x':np.array([1.,4.,2.,3.]),'y':np.array([4.,2.,3.,1.])})
    if reason=='extension-not-built':
        monkeypatch.setattr(api,'_load_native',lambda:None)
    elif reason=='public-library-version-unverified':
        monkeypatch.setattr(api,'_NUMPY_VERSION','unverified-version')
    elif reason=='dtype-outside-native64-envelope':
        frame=frame.astype(np.int32)
    else:
        frame=pd.DataFrame({'x':np.array([1<<53,(1<<53)+1,(1<<53)+2,(1<<53)+3],dtype=np.int64),
                            'y':np.array([1.,3.,2.,4.])})
    expected=stats.spearmanr(frame.x,frame.y)
    result=run_statistical_tests(frame,analysis_columns=['x','y'])
    initialize_artifact_index(tmp_path)
    write_statistical_test_artifacts(tmp_path,result)
    payload=json.loads((tmp_path/'statistical_tests/rank_correlations.json').read_text())
    spearman=next(row for row in payload['results'] if row['test_type']=='spearman_correlation')
    assert spearman['computation']=={'engine':'scipy-public','reason':reason}
    assert bits(spearman['statistic'])==bits(expected.statistic)
    assert bits(spearman['p_value'])==bits(expected.pvalue)
    assert spearman['warnings']==[]
