"""Read-only verification of explicitly approved, typed deliverables.

Text is never interpreted here. An operation receipt supplies provenance; a
producer-specific reader, not the receipt's success flag, verifies its output.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math

from jsonschema import Draft202012Validator

from ..canonical import sha256_canonical

_TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 200}
_REF = {'type': 'object', 'required': ['run_id', 'artifact_id'],
        'properties': {'run_id': _TEXT, 'artifact_id': _TEXT}, 'additionalProperties': False}
SLOT_SCHEMA = {'oneOf': [
    {'type': 'object', 'required': ['criterion_index'], 'properties': {
        'criterion_index': {'type': 'integer', 'minimum': 0}}, 'additionalProperties': False},
    {'type': 'object', 'required': ['step_id', 'output_index'], 'properties': {
        'step_id': _TEXT, 'output_index': {'type': 'integer', 'minimum': 0}}, 'additionalProperties': False}]}
REQUIREMENTS_SCHEMA = {'type': 'array', 'maxItems': 40, 'items': {
    'type': 'object', 'required': ['id', 'covers', 'operation'], 'additionalProperties': False,
    'properties': {'id': _TEXT, 'covers': {'type': 'array', 'minItems': 1, 'maxItems': 1612,
        'uniqueItems': True, 'items': SLOT_SCHEMA}, 'allow_not_applicable': {'type': 'boolean'},
        'operation': {'type': 'object', 'required': ['step_id', 'operation_id', 'spec'],
            'properties': {'step_id': _TEXT, 'operation_id': _TEXT, 'spec': {'type': 'object'}},
            'additionalProperties': False}}}}
PROOFS_SCHEMA = {'type': 'array', 'maxItems': 40, 'items': {
    'type': 'object', 'required': ['requirement_id', 'operation_record_id', 'workflow_step_id', 'artifacts'],
    'properties': {'requirement_id': _TEXT, 'operation_record_id': _TEXT, 'workflow_step_id': _TEXT,
        'artifacts': {'type': 'array', 'minItems': 1, 'maxItems': 24, 'uniqueItems': True, 'items': _REF}},
    'additionalProperties': False}}


def slots(criteria, steps):
    return ([{'criterion_index': i} for i in range(len(criteria))]
            + [{'step_id': step.step_id, 'output_index': i}
               for step in steps for i in range(len(step.expected_outputs))])


def basis(plan):
    """Scientific declarations only; progress and late result IDs are not approval."""
    return sha256_canonical({'question': plan.question, 'criteria': list(plan.criteria),
        'outputs': [{'step_id': s.step_id, 'expected_outputs': list(s.expected_outputs)}
                    for s in plan.steps if s.expected_outputs],
        'completion': plan.completion})


def validate_definitions(contract, criteria, steps):
    """Validate declarations without creating proposals or executing anything."""
    definitions = (contract or {}).get('requirements', [])
    if not Draft202012Validator(REQUIREMENTS_SCHEMA).is_valid(definitions):
        raise ValueError('completion.requirements must contain bounded typed definitions, not success flags')
    legal = {sha256_canonical(slot) for slot in slots(criteria, steps)}
    ids, producers = set(), set()
    from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
    from .workflow_contract_parts.validation import _validate_step_spec
    from .workflow_contract_parts.graph import _validate_source_commitment
    from ..contracts.common.errors import OperationValidationError
    for item in definitions:
        operation = item['operation']
        if item['id'] in ids or operation['step_id'] in producers:
            raise ValueError('requirement and producer step identities must be unique')
        ids.add(item['id'])
        producers.add(operation['step_id'])
        if any(sha256_canonical(slot) not in legal for slot in item['covers']):
            raise ValueError('requirement covers an absent criterion or expected output')
        try:
            if operation['operation_id'] in WORKFLOW_STEP_SPEC_CONTRACTS:
                _validate_step_spec(operation['operation_id'],
                    {k: v for k, v in operation['spec'].items() if k != 'source'})
            if 'source' in operation['spec']:
                _validate_source_commitment(operation['step_id'], operation['spec']['source'])
        except OperationValidationError as exc:
            raise ValueError(str(exc)) from exc
    return definitions


def definition_addition(old, new):
    """A legacy/draft plan may gain definitions without changing its source contract."""
    if {k: v for k, v in old.items() if k != 'requirements'} != {k: v for k, v in new.items() if k != 'requirements'}:
        return False
    existing = {r['id']: r for r in old.get('requirements', [])}
    incoming = {r['id']: r for r in new.get('requirements', [])}
    return all(incoming.get(key) == value for key, value in existing.items())


def _approved(project_root, plan):
    from ..analysis_ledger import read
    from .plans import Plan
    if plan.status not in {'approved', 'completed'} or plan.approved_version is None:
        return False
    entries = [row for row in read(project_root) if row.get('event_type') == 'criteria_fixed'
        and row.get('plan_id') == plan.plan_id and row.get('plan_version') == plan.approved_version]
    return len(entries) == 1 and basis(Plan.from_dict(entries[0]['plan_snapshot'])) == basis(plan)


def _validated_record(project_root, record_id):
    from .operation_records import OperationRecordStore
    from .proposals import ProposalStore
    from .operation_requests import OperationRequest
    root = project_root / 'workbench'
    record = OperationRecordStore(root, create=False).get(record_id)
    proposals = [p for p in ProposalStore(root, create=False).revisions(record.proposal_id)
                 if p.revision == record.proposal_revision and p.fingerprint == record.proposal_fingerprint]
    if len(proposals) != 1:
        raise ValueError('original_proposal_unverified')
    proposal = proposals[0]
    identity = {key: getattr(proposal, key) for key in ('proposal_id', 'operation_id', 'operation_version',
        'revision', 'target', 'preconditions', 'changes', 'evidence_refs', 'expected_effect', 'risks')}
    fingerprint = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, default=list).encode()).hexdigest()
    if (fingerprint != proposal.fingerprint or record.operation_id != proposal.operation_id
            or record.operation_version != proposal.operation_version or record.target != proposal.target
            or record.preconditions != proposal.preconditions or record.changes != proposal.changes
            or record.agent_session_id != proposal.session_id or record.chain_id != proposal.chain_id):
        raise ValueError('executed_request_changed')
    if record.status != 'completed' or record.error or record.verification.get('passed') is not True:
        raise ValueError('operation_not_completed_and_verified')
    if record.operation_id != 'operation.multi_step':
        raise ValueError('producer_record_kind_not_supported')
    request = OperationRequest.from_arguments(proposal.to_dict())
    workflow = record.outputs.get('workflow_state') or {}
    if workflow.get('status') != 'completed':
        raise ValueError('workflow_not_completed')
    return record, workflow, sha256_canonical(asdict(request))


def _record(project_root, proof, cache):
    record_id = proof['operation_record_id']
    if record_id not in cache:
        try:
            cache[record_id] = _validated_record(project_root, record_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            cache[record_id] = exc
    cached = cache[record_id]
    if isinstance(cached, Exception):
        raise cached
    record, workflow, request_sha = cached
    matches = [s for s in record.changes.get('steps', []) if s.get('step_id') == proof['workflow_step_id']]
    state = (workflow.get('steps') or {}).get(proof['workflow_step_id'])
    if len(matches) != 1 or not state or state.get('status') != 'completed' or state.get('error'):
        raise ValueError('producer_step_not_completed')
    return record, matches[0], state, request_sha


def _source(products, source, ref):
    registered = products.load(source)
    return (registered is not None and registered.sha256 == source['sha256']
            and any(item is registered for item in products.ancestors(ref)))


def _human_confirmation(record):
    confirmation = record.confirmation
    return (record.actor_type in {'user', 'human_ui', 'human_cli'}
            and confirmation.get('actor_type') == record.actor_type
            and confirmation.get('proposal_id') == record.proposal_id
            and confirmation.get('revision') == record.proposal_revision
            and confirmation.get('fingerprint') == record.proposal_fingerprint)


def _published(record, state, ref):
    return (f"{ref['run_id']}:{ref['artifact_id']}" in state.get('artifact_ids', [])
        or ref['run_id'] == record.target['run_id'] and ref['artifact_id'] in state.get('artifact_ids', []))


def _upstream(record, step_id, definitions, *, scientific=True):
    """Project an original completed producer, never resolve a live workflow."""
    workflow = record.outputs['workflow_state']
    if (workflow['workflow_id'] != record.execution.get('workflow_id')
            or not workflow.get('plan_fingerprint')
            or workflow['plan_fingerprint'] != record.execution.get('workflow_plan_fingerprint')):
        raise ValueError('workflow_binding_unverified')
    matches = [s for s in record.changes['steps'] if s['step_id'] == step_id]
    state = workflow['steps'].get(step_id)
    if len(matches) != 1 or not state or state['status'] != 'completed' or state.get('error'):
        raise ValueError('producer_step_not_completed')
    step = matches[0]
    if scientific:
        fixed = definitions.get(step_id)
        if fixed is not None:
            if fixed['operation_id'] != step['operation_id'] or fixed['spec'] != step['spec']:
                raise ValueError('upstream_scientific_spec_changed')
        elif not _human_confirmation(record):
            # An Auto execution receipt is not human approval of an unspecified
            # scientific input. Ask may reuse the exact whole request confirmation.
            raise ValueError('upstream_scientific_definition_unverified')
    return step, state


def _dataset_binding(products, record, step, state, source, definitions, seen):
    from .workflow_runtime_parts.constants import _PRODUCED_DATASET_SCHEMA
    if step['operation_id'] != 'data.subset':
        raise ValueError('typed_dataset_verifier_not_available: ' + step['operation_id'])
    produced = state.get('produced_dataset') or {}
    if not isinstance(produced, dict):
        raise ValueError('produced_dataset_unverified')
    ref = {key: produced.get(key) for key in ('run_id', 'artifact_id')}
    artifact = products.load(ref)
    if (produced.get('schema_version') != _PRODUCED_DATASET_SCHEMA
            or produced.get('run_id') != record.target['run_id'] or not produced.get('node_ref')
            or produced.get('dataset_kind') != 'derived_data'
            or artifact is None or artifact.artifact_type != 'derived_data'
            or artifact.sha256 != produced.get('content_sha256') or not _published(record, state, ref)
            or not state.get('result_fingerprint')
            or produced.get('result_fingerprint') != state['result_fingerprint']):
        raise ValueError('produced_dataset_unverified')
    parent = _step_source(products, record, step, source, definitions, seen)
    if not _source(products, parent, ref):
        raise ValueError('produced_dataset_source_unverified')
    return {**ref, 'sha256': artifact.sha256, 'node_ref': produced['node_ref']}


def _step_source(products, record, step, source, definitions, seen=()):
    if step['step_id'] in seen:
        raise ValueError('cyclic_source_binding')
    commitment = step['spec'].get('source')
    if commitment is None:
        from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
        pending, visited = list(step.get('depends_on', [])), set()
        while pending:
            dependency = pending.pop()
            if dependency in visited:
                continue
            visited.add(dependency)
            ancestor, _ = _upstream(record, dependency, definitions, scientific=False)
            contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(ancestor['operation_id'])
            if contract is None or contract.produces_dataset:
                raise ValueError('implicit_dataset_source_unverified; declare a supported persisted source')
            pending.extend(ancestor.get('depends_on', []))
            if ancestor['spec'].get('source'):
                pending.append(ancestor['spec']['source']['from_step'])
        ref = {key: record.target[key] for key in ('run_id', 'artifact_id')}
        artifact = products.load(ref)
        if artifact is None or not _source(products, source, ref):
            raise ValueError('workflow_target_source_unverified')
        return {**ref, 'sha256': artifact.sha256, 'node_ref': record.target['node_ref']}
    # source.from_step itself declares the edge; the compiler inserts it into
    # depends_on while the immutable original proposal may omit that list.
    if commitment['output'] != 'produced_dataset':
        raise ValueError('source_dependency_unverified')
    producer, state = _upstream(record, commitment['from_step'], definitions)
    return _dataset_binding(products, record, producer, state, source, definitions, (*seen, step['step_id']))


def _model_kernel(products, record, state, branch, source):
    from ..artifacts import read_json
    from .context_compiler import read_completion_dataset_source
    from ..contracts.model.inference_kernel import validate_inference_kernel
    model_id = branch.get('model_id')
    frozen = branch.get('branch_spec')
    if not isinstance(model_id, str) or not model_id or not isinstance(frozen, dict) or frozen.get('by_group'):
        raise ValueError('single_model_binding_unverified')
    ref = {'run_id': branch['run_id'], 'artifact_id': model_id}
    kernel_ref = {**ref, 'artifact_id': 'inference_kernel_' + model_id}
    kernel = products.load(kernel_ref)
    if (model_id not in branch.get('artifact_ids', []) or not _published(record, state, ref)
            or kernel is None or kernel.artifact_type != 'inference_kernel'
            or kernel.sha256 != branch.get('inference_kernel_sha256')
            or (kernel.payload or {}).get('model_id') != model_id):
        raise ValueError('inference_kernel_unverified')
    validate_inference_kernel(kernel.payload)
    run = products.runs / ref['run_id']
    manifest = read_json(run / 'run_manifest.json')
    if not isinstance(manifest, dict):
        raise ValueError('model_run_manifest_unverified')
    origin = manifest.get('dataset_source') or {}
    lineage = read_completion_dataset_source(run)
    if (manifest.get('status') != 'completed' or lineage is None
            or lineage['source'] != {k: source[k] for k in ('run_id', 'artifact_id', 'sha256')}
            or origin.get('source_run_id') != source['run_id']
            or origin.get('source_artifact_id') != source['artifact_id']
            or origin.get('source_sha256') != source['sha256'] or origin.get('op_node_id') != source['node_ref']
            or not _source(products, source, ref)):
        raise ValueError('model_input_source_unverified')
    return ref


def _model_output(products, definition, record, state, refs, source, definitions):
    spec = definition['operation']['spec']
    step, _ = _upstream(record, definition['operation']['step_id'], definitions)
    input_source = _step_source(products, record, step, source, definitions)
    branches = state.get('model_branches') or []
    expected = spec.get('branches') or []
    if not expected or len(branches) != len(expected):
        raise ValueError('model_branches_unverified')
    verified = []
    for requested in expected:
        candidates = [b for b in branches if b.get('branch_id') == requested['branch_id']]
        if len(candidates) != 1:
            raise ValueError('model_branch_ambiguous')
        branch = candidates[0]
        ref = _model_kernel(products, record, state, branch, input_source)
        if ref not in refs or f"{ref['run_id']}:{ref['artifact_id']}" not in state.get('artifact_ids', []):
            raise ValueError('model_not_published_by_this_step')
        artifact = products.load(ref)
        model = products.model(ref, artifact)
        if model is None or model.get('model_id') != ref['artifact_id'] or not _source(products, source, ref):
            raise ValueError('model_or_source_unverified')
        frozen = branch.get('branch_spec') or {}
        outcome = model.get('y_column')
        if model.get('model_type') == 'iv_2sls':
            actual = model.get('point_definition')
            kernel = products.load({**ref, 'artifact_id': 'inference_kernel_' + ref['artifact_id']}).payload
            if (not isinstance(actual, dict)
                    or sha256_canonical(actual) != model.get('point_estimation_fingerprint')
                    or actual.get('family') != 'iv_2sls' or actual.get('intercept') is not True
                    or actual.get('outcome') != [requested['outcome']]
                    or actual.get('exogenous') != ['Intercept', *requested['predictors']]
                    or actual.get('endogenous') != spec.get('iv_endog')
                    or actual.get('instruments') != spec.get('iv_instruments')
                    or len(str(actual.get('actual_design_sha256', ''))) != 64
                    or requested.get('categorical') or requested.get('polynomials')
                    or kernel.get('param_names') != actual['exogenous'] + actual['endogenous']
                    or kernel.get('nobs') != model['nobs']
                    or kernel.get('covariance_estimator') != frozen.get('covariance')):
                raise ValueError('iv_runtime_definition_unverified')
            outcome = actual['outcome'][0]
        if (frozen.get('model_family') != spec.get('model_family', 'ols')
                or frozen.get('outcome') != requested['outcome']
                or frozen.get('predictors') != requested['predictors']
                or frozen.get('categorical', []) != requested.get('categorical', [])
                or frozen.get('polynomials', []) != requested.get('polynomials', [])
                or outcome != requested['outcome']):
            raise ValueError('model_scientific_spec_changed')
        for key, value in spec.items():
            if key in {'branches', 'source'}:
                continue
            if key not in frozen:
                raise ValueError('model_scientific_fields_unverified: ' + key)
            expected_value = requested.get('covariance', value) if key == 'covariance' else value
            if frozen[key] != expected_value:
                raise ValueError('model_scientific_spec_changed')
        for key, value in requested.items():
            if key == 'branch_id':
                continue
            if key not in frozen:
                raise ValueError('model_scientific_fields_unverified: branches.' + key)
            if frozen[key] != value:
                raise ValueError('model_scientific_spec_changed')
        if model.get('model_type') in {'panel_ols', 'iv_2sls', 'survival_cox', 'did'}:
            companion = products.load({**ref, 'artifact_id': branch['model_id'] + '.completion'})
            if companion is None:
                raise ValueError('native_model_completion_unverified')
            verified.append({**ref, 'artifact_id': branch['model_id'] + '.completion', 'sha256': companion.sha256})
        verified.append({**ref, 'sha256': artifact.sha256})
    if any(ref not in [{'run_id': b['run_id'], 'artifact_id': b['model_id']} for b in branches] for ref in refs):
        raise ValueError('unrelated_artifact_reference')
    return verified


def _iv_ar_output(products, definition, record, state, refs, source, definitions,
                  proofs, read_record, approved):
    from .completion_profiles import iv_ar_wrapper, verified_iv_ar
    from .postestimation_steps import model_step_reference
    step, _ = _upstream(record, definition['operation']['step_id'], definitions)
    input_source = _step_source(products, record, step, source, definitions)
    spec = step['spec']
    symbolic = model_step_reference(spec['model_ref'])
    candidates = []
    if symbolic is not None:
        producer, produced = _upstream(record, symbolic[0], definitions)
        candidates = [(record, producer, produced, branch) for branch in produced.get('model_branches', [])
                      if branch.get('branch_id') == symbolic[1]]
    else:
        target = {'run_id': spec.get('model_run_id', record.target['run_id']), 'artifact_id': spec['model_ref']}
        for producer in definitions.values():
            if producer['operation_id'] != 'model.genesis':
                continue
            matches = [p for p in proofs if p['workflow_step_id'] == producer['step_id']]
            if len(matches) != 1:
                continue
            owner, executed, produced, _ = read_record(matches[0])
            if executed['operation_id'] != producer['operation_id'] or executed['spec'] != producer['spec']:
                raise ValueError('upstream_scientific_spec_changed')
            if not approved and not _human_confirmation(owner):
                raise ValueError('human_request_confirmation_or_approved_basis_required')
            candidates.extend((owner, executed, produced, b) for b in produced.get('model_branches', [])
                if {'run_id': b.get('run_id'), 'artifact_id': b.get('model_id')} == target)
    if len(candidates) != 1:
        raise ValueError('iv_ar_model_producer_unverified')
    owner, producer, produced, branch = candidates[0]
    if producer['operation_id'] != 'model.genesis':
        raise ValueError('typed_model_producer_not_available')
    model_source = _step_source(products, owner, producer, source, definitions)
    if input_source != model_source:
        raise ValueError('iv_ar_model_source_unverified')
    model_refs = [{'run_id': b['run_id'], 'artifact_id': b['model_id']} for b in produced['model_branches']]
    _model_output(products, {'operation': producer}, owner, produced, model_refs, source, definitions)
    main_ref = {'run_id': branch['run_id'], 'artifact_id': branch['model_id']}
    main = products.model(main_ref, products.load(main_ref))
    verified = []
    for ref in refs:
        artifact = products.load(ref)
        wrapper = iv_ar_wrapper(artifact)
        origin = (wrapper or {}).get('source') or {}
        execution = (wrapper or {}).get('execution') or {}
        if (not _published(record, state, ref) or wrapper is None
                or origin.get('workflow_id') != record.outputs.get('workflow_id')
                or origin.get('workflow_step_id') != state['step_id']
                or origin.get('workflow_step_fingerprint') != state['fingerprint']
                or origin.get('run_id') != record.target['run_id']
                or execution.get('workflow_id') != record.outputs.get('workflow_id')
                or execution.get('plan_fingerprint') != record.execution.get('workflow_plan_fingerprint')
                or any(origin.get(k) != input_source[k] for k in ('artifact_id', 'sha256', 'node_ref'))
                or not _source(products, source, ref)):
            raise ValueError('iv_ar_published_source_unverified')
        region = verified_iv_ar(products, main_ref, main, ref, artifact)
        if not isinstance(region, dict):
            raise ValueError('iv_ar_model_binding_unverified')
        certificate = region.get('global_certification') or {}
        computation = region.get('computation') or {}
        common = {'coefficient_order', 'cauchy_bound', 'distinct_real_roots', 'root_brackets',
                  'cell_accepted', 'boundary_tolerance'}
        if (certificate.get('status') != 'certified'
                or certificate.get('arithmetic') != 'exact_binary64_input_rationals'
                or not common <= certificate.keys()
                or region.get('kind') not in {'interval', 'singleton', 'whole_line', 'ray_below',
                    'ray_above', 'union_of_rays', 'disjoint', 'empty'}
                or not isinstance(region.get('components'), list)
                or not region.get('critical_binary64_ratio') or region.get('coverage_certified') is not False):
            raise ValueError('iv_ar_global_certificate_unverified')
        if region.get('method') == 'robust_hc0':
            if computation.get('certification_target') != 'original_binary64_observations':
                raise ValueError('iv_ar_original_input_unverified')
            if computation.get('path') == 'verified_numpy':
                reduction = certificate.get('reduction') or {}
                if (certificate.get('algorithm') != 'gamma_moments_rational_intervals_sturm_bernstein_v1'
                        or certificate.get('input_topology_certified') is not True
                        or not all(certificate.get(k) for k in ('numerator_coefficient_bounds',
                            'denominator_coefficient_bounds', 'denominator_proof'))
                        or not {'root_proofs', 'complement_proof'} <= certificate.keys()
                        or reduction.get('rows') != main['nobs']
                        or len(str(reduction.get('input_sha256', ''))) != 64
                        or not all(reduction.get(k) for k in ('gamma_steps', 'gamma', 'underflow_allowance', 'moment_bounds'))):
                    raise ValueError('iv_ar_original_input_unverified')
            elif computation.get('path') != 'exact_fallback':
                raise ValueError('iv_ar_original_input_unverified')
        elif region.get('method') != 'homoskedastic':
            raise ValueError('iv_ar_method_unverified')
        if (region.get('method') == 'homoskedastic' or computation.get('path') == 'exact_fallback') and (
                certificate.get('algorithm') != 'sturm_sign_decomposition_v1'
                or not certificate.get('numerator') or not certificate.get('denominator')):
            raise ValueError('iv_ar_global_certificate_unverified')
        verified.append({**ref, 'sha256': artifact.sha256})
    return verified


def _joint_f_output(products, definition, record, state, refs, source, definitions):
    step, _ = _upstream(record, definition['operation']['step_id'], definitions)
    candidates = []
    for dependency in step.get('depends_on', []):
        producer, produced_state = _upstream(record, dependency, definitions, scientific=False)
        for branch in produced_state.get('model_branches') or []:
            if branch.get('branch_id') == step['spec']['branch_id']:
                candidates.append((producer, produced_state, branch))
    if len(candidates) != 1:
        raise ValueError('model_branch_ambiguous')
    producer, produced_state, branch = candidates[0]
    _upstream(record, producer['step_id'], definitions)
    if producer['operation_id'] != 'model.genesis':
        raise ValueError('typed_model_producer_not_available')
    input_source = _step_source(products, record, producer, source, definitions)
    model_ref = _model_kernel(products, record, produced_state, branch, input_source)
    producer_refs = [{'run_id': b['run_id'], 'artifact_id': b['model_id']}
                     for b in produced_state['model_branches']]
    _model_output(products, {'operation': producer}, record, produced_state, producer_refs, source, definitions)
    if _step_source(products, record, step, source, definitions) != input_source:
        raise ValueError('joint_f_model_source_unverified')
    verified = []
    for ref in refs:
        qualified = f"{ref['run_id']}:{ref['artifact_id']}"
        if qualified not in state.get('artifact_ids', []) and ref['artifact_id'] not in state.get('artifact_ids', []):
            raise ValueError('test_not_published_by_this_step')
        artifact = products.load(ref)
        payload = artifact.payload if artifact else None
        result = (payload or {}).get('result') or {}
        origin = (payload or {}).get('source') or {}
        if (origin.get('model_run_id') != model_ref['run_id'] or origin.get('model_artifact_id') != model_ref['artifact_id']
                or result.get('branch_id') != branch['branch_id']
                or result.get('covariance') != branch['branch_spec'].get('covariance')):
            raise ValueError('joint_f_model_binding_unverified')
        if (artifact is None or artifact.artifact_type != 'statistical_test'
                or payload.get('schema_version') != 'workbench.workflow.post-estimation/v1'
                or origin.get('workflow_step_id') != state['step_id']
                or origin.get('workflow_id') != record.outputs.get('workflow_id')
                or origin.get('workflow_step_fingerprint') != state['fingerprint']
                or any(origin.get(k) != input_source[k] for k in ('artifact_id', 'sha256', 'node_ref'))
                or result.get('schema_version') != 'workbench.model.joint-f-test/v1'
                or result.get('test') != 'joint_f_test' or result.get('distribution') != 'F'
                or result.get('term_selectors') != definition['operation']['spec'].get('term_selectors')
                or not _source(products, source, ref)):
            raise ValueError('typed_joint_f_result_unverified')
        if not all(type(result.get(k)) in (int, float) and math.isfinite(result[k])
                   for k in ('f_statistic', 'p_value', 'numerator_df', 'denominator_df')):
            raise ValueError('joint_f_result_not_computed')
        if not 0 <= result['p_value'] <= 1 or result['f_statistic'] < 0 or min(result['numerator_df'], result['denominator_df']) <= 0:
            raise ValueError('joint_f_result_not_computed')
        verified.append({**ref, 'sha256': artifact.sha256})
    return verified


def _report_output(products, record, state, refs, source, selected_evidence):
    from .completion import report_missing_sources
    selected = [ref for key in ('models', 'diagnostics', 'sensitivity', 'results')
                for ref in (selected_evidence or {}).get(key, [])]
    verified = []
    for ref in refs:
        artifact = products.load(ref)
        published = (f"{ref['run_id']}:{ref['artifact_id']}" in state.get('artifact_ids', [])
            or ref['run_id'] == record.target.get('run_id') and ref['artifact_id'] in state.get('artifact_ids', []))
        if (not published or artifact is None or artifact.artifact_type != 'report'
                or not ((artifact.payload or {}).get('sections') or
                        artifact.suffix in {'.html', '.pdf', '.md'} and artifact.size_bytes > 0)
                or not _source(products, source, ref)
                or report_missing_sources(products, ref, selected)):
            raise ValueError('registered_report_or_result_sources_unverified')
        verified.append({**ref, 'sha256': artifact.sha256})
    return verified


def verify(project_root, plan, products, selected_evidence=None):
    """Return small verification metadata; never write records or replay an effect."""
    from pathlib import Path
    project_root = Path(project_root)
    required = slots(plan.criteria, plan.steps) if plan else []
    result = {'plan_id': plan.plan_id if plan else '', 'plan_version': plan.version if plan else 0,
        'basis_sha256': basis(plan) if plan else '', 'status': 'requirements_met',
        'requirements': [], 'unbound_slots': []}
    if not plan or not plan.completion or plan.completion.get('scope', 'analysis') != 'analysis':
        result['status'] = 'not_required'
        return result
    try:
        definitions = validate_definitions(plan.completion, plan.criteria, plan.steps)
    except (ValueError, TypeError, KeyError) as exc:
        result['status'] = 'partial'
        result['unbound_slots'] = required
        result['requirements'] = [{'id': '', 'status': 'unverified', 'reason': str(exc), 'verified_artifacts': []}]
        return result
    proofs = (plan.completion_evidence or {}).get('requirements', [])
    proof_valid = Draft202012Validator(PROOFS_SCHEMA).is_valid(proofs)
    approved = _approved(project_root, plan)
    source = plan.completion['source']
    covered = {sha256_canonical(slot) for item in definitions for slot in item['covers']}
    result['unbound_slots'] = [slot for slot in required if sha256_canonical(slot) not in covered]
    records = {}
    definitions_by_step = {d['operation']['step_id']: d['operation'] for d in definitions}
    for definition in definitions:
        row = {'id': definition['id'], 'status': 'unverified', 'reason': '', 'verified_artifacts': []}
        result['requirements'].append(row)
        try:
            if plan.status == 'needs_approval':
                raise ValueError('approved_requirement_basis_unverified')
            operation_id = definition['operation']['operation_id']
            if operation_id not in {'model.genesis', 'model.joint_f_test', 'report.compose', 'data.subset', 'iv.ar_confidence'}:
                raise ValueError('typed_artifact_verifier_not_available: ' + operation_id)
            spec = definition['operation']['spec']
            matches = [p for p in proofs if p['requirement_id'] == definition['id']] if proof_valid else []
            if len(matches) != 1:
                raise ValueError('unique_execution_evidence_required')
            proof = matches[0]
            record, step, state, request_sha = _record(project_root, proof, records)
            if (proof['workflow_step_id'] != definition['operation']['step_id']
                    or step['operation_id'] != operation_id or step['spec'] != spec):
                raise ValueError('executed_scientific_spec_changed')
            if not approved and not _human_confirmation(record):
                raise ValueError('human_request_confirmation_or_approved_basis_required')
            if operation_id == 'report.compose':
                row['verified_artifacts'] = _report_output(products, record, state, proof['artifacts'], source, selected_evidence)
            elif operation_id == 'iv.ar_confidence':
                row['verified_artifacts'] = _iv_ar_output(products, definition, record, state, proof['artifacts'], source,
                    definitions_by_step, proofs, lambda p: _record(project_root, p, records), approved)
            elif operation_id == 'data.subset':
                _upstream(record, step['step_id'], definitions_by_step)
                binding = _dataset_binding(products, record, step, state, source, definitions_by_step, ())
                if proof['artifacts'] != [{k: binding[k] for k in ('run_id', 'artifact_id')}]:
                    raise ValueError('produced_dataset_proof_unverified')
                row['verified_artifacts'] = [{k: binding[k] for k in ('run_id', 'artifact_id', 'sha256')}]
            else:
                reader = _model_output if operation_id == 'model.genesis' else _joint_f_output
                row['verified_artifacts'] = reader(products, definition, record, state, proof['artifacts'], source, definitions_by_step)
            row['status'] = 'verified'
            # A digest is recorded by the verifier, not accepted from the caller.
            row['reason'] = 'verified_registered_producer; request_sha256=' + request_sha
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row['reason'] = str(exc)
    if not definitions:
        result['requirements'].append({'id': '', 'status': 'unverified',
            'reason': 'No machine-checkable approved deliverable definitions were saved; retain partial completion for human takeover.',
            'verified_artifacts': []})
    if result['unbound_slots'] or any(r['status'] != 'verified' for r in result['requirements']):
        result['status'] = 'partial'
    return result
