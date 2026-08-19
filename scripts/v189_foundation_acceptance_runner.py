#!/usr/bin/env python3
"""Run the fixed, candidate-bound v1.8.9 Foundation acceptance suites."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from workbench.qa.v189_foundation_acceptance import (
    AcceptanceStatus,
    CandidateIdentityError,
    CandidateIdentityV1,
    inspect_candidate,
    live_acceptance_matrix,
    provider_mode_status,
    write_sidecar_once,
)


BACKEND_TESTS = (
    "tests/test_v189_agent_notebook_cutover.py",
    "tests/test_v189_artifact_integrity.py",
    "tests/test_v189_consumer_projection.py",
)
FRONTEND_TESTS = (
    "src/lineage/LineageRouteContainer.v189.test.tsx",
    "src/notebook/NotebookRouteView.v189.test.tsx",
    "src/report/ReportView.integration-v189.test.tsx",
    "src/evaluation/v189/status.test.ts",
)


class RunnerError(RuntimeError):
    pass


def _trusted_node() -> Path:
    for raw in ("/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"):
        path = Path(raw)
        try:
            resolved = path.resolve(strict=True)
            if resolved.is_file() and os.access(resolved, os.X_OK):
                return resolved
        except OSError:
            continue
    raise RunnerError("trusted node executable is unavailable")


def _regular_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def _ensure_sidecar_root(output_dir: Path, candidate: CandidateIdentityV1) -> Path:
    output_dir = output_dir.resolve()
    try:
        output_dir.relative_to(candidate.worktree)
    except ValueError:
        return output_dir
    raise RunnerError("output-dir must be outside the candidate worktree")


def _command_result(
    name: str,
    command: tuple[str, ...],
    cwd: Path,
    environment: dict[str, str],
    required_files: tuple[Path, ...],
) -> dict[str, object]:
    missing = [str(path) for path in required_files if not _regular_file(path)]
    base: dict[str, object] = {"name": name, "command": list(command), "cwd": str(cwd)}
    if missing:
        return {**base, "status": AcceptanceStatus.BLOCKED.value, "reason": "required acceptance artifact missing", "missing": missing}
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {**base, "status": AcceptanceStatus.BLOCKED.value, "reason": f"fixed command unavailable or timed out: {error.__class__.__name__}"}
    return {
        **base,
        "status": AcceptanceStatus.PASS.value if completed.returncode == 0 else AcceptanceStatus.FAIL.value,
        "returncode": completed.returncode,
        "stdout_sha256": __import__("hashlib").sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": __import__("hashlib").sha256(completed.stderr.encode()).hexdigest(),
    }


def run_acceptance(
    *,
    candidate_worktree: Path,
    candidate_sha: str,
    output_dir: Path,
    deterministic: bool,
    provider_requested: bool,
) -> tuple[Path, dict[str, object]]:
    if not deterministic and not provider_requested:
        raise RunnerError("select --deterministic or --provider")
    identity = inspect_candidate(candidate_worktree, candidate_sha, interpreter=sys.executable)
    sidecar_root = _ensure_sidecar_root(output_dir, identity)
    matrix = live_acceptance_matrix()
    provider = provider_mode_status(provider_requested=provider_requested, provider_configured=False)

    environment = dict(os.environ)
    environment.update({
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(identity.backend_source),
        "V189_CANDIDATE_SHA": identity.commit_sha,
    })
    backend_paths = tuple(identity.worktree / item for item in BACKEND_TESTS)
    backend_command = (str(identity.interpreter), "-m", "pytest", *BACKEND_TESTS, "-q", "--disable-warnings")
    results = [
        _command_result("candidate_backend", backend_command, identity.worktree, environment, backend_paths)
    ]

    frontend_root = identity.worktree / "frontend"
    frontend_environment = dict(environment)
    frontend_environment["V189_CANDIDATE_FRONTEND"] = str(identity.frontend_source)
    node = None
    try:
        node = _trusted_node()
    except RunnerError as error:
        results.append({"name": "frontend_evaluation", "status": AcceptanceStatus.BLOCKED.value, "reason": str(error)})
    if node is not None:
        vitest = frontend_root / "node_modules/vitest/vitest.mjs"
        frontend_paths = tuple(frontend_root / item for item in FRONTEND_TESTS)
        frontend_command = (str(node), str(vitest), "run", *FRONTEND_TESTS)
        results.append(_command_result("frontend_evaluation", frontend_command, frontend_root, frontend_environment, (vitest, *frontend_paths)))

    statuses = [str(result.get("status")) for result in results]
    if any(status == AcceptanceStatus.FAIL.value for status in statuses):
        overall = AcceptanceStatus.FAIL.value
    elif any(status == AcceptanceStatus.BLOCKED.value for status in statuses):
        overall = AcceptanceStatus.BLOCKED.value
    else:
        overall = AcceptanceStatus.PASS.value
    if provider_requested:
        overall = AcceptanceStatus.NOT_VERIFIED.value if overall == AcceptanceStatus.PASS.value else overall

    run_id = f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:12]}"
    run_dir = sidecar_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "workbench.v1.8.9.foundation-acceptance.v1",
        "run_id": run_id,
        "candidate_sha": identity.commit_sha,
        "candidate_parent_sha": identity.parent_sha,
        "candidate_worktree": str(identity.worktree),
        "matrix": matrix.to_dict(),
        "product_path": results,
        "provider": {
            "status": provider.status.value,
            "provider_called": provider.provider_called,
            "reason": provider.reason,
        },
        "browser_status": AcceptanceStatus.NOT_VERIFIED.value,
        "release_status": AcceptanceStatus.NOT_VERIFIED.value,
        "status": overall,
    }
    write_sidecar_once(run_dir / "manifest.json", manifest)
    return run_dir, manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-worktree", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--deterministic", action="store_true")
    mode.add_argument("--provider", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        run_dir, manifest = run_acceptance(
            candidate_worktree=args.candidate_worktree,
            candidate_sha=args.candidate_sha,
            output_dir=args.output_dir,
            deterministic=args.deterministic,
            provider_requested=args.provider,
        )
    except (CandidateIdentityError, RunnerError, ValueError) as error:
        print(json.dumps({"status": AcceptanceStatus.BLOCKED.value, "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps({"run_dir": str(run_dir), "status": manifest["status"], "candidate_sha": manifest["candidate_sha"]}, sort_keys=True))
    return 0 if manifest["status"] == AcceptanceStatus.PASS.value else 2


if __name__ == "__main__":
    raise SystemExit(main())

