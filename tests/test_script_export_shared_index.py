"""Concurrent completed-owner writes use one artifact index transaction."""
from concurrent.futures import ThreadPoolExecutor
import threading

from test_script_export_public_integrity import clone
from test_script_export_lineage_builder import data_path, model_path
from workbench.agent.workflow import compile_workflow, WorkflowExecutor
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.artifacts import read_json
from workbench.services.script_export import export_analysis_script


def test_postestimation_registration_survives_export_publication(model_path,tmp_path,monkeypatch):
    import workbench.agent.workflow_runtime as runtime
    from workbench.script_export import storage
    project,run_id,_ = clone(model_path,tmp_path)
    export_open = threading.Event(); writer_started = threading.Event(); writer_finished = threading.Event()
    directory = storage._directory; register = runtime.register_artifact
    def publication_window(parent,name,**kwargs):
        fd = directory(parent,name,**kwargs)
        if name == 'scripts' and not export_open.is_set():
            export_open.set()
            assert writer_started.wait(15)
            # A shared transaction blocks this registration; a legacy writer
            # completes here and exposes its lost update after export resumes.
            writer_finished.wait(2)
        return fd
    def mark_registration(*args,**kwargs):
        writer_started.set()
        record = register(*args,**kwargs)
        writer_finished.set()
        return record
    monkeypatch.setattr(storage,'_directory',publication_window)
    monkeypatch.setattr(runtime,'register_artifact',mark_registration)
    draft = compile_workflow(workflow_id='wf-export-shared-index',target={
        'run_id':run_id,'node_ref':'stage:cleaned','artifact_id':'cleaned_dataset'},preconditions={
        'context_version':'node-operation-context/v1','context_fingerprint':'sha256:shared-index',
        'active_head_run_id':run_id,'owner_resolution':'single_candidate'},available_columns=['g','x','z','xz','y','keep'],
        steps=[{'step_id':'read','operation_id':'postestimation.lincom',
                'spec':{'model_ref':'model:ols_1','terms':{'x':1}}}])
    with ThreadPoolExecutor(max_workers=2) as pool:
        exporting = pool.submit(export_analysis_script,project,run_id,'model:ols_1','python')
        assert export_open.wait(15)
        writing = pool.submit(WorkflowExecutor(project).execute,draft,build_workflow_step_executor(project,draft))
        result = exporting.result(timeout=30); state = writing.result(timeout=30)
    assert state.status == 'completed'
    post_ids = state.steps['read'].artifact_ids
    assert post_ids and writer_finished.is_set()
    ids = [item['artifact_id'] for item in read_json(project/'runs'/run_id/'artifacts_index.json')['artifacts']]
    assert all(ids.count(identity) == 1 for identity in [result['artifact_id'],*post_ids])
