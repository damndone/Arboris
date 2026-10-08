"""Export the actual public data path, retaining each owner and operation."""
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.app import app
from workbench.artifacts import read_json
from workbench.data_operations import (DataTransformSpecV1, FeatureRecipeOperationSpecV1,
    apply_data_transform, apply_feature_recipe_operation, preview_data_transform, preview_feature_recipe)
from workbench.predictive_research.contracts import FeatureRecipeV1
from workbench.projects import create_project
from workbench.script_export.runtime import PYTHON_PRELUDE
from workbench.tabular_io import read_statistical


def finished(client, project, run_id):
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        response = client.get(f"/runs/{run_id}", params={"project_root": str(project)})
        assert response.status_code == 200, response.text
        if response.json()["status"] in {"completed", "failed", "blocked", "partial"}:
            assert response.json()["status"] == "completed", response.text
            return
        time.sleep(0.05)
    pytest.fail("Public run did not complete within 90 seconds")


@pytest.fixture(scope="module")
def data_path(tmp_path_factory):
    root = tmp_path_factory.mktemp("script-lineage")
    project = create_project(root, "public").root
    rng = np.random.default_rng(18111004)
    n = 800
    x = rng.normal(size=n); z = rng.normal(size=n)
    frame = pd.DataFrame({"g": np.repeat(np.arange(40), 20), "x": x, "z": z,
        "y": 1 + .4*x - .2*z + .3*x*z + rng.normal(size=n), "keep": np.tile([0, 1], n//2)})
    source = root / "public.dta"
    frame.to_stata(source, write_index=False, value_labels={"keep": {0: "excluded", 1: "included"}})
    with TestClient(app) as client:
        submitted = client.post("/runs", data={"project_root": str(project), "mode": "auto", "model_type": "ols", "y": "y", "x": "x,z"},
            files={"file": (source.name, source.read_bytes(), "application/octet-stream")})
        assert submitted.status_code == 200, submitted.text
        run_id = submitted.json()["run_id"]
        finished(client, project, run_id)
    subset = DataTransformSpecV1(source_run_id=run_id, source_node_id="stage:cleaned", source_artifact_id="cleaned_dataset",
        operation="subset", parameters={"columns": list(frame.columns), "equals": {"keep": 1}})
    selected = apply_data_transform(project, subset, preview_data_transform(project, subset))
    recipe = FeatureRecipeV1(recipe_id="recipe_xz", operation_id="derived_variable", operation_version=1,
        inputs=("x", "z"), outputs=("xz",), output_types=("numeric",), parameters={"operator": "multiply"},
        fit_scope="stateless", source_artifact=selected.artifact_id, lineage_parent=selected.child_node_id)
    spec = FeatureRecipeOperationSpecV1(source_run_id=run_id, source_node_id=selected.child_node_id,
        source_artifact_id=selected.artifact_id, recipe=recipe)
    derived = apply_feature_recipe_operation(project, spec, preview_feature_recipe(project, spec))
    return project, run_id, selected, derived


@pytest.fixture(scope="module")
def model_path(data_path):
    project, run_id, _, derived = data_path
    with TestClient(app) as client:
        response = client.post("/data-operations/model-run", params={"project_root": str(project)}, json={
            "source_run_id": run_id, "source_node_id": derived.child_node_id, "source_artifact_id": derived.artifact_id,
            "model_type": "ols", "y": "y", "x": ["x", "z", "xz"], "covariance": "clustered", "entity_col": "g"})
        assert response.status_code == 200, response.text
        model_run = response.json()["run_id"]
        finished(client, project, model_run)
    return project, model_run, data_path


def test_current_model_bridge_preserves_explicit_cluster_column(model_path):
    project, model_run, data_path = model_path
    derived = data_path[3]
    kernel = read_json(project / "runs" / model_run / "model_results/inference_kernels/ols_1.json")
    assert kernel["n_clusters"] == 40
    assert kernel["reference_distribution"] == "t"
    assert kernel["df_resid"] == 39
    inputs = read_json(project / "runs" / model_run / "run_inputs.json")
    assert inputs["executed_payload"]["entity_col"] == "g"
    assert inputs["dataset_source"]["source_artifact_id"] == derived.artifact_id


def test_lineage_builder_is_available_for_server_owned_completed_paths():
    assert importlib.util.find_spec("workbench.script_export.builder") is not None


def test_completed_owner_registers_the_final_diagnostic_bytes(model_path):
    import hashlib
    project, run_id, _ = model_path
    root = project / "runs" / run_id
    records = read_json(root / "artifacts_index.json")["artifacts"]
    diagnostics = [item for item in records if item["artifact_id"] == "diagnostics_ols_1"]
    assert len(diagnostics) == 1
    assert diagnostics[0]["sha256"] == hashlib.sha256((root / diagnostics[0]["path"]).read_bytes()).hexdigest()


def build(model_path, target="model:ols_1"):
    assert importlib.util.find_spec("workbench.script_export.builder") is not None
    from workbench.script_export.builder import build_script_plan
    return build_script_plan(model_path[0], model_path[1], target)


def test_model_export_keeps_original_stata_source_and_every_data_step(model_path):
    built = build(model_path)
    assert [source.format for source in built.plan.sources] == ["dta"]
    assert [step.operation for step in built.plan.steps] == ["data.cleaning", "data.subset", "data.feature_recipe", "data.cleaning", "model.ols"]
    model = built.plan.steps[-1]
    assert model.parameters["covariance"] == "clustered"
    assert model.parameters["cluster"] == "g"
    assert model.parameters["x"] == ("x", "z", "xz")
    assert model.expected["nobs"] == 400
    assert all(source.filename in built.files for source in built.plan.sources)
    assert built.plan.to_dict() == build(model_path).plan.to_dict()


@pytest.fixture(scope="module")
def wald_path(model_path):
    from workbench.agent.workflow import compile_workflow, WorkflowExecutor
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    project, run_id, _ = model_path
    draft = compile_workflow(workflow_id="wf-script-cluster-wald", target={"run_id": run_id,
        "node_ref": "stage:cleaned", "artifact_id": "cleaned_dataset"}, preconditions={
        "context_version": "node-operation-context/v1", "context_fingerprint": "sha256:script-cluster-wald",
        "active_head_run_id": run_id, "owner_resolution": "single_candidate"},
        available_columns=["g", "x", "z", "xz", "y", "keep"], steps=[{"step_id": "joint",
        "operation_id": "postestimation.wald", "spec": {"model_ref": "model:ols_1",
        "constraints": [{"terms": {"x": 1}, "value": 0}, {"terms": {"xz": 1}, "value": 0}]}}])
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == "completed"
    return model_path, state.steps["joint"].artifact_ids[0]


def test_builder_uses_the_actual_durable_wald_and_model_owner(wald_path):
    model_path, artifact_id = wald_path
    built = build(model_path, "artifact:" + artifact_id)
    assert built.plan.steps[-1].operation == "postestimation.wald"
    statistic = built.plan.steps[-1].expected["statistics"]["test"]
    assert statistic["distribution"] == "F"
    assert statistic["df"] == 2
    assert statistic["df_denominator"] == 39
    assert built.plan.steps[-1].parameters["models"] == (built.plan.steps[-2].step_id,)


@pytest.mark.parametrize("language", ["stata", "r", "python"])
def test_actual_stata_subset_generate_cluster_wald_path_runs_in_each_language(wald_path, language):
    from test_script_export_data_oracles import fresh_directory, execute
    from workbench.script_export.render import export_script
    model_path, artifact_id = wald_path
    built = build(model_path, "artifact:" + artifact_id)
    directory = fresh_directory()
    for name, raw in built.files.items():
        (directory / name).write_bytes(raw)
    exported = export_script(built.plan, language, result_snapshots={})
    assert "data.feature_recipe" in exported.text
    code, output = execute(exported, directory, built.plan)
    assert code == 0, output


@pytest.mark.parametrize("changed", ["raw", "recipe", "schema"])
def test_builder_refuses_changed_ancestor_evidence(model_path, changed):
    project, _, data_path = model_path
    source_root = project / "runs" / data_path[1]
    target = {"raw": source_root / "raw_snapshot/public.dta", "recipe": source_root / data_path[2].recipe_path,
        "schema": (source_root / data_path[3].artifact_path).with_suffix(".schema.json")}[changed]
    original = target.read_bytes()
    if changed == "schema":
        payload = json.loads(original); payload["dtypes"]["x"] = "string"
        target.write_text(json.dumps(payload))
    else:
        target.write_bytes(original + b" ")
    try:
        from workbench.script_export.plan import ScriptExportRefusal
        with pytest.raises(ScriptExportRefusal, match="hash|SHA|changed|schema|fingerprint"):
            build(model_path)
    finally:
        target.write_bytes(original)


def test_python_stata_source_reader_preserves_numeric_value_labels(tmp_path):
    source = tmp_path / "labeled.dta"
    pd.DataFrame({"group": [0., 1., 1.], "x": [1., 2., 3.]}).to_stata(source, write_index=False,
        value_labels={"group": {0: "control", 1: "treated"}})
    scope = {"__file__": str(tmp_path / "analysis.py")}
    exec(PYTHON_PRELUDE, scope)
    import hashlib
    actual = scope["wb_read"](source.name, hashlib.sha256(source.read_bytes()).hexdigest(), "dta")
    expected = read_statistical(source, "dta")
    assert pd.api.types.is_numeric_dtype(actual["group"]), actual.dtypes
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)


@pytest.mark.parametrize('recipe_kind', ['subset', 'feature'])
def test_builder_checks_recipe_source_digest_after_owner_index_validation(model_path, recipe_kind):
    import hashlib
    from workbench.script_export.plan import ScriptExportRefusal
    project, _, data_path = model_path
    root = project / 'runs' / data_path[1]
    recipe_path = root / data_path[2 if recipe_kind == 'subset' else 3].recipe_path
    index_path = root / 'artifacts_index.json'
    original_recipe = recipe_path.read_bytes(); original_index = index_path.read_bytes()
    payload = json.loads(original_recipe)
    if recipe_kind == 'subset':
        payload['preview']['source_sha256'] = '0'*64
    else:
        payload['source_sha256'] = '0'*64
    changed = json.dumps(payload).encode()
    recipe_path.write_bytes(changed)
    index = json.loads(original_index)
    for item in index['artifacts']:
        if item['path'] == recipe_path.relative_to(root).as_posix():
            item['sha256'] = hashlib.sha256(changed).hexdigest()
    index_path.write_text(json.dumps(index))
    try:
        with pytest.raises(ScriptExportRefusal):
            build(model_path)
    finally:
        recipe_path.write_bytes(original_recipe); index_path.write_bytes(original_index)


def test_builder_refuses_incomplete_durable_postestimation_state(wald_path):
    from workbench.script_export.plan import ScriptExportRefusal
    model_path, artifact_id = wald_path
    path = model_path[0] / 'workbench/workflows/wf-script-cluster-wald.jsonl'
    original = path.read_bytes()
    state = json.loads(original.splitlines()[-1])
    state['steps']['joint']['status'] = 'failed'
    path.write_bytes(original + json.dumps(state).encode() + b'\n')
    try:
        with pytest.raises(ScriptExportRefusal, match='binding'):
            build(model_path, 'artifact:' + artifact_id)
    finally:
        path.write_bytes(original)


def test_http_export_writes_a_complete_downloadable_local_bundle(wald_path):
    import io
    import zipfile
    model_path, artifact_id = wald_path
    project, run_id, _ = model_path
    request = {'target': 'artifact:' + artifact_id, 'language': 'r', 'require_native': True}
    with TestClient(app) as client:
        response = client.post(f'/runs/{run_id}/script-export', params={'project_root': str(project)}, json=request)
        assert response.status_code == 200, response.text
        summary = response.json()
        assert summary['fully_native'] is True
        assert len(summary['coverage']) == 6
        assert 'text' not in summary and 'expected' not in summary
        download = client.get(summary['download_url'])
        assert download.status_code == 200
        with zipfile.ZipFile(io.BytesIO(download.content)) as bundle:
            names = bundle.namelist()
            assert 'analysis.R' in names and 'plan.json' in names and 'manifest.json' in names
            assert any(name.endswith('.dta') for name in names)
        repeated = client.post(f'/runs/{run_id}/script-export', params={'project_root': str(project)}, json=request)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()['artifact_id'] == summary['artifact_id']


def test_http_export_rejects_client_expected_numbers(wald_path):
    model_path, artifact_id = wald_path
    with TestClient(app) as client:
        response = client.post(f'/runs/{model_path[1]}/script-export', params={'project_root': str(model_path[0])},
            json={'target': 'artifact:' + artifact_id, 'language': 'python', 'expected': {'statistic': 1}})
    assert response.status_code == 422, response.text


def test_egress_denial_happens_before_export_files_are_written(wald_path):
    from workbench.egress import policy_path
    model_path, artifact_id = wald_path
    project, run_id, _ = model_path
    path = policy_path(project); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'version': 1, 'providers': {'local': {'allow': ['workbench_state']}}}))
    export_root = project / 'runs' / run_id / 'exports/scripts'
    before = sorted(str(item) for item in export_root.rglob('*'))
    try:
        with TestClient(app) as client:
            response = client.post(f'/runs/{run_id}/script-export', params={'project_root': str(project)},
                json={'target': 'artifact:' + artifact_id, 'language': 'python'})
        assert response.status_code == 403, response.text
        assert response.json()['error']['code'] == 'SCRIPT_EXPORT_EGRESS_DENIED'
        assert sorted(str(item) for item in export_root.rglob('*')) == before
    finally:
        path.write_text(json.dumps({'version': 1, 'providers': {}}))


