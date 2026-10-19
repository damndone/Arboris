"""Static skill contracts and development-task coverage, not model-quality evidence.

A scenario's three phrasings are separate dev tasks, not independent DGPs.
Only this test imports development tasks; product skills contain no task IDs or truth.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1] / 'backend/workbench/agent/builtin_skills'
DEV_TASKS = {
    'cross-sectional-analysis': (
        'leverage.open', 'leverage.specific', 'leverage.goal',
        'cs_hetero.specific', 'cs_ovb.goal', 'collinear.specific',
    ),
    'generalized-outcome-analysis': (
        'count_overdispersed.open', 'count_overdispersed.specific', 'count_overdispersed.goal',
        'binary_logit.open', 'binary_logit.specific', 'binary_logit.goal',
    ),
}
SECTIONS = (
    'Applicability', 'Design, sample, and estimand', 'Required evidence',
    'Diagnostics and sensitivity', 'Completion self-check', 'Failure and partial completion',
)


def _skill(name):
    path = ROOT / name / 'SKILL.md'
    assert path.is_file(), f'Missing built-in analysis skill: {name}'
    text = path.read_text(encoding='utf-8')
    assert text.startswith('---\n')
    frontmatter, body = text[4:].split('\n---\n', 1)
    return yaml.safe_load(frontmatter), body


@pytest.mark.parametrize('name', DEV_TASKS)
def test_analysis_skill_has_discoverable_frontmatter_and_a_complete_guidance_contract(name):
    metadata, body = _skill(name)
    assert metadata['name'] == name
    assert isinstance(metadata['description'], str) and metadata['description'].strip()
    assert set(metadata) == {'name', 'description'}
    for section in SECTIONS:
        assert f'## {section}\n' in body
    for requirement in ('independent unit', 'sample', 'estimand', 'inspect_operation_contract',
                        'inspect_project_model_coefficients', 'evidence_ref', 'run_id', 'model_id', 'nobs'):
        assert requirement in body


@pytest.mark.parametrize('name', DEV_TASKS)
def test_each_analysis_skill_maps_to_at_least_five_existing_development_tasks(name):
    from scripts.agent_eval.tasks import dev_tasks

    catalog = {task.id: task for task in dev_tasks()}
    mapped = DEV_TASKS[name]
    assert len(set(mapped)) >= 5
    assert set(mapped) <= set(catalog)
    expected_scenarios = {'leverage', 'cs_hetero', 'cs_ovb', 'collinear'} if name == 'cross-sectional-analysis' else {'count_overdispersed', 'binary_logit'}
    assert {catalog[task_id].scenario.id for task_id in mapped} == expected_scenarios
    # Six generalized tasks cover two DGPs, each asked three ways.
    if name == 'generalized-outcome-analysis':
        assert len({catalog[task_id].scenario.id for task_id in mapped}) == 2
        assert {catalog[task_id].variant for task_id in mapped} == {'open', 'specific', 'goal'}
    _, body = _skill(name)
    assert not any(task_id in body for task_id in catalog)
    assert 'scripts.agent_eval' not in body


@pytest.mark.parametrize('name', DEV_TASKS)
def test_skills_require_actual_artifacts_and_fail_honestly_without_unsupported_substitutes(name):
    _, body = _skill(name)
    for rule in ('does not certify', 'single-question', 'Do not silently substitute',
                 'HC3', 'cluster', 'at most two unsuccessful attempts', 'partial completion',
                 'Do not choose', 'significant', 'missing_terms', 'None', 'approval'):
        assert rule in body
    assert 'inspect_operation_artifact' in body
    assert 'same source' in body
    assert 'raw rows' in body


def test_cross_sectional_skill_requires_influence_disposition_and_real_sensitivity_evidence():
    _, body = _skill('cross-sectional-analysis')
    for requirement in ("Cook", 'influence', 'sensitivity', 'VIF', 'heteroskedasticity',
                        'full-sample', 'control', 'conditional association'):
        assert requirement in body
    assert 'existence of a diagnostic artifact is not a passed diagnosis' in body
    assert 'Do not delete observations merely to improve significance' in body


def test_generalized_skill_requires_matching_fits_and_server_reported_effect_scales():
    _, body = _skill('generalized-outcome-analysis')
    for requirement in ('Poisson', 'negative-binomial', 'binary', 'binomial', 'overdispersion',
                        'postestimation.margins', 'probability', 'uncertainty', 'seed OLS'):
        assert requirement in body
    assert 'Do not compute a percentage or marginal effect from prose' in body
    assert 'variance source' in body
