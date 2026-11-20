"""One evidence key for a gate or benchmark run: what was tested, where, and against what.

2026-11-06 risk review, finding 11: the gate summary recorded only HEAD, so the same HEAD
with different uncommitted edits, another dependency set or another native build produced
evidence that looked the same. The key here covers

- the source tree as it is on disk: every tracked and untracked-not-ignored file, so staged,
  unstaged and new files all count (checked again at the end of a run);
- the interpreter, OS and architecture, and every installed distribution, compared with
  ``constraints/python-environment.lock``;
- dependency locks (pyproject, npm, Cargo) and the native build receipts;
- the test selection, input hashes and threshold version a caller passes in.

Two runs share ``key_sha256`` only when all of these agree. Stdlib only: the gate calls it
with the system ``python3`` before any virtualenv is chosen.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

SCHEMA_VERSION = "workbench.evidence-key/v1"
LOCK_PATH = Path("constraints/python-environment.lock")
DEPENDENCY_LOCKS = ("pyproject.toml", "frontend/package.json", "frontend/package-lock.json",
                    "native/engine/Cargo.lock", "native/kernels/Cargo.lock",
                    "native/quant_replay/Cargo.lock", "native/time_series/Cargo.lock")

_ENVIRONMENT_PROBE = r"""
import importlib.metadata as metadata, json, platform, sys
seen = {}
for distribution in metadata.distributions():
    name = (distribution.metadata["Name"] or "").lower().replace("_", "-")
    if name and name not in seen:
        direct = distribution.read_text("direct_url.json")
        seen[name] = {"version": distribution.version, **({"direct_url": json.loads(direct)} if direct else {})}
print(json.dumps({
    "executable": sys.executable, "version": sys.version, "implementation": sys.implementation.name,
    "prefix": sys.prefix, "base_prefix": sys.base_prefix,
    "os": platform.system(), "os_release": platform.release(), "mac_ver": platform.mac_ver()[0],
    "machine": platform.machine(), "distributions": dict(sorted(seen.items())),
}))
"""

_NATIVE_PROBE = r"""
import json, sys
from pathlib import Path
from workbench.native_build import MODULES, variants, verify_build
repo = Path(sys.argv[1])
receipts = {}
for name, (output, *_) in MODULES.items():
    for variant in variants(repo / "native" / name):
        try:
            record = verify_build(repo / "native" / name, repo / "local" / output, variant=variant)
            receipts[f"{name}:{variant}"] = {"build_identity_sha256": record.get("build_identity_sha256")}
        except Exception as error:
            receipts[f"{name}:{variant}"] = {"error": f"{type(error).__name__}: {error}"}
print(json.dumps(receipts))
"""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(["git", *arguments], cwd=repo, capture_output=True, check=True).stdout


def source_tree(repo: Path, exclude: tuple[str, ...] = ()) -> dict:
    """Digest of the working tree as tested, not of HEAD; ``exclude`` names a run's own output prefixes."""
    paths = sorted({path for path in _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
                    .decode("utf-8", "surrogateescape").split("\0") if path and not path.startswith(exclude)})
    digest = hashlib.sha256()
    missing = 0
    for relative in paths:
        path = repo / relative
        if path.is_symlink():
            entry = "link:" + _sha256_bytes(os.readlink(path).encode("utf-8", "surrogateescape"))
        elif path.is_file():
            entry = "file:" + file_sha256(path)
        else:
            entry, missing = "missing", missing + 1
        digest.update(f"{relative}\0{entry}\n".encode("utf-8", "surrogateescape"))
    status = _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=False)
    return {"head": head.stdout.strip() if head.returncode == 0 else None, "sha256": digest.hexdigest(),
            "files": len(paths), "missing_files": missing, "dirty": bool(status),
            "status_sha256": _sha256_bytes(status)}


def _local_directory(entry: dict) -> bool:
    return "dir_info" in entry.get("direct_url", {})


