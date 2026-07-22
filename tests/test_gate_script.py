import os
import shutil
import subprocess
from pathlib import Path


GATE_SCRIPT = Path(__file__).parents[1] / "scripts" / "gate.sh"
VITE_CONFIG = Path(__file__).parents[1] / "frontend" / "vite.config.ts"


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    path.chmod(0o755)


def _write_fake_python(path: Path, *, name: str, has_pytest: bool) -> None:
    pytest_exit = 0 if has_pytest else 1
    _write_executable(
        path,
        f"""#!/usr/bin/env bash
if [ "${{1:-}}" = "-c" ] && [ "${{2:-}}" = "import pytest" ]; then
  exit {pytest_exit}
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "pytest" ]; then
  printf '%s:%s\\n' '{name}' "$*" >> "$GATE_PYTHON_LOG"
  exit {pytest_exit}
fi
if [ "${{1:-}}" = "scripts/devline_control.py" ] && [ "${{2:-}}" = "verify" ] && [ "${{3:-}}" = "--all" ]; then
  printf '%s:%s\\n' '{name}' "$*" >> "$GATE_PYTHON_LOG"
  exit "${{GATE_DEVLINE_CONTROL_EXIT:-0}}"
fi
exit 0
""",
    )


def _run_gate(
    tmp_path: Path,
    *,
    local_has_pytest: bool,
    common_has_pytest: bool,
    override_has_pytest: bool | None = None,
    mode: str = "--full",
    changed_files: tuple[str, ...] = (),
    devline_control_exit: int = 0,
    shared_modules: bool = False,
    local_modules: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str], dict[str, Path]]:
    worktree = tmp_path / "worktree"
    common_checkout = tmp_path / "common"
    local_python = worktree / ".venv" / "bin" / "python"
    common_python = common_checkout / ".venv" / "bin" / "python"
    override_python = tmp_path / "override" / "bin" / "python"
    python_log = tmp_path / "python.log"
    fake_bin = tmp_path / "bin"

    (worktree / "scripts").mkdir(parents=True)
    (worktree / "frontend").mkdir()
    shutil.copy2(GATE_SCRIPT, worktree / "scripts" / "gate.sh")
    _write_fake_python(local_python, name="local", has_pytest=local_has_pytest)
    _write_fake_python(common_python, name="common", has_pytest=common_has_pytest)
    if override_has_pytest is not None:
        _write_fake_python(
            override_python,
            name="override",
            has_pytest=override_has_pytest,
        )

    _write_executable(
        fake_bin / "git",
        f"""#!/usr/bin/env bash
if [ "${{1:-}} ${{2:-}}" = "rev-parse --git-common-dir" ]; then
  printf '%s\\n' '{common_checkout / ".git"}'
fi
if [ "${{1:-}} ${{2:-}}" = "diff --name-only" ] || [ "${{1:-}} ${{2:-}} ${{3:-}}" = "diff --cached --name-only" ] || [ "${{1:-}} ${{2:-}}" = "ls-files --others" ]; then
  printf '%s' "${{GATE_CHANGED_FILES:-}}"
fi
exit 0
""",
    )
    _write_executable(fake_bin / "npx", "#!/usr/bin/env bash\nexit 0\n")

    # The shared-dependency preflight only engages when the common checkout
    # actually has an install to borrow.
    shared_path = common_checkout / "frontend" / "node_modules"
    if shared_modules:
        shared_path.mkdir(parents=True)
        (shared_path / "marker").write_text("shared", encoding="utf-8")
    local_path = worktree / "frontend" / "node_modules"
    if local_modules == "real":
        local_path.mkdir(parents=True)
        (local_path / "marker").write_text("duplicate", encoding="utf-8")
    elif local_modules == "link":
        local_path.symlink_to(shared_path)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["GATE_PYTHON_LOG"] = str(python_log)
    env["GATE_CHANGED_FILES"] = "\n".join(changed_files)
    env["GATE_DEVLINE_CONTROL_EXIT"] = str(devline_control_exit)
    if override_has_pytest is not None:
        env["WORKBENCH_PYTHON"] = str(override_python)
    else:
        env.pop("WORKBENCH_PYTHON", None)

    result = subprocess.run(
        ["bash", "scripts/gate.sh", mode],
        cwd=worktree,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    invocations = python_log.read_text().splitlines() if python_log.exists() else []
    paths = {
        "local": local_python,
        "common": common_python,
        "override": override_python,
    }
    return result, invocations, paths


def test_gate_script_exposes_explicit_quick_and_full_modes() -> None:
    source = GATE_SCRIPT.read_text()

    assert "--quick" in source
    assert "--full" in source
    assert "--help" in source


def test_gate_prefers_explicit_workbench_python_override(tmp_path: Path) -> None:
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
        override_has_pytest=True,
    )

    assert result.returncode == 0, result.stderr
    assert len(invocations) == 2
    assert all(line.startswith("override:") for line in invocations)


def test_gate_uses_local_venv_when_it_can_import_pytest(tmp_path: Path) -> None:
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
    )

    assert result.returncode == 0, result.stderr
    assert len(invocations) == 2
    assert all(line.startswith("local:") for line in invocations)


def test_gate_falls_back_to_common_checkout_venv(tmp_path: Path) -> None:
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=False,
        common_has_pytest=True,
    )

    assert result.returncode == 0, result.stderr
    assert len(invocations) == 2
    assert all(line.startswith("common:") for line in invocations)


def test_gate_skips_unusable_override_before_local_venv(tmp_path: Path) -> None:
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
        override_has_pytest=False,
    )

    assert result.returncode == 0, result.stderr
    assert len(invocations) == 2
    assert all(line.startswith("local:") for line in invocations)


