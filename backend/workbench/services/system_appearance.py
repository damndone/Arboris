"""Resolve the local Workbench host's native light/dark appearance.

Browsers normally expose the user's choice through ``prefers-color-scheme``.
Embedded browser hosts can override that signal with the host application's
theme, so a loopback Workbench may need a bounded native projection instead.
Unsupported platforms deliberately return ``None`` and let the browser remain
the authority.
"""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Callable
from typing import Literal

Theme = Literal["dark", "light"]
AppearanceProjection = dict[str, Theme | str | None]
Runner = Callable[..., subprocess.CompletedProcess[str]]

_DARWIN_APPEARANCE_COMMAND = [
    "/usr/bin/defaults",
    "read",
    "NSGlobalDomain",
    "AppleInterfaceStyle",
]


def detect_system_appearance(
    *,
    system_name: str | None = None,
    run: Runner = subprocess.run,
) -> AppearanceProjection:
    """Return a bounded native projection or a browser-fallback marker."""

    if (system_name or platform.system()) != "Darwin":
        return {"theme": None, "source": "browser"}

    try:
        completed = run(
            _DARWIN_APPEARANCE_COMMAND,
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
            shell=False,
            env={"LC_ALL": "C", "LANG": "C", "PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError):
        return {"theme": None, "source": "browser"}

    if completed.returncode == 0 and completed.stdout.strip().lower() == "dark":
        return {"theme": "dark", "source": "darwin-native"}
    if completed.returncode == 1 and "does not exist" in completed.stderr.lower():
        return {"theme": "light", "source": "darwin-native"}
    return {"theme": None, "source": "browser"}
