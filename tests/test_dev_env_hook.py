"""The shared-virtualenv checkout hook (scripts/dev_env/workbench_checkout_hook.py).

A process imports the code of the checkout it belongs to: an explicit
PYTHONPATH, else the checkout its parent recorded, else the checkout it runs
in, else the editable install (the main checkout). The real interpreter
behaviour is exercised with a throwaway site directory, never the shared
virtualenv.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "scripts" / "dev_env" / "workbench_checkout_hook.py"


def _hook():
    spec = importlib.util.spec_from_file_location("workbench_checkout_hook_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checkout(root: Path, name: str) -> Path:
    package = root / name / "backend" / "workbench"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(f"CHECKOUT = {name!r}\n", encoding="utf-8")
    return (root / name / "backend").resolve()


@pytest.fixture()
def tree(tmp_path: Path) -> dict[str, Path]:
    return {
        "main": _checkout(tmp_path, "main"),
        "worktree": _checkout(tmp_path, "worktree"),
        "elsewhere": (tmp_path / "elsewhere").resolve(),
    }


def test_inside_a_worktree_its_backend_goes_ahead_of_the_editable_install(tree) -> None:
    hook = _hook()
    (tree["elsewhere"]).mkdir()
    sys_path = ["", "/lib/python3.14", "/site-packages", str(tree["main"])]
    environ: dict[str, str] = {}

    assert hook.apply(sys_path, environ, tree["worktree"].parent / "backend" / "workbench") == "cwd"
    assert sys_path == ["", "/lib/python3.14", "/site-packages", str(tree["worktree"]), str(tree["main"])]
    assert environ[hook.ENV] == str(tree["worktree"])


def test_outside_any_checkout_the_editable_install_is_used_and_recorded(tree) -> None:
    hook = _hook()
    tree["elsewhere"].mkdir()
    sys_path = ["", "/site-packages", str(tree["main"])]
    environ: dict[str, str] = {}

    assert hook.apply(sys_path, environ, tree["elsewhere"]) == "default"
    assert sys_path == ["", "/site-packages", str(tree["main"])]
    assert environ[hook.ENV] == str(tree["main"])


def test_a_child_in_a_temporary_directory_keeps_its_parents_checkout(tree) -> None:
    hook = _hook()
    tree["elsewhere"].mkdir()
    sys_path = ["", "/site-packages", str(tree["main"])]
    environ = {hook.ENV: str(tree["worktree"])}

    assert hook.apply(sys_path, environ, tree["elsewhere"]) == "inherited"
    assert sys_path[2] == str(tree["worktree"])


def test_an_explicit_pythonpath_is_left_alone(tree) -> None:
    hook = _hook()
    sys_path = ["", str(tree["worktree"]), "/site-packages", str(tree["main"])]
    environ = {"PYTHONPATH": str(tree["worktree"]), hook.ENV: str(tree["main"])}

    assert hook.apply(sys_path, environ, tree["main"]) == "pythonpath"
    assert sys_path == ["", str(tree["worktree"]), "/site-packages", str(tree["main"])]


def test_a_recorded_checkout_that_no_longer_exists_is_replaced(tree) -> None:
    hook = _hook()
    tree["elsewhere"].mkdir()
    environ = {hook.ENV: str(tree["elsewhere"] / "archived" / "backend")}
    sys_path = ["", str(tree["main"])]

    assert hook.apply(sys_path, environ, tree["elsewhere"]) == "default"
    assert environ[hook.ENV] == str(tree["main"])


def test_install_never_raises(monkeypatch) -> None:
    hook = _hook()
    monkeypatch.setattr(hook, "apply", lambda *_a: (_ for _ in ()).throw(RuntimeError("boom")))
    hook.install()


def _site_with_hook(tmp_path: Path, main_backend: Path) -> Path:
    """A site directory laid out as the installer lays out site-packages."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "__editable__.workbench.pth").write_text(f"{main_backend}\n", encoding="utf-8")
    (site / "_workbench_checkout.py").write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
    (site / "zz_workbench_checkout.pth").write_text("import _workbench_checkout\n", encoding="utf-8")
    return site


def _imported_checkout(site: Path, cwd: Path, extra_env: dict[str, str] | None = None) -> str:
    environ = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "WORKBENCH_CHECKOUT_BACKEND"}}
    environ.update(extra_env or {})
    code = f"import site; site.addsitedir({str(site)!r}); import workbench; print(workbench.CHECKOUT)"
    result = subprocess.run([sys.executable, "-S", "-c", code], cwd=cwd, env=environ, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_real_interpreter_follows_the_rules(tree, tmp_path: Path) -> None:
    tree["elsewhere"].mkdir()
    site = _site_with_hook(tmp_path, tree["main"])

    assert _imported_checkout(site, tree["elsewhere"]) == "main"
    assert _imported_checkout(site, tree["worktree"].parent) == "worktree"
    assert _imported_checkout(site, tree["elsewhere"], {"WORKBENCH_CHECKOUT_BACKEND": str(tree["worktree"])}) == "worktree"
    assert _imported_checkout(site, tree["worktree"].parent, {"PYTHONPATH": str(tree["main"])}) == "main"