def test_gate_fails_clearly_without_a_pytest_capable_python(tmp_path: Path) -> None:
    result, invocations, paths = _run_gate(
        tmp_path,
        local_has_pytest=False,
        common_has_pytest=False,
    )

    assert result.returncode == 1
    assert invocations == []
    assert "No pytest-capable Python interpreter found" in result.stderr
    assert str(paths["local"]) in result.stderr
    assert str(paths["common"]) in result.stderr


def test_quick_mode_has_a_targeted_agent_llm_suite() -> None:
    source = GATE_SCRIPT.read_text()

    assert "tests/test_agent_*.py" in source
    assert "tests/test_llm_*.py" in source


def test_quick_mode_has_a_conservative_full_backend_fallback() -> None:
    source = GATE_SCRIPT.read_text()

    assert "QUICK backend full fallback" in source


def test_quick_mode_covers_request_independent_rerun_service_slice() -> None:
    source = GATE_SCRIPT.read_text()

    assert "backend/workbench/services/rerun_service.py" in source
    assert "backend/workbench/lineage/run_inputs.py" in source
    assert "tests/test_rerun_service.py" in source


def test_quick_mode_covers_known_v17_rerun_lineage_surface() -> None:
    source = GATE_SCRIPT.read_text()

    assert "backend/workbench/services/run_service.py" in source
    assert "backend/workbench/services/results_service.py" in source
    assert "backend/workbench/lineage/node_write_validation.py" in source
    assert "tests/test_api_run_params.py" in source
    assert "tests/test_node_write_validation.py" in source


def test_quick_mode_keeps_agent_http_wiring_in_the_focused_surface() -> None:
    source = GATE_SCRIPT.read_text()

    assert "backend/workbench/http/agent_routes.py" in source
    assert "backend/workbench/app.py" in source


def test_quick_mode_keeps_llm_provider_settings_in_the_focused_surface() -> None:
    source = GATE_SCRIPT.read_text()

    assert "backend/workbench/http/llm_routes.py" in source
    assert "backend/workbench/llm/provider_store.py" in source


def test_quick_mode_runs_gate_contract_tests_when_the_gate_changes() -> None:
    source = GATE_SCRIPT.read_text()

    assert "run_gate_script_tests" in source


def test_quick_mode_verifies_formal_fms_changes_and_fails_closed(tmp_path: Path) -> None:
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
        mode="--quick",
        changed_files=("backend/workbench/development_control/events.py",),
        devline_control_exit=2,
    )

    assert result.returncode == 1
    assert any(
        line.startswith("local:scripts/devline_control.py verify --all")
        for line in invocations
    )
    assert "QUICK formal development-control verification" in result.stdout


def test_quick_mode_verifies_formal_agent_control_files(tmp_path: Path) -> None:
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
        mode="--quick",
        changed_files=(".agent/development-control/global-rules.json",),
    )

    assert result.returncode == 0, result.stderr
    assert any(
        line.startswith("local:scripts/devline_control.py verify --all")
        for line in invocations
    )


def test_quick_mode_does_not_replay_fms_history_for_product_only_change(tmp_path: Path) -> None:
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
        mode="--quick",
        changed_files=("backend/workbench/engine/context.py",),
    )

    assert result.returncode == 0, result.stderr
    assert not any("scripts/devline_control.py verify --all" in line for line in invocations)


def test_vite_proxy_defaults_to_the_documented_backend_port() -> None:
    source = VITE_CONFIG.read_text()

    assert 'process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000"' in source


def test_gate_refuses_a_worktree_that_duplicated_the_shared_install(
    tmp_path: Path,
) -> None:
    """Three worktrees each carried a full copy of frontend/node_modules.

    All three had the same package-lock hash as the main checkout, so the
    431 MB they occupied bought nothing. link-shared-deps.sh had existed for
    this since v1.6.6; nothing enforced it, so nothing stopped an `npm install`
    from happening inside a worktree.
    """
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
        shared_modules=True,
        local_modules="real",
    )

    assert result.returncode == 3, result.stderr
    assert "REFUSING" in result.stderr
    assert "must not install their own" in result.stderr
    # The fix has to be runnable straight from the message.
    assert "link-shared-deps.sh" in result.stderr
    # Refused before doing any work.
    assert invocations == []


def test_gate_accepts_a_worktree_linked_to_the_shared_install(tmp_path: Path) -> None:
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
        shared_modules=True,
        local_modules="link",
    )

    assert result.returncode == 0, result.stderr
    assert "REFUSING" not in result.stderr
    assert "NOTE: this worktree has no" not in result.stderr
    assert invocations, "a linked worktree should have gone on to run the suite"


def test_gate_points_an_unlinked_worktree_at_the_shared_install_without_blocking(
    tmp_path: Path,
) -> None:
    """Missing costs nothing to leave alone; duplicated is the waste itself."""
    result, invocations, _ = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
        shared_modules=True,
        local_modules=None,
    )

    assert result.returncode == 0, result.stderr
    assert "NOTE: this worktree has no" in result.stderr
    assert "REFUSING" not in result.stderr
    assert invocations


def test_gate_does_not_police_a_worktree_that_carries_its_own_venv(
    tmp_path: Path,
) -> None:
    """A local .venv is a supported configuration, not duplication to refuse.

    The first version of this preflight checked .venv too and broke the Python
    resolution-order tests above. It was never the waste anyway: the worktrees
    that duplicated node_modules had no .venv at all.
    """
    result, invocations, paths = _run_gate(
        tmp_path,
        local_has_pytest=True,
        common_has_pytest=True,
        shared_modules=True,
        local_modules="link",
    )

    assert paths["local"].exists(), "the harness should have built a local venv"
    assert result.returncode == 0, result.stderr
    assert "REFUSING" not in result.stderr
    assert all(line.startswith("local:") for line in invocations)
