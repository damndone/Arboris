"""The project lint rules hold, and each rule still catches the defect it came from."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import lint_rules  # noqa: E402


def test_the_repository_has_no_lint_violations():
    assert [str(violation) for violation in lint_rules.run()] == []


def test_every_rule_names_the_defect_it_came_from():
    assert all(rule.origin.strip() and rule.rule_id for rule in lint_rules.RULES)
    assert len({rule.rule_id for rule in lint_rules.RULES}) == len(lint_rules.RULES)


def _fake_root(tmp_path: Path, runner_source: str, gitignore: str = "node_modules\n") -> Path:
    runner = tmp_path / "backend/workbench/econometrics/runner.py"
    runner.parent.mkdir(parents=True)
    runner.write_text(runner_source)
    (tmp_path / ".gitignore").write_text(gitignore)
    return tmp_path


@pytest.mark.parametrize("source, flagged", [
    ("def _fit_ols_formula(f, d):\n    return smf.ols(formula=f, data=d).fit()\n", False),
    ("def run_ols(f, d):\n    return smf.ols(formula=f, data=d).fit()\n", True),
    ("def run_ols(f, d, w):\n    return smf.wls(formula=f, data=d, weights=w).fit()\n", True),
])
def test_an_ols_fit_outside_the_omission_path_is_flagged(tmp_path, source, flagged):
    found = list(lint_rules.ols_fits_go_through_the_omission_path(_fake_root(tmp_path, source)))
    assert bool(found) is flagged


def test_a_trailing_slash_on_node_modules_is_flagged(tmp_path):
    root = _fake_root(tmp_path, "", gitignore="dist\nnode_modules/\n")
    [violation] = lint_rules.gitignore_names_node_modules_without_a_trailing_slash(root)
    assert violation.line == 2


def test_an_ols_call_without_a_dataset_snapshot_is_flagged(tmp_path):
    root = _fake_root(tmp_path, "")
    caller = root / "backend/workbench/caller.py"
    caller.write_text("a = run_ols(frame, 'y', ['x'], True, 'm')\n"
                      "b = _orch().run_ols(frame, y='y', x=['x'], robust=True, model_id='m', dataset_snapshot={})\n")
    [violation] = lint_rules.ols_calls_pass_a_dataset_snapshot(root)
    assert (violation.path, violation.line) == ("backend/workbench/caller.py", 1)


def test_a_direct_row_set_read_is_flagged_outside_the_derivation(tmp_path):
    root = _fake_root(tmp_path, "")
    reader = root / "backend/workbench/reader.py"
    reader.write_text("a = sample['row_set']\nb = sample.get('row_set')\nc = sample.get('row_order')\n")
    found = list(lint_rules.analysis_sample_row_set_is_derived(root))
    assert [(violation.path, violation.line) for violation in found] == [
        ("backend/workbench/reader.py", 1), ("backend/workbench/reader.py", 2)]


def test_a_linearmodels_formula_call_is_flagged_outside_its_fallbacks(tmp_path):
    root = _fake_root(tmp_path, "")
    (root / "backend/workbench/econometrics").mkdir(parents=True, exist_ok=True)
    module = root / "backend/workbench/econometrics/panel_iv.py"
    module.write_text("def run_iv_2sls():\n    return iv.IV2SLS.from_formula(f, data=d)\n"
                      "def other():\n    return panel.PanelOLS.from_formula(f, data=d)\n"
                      "def manova():\n    return MANOVA.from_formula(f, data=d)\n")
    [violation] = lint_rules.linearmodels_fits_skip_formulaic_when_they_can(root)
    assert (violation.path, violation.line) == ("backend/workbench/econometrics/panel_iv.py", 4)


def test_a_restricted_import_names_the_public_interface_to_use(tmp_path):
    root = _fake_root(tmp_path, "")
    agent = root / "backend/workbench/agent"
    agent.mkdir(parents=True)
    (agent / "model.py").write_text("from workbench.llm.client import LLMUpstreamError\n")
    (agent / "relative.py").write_text("import json\nfrom ..llm.client import LLMRequestBudgetExceeded\n")
    (agent / "absolute.py").write_text("import workbench.llm.client\n")
    (agent / "parent.py").write_text("from workbench.llm import client\n")
    (agent / "fine.py").write_text("from .model import LLMRequestBudgetExceeded\nfrom workbench.llm.config import LLMConfig\n")
    found = list(lint_rules.imports_respect_layer_boundaries(root))
    assert [(v.path, v.line) for v in found] == [
        ("backend/workbench/agent/absolute.py", 1), ("backend/workbench/agent/parent.py", 1),
        ("backend/workbench/agent/relative.py", 2)]
    assert all("workbench.agent.model" in v.message for v in found)


def test_every_restricted_import_says_what_to_use_and_where_it_came_from():
    for boundary in lint_rules.RESTRICTED_IMPORTS:
        assert boundary.message.strip() and boundary.origin.strip()
        assert all(path.startswith(boundary.files) for path in boundary.allow)


def test_context_tools_redirect_run_file_reads_to_the_compiler(tmp_path):
    agent = tmp_path / "backend/workbench/agent"
    tools = agent / "context_tools_support"
    tools.mkdir(parents=True)
    (agent / "context_compiler.py").write_text("path = root / 'artifacts_index.json'\n")
    (tools / "reader.py").write_text(
        "index = read_json(root / 'artifacts_index.json')\n"
        "profile = read_json(root / 'staged/data_profile.json')\n"
        "manifest = read_context_run_manifest(root)\n"
    )

    violations = list(lint_rules.agent_context_run_files_use_the_compiler(tmp_path))
    assert [item.line for item in violations] == [1, 2]
    assert "context_compiler.read_context_artifact_index" in violations[0].message
    assert "context_compiler.read_context_data_profile" in violations[1].message


def test_monkeypatch_stub_signature_catches_the_old_pair_ranks_stub(tmp_path):
    root = _fake_root(tmp_path, "")
    (root / "backend/workbench/native_math.py").write_text(
        "def _pair_ranks(a, b, keys, cache, check_cancel): pass\n"
    )
    tests = root / "tests"
    tests.mkdir()
    (tests / "test_default_path_speedups.py").write_text(
        "from workbench import native_math\n"
        "def test_stats(monkeypatch):\n"
        "    def corrected(a, b, keys, cache, check_cancel): pass\n"
        "    monkeypatch.setattr(native_math, '_pair_ranks', corrected)\n"
        "    monkeypatch.setattr(native_math, '_pair_ranks', lambda *args: None)\n"
        "    monkeypatch.setattr(native_math, '_pair_ranks', lambda matrix, keys, cache, check_cancel: None)\n"
        "    def stale(matrix, keys, cache, check_cancel): pass\n"
        "    monkeypatch.setattr(native_math, '_pair_ranks', stale)\n"
    )

    rule = next((item for item in lint_rules.RULES if item.rule_id == "monkeypatch-stub-signature"), None)
    assert rule is not None
    found = list(rule.check(root))
    assert [violation.line for violation in found] == [6, 8]
    assert all("workbench.native_math._pair_ranks" in violation.message for violation in found)


def test_private_cross_package_import_only_allows_the_frozen_occurrence(tmp_path):
    root = _fake_root(tmp_path, "")
    caller = root / "backend/workbench/http/caller.py"
    caller.parent.mkdir()
    caller.write_text(
        "from workbench.repository.run_repository import _read_manifest\n"
        "from ..repository.run_repository import _read_manifest as _again\n"
        "from ..repository.run_repository import read_manifest\n"
        "from .internal import _helper\n"
    )
    baseline = root / "scripts/lint_baselines/private_imports.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(
        '{"backend/workbench/http/caller.py": {"workbench.repository.run_repository._read_manifest": 1}}\n'
    )

    rule = next((item for item in lint_rules.RULES if item.rule_id == "private-cross-package-imports"), None)
    assert rule is not None
    [violation] = rule.check(root)
    assert violation.line == 2
    assert "export a public name from workbench.repository.run_repository" in violation.message


def test_agents_md_pin_flags_a_policy_edit(tmp_path):
    target = tmp_path / "AGENTS.md"
    target.write_bytes((lint_rules.ROOT / "AGENTS.md").read_bytes())

    rule = next((item for item in lint_rules.RULES if item.rule_id == "agents-md-pinned"), None)
    assert rule is not None
    assert list(rule.check(tmp_path)) == []
    with target.open("ab") as stream:
        stream.write(b"\nAnother rule\n")
    [violation] = rule.check(tmp_path)
    assert violation.path == "AGENTS.md"
    assert "user approval" in violation.message


def test_new_performance_project_roots_must_use_the_retention_owner(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "perf_1m.py").write_text(
        "from workbench.projects import create_project as raw_project\n"
        "from workbench import projects\n"
        "from perf_evidence import create_active_project\n"
        "def family_run(out):\n"
        "    return raw_project(out, 'benchmark')\n"
        "def interactive(out):\n"
        "    raw_project(out, 'timestamped-project')\n"
        "    projects.create_project(out, 'duplicate')\n"
        "def managed(active):\n"
        "    return create_active_project(active)\n"
    )
    (scripts / "perf_new.py").write_text(
        "import workbench.projects as projects\n"
        "def another_run(out):\n"
        "    return projects.create_project(out, 'new-project')\n"
    )
    rule = next((rule for rule in lint_rules.RULES if rule.rule_id == "perf-project-retention-owner"), None)
    assert rule is not None
    violations = list(rule.check(tmp_path))
    assert [(item.path, item.line) for item in violations] == [
        ("scripts/perf_1m.py", 7), ("scripts/perf_1m.py", 8), ("scripts/perf_new.py", 3),
    ]
    assert all("perf_evidence.create_active_project" in item.message
               and "perf_evidence.finalize_active" in item.message for item in violations)
