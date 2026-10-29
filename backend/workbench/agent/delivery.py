"""The delivery check: what the plan's completion contract still lacks, and the next step.

One function for every place that reports it: the inspect_analysis_completion
tool, the final-answer gate, and (v1.9.1) the result of each operation, so the
Agent learns where it stands without asking. In the free-route DeepSeek rounds
18 of 40 completion checks came straight after an operation result.
"""

from __future__ import annotations

from typing import Any

#: What an operation result carries of the check: enough to act on, not the evidence catalog.
DIGEST_FIELDS = ("status", "missing", "next_step", "compose_report", "sensitivity_options", "primary_candidates",
                 "dropped_references", "disclosures", "verified_artifacts", "scientific_validity",
                 "playbook_status", "criteria_verification")


def review_plan_basis_sha256(*, question, criteria, completion):
    """Research-review inputs that change its meaning, excluding execution progress."""
    from ..canonical import sha256_canonical
    return sha256_canonical({'question': question, 'criteria': list(criteria), 'completion': completion})


def delivery_check(project_root, plan, *, suggest=False):
    return delivery_state(project_root, plan, suggest=suggest)[0]


def delivery_state(project_root, plan, *, suggest=False):
    """The check and its selected references share one bounded product cache."""
    from .completion import _Products, derive_evidence, evaluate
    from .task_requirements import enforce
    from .plan_criteria import verify
    from ..canonical import sha256_canonical

    products = _Products(project_root)
    evidence, bound = derive_evidence(project_root, plan.completion if plan else None,
                                      plan.completion_evidence if plan else None, _products=products)
    result = evaluate(project_root, plan.completion if plan else None, evidence, suggest=suggest, options=True, _products=products)
    if plan is not None:
        result = enforce(result, plan.task_requirements)
    result['playbook_status'] = result['status']
    checked = verify(project_root, plan, products, evidence)
    result['criteria_verification'] = checked
    if checked['status'] == 'partial':
        result['status'] = 'partial'
        result['missing'] = list(dict.fromkeys([*result['missing'], 'plan:approved_criteria_unverified']))
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
    if 'completion_contract:select_playbooks_and_source' in result['missing']:
        result['next_step'] = ('No completion contract was saved. Call update_plan with completion: select scope '
            'and playbooks from the user request, and bind the registered dataset source. '
            'When adding steps, omit status or use pending; only stored execution receipts can mark them done. '
            'For work already executed, bind its verified completion_evidence; do not rerun it to create plan history. '
            'Check saved is true before checking completion again. Keep unverified evidence partial.')
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
    elif result.get('sensitivity_options') and result['status'] == 'partial':
        # off3 leverage.goal composed its report three times before the sensitivity fit it lacked.
        from .completion_sensitivity import SENSITIVITY_NEXT_STEP
        result['next_step'] = SENSITIVITY_NEXT_STEP
    elif 'compose_report' in bound and result['status'] == 'partial':
        result['compose_report'] = bound['compose_report']
        result['next_step'] = ('No report covers the bound results yet. Propose compose_report exactly as given '
                               '(run_operation, operation.multi_step with one report.compose step).')
    if result['status'] == 'partial' and plan and (evidence or {}).get('models'):
        def repairable(code):
            return (code.startswith('report:') or ':model:' in code or ':sensitivity:' in code
                or code.endswith(':diagnostics:computed_and_model_bound')
                or code == 'iv:diagnostics:ar_unavailable')
        if all(repairable(code) for code in result['missing']):
            result['recovery_action'] = 'inspect_and_repair'
            from ..canonical import sha256_canonical
            result['recovery_question_sha256'] = sha256_canonical(plan.question)
    if checked['status'] == 'partial':
        result['next_step'] = ('Approved criteria or expected outputs remain unverified. Inspect criteria_verification; '
            'bind existing producer records and registered artifacts without rerunning. Missing machine definitions '
            'need a visible plan revision and approval; unsupported claims remain partial for human takeover.')
    return result, evidence


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
    for key in ("compose_report", "sensitivity_options", "primary_candidates", "disclosures"):
        if digest.get(key):
            lines.append(f"{key}: " + json.dumps(digest[key], ensure_ascii=False)[:3000])
    lines.append("This is the same check inspect_analysis_completion returns; call it only for its evidence catalog "
                 "or repair steps.")
    return lines
