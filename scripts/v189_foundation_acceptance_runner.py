#!/usr/bin/env python3
"""Run fixed, candidate-bound v1.8.9 deterministic acceptance suites.

The runner is intentionally conservative: it never changes the candidate,
never writes evidence inside it, never calls a provider in deterministic mode,
and never labels provider mode successful without an explicitly authorized
provider adapter.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import uuid

from workbench.qa.v189_foundation_acceptance import (
    AcceptanceStatus,
    CandidateIdentityError,
    CandidateIdentityV1,
    candidate_integrity_status,
    inspect_candidate,
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
    """The acceptance invocation is invalid or cannot be recorded safely."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_node() -> Path:
    raw = shutil.which("node")
    if raw is None:
        raise RunnerError("trusted node executable is unavailable")
    path = Path(raw)
    try:
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except OSError as error:
        raise RunnerError("trusted node executable is unavailable") from error
    if not stat.S_ISREG(info.st_mode) or not os.access(resolved, os.X_OK):
        raise RunnerError("trusted node executable is not executable")
    return resolved


def _regular_file(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def _ensure_sidecar_root(output_dir: Path, candidate: CandidateIdentityV1) -> Path:
    output_dir = Path(output_dir).resolve()
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
    base: dict[str, object] = {
        "name": name,
        "command": list(command),
        "cwd": str(cwd),
    }
    if missing:
        return {
            **base,
            "status": AcceptanceStatus.BLOCKED.value,
            "reason": "required acceptance artifact missing",
            "missing": missing,
        }
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
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            **base,
            "status": AcceptanceStatus.BLOCKED.value,
            "reason": f"fixed command unavailable or timed out: {type(error).__name__}",
        }
    return {
        **base,
        "status": (
            AcceptanceStatus.PASS.value
            if completed.returncode == 0
            else AcceptanceStatus.FAIL.value
        ),
        "returncode": completed.returncode,
        "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
        "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
    }


def _overall_status(results: list[Mapping[str, object]], *, provider_requested: bool) -> str:
    statuses = [str(result.get("status")) for result in results]
    if any(status == AcceptanceStatus.FAIL.value for status in statuses):
        return AcceptanceStatus.FAIL.value
    if any(status == AcceptanceStatus.BLOCKED.value for status in statuses):
        return AcceptanceStatus.BLOCKED.value
    if provider_requested:
        return AcceptanceStatus.NOT_VERIFIED.value
    return AcceptanceStatus.PASS.value



_CANDIDATE_INVENTORY_SCRIPT = r'''
import json
from workbench.evidence.coverage import build_consumer_coverage
from workbench.providers.catalog import load_builtin_catalog
from workbench.qa.v189_foundation_acceptance import live_acceptance_matrix

catalog = load_builtin_catalog()
coverage = build_consumer_coverage(catalog)
matrix = live_acceptance_matrix()
print(json.dumps({
    "catalog_digest": catalog.digest,
    "provider_ids": list(catalog.provider_ids),
    "coverage_digest": coverage.coverage_digest,
    "coverage_rows": len(coverage.rows),
    "coverage_covered": coverage.covered_count,
    "coverage_blocked": coverage.blocked_count,
    "matrix": matrix.to_dict(),
}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
'''


