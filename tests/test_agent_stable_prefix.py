"""Stable standing context leads; obsolete copies never consume the prefix."""
from workbench.agent.context import ContextBuilder
from workbench.agent.session import JsonlSessionRepository


def test_latest_standing_layers_form_the_same_prefix_despite_append_order(tmp_path):
    repository = JsonlSessionRepository(tmp_path)
    values = {'workbench_agent_protocol':'protocol','workbench_agent_identity':'identity',
        'workbench_instructions':'project instructions','workbench_context':'project map',
        'workbench_agent_focus':'focus','workbench_project_recall':'recall'}
    snapshots = []
    for session, names in [('a',list(values)),('b',list(reversed(values)))]:
        repository.create_session(session,chain_id=session,role='chain')
        repository.append(session,'message',{'role':'user','content':'Earlier question'})
        for name in names:
            repository.append(session,'custom_message',{'name':name,'audience':'model','content':values[name]})
        repository.append(session,'custom_message',{'name':'workbench_context','audience':'model','content':'refreshed project map'})
        repository.append(session,'message',{'role':'user','content':'Current question'})
        snapshots.append(ContextBuilder(repository).build(session).messages)
    assert snapshots[0][:6] == snapshots[1][:6]
    assert [m.get('name') for m in snapshots[0][:6]] == list(values)
    assert snapshots[0][3]['content'] == 'refreshed project map'
    assert [m['content'] for m in snapshots[0][6:]] == ['Earlier question','Current question']
