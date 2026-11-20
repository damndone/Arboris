"""The delivery check: what the plan's completion contract still lacks, and the next step.

One function for every place that reports it: the inspect_analysis_completion
tool, the final-answer gate, and (v1.9.1) the result of each operation, so the
Agent learns where it stands without asking. In the free-route DeepSeek rounds
18 of 40 completion checks came straight after an operation result.
"""

from __future__ import annotations

from typing import Any

from .completion_outcome import NOT_SERVED, not_served_step

#: What an operation result carries of the check: enough to act on, not the evidence catalog.
DIGEST_FIELDS = ("status", "missing", "next_step", "repair_steps", "compose_report", "sensitivity_options", "primary_candidates",
                 "dropped_references", "disclosures", "verified_artifacts", "scientific_validity",
                 "playbook_status", "criteria_verification", "outcome_not_served")


def review_plan_basis_sha256(*, question, criteria, completion):
    """Research-review inputs that change its meaning, excluding execution progress."""
    from ..canonical import sha256_canonical
    return sha256_canonical({'question': question, 'criteria': list(criteria), 'completion': completion})


def delivery_check(project_root, plan, *, suggest=False, session_id=None, requirements=None):
    return delivery_state(project_root, plan, suggest=suggest, session_id=session_id, requirements=requirements)[0]