def test_agent_script_export_uses_the_same_owner_and_returns_metadata_only(wald_path):
    from workbench.agent.context_tools import NodeOperationContextProvider
    from workbench.agent.tools import ToolContext
    model_path, artifact_id = wald_path
    definitions = NodeOperationContextProvider(model_path[0]).tool_definitions(chain_id='script-chain', session_id='script-session')
    matching = [item for item in definitions if item.tool_id == 'export_analysis_script']
    assert len(matching) == 1
    context = ToolContext(session_id='script-session', metadata={'project': str(model_path[0]), 'chain': 'script-chain'})
    output = matching[0].handler({'run_id': model_path[1], 'target': 'artifact:' + artifact_id, 'language': 'python', 'require_native': True}, context)
    assert output['fully_native'] is True and output['artifact_id'].startswith('script_export_python_')
    assert 'text' not in output and 'coefficients' not in output and 'expected' not in output


@pytest.fixture(scope='module', params=['lincom', 'nlcom', 'margins'])
def more_post_paths(model_path, request):
    from workbench.agent.workflow import compile_workflow, WorkflowExecutor
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    specs = {'lincom': {'terms': {'x': 1, 'xz': -1}, 'constant': .1},
        'nlcom': {'expression': 'exp(x)'}, 'margins': {'variables': ['x', 'xz'], 'at': 'average'}}
    project, run_id, _ = model_path
    draft = compile_workflow(workflow_id='wf-script-' + request.param,
        target={'run_id': run_id, 'node_ref': 'stage:cleaned', 'artifact_id': 'cleaned_dataset'},
        preconditions={'context_version': 'node-operation-context/v1', 'context_fingerprint': 'sha256:script-more-post',
            'active_head_run_id': run_id, 'owner_resolution': 'single_candidate'},
        available_columns=['g', 'x', 'z', 'xz', 'y', 'keep'], steps=[{'step_id': 'test',
        'operation_id': 'postestimation.' + request.param, 'spec': {'model_ref': 'model:ols_1', **specs[request.param]}}])
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == 'completed'
    return model_path, state.steps['test'].artifact_ids[0]