def read_lock(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, _, version = line.partition("==")
            pins[name.strip().lower().replace("_", "-")] = version.strip()
    return pins


def environment(python: str | None, repo: Path) -> dict:
    """Interpreter, platform and installed distributions of the interpreter that ran the tests."""
    if not python:
        return {"error": "no_test_interpreter"}
    done = subprocess.run([python, "-I", "-c", _ENVIRONMENT_PROBE], capture_output=True, text=True, check=False)
    if done.returncode:
        return {"python": python, "error": done.stderr.strip()[-800:]}
    try:
        probe = json.loads(done.stdout)
    except ValueError:
        return {"python": python, "error": "environment_probe_output_not_json"}
    installed = {name: entry["version"] for name, entry in probe["distributions"].items()
                 if not _local_directory(entry)}  # a local/editable install is identified by its tree
    probe["distributions_sha256"] = canonical_sha256(probe["distributions"])
    lock = repo / LOCK_PATH
    if lock.is_file():
        pinned = read_lock(lock)
        probe["lock"] = {"path": str(LOCK_PATH), "sha256": file_sha256(lock),
                         "missing": sorted(set(pinned) - set(installed)),
                         "unlisted": sorted(set(installed) - set(pinned)),
                         "different": {name: {"locked": pinned[name], "installed": installed[name]}
                                       for name in sorted(set(pinned) & set(installed))
                                       if pinned[name] != installed[name]}}
        probe["lock"]["matches"] = not (probe["lock"]["missing"] or probe["lock"]["unlisted"]
                                        or probe["lock"]["different"])
    else:
        probe["lock"] = {"path": str(LOCK_PATH), "matches": False, "error": "lock_missing"}
    return probe


def native_receipts(python: str | None, repo: Path) -> dict:
    if not python or not (repo / "backend/workbench/native_build.py").is_file():
        return {"error": "no_test_interpreter" if not python else "no_native_build_module"}
    done = subprocess.run([python, "-I", "-c", f"import sys; sys.path.insert(0, {str(repo / 'backend')!r})\n"
                           + _NATIVE_PROBE, str(repo)], capture_output=True, text=True, check=False)
    if done.returncode:
        return {"error": done.stderr.strip()[-800:]}
    try:
        receipts = json.loads(done.stdout)
    except ValueError:
        return {"error": "native_probe_output_not_json"}
    failed = sorted(name for name, receipt in receipts.items() if "error" in receipt)
    return {**receipts, **({"error": "unverified native builds: " + ", ".join(failed)} if failed else {})}


def tools() -> dict:
    found = {}
    for name in ("node", "cargo", "rustc", "c++"):
        path = shutil.which(name)
        if path:
            done = subprocess.run([path, "--version"], capture_output=True, text=True, check=False)
            found[name] = (done.stdout or done.stderr).strip().splitlines()[0] if done.returncode == 0 else None
    return found


def evidence_key(repo: Path, *, python: str | None, scope: str, test_selection=None, inputs=None,
                 thresholds=None, tree: dict | None = None, exclude: tuple[str, ...] = ()) -> dict:
    """The full identity of one run; ``key_sha256`` changes when any part changes."""
    repo = repo.resolve()
    key = {
        "schema_version": SCHEMA_VERSION, "scope": scope,
        "source_tree": tree or source_tree(repo, exclude),
        "dependency_locks": {name: file_sha256(repo / name) if (repo / name).is_file() else None
                             for name in DEPENDENCY_LOCKS},
        "environment": environment(python, repo),
        "native_builds": native_receipts(python, repo),
        "tools": tools(),
        "driver_python": {"executable": sys.executable, "version": sys.version, "machine": platform.machine()},
        "test_selection": test_selection, "inputs": inputs, "thresholds": thresholds,
    }
    stable = {**key, "environment": {k: v for k, v in key["environment"].items() if k != "lock"}}
    key["key_sha256"] = canonical_sha256(stable)
    return key


def write_lock(python: str, repo: Path) -> Path:
    """Pin every distribution the accepted environment holds (the project itself excluded)."""
    probe = environment(python, repo)
    if "error" in probe:
        raise SystemExit(probe["error"])
    lines = ["# Installed distributions of the accepted shared environment; written by",
             "# scripts/evidence_identity.py lock. Install with: pip install -c this-file ...",
             f"# python {probe['version'].split()[0]} {probe['os']} {probe['machine']}"]
    for name, entry in probe["distributions"].items():
        if not _local_directory(entry):
            lines.append(f"{name}=={entry['version']}")
    path = repo / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


if __name__ == "__main__":
    operation, *arguments = sys.argv[1:]
    if operation == "lock":
        print(write_lock(arguments[0], Path.cwd()))
    elif operation == "key":
        print(json.dumps(evidence_key(Path.cwd(), python=arguments[0], scope=arguments[1]), indent=2))
    else:
        raise SystemExit(f"unknown operation: {operation}")
