"""Which Workbench checkout a Python process in the shared virtualenv imports.

The shared virtualenv has one editable install of Workbench, pointing at the
main checkout (``scripts/install_dev_env.py``), so ``workbench`` and
``uvicorn workbench.api:app`` run the released code from anywhere. Every
development worktree shares that virtualenv, and a process started inside a
worktree must import that worktree's code, never the main checkout's: until
v1.8.12 the install named an old worktree, and subprocess tests silently ran
that version's code.

This module is copied into site-packages as ``_workbench_checkout.py`` and
imported by ``zz_workbench_checkout.pth`` (processed after the editable
install's ``.pth``), so it runs once at interpreter start-up. It decides, in
order:

1. ``PYTHONPATH`` already provides a ``workbench`` package: leave it.
2. The parent process recorded its checkout in ``WORKBENCH_CHECKOUT_BACKEND``
   and it still exists: use it (a test in a worktree that starts a
   subprocess in a temporary directory keeps that worktree's code).
3. The working directory is inside a checkout: use that checkout.
4. Otherwise: the editable install (the main checkout).

and records the result in ``WORKBENCH_CHECKOUT_BACKEND`` for child processes.
Standard library only; any failure leaves the interpreter as it was.
"""

from __future__ import annotations

import os
import sys
from collections.abc import MutableMapping, MutableSequence
from pathlib import Path

ENV = "WORKBENCH_CHECKOUT_BACKEND"


def is_backend(path: Path) -> bool:
    """A directory holding the ``workbench`` package."""
    try:
        return (path / "workbench" / "__init__.py").is_file()
    except OSError:
        return False


def checkout_backend_for(directory: Path) -> Path | None:
    """The ``backend`` of the checkout containing ``directory``, if any."""
    for candidate in (directory, *directory.parents):
        if is_backend(candidate / "backend"):
            return (candidate / "backend").resolve()
    return None


def choose(cwd: Path, environ: MutableMapping[str, str]) -> tuple[Path | None, str]:
    """The backend to put first, and why; ``None`` keeps the interpreter's own choice."""
    for entry in environ.get("PYTHONPATH", "").split(os.pathsep):
        if entry and is_backend(Path(entry)):
            return None, "pythonpath"
    inherited = environ.get(ENV)
    if inherited and is_backend(Path(inherited)):
        return Path(inherited).resolve(), "inherited"
    found = checkout_backend_for(cwd)
    if found is not None:
        return found, "cwd"
    return None, "default"


def apply(sys_path: MutableSequence[str], environ: MutableMapping[str, str], cwd: Path) -> str:
    """Adjust ``sys_path`` and record the choice in ``environ``; returns the reason."""
    backend, reason = choose(cwd, environ)
    if backend is not None:
        resolved = [Path(entry).resolve() if entry else None for entry in sys_path]
        if backend not in resolved:
            # Ahead of the editable install's entry (the first other backend),
            # behind the standard library and site-packages.
            position = next(
                (index for index, entry in enumerate(sys_path) if entry and is_backend(Path(entry))),
                len(sys_path),
            )
            sys_path.insert(position, str(backend))
        environ[ENV] = str(backend)
    elif reason == "default":
        default = next((entry for entry in sys_path if entry and is_backend(Path(entry))), None)
        if default is not None:
            environ[ENV] = str(Path(default).resolve())
    return reason


def install() -> None:
    try:
        apply(sys.path, os.environ, Path.cwd())
    except Exception:  # noqa: BLE001 - start-up must never fail because of this hook
        pass


if __name__ == "_workbench_checkout":
    install()