@pytest.mark.parametrize('language', ['stata', 'r', 'python'])
def test_other_durable_postestimation_paths_run_natively(more_post_paths, language):
    from test_script_export_data_oracles import fresh_directory, execute
    from workbench.script_export.render import export_script
    model_path, artifact_id = more_post_paths
    built = build(model_path, 'artifact:' + artifact_id)
    directory = fresh_directory()
    for name, raw in built.files.items():
        (directory / name).write_bytes(raw)
    exported = export_script(built.plan, language, result_snapshots={}, require_native=True)
    code, output = execute(exported, directory, built.plan)
    assert code == 0, output


def test_builder_refuses_a_reindexed_post_result_that_disagrees_with_its_kernel(wald_path):
    import hashlib
    from workbench.script_export.plan import ScriptExportRefusal
    model_path, artifact_id = wald_path
    root = model_path[0] / 'runs' / model_path[1]
    index_path = root / 'artifacts_index.json'; original_index = index_path.read_bytes()
    index = json.loads(original_index)
    record = next(item for item in index['artifacts'] if item['artifact_id'] == artifact_id)
    path = root / record['path']; original = path.read_bytes()
    payload = json.loads(original); payload['result']['statistic'] += 10
    raw = json.dumps(payload).encode(); path.write_bytes(raw)
    record['sha256'] = hashlib.sha256(raw).hexdigest(); index_path.write_text(json.dumps(index))
    try:
        with pytest.raises(ScriptExportRefusal):
            build(model_path, 'artifact:' + artifact_id)
    finally:
        path.write_bytes(original); index_path.write_bytes(original_index)