def delivery_state(project_root, plan, *, suggest=False, session_id=None, requirements=None):
    """The check and its selected references share one bounded product cache.

    ``requirements`` are the server-bound task requirements when no plan is saved yet; a
    saved plan carries its own.
    """
    from .completion import _Products, derive_evidence, evaluate
    from .task_requirements import enforce
    from .plan_criteria import verify
    from ..canonical import sha256_canonical

    products = _Products(project_root)
    evidence, bound = derive_evidence(project_root, plan.completion if plan else None,
                                      plan.completion_evidence if plan else None, _products=products,
                                      session_id=session_id)
    result = evaluate(project_root, plan.completion if plan else None, evidence, suggest=suggest, options=True, _products=products)
    if plan is not None:
        result = enforce(result, plan.task_requirements)
    # An approved criterion can depend on the report itself. Check the analysis
    # requirements before adding the separate criteria verification result.
    analysis_missing = tuple(result['missing'])
    result['playbook_status'] = result['status']
    checked = verify(project_root, plan, products, evidence)
    result['criteria_verification'] = checked
    if checked['status'] == 'partial':
        result['status'] = 'partial'
        result['missing'] = list(dict.fromkeys([*result['missing'], 'plan:approved_criteria_unverified']))
    elif checked['status'] == 'not_machine_checked':
        result['criteria_not_machine_checked'] = True
    result['verified_manifest_sha256'] = sha256_canonical({
        'products': result['verified_manifest_sha256'],
        'criteria': {key: value for key, value in checked.items() if key != 'plan_version'}})
    result['review_plan_basis_sha256'] = review_plan_basis_sha256(
        question=plan.question if plan else '', criteria=plan.criteria if plan else (),
        completion=plan.completion if plan else None)
    result['bound_by_workbench'] = bound['bound_by_workbench']
    if bound['dropped']:
        # Named back to the Agent: a reference that does not resolve to the right kind
        # of verified product is not evidence, whatever it was meant to be.
        result['dropped_references'] = bound['dropped'][:12]
    ar_repair = next((step for step in result.get('repair_steps', [])
                      if step.get('reason') == 'ar_not_requested'), None)
    if 'completion_contract:select_playbooks_and_source' in result['missing']:
        result['next_step'] = _NO_CONTRACT_STEP
    elif NOT_SERVED in result['missing'] and result.get('outcome_not_served'):
        result['next_step'] = not_served_step(result['outcome_not_served'])
    elif result['status'] == 'requirements_met':
        # In the paid fix2 round (iv_weak, Auto) the Agent met every requirement and still
        # would not call the analysis complete, reading not_certified as unfinished.
        result['next_step'] = ('Delivery requirements are met: answer the focused question and state its limitations.'
                              if result.get('scope') == 'question' else
                              'Delivery requirements are met: report this analysis as complete and state its '
                               'scientific limitations. A finding that the data cannot support the requested '
                               'claim is a complete answer, not a missing step.')
    elif bound['primary_candidates']:
        result['primary_candidates'] = bound['primary_candidates']
        result['next_step'] = ('Several fits are eligible as the primary model. Choose one by the fixed '
                               'specification and question, never by significance, and call update_plan with '
                               'completion_evidence {"models": [its run_id and artifact_id]}; the Workbench binds '
                               'its diagnostics, the other fits and the report.')
    elif ar_repair and result['status'] == 'partial':
        import json
        result['next_step'] = (ar_repair['action'] + ' Operation: '
                               + json.dumps(ar_repair['operation'], ensure_ascii=False))
    elif result.get('sensitivity_options') and result['status'] == 'partial':
        # off3 leverage.goal composed its report three times before the sensitivity fit it lacked.
        from .completion_sensitivity import SENSITIVITY_NEXT_STEP
        result['next_step'] = SENSITIVITY_NEXT_STEP
    elif any(code.endswith(':sensitivity:distinct_point_estimation') for code in analysis_missing):
        result['next_step'] = ('Propose a source-bound sensitivity fit with a distinct point-estimation '
                               'specification before composing the report. Follow the current approval requirements.')
    elif 'compose_report' in bound and result['status'] == 'partial':
        if analysis_missing and all(code.startswith('report:') for code in analysis_missing):
            result['compose_report'] = bound['compose_report']
            reference_step = ('Pass the report request_ref to run_operation when offered.' if suggest else
                              'Call inspect_analysis_completion for the report request_ref and pass it to run_operation.')
            result['next_step'] = (reference_step + ' If no reference is offered, use the exact compose_report '
                                   'specification with run_operation as operation.multi_step.')
        elif analysis_missing:
            result['next_step'] = 'Resolve the outstanding analysis requirements before composing the delivery report.'
    # Eligible but unchosen primary fits count too: binding one is the gate's own next step, and
    # requiring a bound model first left that state without a recovery (open.r3, 2026-11-10).
    if result['status'] == 'partial' and plan and ((evidence or {}).get('models') or NOT_SERVED in result['missing']
                                                   or bound['primary_candidates']):
        def repairable(code):
            return (code.startswith('report:') or ':model:' in code or ':sensitivity:' in code or code == NOT_SERVED
                or code.endswith(':diagnostics:computed_and_model_bound')
                or code == 'iv:diagnostics:ar_unavailable')
        if all(repairable(code) for code in result['missing']):
            result['recovery_action'] = 'inspect_and_repair'
            from ..canonical import sha256_canonical
            result['recovery_question_sha256'] = sha256_canonical(plan.question)
    bound_requirements = plan.task_requirements if plan is not None else requirements
    if _full_analysis_without_contract(result, bound_requirements):
        # The person asked for a full analysis (server-bound requirements) and no contract is
        # saved, with or without a plan: unfinished work with an executable next step, not a
        # quiet answer. Nine Ask nudges in the 2026-11-10 NVIDIA positions waited on this alone.
        # The recovery answers only the request that asked for the full analysis (or an
        # explicit request to finish it), never a later focused question.
        from ..canonical import sha256_canonical
        result['recovery_action'] = 'inspect_and_repair'
        result['recovery_question_sha256'] = (sha256_canonical(plan.question) if plan is not None
                                              else bound_requirements['sources'][-1]['sha256'])
        if plan is None and (latest := _latest_user_request(project_root, session_id, bound_requirements)):
            from .task_requirements import FULL_ANALYSIS

            # Same-scope requirements retain their first source. A later explicit full
            # request owns this repair; a later coefficient question must not resume it.
            if FULL_ANALYSIS.search(latest[1].payload['content']):
                result['recovery_question_sha256'] = latest[0]['sha256']
    elif question := _computed_question_request(result, bound_requirements, products, project_root, session_id):
        # The person asked for this focused work to be finished and it was computed: it still needs
        # its source/result binding. Repair that omission, not the scope.
        result['recovery_action'] = 'inspect_and_repair'
        result['recovery_scope'] = 'question'
        result['recovery_question_sha256'] = question['sha256']
        result['next_step'] = (_NO_CONTRACT_STEP + ' For this focused question use scope: "question", '
            'playbooks: [], and bind the existing source-bound computed result. Do not add a full analysis, '
            'diagnostics or a report just to repair this binding.')
    if checked['status'] == 'partial':
        criteria_guidance = ('A plan marked needs_approval still requires approval; otherwise an executed result '
            'contradicts an approved definition (see criteria_verification): revise the plan visibly rather than refit.')
        result['next_step'] = ((result['next_step'] + ' ') if result.get('next_step') else '') + criteria_guidance
    return result, evidence


