"""Publish source-bound Notebook planning into the current Agent's proposal cards."""
from dataclasses import replace

from ..notebook import NotebookService
from ..trace import TraceWriter
from ..tools import ToolVisibleError
from .factory import build_planner, _baseline_planning_evidence
from .types import PlanningRefusal, NotebookPlanningContractError


class AnalysisPlanningPhase:
    def __init__(self, phase, *, service, notebook_id, trace, orchestrator, chain_id):
        self.phase = phase
        self.service = service
        self.notebook_id = notebook_id
        self.trace = trace
        self.orchestrator = orchestrator
        self.chain_id = chain_id
        self.episode_id = phase.episode_id

    def request(self, transcript):
        return self.phase.request(transcript)

    def checkpoint(self):
        return {**self.phase.checkpoint(), "kind":"analysis_planning/v1",
            "notebook_id":self.notebook_id, "chain_id":self.chain_id,
            "context":self.phase.context.to_dict(), "trace_id":self.trace.trace_id,
            "trace_scope":self.trace.scope, "trace_versions":self.trace.versions}

    def failure(self, reason, error=None):
        return self.phase.failure(reason, error)

    async def consume(self, events, *, error=None):
        step = await self.phase.consume(events, error=error)
        if step.next != "completed" or isinstance(step.result, PlanningRefusal):
            return step
        result = step.result
        context = self.service.compile_context(self.notebook_id)
        drafts, decision = self.service.derive_server_recommendation(self.notebook_id,
            context=context, drafts=tuple(result.option_drafts), batch_id=result.decision.batch_id,
            evidence_pack=result.evidence_pack)
        revisions = self.service.propose_batch(self.notebook_id, context=context, drafts=drafts, trace=self.trace,
            batch_id=decision.batch_id, recommendation_decision=decision, revalidate_existing=True)
        from ..notebook.agent_bridge import publish_option

        session_id = self.orchestrator._chain(self.chain_id)[0]
        proposals = [publish_option(self.service, self.orchestrator, session_id=session_id,
            notebook_id=self.notebook_id, revision=revision).to_dict() for revision in revisions]
        return replace(step, public_result={"requires_confirmation":True, "proposal":proposals[0],
            "proposal_ids":[p["proposal_id"] for p in proposals], "notebook_id":self.notebook_id})


def create_phase(*, core, orchestrator, chain_id, arguments):
    service = orchestrator.notebook_service or NotebookService(orchestrator.repository.root.parent)
    notebook = service.get_notebook(arguments["notebook_id"])
    service.set_focus(notebook.notebook_id, user_focus={**notebook.user_focus, "goal":arguments["question"]})
    context = service.compile_context(notebook.notebook_id)
    if context.projection_source is None:
        raise ToolVisibleError("A source-bound Notebook is required to plan an analysis.")
    trace = TraceWriter(service.project_root, scope={"project_id":notebook.project_id,
        "notebook_id":notebook.notebook_id, "run_family_id":notebook.run_family_id}, versions={
        "app_commit":"local-workbench", "model_id":core.model_name,
        "prompt_version":"notebook-plan/1", "vocabulary_version":"notebook/1", "context_profile":"notebook-plan/v1"})
    planner = build_planner(service.project_root, service, notebook.notebook_id, context, trace,
        adapter=core.adapter, phase_runner=None, provider_timeout_s=90,
        planning_timeout_s=None, operation_adapter="operation.multi_step")
    phase = planner.create_phase(context=context, initial_evidence=_baseline_planning_evidence(
        service, notebook.notebook_id, context, trace))
    return AnalysisPlanningPhase(phase, service=service, notebook_id=notebook.notebook_id,
        trace=trace, orchestrator=orchestrator, chain_id=chain_id)


def restore_phase(*, core, orchestrator, chain_id, checkpoint):
    """Rebuild the concrete planning phase from its checked durable input."""
    from ..context_compiler import NotebookPlanningContextV1, freshness_dependency_fingerprint
    from ..notebook.evidence import DataEvidencePackV1, EvidenceRecord
    from ..turn_journal import TurnRecoveryRequired

    if checkpoint["kind"] != "analysis_planning/v1" or checkpoint["chain_id"] != chain_id:
        raise TurnRecoveryRequired("planning phase identity changed")
    service = orchestrator.notebook_service or NotebookService(orchestrator.repository.root.parent)
    context = NotebookPlanningContextV1(**checkpoint["context"])
    try:
        current = service.compile_context(checkpoint["notebook_id"])
        if freshness_dependency_fingerprint(current) != checkpoint["context_fingerprint"]:
            raise TurnRecoveryRequired("planning source changed since the original request")
    except (OSError, ValueError) as exc:
        raise TurnRecoveryRequired("planning source cannot be verified") from exc
    trace = TraceWriter(service.project_root, scope=checkpoint["trace_scope"],
        versions=checkpoint["trace_versions"], trace_id=checkpoint["trace_id"])
    planner = build_planner(service.project_root, service, checkpoint["notebook_id"], context, trace,
        adapter=core.adapter, phase_runner=None, provider_timeout_s=90,
        planning_timeout_s=None, operation_adapter="operation.multi_step")
    pack = checkpoint["evidence"]
    evidence = DataEvidencePackV1(source_id=pack["source_id"],
        records=tuple(EvidenceRecord(**record) for record in pack["records"]),
        pack_omissions=tuple(pack["pack_omissions"]))
    phase = planner.create_phase(context=context, initial_evidence=evidence, episode_id=checkpoint["episode_id"])
    try:
        phase.restore_checkpoint(checkpoint)
    except NotebookPlanningContractError as exc:
        raise TurnRecoveryRequired(str(exc)) from exc
    return AnalysisPlanningPhase(phase, service=service, notebook_id=checkpoint["notebook_id"],
        trace=trace, orchestrator=orchestrator, chain_id=chain_id)