def test_nondefault_postestimation_level_is_preserved_in_coverage_before_writing(model_path):
    from workbench.agent.workflow import compile_workflow, WorkflowExecutor
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    project, run_id, _ = model_path
    draft = compile_workflow(workflow_id='wf-script-level90', target={'run_id': run_id,
        'node_ref': 'stage:cleaned', 'artifact_id': 'cleaned_dataset'}, preconditions={
        'context_version': 'node-operation-context/v1', 'context_fingerprint': 'sha256:script-level90',
        'active_head_run_id': run_id, 'owner_resolution': 'single_candidate'},
        available_columns=['g', 'x', 'z', 'xz', 'y', 'keep'], steps=[{'step_id': 'test',
        'operation_id': 'postestimation.lincom', 'spec': {'model_ref': 'model:ols_1', 'terms': {'x': 1}, 'level': .9}}])
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == 'completed'
    artifact_id = state.steps['test'].artifact_ids[0]
    with TestClient(app) as client:
        response = client.post(f'/runs/{run_id}/script-export', params={'project_root': str(project)},
            json={'target': 'artifact:' + artifact_id, 'language': 'python', 'require_native': True})
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'NOT_FULLY_NATIVE'


@pytest.fixture(scope='module')
def lr_path(data_path):
    from workbench.agent.workflow import compile_workflow, WorkflowExecutor
    from workbench.agent.workflow_runtime import build_workflow_step_executor
    project, source_run, _, derived = data_path
    runs = []
    with TestClient(app) as client:
        for predictors in [['x', 'z', 'xz'], ['x']]:
            response = client.post('/data-operations/model-run', params={'project_root': str(project)}, json={
                'source_run_id': source_run, 'source_node_id': derived.child_node_id, 'source_artifact_id': derived.artifact_id,
                'model_type': 'ols', 'y': 'y', 'x': predictors, 'covariance': 'unadjusted'})
            assert response.status_code == 200, response.text
            runs.append(response.json()['run_id']); finished(client, project, runs[-1])
    draft = compile_workflow(workflow_id='wf-script-lr', target={'run_id': runs[0],
        'node_ref': 'stage:cleaned', 'artifact_id': 'cleaned_dataset'}, preconditions={
        'context_version': 'node-operation-context/v1', 'context_fingerprint': 'sha256:script-lr',
        'active_head_run_id': runs[0], 'owner_resolution': 'single_candidate'},
        available_columns=['g', 'x', 'z', 'xz', 'y', 'keep'], steps=[{'step_id': 'test', 'operation_id': 'postestimation.lr',
        'spec': {'model_ref': 'model:ols_1', 'restricted_model_ref': 'model:ols_1', 'restricted_model_run_id': runs[1]}}])
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == 'completed'
    return (project, runs[0], data_path), state.steps['test'].artifact_ids[0]