def _candidate_inventory(
    identity: CandidateIdentityV1,
    environment: dict[str, str],
) -> dict[str, object]:
    """Derive catalog/coverage/matrix facts inside the candidate interpreter."""

    command = (str(identity.interpreter), "-c", _CANDIDATE_INVENTORY_SCRIPT)
    try:
        completed = subprocess.run(
            command,
            cwd=identity.worktree,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RunnerError(f"candidate catalog discovery unavailable: {type(error).__name__}") from error
    if completed.returncode != 0:
        raise RunnerError(
            "candidate catalog discovery failed: "
            + (completed.stderr.strip()[-500:] or f"returncode={completed.returncode}")
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RunnerError("candidate catalog discovery returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise RunnerError("candidate catalog discovery returned a non-object")
    return payload


def run_acceptance(
    *,
    candidate_worktree: Path,
    candidate_sha: str,
    output_dir: Path,
    deterministic: bool,
    provider_requested: bool,
) -> tuple[Path, dict[str, object]]:
    if deterministic == provider_requested:
        raise RunnerError("select exactly one of --deterministic or --provider")
    identity = inspect_candidate(candidate_worktree, candidate_sha, interpreter=sys.executable)
    sidecar_root = _ensure_sidecar_root(output_dir, identity)

    environment = dict(os.environ)
    environment.update(
        {
            "LC_ALL": "C",
            "LANG": "C",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(identity.backend_source),
            "V189_CANDIDATE_SHA": identity.commit_sha,
            "V189_PROVIDER_CALLED": "false",
        }
    )
    inventory = _candidate_inventory(identity, environment)
    results: list[dict[str, object]] = []
    node_path: Path | None = None
    if deterministic:
        backend_paths = tuple(identity.worktree / item for item in BACKEND_TESTS)
        backend_command = (
            str(identity.interpreter),
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            *BACKEND_TESTS,
            "-q",
            "--disable-warnings",
        )
        results.append(
            _command_result(
                "candidate_backend",
                backend_command,
                identity.worktree,
                environment,
                backend_paths,
            )
        )

        frontend_root = identity.worktree / "frontend"
        frontend_environment = dict(environment)
        frontend_environment["V189_CANDIDATE_FRONTEND"] = str(identity.frontend_source)
        try:
            node_path = _trusted_node()
        except RunnerError as error:
            results.append(
                {
                    "name": "frontend_evaluation",
                    "status": AcceptanceStatus.BLOCKED.value,
                    "reason": str(error),
                }
            )
        if node_path is not None:
            vitest = frontend_root / "node_modules/vitest/vitest.mjs"
            frontend_paths = tuple(frontend_root / item for item in FRONTEND_TESTS)
            frontend_command = (str(node_path), str(vitest), "run", *FRONTEND_TESTS)
            results.append(
                _command_result(
                    "frontend_evaluation",
                    frontend_command,
                    frontend_root,
                    frontend_environment,
                    (vitest, *frontend_paths),
                )
            )
    else:
        results.append(
            {
                "name": "provider_evaluation",
                "status": AcceptanceStatus.NOT_VERIFIED.value,
                "reason": "provider adapter and explicit authorization are not configured",
                "provider_called": False,
            }
        )

    results.append(
        {
            "name": "candidate_post_run_integrity",
            **candidate_integrity_status(
                identity.worktree,
                identity.commit_sha,
                interpreter=identity.interpreter,
            ),
        }
    )
    provider = provider_mode_status(
        provider_requested=provider_requested,
        provider_configured=False,
    )
    run_id = f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:12]}"
    run_dir = sidecar_root.resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema_version": "workbench.v1.8.9.foundation-acceptance.v1",
        "run_id": run_id,
        "candidate_sha": identity.commit_sha,
        "candidate_parent_sha": identity.parent_sha,
        "candidate_worktree": str(identity.worktree),
        "evaluator": {
            "runner_path": str(Path(__file__).resolve()),
            "runner_sha256": _sha256_file(Path(__file__).resolve()),
        },
        "environment": {
            "python": sys.version,
            "interpreter": str(identity.interpreter),
            "node": str(node_path) if node_path is not None else None,
            "provider_called": False,
        },
        "catalog": {
            "digest": inventory["catalog_digest"],
            "provider_ids": inventory["provider_ids"],
        },
        "coverage": {
            "digest": inventory["coverage_digest"],
            "rows": inventory["coverage_rows"],
            "covered": inventory["coverage_covered"],
            "blocked": inventory["coverage_blocked"],
        },
        "matrix": inventory["matrix"],
        "product_path": results,
        "provider": {
            "status": provider.status.value,
            "provider_called": provider.provider_called,
            "reason": provider.reason,
        },
        "browser_status": AcceptanceStatus.NOT_VERIFIED.value,
        "release_status": AcceptanceStatus.NOT_VERIFIED.value,
        "status": _overall_status(
            [
                result
                for result in results
                if result.get("name") != "provider_evaluation"
            ],
            provider_requested=provider_requested,
        ),
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
        print(
            json.dumps(
                {"status": AcceptanceStatus.BLOCKED.value, "reason": str(error)},
                sort_keys=True,
            )
        )
        return 2
    print(
        json.dumps(
            {
                "run_dir": str(run_dir),
                "status": manifest["status"],
                "candidate_sha": manifest["candidate_sha"],
            },
            sort_keys=True,
        )
    )
    return 0 if manifest["status"] == AcceptanceStatus.PASS.value else 2


if __name__ == "__main__":
    raise SystemExit(main())
