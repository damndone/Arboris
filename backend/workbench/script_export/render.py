"""Pure, deterministic script rendering from a frozen ScriptPlan."""
from __future__ import annotations
from collections.abc import Mapping
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .result_snapshot import ResultSnapshotRef
from .plan import CoverageEntry, LANGUAGES, ScriptExport, ScriptExportRefusal, ScriptPlan, Language
from .exporters import EXPORTERS
from .integration_exporters import EXPORTERS as INTEGRATION_EXPORTERS
from .runtime import RenderContext, PYTHON_PRELUDE, R_PRELUDE, STATA_PRELUDE, CSV_PYTHON_PRELUDE, CSV_R_PRELUDE
from .syntax import comment, literal, refuse


def resolve_exporter(step, language):
    spec = EXPORTERS.get(step.operation) or INTEGRATION_EXPORTERS.get(step.operation)
    if spec is None:
        raise ScriptExportRefusal('UNDECLARED_OPERATION', f'No export declaration for {step.operation}', steps=(step.step_id,))
    if step.kind == 'postestimation' and step.parameters.get('level', .95) != .95:
        from .exporters import LanguageExporter
        return LanguageExporter(None, 'snapshot', 'Non-default confidence-level inference continues from the completed Workbench result; native interval export is not validated.')
    return spec.resolve(step, language)