@pytest.mark.parametrize('language', ['stata', 'r', 'python'])
def test_durable_two_model_lr_path_runs_natively(lr_path, language):
    from test_script_export_data_oracles import fresh_directory, execute
    from workbench.script_export.render import export_script
    model_path, artifact_id = lr_path
    built = build(model_path, 'artifact:' + artifact_id)
    assert len(built.plan.steps[-1].parameters['models']) == 2
    assert built.plan.steps[-1].expected['statistics']['test']['df'] == 2
    directory = fresh_directory()
    for name, raw in built.files.items():
        (directory / name).write_bytes(raw)
    exported = export_script(built.plan, language, result_snapshots={}, require_native=True)
    code, output = execute(exported, directory, built.plan)
    assert code == 0, output


def test_public_target_listing_offers_the_selected_models_persisted_wald(wald_path):
    model_path, artifact_id = wald_path
    project, run_id, _ = model_path
    with TestClient(app) as client:
        response = client.get(f'/runs/{run_id}/script-export/targets', params={
            'project_root': str(project), 'model_target': 'model:ols_1'})
        assert response.status_code == 200, response.text
        targets = response.json()['targets']
        assert targets[0] == {'target':'model:ols_1','label':'Model only'}
        assert {'target':'artifact:'+artifact_id,'label':'Model and Wald test'} in targets
        assert all(set(item) == {'target','label'} for item in targets)