_NO_CONTRACT_STEP = ('No completion contract was saved. Call update_plan with completion: select scope '
    'and playbooks from the user request, and bind the registered dataset source. '
    'When adding steps, omit status or use pending; only stored execution receipts can mark them done. '
    'For work already executed, bind its verified completion_evidence; do not repeat it merely to create plan history. '
    'A genuinely missing analysis may be proposed as a scientifically justified supported specification '
    'through the original permissions and approval path; unavailable or unjustified work stays partial. '
    'Check saved is true before checking completion again. Keep unverified evidence partial.')

#: Items that can accompany a missing contract: the requested estimands it would bind.
_CONTRACT_GAP = frozenset({'completion_contract:select_playbooks_and_source', 'target:requested_estimand_unbound'})


def _full_analysis_without_contract(result, requirements) -> bool:
    requirements = requirements or {}
    return (result['status'] == 'partial'
            and 'completion_contract:select_playbooks_and_source' in result['missing']
            and set(result['missing']) <= _CONTRACT_GAP
            and requirements.get('status') == 'verified' and requirements.get('scope') == 'analysis'
            and bool(requirements.get('sources')) and 'sha256' in requirements['sources'][-1])


def _computed_question_request(result, requirements, products, project_root, session_id):
    requirements = requirements or {}
    if (not session_id or requirements.get('scope') != 'question'
            or not _full_analysis_without_contract(result, {**requirements, 'scope': 'analysis'})):
        return None
    from .completion import _DATA_TYPES, _session_result_refs, computed_result

    # Requirement sources only grow when scope/estimands change. The latest substantive
    # message and operations' server-owned command IDs identify this question instead.
    latest = _latest_user_request(project_root, session_id, requirements)
    if latest is None:
        return None
    question, entry, repository = latest
    from .task_requirements import asks_to_finish

    # A plain question answered from a computed result stays quiet: replaying 55 recorded focused
    # questions, 50 would have been resumed for a contract nobody asked for (two more requests each).
    if not asks_to_finish(entry.payload['content']):
        return None
    commands = _question_command_ids(repository, session_id, requirements, entry)
    if not commands:
        return None
    refs = _session_result_refs(project_root, session_id, command_ids=commands)
    if any(computed_result(products, ref, products.load(ref))
           and any(item.artifact_type in _DATA_TYPES for item in products.ancestors(ref)) for ref in refs[:24]):
        return question
    return None


def _latest_user_request(project_root, session_id, requirements):
    from pathlib import Path
    from ..canonical import sha256_canonical
    from .session import EntryRef, JsonlSessionRepository

    question = requirements.get('latest_request') or {}
    if not session_id or question.get('kind') != 'user_message' or question.get('session_id') != session_id:
        return None
    try:
        repository = JsonlSessionRepository(Path(project_root) / 'workbench', create=False)
        entry = repository.get_entry(EntryRef(session_id, question['entry_id']))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    command = entry.payload.get('command_id')
    if (entry.entry_type != 'message' or entry.payload.get('role') != 'user'
            or not isinstance(command, str) or not command
            or not isinstance(entry.payload.get('content'), str)
            or sha256_canonical(entry.payload['content']) != question.get('sha256')):
        return None
    return question, entry, repository


