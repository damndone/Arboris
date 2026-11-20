"""Independent average-rank definitions and public numerical/selection contract."""
from fractions import Fraction
from itertools import permutations,product
from types import SimpleNamespace
import logging
import struct

import numpy as np
import pytest
from scipy import stats


@pytest.fixture
def kernel():
    from workbench import native_math
    return native_math


@pytest.fixture
def native(kernel):
    result=kernel._load_native()
    if result is None:pytest.skip('build native/spearman_ranks/build.py for native checks')
    return result


def bits(value):return np.asarray(value,dtype=np.float64).tobytes()


def definition(values):
    return [float(Fraction(2*sum(other<v for other in values)+sum(other==v for other in values)+1,2)) for v in values]


@pytest.mark.parametrize('dtype,base',[(np.float64,0),(np.int64,(1<<63)-3),(np.uint64,(1<<64)-3)])
def test_enumerated_tie_patterns_use_independent_order_count_definition(kernel,native,dtype,base):
    for pattern in product(range(3),repeat=5):
        values=np.asarray([base+x for x in pattern],dtype=dtype)
        ranks=kernel.average_ranks(values.reshape(-1,1))
        assert ranks[:,0].tolist()==definition(values.tolist())


def test_all_six_item_permutations_and_immutable_f_layout(kernel,native):
    for order in permutations(range(6)):
        matrix=np.asarray(order,dtype=np.int64).reshape(-1,1)
        assert kernel.average_ranks(matrix)[:,0].tolist()==[x+1. for x in order]
    values=np.array([[3.,1.],[1.,4.],[2.,4.],[2.,2.]])
    ranks=kernel.average_ranks(values)
    assert ranks.strides==(8,32) and ranks.flags.f_contiguous and not ranks.flags.writeable
    assert ranks.tobytes(order='F')==struct.pack('=8d',4,1,2.5,2.5,1,3.5,3.5,2)
    with pytest.raises(ValueError):ranks.setflags(write=True)


@pytest.mark.parametrize('alternative',['less','greater','two-sided'])
@pytest.mark.parametrize('dtype',[np.float64,np.int64,np.uint64])
def test_public_pair_float_bits_and_reduction_order(kernel,native,alternative,dtype):
    a=np.asarray([5,1,4,1,7,8,4,10],dtype=dtype)
    b=np.asarray([3,4,1,8,6,7,7,2],dtype=dtype)
    result=kernel.evaluate_spearman(a,b,alternative=alternative)
    reference=stats.spearmanr(a,b,alternative=alternative)
    assert result.engine=='native-average-rank' and result.reason is None
    assert bits(result.statistic)==bits(reference.statistic)
    assert bits(result.pvalue)==bits(reference.pvalue)


@pytest.mark.parametrize('dtype,values',[
    (np.float64,[-np.nextafter(0.,1.),-0.,0.,np.nextafter(0.,1.)]),
    (np.int64,[-(1<<63),1<<53,(1<<53)+1,(1<<63)-1]),
    (np.uint64,[0,1<<53,(1<<53)+1,(1<<64)-1]),
])
def test_native64_boundaries_and_noncontiguous_input(kernel,native,dtype,values):
    matrix=np.asarray([values,list(reversed(values))],dtype=dtype).T
    for source in (matrix,np.asfortranarray(matrix),matrix[::-1,::-1]):
        ranked=kernel.average_ranks(source)
        for col in range(2):assert ranked[:,col].tolist()==definition(source[:,col].tolist())


def test_unsafe_public_promotion_explicitly_preserves_original_semantics(kernel,native):
    a=np.array([1<<53,(1<<53)+1,(1<<53)+2,(1<<53)+3],dtype=np.int64)
    b=np.array([3.,1.,4.,2.])
    result=kernel.evaluate_spearman(a,b)
    reference=stats.spearmanr(a,b)
    assert result.engine=='scipy-public' and result.reason=='public-integer-promotion-unsafe'
    assert result.native_public_promotion_refused
    assert bits(result.statistic)==bits(reference.statistic) and bits(result.pvalue)==bits(reference.pvalue)


@pytest.mark.parametrize('a,b,reason',[
    (np.array([1.,2.,np.nan]),np.array([3.,2.,1.]),'nonfinite-input'),
    (np.array([1.,2.,np.inf]),np.array([3.,2.,1.]),'nonfinite-input'),
    (np.array([1,2,3],dtype=np.int32),np.array([3,2,1],dtype=np.int32),'dtype-outside-native64-envelope'),
    (np.array([1.,1.,1.]),np.array([3.,2.,1.]),'constant-input'),
])
def test_reference_envelope_preserves_public_results(kernel,a,b,reason):
    with np.errstate(invalid='ignore'):
        result=kernel.evaluate_spearman(a,b)
        reference=stats.spearmanr(a,b)
    assert result.engine=='scipy-public' and result.reason==reason
    assert bits(result.statistic)==bits(reference.statistic) and bits(result.pvalue)==bits(reference.pvalue)


