"""Publish source-bound delivery evidence without changing estimation contracts.

LMM retains its admission-gated FD writer. These ordinary run products use the
same artifact owner as the other native Cox/panel/IV diagnostic products.
"""
from __future__ import annotations

from workbench.artifacts import read_json, register_artifact, write_json
from workbench.canonical import sha256_canonical
from workbench.services.completion_products import source_binding
from workbench.services.pinned_run_directory import open_pinned_run_directory


def publish_completion_evidence(ctx, env, primary, *, point_definition, retained_positions,
                                diagnostics, diagnostic_artifact_ids=()):
    with open_pinned_run_directory(env.run_root.parent, env.run_root.name) as pinned:
        source = source_binding(pinned, ctx.data.frame, artifact_id=ctx.data.artifact_id)
    model_id = primary['model_id']
    registered = {record['artifact_id']: record['sha256']
                  for record in read_json(env.run_root / 'artifacts_index.json')['artifacts']}
    payload = {'contract': 'analysis-completion.evidence.v1', 'model_id': model_id,
        'model_type': primary['model_type'], 'nobs': primary['nobs'],
        'status': 'complete' if source else 'unavailable',
        'reason': None if source else 'source_unverified', 'source': source,
        'model_payload_sha256': sha256_canonical(primary),
        'point_estimation_fingerprint': sha256_canonical(point_definition),
        'analysis_sample_fingerprint': sha256_canonical(list(retained_positions)),
        'retained_positions': list(retained_positions), 'diagnostics': diagnostics,
        'diagnostic_artifact_ids': list(diagnostic_artifact_ids),
        'diagnostic_artifact_sha256': {key: registered[key] for key in diagnostic_artifact_ids},
        'scientific_validity': 'not_certified'}
    path = env.run_root / 'model_results' / f'{model_id}.completion.json'
    write_json(path, payload)
    register_artifact(env.run_root, f'{model_id}.completion', path, 'analysis_completion_evidence',
                      'diagnostics', [model_id, ctx.data.artifact_id, *diagnostic_artifact_ids])
    return payload
