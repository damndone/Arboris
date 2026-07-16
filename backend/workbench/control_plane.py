"""Supported deployment boundary for Agent operation control-plane state."""

from __future__ import annotations

import os


class SingleWorkerConfigurationError(RuntimeError):
    """Raised when the JSONL control plane is configured for multiple workers."""


CONTROL_PLANE_MODE = "single_worker"
_WORKER_ENV_NAMES = ("WORKBENCH_WORKERS", "WEB_CONCURRENCY")


def validate_control_plane() -> dict[str, int | str]:
    """Validate the deployment contract before the app starts serving.

    Agent operation claims, leases, and active-head records currently use the
    project-local JSONL/file-lock control plane. It is intentionally a
    single-worker deployment contract; a future transactional control plane
    must replace this guard before multi-worker support is advertised.
    """

    mode = os.getenv("WORKBENCH_CONTROL_PLANE_MODE", CONTROL_PLANE_MODE).strip()
    if mode != CONTROL_PLANE_MODE:
        raise SingleWorkerConfigurationError(
            "WORKBENCH_CONTROL_PLANE_MODE must be 'single_worker'; "
            "multi-worker control-plane storage is not supported"
        )

    for env_name in _WORKER_ENV_NAMES:
        raw = os.getenv(env_name)
        if raw is None or raw.strip() == "":
            continue
        try:
            workers = int(raw)
        except ValueError as exc:
            raise SingleWorkerConfigurationError(
                f"{env_name} must be 1 for the single_worker control plane"
            ) from exc
        if workers != 1:
            raise SingleWorkerConfigurationError(
                f"{env_name}={workers} is incompatible with the single_worker "
                "control plane; use one backend worker"
            )

    return {"mode": CONTROL_PLANE_MODE, "workers": 1}


def control_plane_capability() -> dict[str, str | int]:
    """Return the public deployment fact without creating project storage."""

    return {"control_plane_mode": CONTROL_PLANE_MODE, "workers": 1}