def export_script(plan: ScriptPlan, language: Language, *, require_native: bool=False,
                  result_snapshots: Mapping[str,ResultSnapshotRef] | None=None) -> ScriptExport:
    if language not in LANGUAGES:
        refuse('Unsupported export language')
    references={};completed=set()
    if result_snapshots is not None:
        from .result_snapshot import ResultSnapshotRef
        known={step.step_id for step in plan.steps}
        if not isinstance(result_snapshots,Mapping) or set(result_snapshots)-known:
            refuse('Unknown result sidecar reference keys','INVALID_RESULT_SNAPSHOT_REFS')
        if any(not isinstance(ref,ResultSnapshotRef) for ref in result_snapshots.values()):
            refuse('Result sidecars require ResultSnapshotRef objects','INVALID_RESULT_SNAPSHOT_REFS')
        references=dict(result_snapshots)
    declarations=[];coverage=[];consumed=set()
    for step in plan.steps:
        declaration=resolve_exporter(step,language)
        if result_snapshots is not None and step.kind=='postestimation':
            predecessors=step.parameters.get('models',())
            if any(key in completed for key in predecessors):
                from .exporters import LanguageExporter
                declaration=LanguageExporter(None,'snapshot','Dependent post-estimation needs its own completed Workbench result sidecar; no fitted state is reconstructed.')
        if result_snapshots is not None and step.kind in {'model','postestimation'} and declaration.status=='snapshot':
            if step.step_id not in references and not require_native:refuse('Missing completed result sidecar for '+step.step_id,'RESULT_SNAPSHOT_REQUIRED')
            from .exporters import LanguageExporter
            declaration=LanguageExporter(None,'snapshot',declaration.note+' Workbench completed this step; numeric values come from a verified result sidecar, without native re-estimation.')
            completed.add(step.step_id)
            if step.step_id in references:consumed.add(step.step_id)
        declarations.append(declaration)
        coverage.append(CoverageEntry(step.step_id,step.operation,declaration.status,declaration.note))
    if set(references)-consumed:refuse('Unconsumed result sidecar references','INVALID_RESULT_SNAPSHOT_REFS')
    blocked=tuple(entry.step_id for entry in coverage if entry.status=='snapshot')
    if require_native and blocked:
        reasons='; '.join(entry.step_id+': '+entry.note for entry in coverage if entry.status=='snapshot')
        raise ScriptExportRefusal('NOT_FULLY_NATIVE','Native export unavailable for: '+reasons,steps=blocked)
    prefix='*' if language=='stata' else '#'
    lines=[f'{prefix} Workbench {comment(plan.workbench_version)}',f'{prefix} project: {comment(plan.project_id)}',
           f'{prefix} run: {comment(plan.run_id)}',f'{prefix} lineage_hash: {comment(plan.lineage_hash)}',f'{prefix} Coverage']
    lines += [f'{prefix} {comment(e.step_id)} | {comment(e.operation)} | {e.status} | {comment(e.note)}' for e in coverage]
    formats = {source.format for source in plan.sources} | {step.snapshot.format for step in plan.steps if step.snapshot}
    statistical = bool(formats & {'dta', 'sav'})
    lines += [{'python':PYTHON_PRELUDE if statistical else CSV_PYTHON_PRELUDE,
        'r':R_PRELUDE if statistical else CSV_R_PRELUDE,'stata':STATA_PRELUDE}[language]]
    ctx=RenderContext(language)
    for i,source in enumerate(plan.sources):
        ctx.datasets[source.source_id]=f'wb_src{i}'
        lines += ctx.read(source.source_id,source.filename,source.sha256,source.format,source.read_options)
    for i,(step,declaration) in enumerate(zip(plan.steps,declarations),1):
        if step.kind=='data_operation':
            from workbench.data_operation_registry import get_data_operation
            from workbench.contracts.common.envelope import thaw_json
            registered=get_data_operation(step.operation)
            if registered is not None:
                try:
                    parameters=thaw_json(step.parameters)
                    unknown=set(parameters)-set(registered.fields)
                    if unknown:refuse('Unsupported data parameters: '+str(sorted(unknown)))
                    registered.validate(parameters)
                except (ValueError,TypeError,KeyError) as exc:
                    if isinstance(exc, ScriptExportRefusal):raise
                    refuse(step.operation.removeprefix('data.')+'.'+str(exc))
        ctx.index=i;ctx.datasets[step.step_id]=f'wb{i}'
        if step.kind=='model':ctx.model_indices[step.step_id]=i
        ctx.packages.update(declaration.packages)
        if step.seed is not None:
            if type(step.seed) is not int or not 0<=step.seed<=2147483647:refuse('Seed must be an integer in [0, 2147483647]')
            lines += [{'stata':f'set seed {step.seed}','r':f'set.seed({step.seed})','python':f'np.random.seed({step.seed})'}[language]]
        if declaration.status=='snapshot':
            has_result=step.step_id in consumed
            if step.snapshot is None and not (has_result and step.kind=='postestimation'):
                raise ScriptExportRefusal('SNAPSHOT_REQUIRED',f'{step.step_id} requires a local dataset snapshot',steps=(step.step_id,))
            lines += [f'{prefix} Workbench completed this step: {comment(step.label)}']
            if step.snapshot is not None:
                snap=step.snapshot
                lines += ctx.read(step.step_id,snap.filename,snap.sha256,snap.format)
                lines += ctx.data_checks(step,{'nrows':snap.nrows,'columns':snap.columns})
            else:
                predecessor=step.parameters['models'][0]
                if predecessor not in ctx.datasets:refuse('Completed post-estimation has no verified dataset predecessor')
                if language=='stata':lines += [f'frame copy {ctx.ref(predecessor)} {ctx.ref(step.step_id)}',f'frame change {ctx.ref(step.step_id)}']
                else:lines += [ctx.assign(step.step_id,ctx.ref(predecessor)+('.copy()' if language=='python' else ''))]
            if has_result:
                from .result_snapshot import result_snapshot_binding
                from .result_runtime import completed_result
                lines += completed_result(step,ctx,references[step.step_id],result_snapshot_binding(plan,step))
            elif step.kind!='data_operation' and step.expected:
                raise ScriptExportRefusal('SNAPSHOT_CANNOT_REPRODUCE_MODEL_NUMBERS','A dataset snapshot cannot independently reproduce model or post-estimation numbers',steps=(step.step_id,))
            if step.kind=='data_operation':lines += ctx.data_checks(step)
        else:
            lines += declaration.renderer(step,ctx)
            if step.kind=='data_operation':lines+=ctx.data_checks(step)
            else:ctx.model_steps[step.step_id]=step
    lines += [f'{prefix} Closing self-checks'] + ctx.checks
    extension={'stata':'do','r':'R','python':'py'}[language]
    return ScriptExport(language,f'analysis.{extension}','\n'.join(lines)+'\n',tuple(coverage),blocked,tuple(sorted(ctx.packages)))
