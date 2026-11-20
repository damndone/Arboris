"""Offline build identity shared by native builders, admission checks and the fast loader.

A manifest is emitted only after a successful build of an unchanged input snapshot. Old
unrecorded binaries are never adopted. Runtime callers verify once before loading and cache
the loaded library; only explicit build/check commands require the compiler to be installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import struct
import subprocess
import sys
import sysconfig
import tempfile

SCHEMA_VERSION = 2
# Output directory, C++ source / Rust crate, Python module / Rust library, exported ABI.
MODULES = {
    "ar_exact": ("native-ar", "ar_exact.cpp", "_ar_exact", 2),
    "canonical_numbers": ("native-canonical", "canonical_numbers.cpp", "_canonical_numbers", 1),
    "cox_breslow": ("native-cox-breslow", "cox_breslow.cpp", "_cox_breslow", 1),
    "engine": ("native-engine", None, "arboris_engine", 1),
    "kendall_counts": ("native-kendall", "kendall_counts.cpp", "_kendall_counts", 4),
    "io_writers": ("native-io", "io_writers.cpp", "_arboris_io", 1),
    "kernels": ("native-kernels", None, "arboris_kernels", 2),
    "quant_replay": ("native-quant-replay", None, "arboris_quant_replay", 1),
    "ridge": ("native-ridge", "ridge.cpp", "_ridge", 1),
    "spearman_ranks": ("native-spearman-ranks", "spearman_rank.cpp", "_spearman_rank", 1),
    "studentized_range": ("native-studentized-range", "studentized_range.cpp", "_studentized_range", 1),
    "time_series": ("native-time-series", None, "arboris_time_series", 1),
}


class NativeBuildError(RuntimeError):
    """A present build cannot be admitted; rebuild it explicitly."""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json_digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def default_output(module: Path) -> Path:
    return module.parents[1] / "local" / MODULES[module.name][0]


def manifest_path(out: Path, variant: str = "row-exact") -> Path:
    return out / ("build-manifest-moments.json" if variant == "moments" else "build-manifest.json")


def variants(module: Path) -> tuple[str, ...]:
    """Every supported production variant; shared by module CLI and aggregate admission."""
    return ("row-exact", "moments") if module.name == "ar_exact" else ("row-exact",)


def _spec(module: Path, variant: str):
    directory, source, name, abi = MODULES[module.name]
    if variant not in variants(module):
        if variant == "moments":
            raise NativeBuildError("moments variant is only supported by ar_exact")
        raise NativeBuildError("unknown native build variant")
    if variant == "moments":
        source, name, abi = "ar_moments.cpp", "_ar_moments_exact", 1
    return directory, source, name, abi


def artifact_names(module: Path, variant: str = "row-exact") -> list[str]:
    _, source, name, _ = _spec(module, variant)
    if source:
        return [name + sysconfig.get_config_var("EXT_SUFFIX")]
    library = ("" if sys.platform == "win32" else "lib") + name + {
        "darwin": ".dylib", "win32": ".dll"}.get(sys.platform, ".so")
    return [library, "target/release/arboris-engine" + (".exe" if sys.platform == "win32" else "")] \
        if module.name == "engine" else [library]


def _sources(module: Path) -> dict[str, str]:
    root = module.parents[1]
    # Inventory equality detects additions as well as modifications/removals, including nested Rust modules.
    suffixes = {".cpp", ".cc", ".c", ".h", ".hpp", ".rs", ".toml", ".lock"}
    paths = [path for path in module.rglob("*") if path.is_file()
             and "target" not in path.relative_to(module).parts
             and (path.suffix in suffixes or path.name == "build.py")]
    paths.append(root / "backend/workbench/native_build.py")
    return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}


def _platform_abi() -> dict:
    return {"platform": sys.platform, "machine": platform.machine(), "byteorder": sys.byteorder,
            "pointer_bits": struct.calcsize("P") * 8, "python_implementation": sys.implementation.name,
            "python_version": platform.python_version(), "soabi": sysconfig.get_config_var("SOABI"),
            "extension_suffix": sysconfig.get_config_var("EXT_SUFFIX"), "build_platform": sysconfig.get_platform()}


def _configuration(module: Path, out: Path, variant: str) -> dict:
    root = module.parents[1]
    _, source, _, _ = _spec(module, variant)
    if source is None:
        command = ["cargo", "build", "--release", "--locked", "--offline", "--target-dir", str(out / "target"),
                   "--manifest-path", str(module / "Cargo.toml")]
        # Cargo reads config files from the working directory's ancestors and CARGO_HOME.
        directories = [root, *root.parents]
        config_paths = [directory / ".cargo" / name for directory in directories for name in ("config", "config.toml")]
        cargo_home = Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo"))
        config_paths += [cargo_home / name for name in ("config", "config.toml")]
        config = {str(path): digest(path) for path in sorted(set(config_paths)) if path.is_file()}
        keys = {"RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "RUSTC", "RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER",
                "RUSTUP_TOOLCHAIN", "CARGO_BUILD_TARGET", "CARGO_BUILD_RUSTFLAGS"}
        keys.update(key for key in os.environ if key.startswith("CARGO_PROFILE_RELEASE_")
                    or (key.startswith("CARGO_TARGET_") and key.endswith(("_RUSTFLAGS", "_LINKER"))))
        environment = {key: os.environ[key] for key in sorted(keys) if key in os.environ}
        return {"command": command, "environment": environment, "cargo_config_sha256": config}
    linker = sysconfig.get_config_var("LDCXXSHARED")
    if not linker:
        raise NativeBuildError("this interpreter does not supply LDCXXSHARED")
    command = shlex.split(linker) + ["-std=c++17", "-O3", "-Wall", "-Wextra", "-Werror", "-fPIC"]
    if module.name in {"cox_breslow", "io_writers", "ridge"}:
        command += ["-ffp-contract=off"]
    elif module.name == "studentized_range":
        command += ["-ffp-contract=on"]
    macro = {"canonical_numbers": "ANALYSIS_SAMPLE_SOURCE_SHA256", "ar_exact":
             "AR_MOMENTS_SOURCE_SHA256" if variant == "moments" else "AR_EXACT_SOURCE_SHA256"}.get(module.name)
    if macro:
        command += ["-D" + macro + '=\"' + digest(module / source) + '\"']
    command += ["-I" + sysconfig.get_path("include"), str(module / source), "-o", str(out / artifact_names(module, variant)[0])]
    return {"command": command, "environment": {key: os.environ[key] for key in ("SDKROOT", "MACOSX_DEPLOYMENT_TARGET")
                                               if key in os.environ}, "cargo_config_sha256": {}}


def _tool(command: str, version_args: list[str]) -> dict:
    located = shutil.which(command)
    if not located:
        raise NativeBuildError(f"native compiler/tool not found: {command}")
    executable = Path(located).resolve()
    done = subprocess.run([located, *version_args], capture_output=True, text=True, check=True)
    version = (done.stdout + done.stderr).strip()
    if not version:
        raise NativeBuildError(f"native compiler/tool returned no version: {command}")
    return {"executable": str(executable), "binary_sha256": digest(executable), "version": version}


def _compiler(module: Path, configuration: dict) -> dict:
    if MODULES[module.name][1] is None:
        return {"cargo": _tool("cargo", ["-Vv"]), "rustc": _tool(os.environ.get("RUSTC", "rustc"), ["-vV"])}
    return {"cxx": _tool(configuration["command"][0], ["--version"])}


def _inputs(module: Path, out: Path, variant: str) -> dict:
    sources = _sources(module)
    configuration = _configuration(module, out, variant)
    return {"schema_version": SCHEMA_VERSION, "module": module.name, "variant": variant,
            "abi_version": _spec(module, variant)[3], "sources": sources, "source_sha256": _json_digest(sources),
            "configuration": configuration, "command": configuration["command"], "platform_abi": _platform_abi()}


def verify_build(module: Path, out: Path, *, check_toolchain: bool = False, variant: str = "row-exact") -> dict:
    """Return the complete verified manifest, or raise before executing any native code."""
    module, out = module.resolve(), out.resolve()
    try:
        record = json.loads(manifest_path(out, variant).read_text())
        expected = _inputs(module, out, variant)
        if not isinstance(record, dict):
            raise NativeBuildError("manifest must be an object")
        for key, value in expected.items():
            if record.get(key) != value:
                raise NativeBuildError(f"manifest {key} is missing, incomplete or stale")
        compiler = record.get("compiler")
        tool_names = {"cargo", "rustc"} if MODULES[module.name][1] is None else {"cxx"}
        if not isinstance(compiler, dict) or compiler.keys() != tool_names:
            raise NativeBuildError("manifest compiler identity is missing or incomplete")
        for tool in compiler.values():
            if not isinstance(tool, dict) or not isinstance(tool.get("executable"), str) \
                    or not Path(tool["executable"]).is_absolute() or not tool.get("version") \
                    or not isinstance(tool.get("binary_sha256"), str) or len(tool["binary_sha256"]) != 64:
                raise NativeBuildError("manifest compiler identity is incomplete")
        if check_toolchain and compiler != _compiler(module, expected["configuration"]):
            raise NativeBuildError("compiler identity changed since build")
        artifacts = record.get("artifacts")
        names = artifact_names(module, variant)
        if not isinstance(artifacts, dict) or set(artifacts) != set(names):
            raise NativeBuildError("manifest binary inventory is missing or incomplete")
        for name in names:
            binary = out / name
            if binary.is_symlink() or not binary.is_file() or digest(binary) != artifacts[name]:
                raise NativeBuildError(f"binary is missing, replaced or modified: {name}")
        if record.get("binary") != str(out / names[0]) or record.get("binary_sha256") != artifacts[names[0]]:
            raise NativeBuildError("manifest primary binary identity is inconsistent")
        payload = {key: value for key, value in record.items() if key != "build_identity_sha256"}
        if record.get("build_identity_sha256") != _json_digest(payload):
            raise NativeBuildError("manifest build identity digest is missing or invalid")
        return record
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise NativeBuildError(f"invalid native {module.name} build: {error}; rebuild with native/{module.name}/build.py") from error


def build(module: Path, out: Path, *, variant: str = "row-exact") -> dict:
    module, out = module.resolve(), out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    # Invalidate prior evidence before replacing any artifact, including when the new build fails.
    manifest_path(out, variant).unlink(missing_ok=True)
    before = _inputs(module, out, variant)
    compiler = _compiler(module, before["configuration"])
    if MODULES[module.name][1] is None:
        # Cargo's freshness cache does not prove that a pre-existing target binary was not replaced.
        # Explicit rebuilds compile from clean release outputs; checks never perform this mutation.
        subprocess.run(["cargo", "clean", "--release", "--target-dir", str(out / "target"),
                        "--manifest-path", str(module / "Cargo.toml")], cwd=module.parents[1], check=True)
    else:
        # Exit zero is insufficient if the compiler produced nothing; never adopt an older output.
        (out / artifact_names(module, variant)[0]).unlink(missing_ok=True)
    print(shlex.join(before["command"]), flush=True)
    subprocess.run(before["command"], cwd=module.parents[1], check=True)
    names = artifact_names(module, variant)
    if MODULES[module.name][1] is None:
        # Overwriting an already mapped Mach-O inode can kill even a fresh
        # loader on macOS. Publish the new image via a fresh inode.
        with tempfile.TemporaryDirectory(prefix=".native-publish-", dir=out) as staging:
            candidate = Path(staging) / names[0]
            shutil.copy2(out / "target/release" / names[0], candidate)
            candidate.replace(out / names[0])
    if before != _inputs(module, out, variant) or compiler != _compiler(module, before["configuration"]):
        raise NativeBuildError("native build inputs/compiler changed during compilation; rebuild")
    record = before | {"compiler": compiler, "artifacts": {name: digest(out / name) for name in names},
                       "binary": str(out / names[0]), "binary_sha256": digest(out / names[0])}
    record["build_identity_sha256"] = _json_digest(record)
    destination = manifest_path(out, variant)
    with tempfile.NamedTemporaryFile(mode="w", dir=out, prefix=".build-manifest-", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(record, stream, sort_keys=True, indent=2)
        stream.write("\n")
    temporary.replace(destination)
    return verify_build(module, out, check_toolchain=True, variant=variant)


def main(module_file: str) -> int:
    module = Path(module_file).resolve().parent
    parser = argparse.ArgumentParser(description="Build or strictly verify this module's recorded native identity, offline.")
    parser.add_argument("--output-dir", type=Path, default=default_output(module))
    parser.add_argument("--check", action="store_true", help="verify only; never compile or adopt an existing binary")
    if len(variants(module)) > 1:
        parser.add_argument("--engine", choices=variants(module), default=variants(module)[0])
    args = parser.parse_args()
    out = args.output_dir.resolve()
    allowed = ((module.parents[1] / "local").resolve(), Path(tempfile.gettempdir()).resolve(), Path("/tmp").resolve())
    if not any(out == path or path in out.parents for path in allowed):
        parser.error("build output must be under local/ or a temporary directory")
    variant = getattr(args, "engine", "row-exact")
    try:
        record = verify_build(module, out, check_toolchain=True, variant=variant) if args.check else build(module, out, variant=variant)
    except (NativeBuildError, OSError, subprocess.CalledProcessError) as error:
        print(f"{module.name}: FAILED: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"module": module.name, "variant": variant, "status": "current", "binary": record["binary"],
                      "build_identity_sha256": record["build_identity_sha256"]}, sort_keys=True))
    return 0