def _question_command_ids(repository, session_id, requirements, question):
    """Include durable confirmation continuations on this request's branch, not old turns."""
    from .session import _payload_digest

    cursor = requirements.get('cursor') or {}
    if cursor.get('session_id') != session_id or not isinstance(cursor.get('entry_id'), str):
        return set()
    try:
        branch = repository.get_branch(session_id, leaf_entry_id=cursor['entry_id'],
                                       payload_entry_types=frozenset({'turn_input'}))
    except (OSError, ValueError, KeyError, TypeError):
        return set()
    positions = [i for i, entry in enumerate(branch)
                 if entry.session_id == session_id and entry.entry_id == question.entry_id]
    if len(positions) != 1:
        return set()
    position = positions[0]
    command = question.payload['command_id']
    commands = {command}
    # A queued substantive question can share a command with earlier work. Its old
    # results do not prove work for the new request; only later continuations qualify.
    if any((entry.idempotency or {}).get('key') == command
           and (entry.idempotency or {}).get('stage') == 'initial_user' for entry in branch[:position]):
        commands.clear()
    for entry in branch[position + 1:]:
        if entry.entry_type != 'turn_input':
            continue
        payload = entry.payload
        if payload.get('continuation') is not True or payload.get('text') is not None:
            break
        current = payload.get('command_id')
        if (entry.session_id == session_id and isinstance(current, str) and current
                and entry.idempotency == {'key': current, 'stage': 'turn_input',
                    'payload_sha256': _payload_digest('turn_input', payload)}):
            commands.add(current)
    return commands


def delivery_digest(check: dict[str, Any] | None) -> dict[str, Any] | None:
    """The check as an operation result carries it; None when there is no completion contract."""

    if not check or check.get("missing") == ["completion_contract:select_playbooks_and_source"]:
        return None
    return {key: check[key] for key in DIGEST_FIELDS if check.get(key) not in (None, [], {})}


def delivery_lines(digest: dict[str, Any] | None) -> list[str]:
    import json

    if not digest:
        return []
    lines = [f"Delivery check after this operation: {digest['status']}"
             + (f"; missing: {', '.join(digest['missing'][:8])}" if digest.get("missing") else "") + "."]
    if digest.get("next_step"):
        lines.append("Next step: " + str(digest["next_step"]))
    checked = digest.get('criteria_verification')
    if checked:
        rows = checked['requirements']
        unbound = checked['unbound_slots']
        summary = {'status': checked['status'], 'basis_sha256': checked['basis_sha256'],
            'requirements': [{'id': row['id'][:120], 'status': row['status'], 'reason': row['reason'][:240]}
                             for row in rows[:6]],
            'unbound_slots': [{k: v[:100] if isinstance(v, str) else v for k, v in slot.items()} for slot in unbound[:8]],
            'omitted_requirements': max(0, len(rows)-6), 'omitted_unbound_slots': max(0, len(unbound)-8)}
        lines.append('Approved deliverables: ' + json.dumps(summary, ensure_ascii=False))
        lines.append('Use inspect_analysis_completion for the complete bounded requirement/proof report; '
                     'reuse registered evidence. Success flags and free-text claims are not proof.')
    if digest.get("verified_artifacts"):
        lines.append("Verified artifact references (integrity only, not scientific certification): "
                     + json.dumps(digest["verified_artifacts"][:8], ensure_ascii=False)[:3000])
    for key in ("repair_steps", "compose_report", "sensitivity_options", "primary_candidates", "disclosures"):
        if digest.get(key):
            lines.append(f"{key}: " + json.dumps(digest[key], ensure_ascii=False)[:3000])
    lines.append("This is the same check inspect_analysis_completion returns; call it only for its evidence catalog "
                 "or repair steps.")
    return lines
