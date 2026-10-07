"""Load authenticated completed results without manufacturing fitted state."""
from __future__ import annotations
import base64
import json
from .syntax import literal,refuse


BRIDGE = '''import base64
import json
import os
from pathlib import Path
import sys
from workbench.contracts.common.envelope import thaw_json
from workbench.script_export.result_snapshot import ResultSnapshotRef, read_result_snapshot

configuration = json.loads(base64.b64decode(sys.argv[2]))
reference = ResultSnapshotRef(**configuration['reference'])
values = read_result_snapshot(Path(sys.argv[1]), reference, expected_binding=configuration['binding'])
for name, distribution in configuration['distributions'].items():
    if values['statistics'][name]['distribution'] != distribution:
        raise AssertionError('Result sidecar reference distribution differs')
if sys.argv[3] == 'r':
    print(json.dumps(thaw_json(values), ensure_ascii=False, allow_nan=False))
elif sys.argv[3] == 'stata':
    lines = []
    for index, path in enumerate(configuration['queries']):
        value = values
        for key in path:
            value = value[key]
        if value is not None and type(value) not in (int, float):
            raise AssertionError('Result sidecar query is not numeric')
        token = '.' if value is None else repr(value)
        lines.append('scalar wb_result_' + str(configuration['index']) + '_' + str(index) + ' = ' + token)
    lines.append('scalar wb_result_valid_' + str(configuration['index']) + ' = 1')
    fd = os.open(sys.argv[4], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        handle.write('\\n'.join(lines) + '\\n')
else:
    raise AssertionError('Unsupported result bridge mode')
'''


def queries(step):
    expected=step.expected;items=[];distributions={}
    if set(expected)-{'nobs','coefficients','std_errors','statistics'}:
        refuse('Unsupported completed-result expected fields','INVALID_RESULT_EXPECTED')
    if 'nobs' in expected and expected['nobs'] is not None:items.append(('nobs',['nobs'],expected['nobs']))
    for kind in ('coefficients','std_errors'):
        for name,value in expected.get(kind,{}).items():items.append((kind,[kind,name],value))
    for name,statistic in expected.get('statistics',{}).items():
        if set(statistic)-{'value','df','df_denominator','p_value','distribution'}:
            refuse('Unsupported completed-result statistic fields','INVALID_RESULT_EXPECTED')
        for field in ('value','df','df_denominator','p_value'):
            if statistic.get(field) is not None:items.append(('statistics.'+field,['statistics',name,field],statistic[field]))
        if statistic.get('distribution') is not None:distributions[name]=statistic['distribution']
    return items,distributions


def bridge_helper(ctx):
    if 'result_bridge' in ctx.helpers:return []
    ctx.helpers.add('result_bridge');ctx.packages.update(('python3','workbench'))
    if ctx.language=='r':
        ctx.packages.add('jsonlite')
        return ['wb_result_bridge <- tempfile(fileext=".py")',f'writeLines({literal(BRIDGE,"r")},wb_result_bridge,useBytes=TRUE)']
    lines=['tempfile wb_result_bridge','tempname wb_result_writer','file open `wb_result_writer\' using "`wb_result_bridge\'", write text']
    for line in BRIDGE.splitlines():
        if '`' in line or '$' in line:refuse('Unsafe internal bridge source')
        lines.append('file write `wb_result_writer\' `"'+line+'"\' _n')
    return lines+['file close `wb_result_writer\'']


def completed_result(step,ctx,reference,binding):
    """Actual values stay outside generated scripts until runtime file access."""
    items,distributions=queries(step);l=ctx.language;lines=[]
    ref={'filename':reference.filename,'sha256':reference.sha256,'schema_version':reference.schema_version}
    configuration={'reference':ref,'binding':binding,'queries':[path for _,path,_ in items],
                   'distributions':distributions,'index':ctx.index}
    if l=='python':
        ctx.packages.add('workbench')
        if 'result_reader' not in ctx.helpers:
            ctx.helpers.add('result_reader')
            lines+=['from workbench.script_export.result_snapshot import ResultSnapshotRef, read_result_snapshot']
        target=f'wb_result_values{ctx.index}'
        lines.append(f'{target} = read_result_snapshot(base,ResultSnapshotRef(**{ref!r}),expected_binding={binding!r})')
        for name,distribution in distributions.items():lines.append(f'assert {target}["statistics"][{name!r}]["distribution"] == {literal(distribution,l)}')
    else:
        lines+=bridge_helper(ctx)
        encoded=base64.b64encode(json.dumps(configuration,ensure_ascii=False,allow_nan=False).encode()).decode()
        if l=='r':
            target=f'wb_result_values{ctx.index}'
            lines += [f'wb_result_json <- system2("python3",c(shQuote(wb_result_bridge),shQuote(base),{literal(encoded,l)},"r"),stdout=TRUE,stderr=TRUE)',
                      'if (!is.null(attr(wb_result_json,"status")) && attr(wb_result_json,"status")!=0) stop(paste(wb_result_json,collapse="\\n"))',
                      f'{target} <- jsonlite::fromJSON(paste(wb_result_json,collapse="\\n"),simplifyVector=FALSE)']
        else:
            lines += ['tempfile wb_result_commands',f'shell python3 "`wb_result_bridge\'" . {encoded} stata "`wb_result_commands\'"',
                      'confirm file "`wb_result_commands\'"','do "`wb_result_commands\'"',f'assert scalar(wb_result_valid_{ctx.index}) == 1']
    for index,(kind,path,value) in enumerate(items):
        expression=f'scalar(wb_result_{ctx.index}_{index})' if l=='stata' else target+''.join(f'[{key!r}]' if l=='python' else f'[[{literal(key,l)}]]' for key in path)
        lines+=ctx.numeric_check(step,kind,expression,value)
    return lines
