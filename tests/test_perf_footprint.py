"""Peak memory is judged by the kernel's footprint high-water mark; ru_maxrss stays a reference.

2026-11-07 host retest (cb0e6fb7): OLS, DID, panel and fast IV failed the 5% peak-RSS
noise rule, DID and panel already in the frozen v1.9.0 lane. The 2026-11-04 diagnostic
showed 0.89 GB of malloc-freed reusable pages inside a 1.48 GB RSS peak; how many stay
resident follows system memory pressure. Every sample records ri_lifetime_max_phys_footprint;
on 2026-11-09 the user chose it as the gate's memory metric, with RSS evaluated as a reference.
"""
from pathlib import Path
import subprocess
import sys

import pytest

from perf_footprint import memory_accounting
from tests.test_perf_ab_gate import lane, observations  # noqa: F401


def _with_footprint(calibration, records, value=80.):
    for row in calibration + records['A'] + records['B']:
        row['footprint_bytes'] = value
        row['requested_delivery']['footprint_bytes'] = value + 5
    return calibration, records


def test_the_gate_verdict_reads_footprint_and_the_rss_reference_still_sees_rss(lane):
    calibration, records = _with_footprint(*observations())
    records['B'][0]['rss_bytes'] *= 2  # RSS noise only
    assert lane.evaluate_ab_case('ols', calibration, records, memory='rss')['failed']
    footprint = lane.evaluate_ab_case('ols', calibration, records)
    assert footprint['failed'] == [] and footprint['memory_metric'] == 'footprint'
    assert set(footprint['medians']['B']) == {'seconds', 'footprint_bytes', 'run_bytes', 'delivery_seconds',
                                              'delivery_footprint_bytes', 'delivery_run_bytes'}


@pytest.mark.parametrize('change', ['noise', 'growth', 'missing'])
def test_the_footprint_verdict_fails_on_footprint_noise_growth_or_absence(lane, change):
    calibration, records = _with_footprint(*observations())
    if change == 'noise':
        records['B'][0]['footprint_bytes'] *= 2
    elif change == 'growth':
        for row in records['B']:
            row['footprint_bytes'] *= 1.06
    else:
        del records['A'][0]['footprint_bytes']
    assert lane.evaluate_ab_case('ols', calibration, records, memory='footprint')['failed']


@pytest.mark.skipif(sys.platform != 'darwin', reason='kernel footprint accounting is read on macOS only')
def test_the_reader_returns_the_lifetime_peak_after_memory_is_freed():
    # A fresh process: in a long test run the lifetime peak may already exceed this block.
    probe = """
from perf_footprint import memory_accounting
before = memory_accounting()['footprint_bytes']
block = bytearray(256 * 1024 * 1024)
block[::16384] = b'1' * len(block[::16384])
peak = memory_accounting()['footprint_bytes']
del block
after = memory_accounting()
assert peak - before >= 250 * 1024 * 1024, (before, peak)
# The read of `peak` is followed by a few small allocations while the block is still alive,
# so the lifetime maximum may grow by a page after it (0 or 16 KiB in 12 runs, 2026-11-10).
assert peak <= after['footprint_bytes'] <= peak + 1024 * 1024, (peak, after)
assert after['reusable_peak_bytes'] >= 0 and after['compressed_peak_bytes'] >= 0
"""
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    done = subprocess.run([sys.executable, '-c', probe], cwd=scripts, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_the_gate_judges_footprint_and_reports_rss_as_a_reference():
    import perf_1m
    import perf_fast_engine
    import perf_native_io
    assert (perf_1m.GATE_MEMORY, perf_1m.REFERENCE_MEMORY) == ('footprint', 'rss')
    for driver in (perf_1m, perf_fast_engine, perf_native_io):
        source = Path(driver.__file__).read_text()
        assert 'memory=GATE_MEMORY' in source and "['reference_memory']" in source.replace('"', "'")


def test_an_rss_only_change_is_reported_but_does_not_fail_the_fast_engine_gate():
    from tests.test_perf_fast_engine import evaluate, report
    import perf_fast_engine
    evidence = report()
    for pair in evidence['pairs']:
        pair['fast']['rss_bytes'] = pair['reference']['rss_bytes'] * 1.2
    assert evaluate(perf_fast_engine, evidence)['passed']
    assert not perf_fast_engine.evaluate_report(evidence, memory='rss')['passed']
