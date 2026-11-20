"""Default A/B acceptance uses complete observations, without launching product workers."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def lane(monkeypatch):
    spec = importlib.util.spec_from_file_location('perf_ab_gate', Path(__file__).parents[1] / 'scripts/perf_1m.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Fixture repositories are not Git checkouts; the evidence key has its own tests.
    monkeypatch.setattr(module, 'evidence_key', lambda repo, **kwargs: {'source_tree': {'sha256': 'tree'}})
    monkeypatch.setattr(module, 'source_tree', lambda repo, *args: {'sha256': 'tree'})
    return module


def observations():
    signature = {'coefficients': {'x': {'estimate': {'binary64': '0x1p+0'},
                                       'std_error': {'binary64': '0x1p-1'}, 'p_value':0.01, 'ci_lower':0.1, 'ci_upper':1.9}}, 'nobs': 100,
                 'inference_kernel': {'param_names':['x'], 'params':[1.], 'vcov':[[.25]], 'vcov_param_names':['x'],
                                      'vcov_scope':'full', 'reference_distribution':'t', 'df_resid':99, 'nobs':100,
                                      'df_method':'residual', 'unavailable':{}, 'n_clusters':None, 'loglik':None,
                                      'covariance_estimator':None, 'estimation_sample_fingerprint':None,
                                      'weights':'none', 'interfaces':['coef_vcov']}}
    signature['statistical_tests'] = statistical_payloads()
    def row(lane, label):
        return {'label': label, 'status': 'completed', 'returncode': 0, 'host_monitor': {'valid': True},
                'seconds': 5. if lane == 'A' else 4., 'rss_bytes': 100., 'footprint_bytes': 90., 'run_bytes': 100.,
                'numeric_signature': copy.deepcopy(signature), 'tracemalloc_peak_bytes': 20.,
                'requested_delivery': {'status': 'completed', 'seconds': 6. if lane == 'A' else 5.,
                                       'rss_bytes': 110., 'footprint_bytes': 95., 'run_bytes': 120., 'figure_count': 1,
                                       'figure_artifact_ids': ['figure']}}
    return [row('A', f'A0_{i}') for i in range(5)], {key: [row(key, f'{key}{i}') for i in range(5)] for key in 'AB'}


def test_complete_report_checks_every_lane_and_delivery_clock(lane):
    calibration, records = observations()
    result = lane.evaluate_ab_case('ols', calibration, records)
    assert result['failed'] == []
    assert set(result['noise']) == {'calibration', 'baseline_pairs', 'all_baseline', 'candidate'}
    assert set(result['medians']['A']) == {'seconds', 'footprint_bytes', 'run_bytes', 'delivery_seconds', 'delivery_footprint_bytes', 'delivery_run_bytes'}
    assert result['absolute_seconds_cap'] == 8.


@pytest.mark.parametrize('metric', ['seconds', 'footprint_bytes', 'run_bytes', 'delivery_seconds', 'delivery_footprint_bytes', 'delivery_run_bytes'])
def test_candidate_noise_is_a_failure_for_each_metric(lane, metric):
    calibration, records = observations()
    if metric.startswith('delivery_'):
        records['B'][0]['requested_delivery'][metric.removeprefix('delivery_')] *= 2
    else:
        records['B'][0][metric] *= 2
    assert lane.evaluate_ab_case('ols', calibration, records)['failed']


@pytest.mark.parametrize('value', [0, -1, None, float('nan'), float('inf')])
def test_invalid_metrics_never_produce_an_accepted_median(lane, value):
    calibration, records = observations()
    records['B'][0]['footprint_bytes'] = value
    assert lane.evaluate_ab_case('ols', calibration, records)['failed']


def test_reference_calibration_bits_are_part_of_the_exact_gate(lane):
    calibration, records = observations()
    calibration[0]['numeric_signature']['coefficients']['x']['estimate']['binary64'] = '0x1.0000000000001p+0'
    assert 'numeric_bits' in lane.evaluate_ab_case('ols', calibration, records)['failed']


def test_incomplete_signature_and_hidden_nan_are_not_repeated_agreement(lane):
    calibration, records = observations()
    for row in calibration + records['A'] + records['B']:
        row['numeric_signature']['coefficients']['x']['std_error']['binary64'] = 'nan'
    assert lane.evaluate_ab_case('ols', calibration, records)['failed']


def test_tracing_never_replaces_unstable_resident_memory(lane):
    calibration, records = observations()
    records['B'][0]['footprint_bytes'] = 300.
    assert lane.evaluate_ab_case('ols', calibration, records, trace_memory=True)['failed']


def test_host_intrusion_and_different_delivery_are_not_accepted(lane):
    calibration, records = observations()
    records['B'][0]['host_monitor']['valid'] = False
    records['B'][1]['requested_delivery']['figure_artifact_ids'] = ['other']
    assert lane.evaluate_ab_case('ols', calibration, records)['failed']


def test_five_fixed_pairs_genuinely_alternate_first_lane(lane):
    assert lane.AB_ORDER == ['A1', 'B1', 'B2', 'A2', 'A3', 'B3', 'B4', 'A4', 'A5', 'B5']
    calibration, records = observations()
    calibration.pop()
    assert lane.evaluate_ab_case('ols', calibration, records)['failed']


def test_inventory_covers_rust_manifest_shared_libraries_and_cli(lane, tmp_path):
    paths = ['backend/workbench/f.py', 'native/engine/src/lib.rs', 'native/engine/Cargo.toml',
             'native/engine/Cargo.lock', 'local/native-engine/libarboris_engine.dylib',
             'local/native-engine/target/release/arboris-engine', 'local/native-engine/build-manifest.json']
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}' if name.endswith('.json') else name)
    assert set(paths) <= lane.product_sources(tmp_path).keys()


def test_legacy_build_is_explicit_not_current_and_current_missing_build_fails(lane, tmp_path):
    assert lane.build_identity(tmp_path)['kind'] == 'legacy_source_and_artifact_hash_only'
    helper = tmp_path / 'backend/workbench/native_build.py'
    helper.parent.mkdir(parents=True)
    helper.write_text('# modern helper, no binaries\n')
    with pytest.raises((RuntimeError, ValueError)):
        lane.build_identity(tmp_path)


def test_eager_baseline_delivery_never_imports_missing_new_module(lane, tmp_path, monkeypatch):
    import builtins
    import hashlib
    original = builtins.__import__
    def imports(name, *args, **kwargs):
        if name == 'workbench.figure_plans':
            raise ImportError('v1.9.0 does not have this module')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', imports)
    (tmp_path / 'figures').mkdir()
    (tmp_path / 'figures/f.png').write_bytes(b'real figure')
    (tmp_path / 'artifacts_index.json').write_text(json.dumps({'artifacts': [{
        'artifact_id': 'f', 'artifact_type': 'figure', 'path': 'figures/f.png',
        'sha256': hashlib.sha256(b'real figure').hexdigest()}]}))
    result = lane.requested_figure_delivery(tmp_path, started=0., requested=True,
        analysis_ready={'seconds': 2., 'rss_bytes': 10., 'run_bytes': 20.})
    assert result['status'] == 'completed' and result['mode'] == 'eager_registered'
    assert result['seconds'] == 2. and result['figure_artifact_ids'] == ['f']


def test_planned_delivery_with_missing_module_fails_instead_of_skipping(lane, tmp_path, monkeypatch):
    import builtins
    original = builtins.__import__
    def imports(name, *args, **kwargs):
        if name == 'workbench.figure_plans':
            raise ImportError('broken planned renderer')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', imports)
    (tmp_path / 'figures').mkdir()
    (tmp_path / 'figures/plan.json').write_text('{}')
    with pytest.raises(ImportError, match='broken planned'):
        lane.requested_figure_delivery(tmp_path, started=0., requested=True)


@pytest.mark.parametrize('missing', ['p_value', 'ci_lower', 'ci_upper'])
def test_shared_missing_inference_field_is_not_exact_agreement(lane, missing):
    calibration, records = observations()
    for row in calibration + records['A'] + records['B']:
        del row['numeric_signature']['coefficients']['x'][missing]
    assert lane.evaluate_ab_case('ols', calibration, records)['failed']


@pytest.mark.parametrize('damage', ['missing', 'covariance', 'df', 'nonfinite', 'missing_definition'])
def test_persisted_kernel_must_be_complete_and_identical(lane, damage):
    calibration, records = observations()
    if damage == 'missing':
        for row in calibration + records['A'] + records['B']:
            del row['numeric_signature']['inference_kernel']
    elif damage == 'covariance':
        records['B'][0]['numeric_signature']['inference_kernel']['vcov'][0][0] += 1e-14
    elif damage == 'df':
        records['B'][0]['numeric_signature']['inference_kernel']['df_resid'] += 1
    elif damage == 'nonfinite':
        for row in calibration + records['A'] + records['B']:
            row['numeric_signature']['inference_kernel']['vcov'][0][0] = {'nonfinite':'NaN'}
    else:
        for row in calibration + records['A'] + records['B']:
            del row['numeric_signature']['inference_kernel']['df_method']
    assert lane.evaluate_ab_case('ols', calibration, records)['failed']


def test_kernel_projection_retains_full_small_matrix_and_na_definitions_only(lane, tmp_path):
    root = tmp_path/'model_results/inference_kernels'
    root.mkdir(parents=True)
    value = observations()[0][0]['numeric_signature']['inference_kernel']
    value['observation_ids'] = list(range(1000))
    (root/'ols_1.json').write_text(json.dumps(value))
    result = lane.primary_inference_signature(tmp_path, 'ols_1')
    assert result == {k:v for k,v in value.items() if k != 'observation_ids'}
    assert result['vcov'] == [[.25]] and result['unavailable'] == {}
    with pytest.raises(FileNotFoundError):
        lane.primary_inference_signature(tmp_path, 'missing')


def test_nonfinite_json_placeholder_in_p_value_is_rejected(lane):
    calibration, records = observations()
    for row in calibration + records['A'] + records['B']:
        row['numeric_signature']['coefficients']['x']['p_value'] = {'nonfinite':'NaN'}
    assert lane.evaluate_ab_case('ols', calibration, records)['failed']


@pytest.fixture
def ab_protocol(lane, tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(lane.require_space.__globals__['shutil'], 'disk_usage', lambda _: SimpleNamespace(free=10**12))
    baseline = tmp_path/'baseline'
    baseline.mkdir()
    prepare = lane.prepare_family
    monkeypatch.setattr(lane, 'prepare_family', lambda case, out: prepare(case, out, rows=40))
    monkeypatch.setattr(lane, 'idle_processes', lambda _: None)
    monkeypatch.setattr(lane, 'product_sources', lambda _: {})
    monkeypatch.setattr(lane, 'build_identity', lambda _: {})
    monkeypatch.setattr(lane, 'baseline_source_state', lambda _: {'git_status':''})
    import subprocess
    monkeypatch.setattr(subprocess, 'check_output', lambda cmd, cwd=None, text=False:
        b'' if cmd[1] == 'diff' else 'baseline' if cwd == baseline or cmd[-1] == 'v1.9.0^{commit}' else 'candidate')
    out = tmp_path/'campaign'
    return lane, out, ['--ab', '--baseline-repo', str(baseline), '--out', str(out),
                       '--inputs', str(tmp_path/'inputs'), '--cases', 'ols']


def test_missing_metrics_preserves_readable_worker_logs_and_stops(ab_protocol, monkeypatch):
    lane, out, command = ab_protocol
    called = []
    def worker(*args, **kwargs):
        called.append(args)
        (out/'active/raw-worker').mkdir(parents=True)
        (out/'active/raw-worker/workflow_log.jsonl').write_text('original failure detail')
        return 1, 'original stdout', 'original traceback', {'valid':True}
    monkeypatch.setattr(lane, 'monitored_worker', worker)
    with pytest.raises(SystemExit, match='failed; evidence retained'):
        lane.ab_main(command)
    assert len(called) == 1 and not (out/'active').exists()
    retained = out/'logs/ols-A0_01.logs'
    assert (retained/'stderr.log').read_text() == 'original traceback'
    assert (retained/'stdout.log').read_text() == 'original stdout'
    assert (retained/'raw-worker/workflow_log.jsonl').read_text() == 'original failure detail'
    saved = lane.finalize_active.__globals__['read_records'](out/'measurements.jsonl')
    assert saved[0]['metadata']['status'] == 'failed'
    assert len(saved[0]['metadata']['retained_logs']) == 3


@pytest.mark.parametrize('kind', ['build', 'opposite_lane_source', 'input_ctime', 'manifest'])
def test_identity_change_during_worker_cannot_be_accepted(ab_protocol, monkeypatch, kind):
    import os
    lane, out, command = ab_protocol
    changed = False
    if kind == 'build':
        monkeypatch.setattr(lane, 'build_identity', lambda _: {'identity': int(changed)})
    if kind == 'opposite_lane_source':
        monkeypatch.setattr(lane, 'product_sources', lambda repo: {'source': int(changed)} if repo.name != 'baseline' else {})
    def worker(args, *a, **kw):
        nonlocal changed
        (out/'active').mkdir()
        (out/'active/partial').write_text('keep failure tree')
        manifest = Path(args[args.index('--manifest')+1])
        if kind == 'input_ctime':
            source = Path(json.loads(manifest.read_text())['source'])
            stat = source.stat()
            source.write_bytes(source.read_bytes())
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        if kind == 'manifest':
            manifest.write_text(manifest.read_text()+'\n')
        changed = True
        return 0, '', '', {'valid':True}
    monkeypatch.setattr(lane, 'monitored_worker', worker)
    with pytest.raises(SystemExit, match='changed'):
        lane.ab_main(command)
    assert (out/'active/partial').exists()
    assert not (out/'measurements.jsonl').exists()


def test_watchdog_uses_full_monitor_and_bounded_terminate_then_kill(lane, tmp_path, monkeypatch):
    import perf_host
    import subprocess
    waits = []
    class Process:
        returncode = -9
        def communicate(self, *, timeout):
            waits.append(timeout)
            if waits.count(2) < 2:
                raise subprocess.TimeoutExpired('worker', timeout)
            return 'last stdout', 'last stderr'
        def terminate(self):
            waits.append('terminate')
        def kill(self):
            waits.append('kill')
        def poll(self):
            return self.returncode
    class Monitor:
        def __init__(self, *args):
            self.errors = []
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.summary = {'valid':not self.errors, 'errors':self.errors, 'covers_worker':True}
        def popen(self, *args, **kwargs):
            return Process()
    monkeypatch.setattr(perf_host, 'monitor_host', Monitor)
    code, stdout, stderr, host = perf_host.monitored_worker(['worker'], tmp_path/'host', timeout=120)
    assert waits == [120, 'terminate', 2, 'kill', 2]
    assert code == -9 and stdout == 'last stdout' and stderr == 'last stderr'
    assert host['covers_worker'] and not host['valid'] and 'worker_timeout' in host['errors'][0]


def test_delivery_keeps_the_original_ols_eight_second_target(lane):
    calibration, records = observations()
    for row in calibration + records['A']:
        row['requested_delivery']['seconds'] = 10.
    for row in records['B']:
        row['requested_delivery']['seconds'] = 9.
    result = lane.evaluate_ab_case('ols', calibration, records)
    assert result['budgets']['delivery_seconds'] == 8.
    assert 'delivery_seconds' in result['failed']


def test_worker_reported_wrong_input_digest_is_not_rewritten_into_agreement(ab_protocol, monkeypatch):
    lane, out, command = ab_protocol
    calls = []
    def worker(args, *a, **kw):
        active = out/'active'
        active.mkdir()
        value = observations()[0][0]
        value.update(input_sha256='wrong-worker-input', run_root=str(active/'benchmark'))
        (active/'benchmark').mkdir()
        (active/'metrics.json').write_text(json.dumps(value))
        calls.append(args)
        return 0, '', '', {'valid':True}
    monkeypatch.setattr(lane, 'monitored_worker', worker)
    with pytest.raises(SystemExit, match='failed; evidence retained'):
        lane.ab_main(command)
    assert len(calls) == 1 and not (out/'active').exists()
    failed = json.loads((out/'ab-results.json').read_text())['cases']['ols']['failed_runs'][0]
    assert failed['status'] == 'failed' and failed['worker_input_sha256'] == 'wrong-worker-input'


def test_report_templates_and_packaged_resources_are_frozen(lane, tmp_path):
    names = ['templates/report.html.j2', 'templates/shared.jinja2', 'templates/report.html',
             'templates/report.css', 'contracts/report.schema.json']
    for name in names:
        path = tmp_path/'backend/workbench'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('original resource')
    before = lane.product_sources(tmp_path)
    assert set('backend/workbench/'+name for name in names) <= before.keys()
    template = tmp_path/'backend/workbench/templates/report.html.j2'
    template.write_text('changed real report template')
    assert lane.product_sources(tmp_path)[str(template.relative_to(tmp_path))] != before[str(template.relative_to(tmp_path))]


def test_baseline_admission_rejects_staged_unstaged_and_untracked_product(lane, tmp_path, monkeypatch):
    import subprocess
    for status in (' M backend/workbench/run.py\n', 'M  native/engine/src/lib.rs\n', '?? backend/workbench/new.py\n'):
        monkeypatch.setattr(subprocess, 'check_output', lambda *a, **kw: status)
        with pytest.raises(SystemExit, match='Baseline backend/native'):
            lane.baseline_source_state(tmp_path)


def test_baseline_admission_allows_untracked_evaluation_scripts(lane, tmp_path, monkeypatch):
    import subprocess
    def git(args, **kwargs):
        assert args == ['git', 'status', '--porcelain=v1', '--untracked-files=all', '--', 'backend', 'native']
        assert kwargs['cwd'] == tmp_path
        return ''  # The existing scripts/agent_eval* harness lies outside both paths.
    monkeypatch.setattr(subprocess, 'check_output', git)
    assert lane.baseline_source_state(tmp_path) == {'git_status': ''}


def test_baseline_git_state_is_refrozen_after_worker(ab_protocol, monkeypatch):
    lane, out, command = ab_protocol
    states = iter([{'git_status':''}, {'git_status':''}, {'git_status':'changed'}])
    monkeypatch.setattr(lane, 'baseline_source_state', lambda _: next(states))
    def worker(*args, **kwargs):
        (out/'active').mkdir()
        (out/'active/partial').write_text('retained')
        return 0, '', '', {'valid':True}
    monkeypatch.setattr(lane, 'monitored_worker', worker)
    with pytest.raises(SystemExit, match='Baseline product Git state changed'):
        lane.ab_main(command)
    assert (out/'active/partial').read_text() == 'retained'


def test_both_readiness_clocks_and_resource_ratios_are_explicit(lane):
    calibration, records = observations()
    result = lane.evaluate_ab_case('ols', calibration, records)
    assert result['ratios'] == {'seconds':.8, 'footprint_bytes':1., 'run_bytes':1.,
                                'delivery_seconds':5./6., 'delivery_footprint_bytes':1., 'delivery_run_bytes':1.}


STAT_FILES = ('anova.json', 'chi_square.json', 'correlations.json', 'evidence.json',
              'fisher_exact.json', 'nonparametric.json', 'rank_correlations.json', 't_tests.json')


def statistical_payloads():
    return {name: {'schema_version':1, 'results':[{'statistic':1.25, 'p_value':.05}]}
            for name in STAT_FILES}


@pytest.fixture
def persisted_statistics_worker(lane, tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(lane, 'require_space', lambda *a, **kw: 10**12)
    monkeypatch.setattr(lane, 'create_project', lambda out, name: SimpleNamespace(root=out/name))
    def generate(name, mutate=lambda value: None, *, case='ols', registered_evidence=False):
        manifest = lane.prepare_family(case, tmp_path/'input'/case, rows=40)
        model_id = {'ols': 'ols_1', 'did': 'did_1', 'panel': 'panel_ols_1', 'cox': 'survival_cox_1'}[case]
        def workflow(root, sources, **kwargs):
            run = root/'runs/r1'
            (run/'model_results/inference_kernels').mkdir(parents=True)
            kernel = observations()[0][0]['numeric_signature']['inference_kernel']
            (run/f'model_results/inference_kernels/{model_id}.json').write_text(json.dumps(kernel))
            (run/f'model_results/{model_id}.json').write_text(json.dumps({'nobs':100, 'coefficients':{
                'x':{'estimate':1., 'std_error':.5, 'p_value':.01, 'ci_lower':.1, 'ci_upper':1.9}}}))
            stats = statistical_payloads()
            mutate(stats)
            (run/'statistical_tests').mkdir()
            for filename, value in stats.items():
                (run/'statistical_tests'/filename).write_text(json.dumps(value))
            registration = [{'artifact_id':'statistical_tests_evidence', 'path':'statistical_tests/evidence.json'}]
            (run/'artifacts_index.json').write_text(json.dumps({'artifacts':registration if registered_evidence else []}))
            return {'status':'completed', 'run_id':'r1'}
        monkeypatch.setattr(lane, 'run_workflow', workflow)
        out = tmp_path/name
        lane.family_run(case, out, manifest=manifest)
        return json.loads((out/'metrics.json').read_text())
    return generate


@pytest.mark.parametrize('filename,field', [('anova.json','statistic'), ('anova.json','p_value'),
                                          ('nonparametric.json','statistic'), ('nonparametric.json','p_value')])
def test_actual_worker_reads_statistical_changes_and_ab_rejects_them(lane, persisted_statistics_worker, filename, field):
    baseline = persisted_statistics_worker('baseline')
    def change(stats):
        stats[filename]['results'][0][field] += 1e-14
    changed = persisted_statistics_worker('changed', change)
    calibration, records = observations()
    for row in calibration+records['A']+records['B']:
        row['numeric_signature'] = baseline['numeric_signature']
    records['B'][0]['numeric_signature'] = changed['numeric_signature']
    assert baseline['numeric_signature'] != changed['numeric_signature']
    assert 'numeric_bits' in lane.evaluate_ab_case('ols', calibration, records)['failed']


@pytest.mark.parametrize('kind', ['missing_all', 'missing_one', 'empty_payload', 'nonfinite', 'missing_statistic', 'missing_p'])
def test_shared_missing_or_nonfinite_statistics_cannot_pass(lane, persisted_statistics_worker, kind):
    def damage(stats):
        if kind == 'missing_all':
            stats.clear()
        elif kind == 'missing_one':
            del stats['anova.json']
        elif kind == 'empty_payload':
            stats['anova.json'] = {}
        elif kind == 'missing_statistic':
            del stats['anova.json']['results'][0]['statistic']
        elif kind == 'missing_p':
            del stats['anova.json']['results'][0]['p_value']
        else:
            stats['anova.json']['results'][0]['statistic'] = float('nan')
    value = persisted_statistics_worker('damaged', damage)
    calibration, records = observations()
    for row in calibration+records['A']+records['B']:
        row['numeric_signature'] = value['numeric_signature']
        row['numeric_signature_error'] = value.get('numeric_signature_error')
    assert lane.evaluate_ab_case('ols', calibration, records)['failed']


@pytest.mark.parametrize('metadata', [
    {'engine':'native-average-rank','reason':None}, {'engine':'native-counts','reason':'exact integer ties'},
])
def test_only_known_rank_engine_reason_metadata_is_compatible(lane, persisted_statistics_worker, metadata):
    baseline = persisted_statistics_worker('baseline')
    def provenance(stats):
        stats['rank_correlations.json']['results'][0]['computation'] = metadata
    changed = persisted_statistics_worker('metadata', provenance)
    assert 'statistical_tests' in baseline['numeric_signature']
    assert baseline['numeric_signature'] == changed['numeric_signature']


@pytest.mark.parametrize('filename,metadata', [
    ('rank_correlations.json', {'engine':'native-counts','reason':None,'tolerance':1e-8}),
    ('rank_correlations.json', {'engine':123,'reason':None}),
    ('rank_correlations.json', {'engine':'unreviewed-engine','reason':None}),
    ('anova.json', {'engine':'native-counts','reason':None}),
])
def test_unknown_computation_fields_are_never_silently_removed(lane, persisted_statistics_worker, filename, metadata):
    baseline = persisted_statistics_worker('baseline')
    def change(stats):
        stats[filename]['results'][0]['computation'] = metadata
    changed = persisted_statistics_worker('unknown', change)
    assert (changed.get('numeric_signature_error') or baseline['numeric_signature'] != changed['numeric_signature'])


@pytest.mark.parametrize("case", ["did", "panel", "cox"])
def test_non_empty_core_statistics_allow_the_producers_unregistered_optional_evidence_absence(
    lane, persisted_statistics_worker, case,
):
    without = persisted_statistics_worker("optional-absent", lambda stats: stats.pop("evidence.json"), case=case)
    assert without["numeric_signature_error"] is None
    assert set(without["numeric_signature"]["statistical_tests"]) == set(STAT_FILES) - {"evidence.json"}
    calibration, records = observations()
    for row in calibration + records["A"] + records["B"]:
        row["numeric_signature"] = without["numeric_signature"]
    assert lane.evaluate_ab_case(case, calibration, records)["failed"] == []

    with_evidence = persisted_statistics_worker("optional-present", case=case, registered_evidence=True)
    records["B"][0]["numeric_signature"] = with_evidence["numeric_signature"]
    assert "numeric_bits" in lane.evaluate_ab_case(case, calibration, records)["failed"]


@pytest.mark.parametrize("case", ["ols", "did"])
def test_missing_required_or_registered_advanced_evidence_does_not_pass(
    lane, persisted_statistics_worker, case,
):
    value = persisted_statistics_worker("missing-advanced", lambda stats: stats.pop("evidence.json"),
                                        case=case, registered_evidence=(case == "did"))
    assert value["numeric_signature_error"]
    calibration, records = observations()
    for row in calibration + records["A"] + records["B"]:
        row["numeric_signature"] = value["numeric_signature"]
        row["numeric_signature_error"] = value["numeric_signature_error"]
    failures = lane.evaluate_ab_case(case, calibration, records)["failed"]
    assert "invalid_statistical_tests_signature" in failures
    assert "invalid_inference_kernel" not in failures