def test_absent_native_is_audited_without_observations(kernel,monkeypatch,caplog):
    monkeypatch.setattr(kernel,'_load_native',lambda:None)
    a=np.array([1.,3.,2.,4.]);b=np.array([3.,1.,4.,2.])
    with caplog.at_level(logging.INFO,logger='workbench.native_math'):
        result=kernel.evaluate_spearman(a,b)
    assert result.engine=='scipy-public' and result.reason=='extension-not-built'
    assert any(getattr(record,'spearman_reason',None)=='extension-not-built' for record in caplog.records)
    assert kernel.backend_info()['engine']=='scipy-public'


def test_broken_foreign_and_non_integer_abi_fail_explicitly(kernel,tmp_path,monkeypatch):
    monkeypatch.setattr(kernel,'_extension_directory',lambda:tmp_path)
    kernel._load_native.cache_clear()
    try:
        (tmp_path/'_spearman_rank.foreign.so').write_bytes(b'foreign')
        with pytest.raises(RuntimeError,match='ABI'):kernel._load_native()
        (tmp_path/'_spearman_rank.foreign.so').unlink()
        exact=tmp_path/('_spearman_rank'+kernel.EXT_SUFFIX);exact.write_bytes(b'corrupt')
        with pytest.raises(ImportError):kernel._load_native()
    finally:kernel._load_native.cache_clear()


@pytest.mark.parametrize('version',[True,1.,None,2])
def test_declared_bad_abi_is_not_treated_as_missing(kernel,tmp_path,monkeypatch,version):
    spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda module:None))
    monkeypatch.setattr(kernel.importlib.util,'spec_from_file_location',lambda *args:spec)
    monkeypatch.setattr(kernel.importlib.util,'module_from_spec',lambda unused:SimpleNamespace(ABI_VERSION=version))
    with pytest.raises(RuntimeError,match='ABI'):kernel._load_extension(tmp_path/'bad.so')


def test_native_runtime_failure_propagates_and_workspace_unwinds(kernel,native,monkeypatch):
    original=RuntimeError('native compute failed')
    def fail(*args):raise original
    monkeypatch.setattr(native,'rank_matrix',fail)
    with pytest.raises(RuntimeError) as captured:
        kernel.evaluate_spearman(np.array([1.,2.,3.]),np.array([2.,3.,1.]))
    assert captured.value is original


def test_allocator_and_python_output_ownership_are_separate(kernel,native):
    before=native.workspace_info()
    raw=native.rank_matrix(np.arange(16,dtype=np.int64).reshape(8,2))
    after=native.workspace_info()
    assert after['cpp_total_requested_bytes']-before['cpp_total_requested_bytes']==208
    assert after['cpp_allocations']-before['cpp_allocations']==4
    assert after['cpp_live_requested_bytes']==0
    assert after['python_output_total_requested_bytes']-before['python_output_total_requested_bytes']==128
    assert after['python_output_live_in_kernel_bytes']==0 and len(raw)==128


@pytest.mark.parametrize('matrix,error',[
    (np.ones((4,2),dtype=np.int32),TypeError),
    (np.ones(4,dtype=np.float64),ValueError),
    (np.ones((3,33),dtype=np.float64),ValueError),
    (np.array([[1.,2.],[3.,np.inf]]),ValueError),
    (np.ones((4,2),dtype=np.dtype('>f8')),TypeError),
])
def test_raw_native_rejects_outside_envelope_and_leaks_no_workspace(kernel,native,matrix,error):
    with pytest.raises(error):native.rank_matrix(matrix)
    assert native.workspace_info()['cpp_live_requested_bytes']==0
    assert native.workspace_info()['python_output_live_in_kernel_bytes']==0


def test_invalid_native_byte_result_is_not_a_silent_reference(kernel,native,monkeypatch):
    monkeypatch.setattr(native,'rank_matrix',lambda *args:b'')
    with pytest.raises(RuntimeError,match='invalid rank byte buffer'):
        kernel.evaluate_spearman(np.array([1.,2.,3.]),np.array([2.,3.,1.]))


def test_invalid_public_alternative_keeps_public_error(kernel,native):
    with pytest.raises(ValueError,match='alternative'):
        kernel.evaluate_spearman(np.array([1.,2.,3.]),np.array([2.,3.,1.]),alternative='bad')