@pytest.fixture(scope='module')
def cast_feature_path(data_path):
    from workbench.data_operations import DataColumnCastSpecV1, apply_data_column_cast, preview_data_column_cast
    project, run_id, selected, _ = data_path
    spec = DataColumnCastSpecV1(run_id, selected.child_node_id, selected.artifact_id, 'x', 'string')
    cast = apply_data_column_cast(project, spec, preview_data_column_cast(project,spec))
    recipe = FeatureRecipeV1(recipe_id='numeric_text_multiply', operation_id='derived_variable', operation_version=1,
        inputs=('x','z'), outputs=('xz_text',), output_types=('numeric',), parameters={'operator':'multiply'},
        fit_scope='stateless', source_artifact=cast.artifact_id, lineage_parent=cast.child_node_id)
    feature = FeatureRecipeOperationSpecV1(run_id,cast.child_node_id,cast.artifact_id,recipe)
    derived = apply_feature_recipe_operation(project,feature,preview_feature_recipe(project,feature))
    with TestClient(app) as client:
        response = client.post('/data-operations/model-run',params={'project_root':str(project)},json={
            'source_run_id':run_id,'source_node_id':derived.child_node_id,'source_artifact_id':derived.artifact_id,
            'model_type':'ols','y':'y','x':['xz_text','z'],'covariance':'unadjusted'})
        assert response.status_code == 200,response.text
        model_run=response.json()['run_id'];finished(client,project,model_run)
    return project,model_run,data_path


def test_string_cast_and_numeric_text_recipe_have_explicit_snapshot_coverage(cast_feature_path):
    from workbench.script_export.render import resolve_exporter
    built = build(cast_feature_path)
    steps = [step for step in built.plan.steps if step.operation in {'data.column.cast','data.feature_recipe'}]
    assert [step.operation for step in steps] == ['data.column.cast','data.feature_recipe']
    for language in ['stata','r','python']:
        assert all(resolve_exporter(step,language).status == 'snapshot' for step in steps)


@pytest.mark.parametrize('language',['stata','r','python'])
def test_actual_string_cast_recipe_continues_from_snapshots_then_checks_native_model(cast_feature_path,language):
    from test_script_export_executed_parameters import execute_completed_owner
    with pytest.MonkeyPatch.context() as monkeypatch:
        execute_completed_owner(cast_feature_path[0],cast_feature_path[1],'model:ols_1',language,monkeypatch,native=False)


def test_real_fifty_node_path_exports_inside_one_second(data_path):
    from workbench.services.script_export import export_analysis_script
    from workbench.script_export.builder import build_script_plan
    project,run_id,_,_=data_path
    node_id='stage:cleaned';artifact_id='cleaned_dataset'
    for _ in range(46):
        spec=DataTransformSpecV1(source_run_id=run_id,source_node_id=node_id,source_artifact_id=artifact_id,
            operation='subset',parameters={'columns':['g','x','z','y','keep']})
        child=apply_data_transform(project,spec,preview_data_transform(project,spec))
        node_id,artifact_id=child.child_node_id,child.artifact_id
    with TestClient(app) as client:
        response=client.post('/data-operations/model-run',params={'project_root':str(project)},json={
            'source_run_id':run_id,'source_node_id':node_id,'source_artifact_id':artifact_id,
            'model_type':'ols','y':'y','x':['x','z'],'covariance':'unadjusted'})
        assert response.status_code == 200,response.text
        target_run=response.json()['run_id'];finished(client,project,target_run)
    built=build_script_plan(project,target_run,'model:ols_1')
    assert len(built.plan.sources)+len(built.plan.steps) == 50
    started=time.perf_counter()
    result=export_analysis_script(project,target_run,'model:ols_1','python',require_native=True)
    elapsed=time.perf_counter()-started
    print('50-node full public bundle seconds:',elapsed,'bytes:',result['bytes'])
    assert elapsed < 1.0
