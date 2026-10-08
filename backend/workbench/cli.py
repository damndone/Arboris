from __future__ import annotations

import enum
import inspect
import json
import os
import socket
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

import typer
import typer.main
from typer.core import TyperGroup

from .projects import create_project


class _WorkbenchGroup(TyperGroup):
    """Typer's group plus the generated commands, each built on first use."""

    def list_commands(self, ctx: Any) -> list[str]:
        return sorted(set(super().list_commands(ctx)) | set(_GENERATED_COMMANDS))

    def get_command(self, ctx: Any, cmd_name: str) -> Any:
        factory = _GENERATED_COMMANDS.get(cmd_name)
        if factory is not None:
            return factory()
        return super().get_command(ctx, cmd_name)


app = typer.Typer(help="Local econometrics workbench.", cls=_WorkbenchGroup)

# Default FE dev-server origin. Override with WORKBENCH_UI_ORIGIN when
# running on a non-standard host/port (e.g. CI proxy, remote tunnel).
_DEFAULT_UI_ORIGIN = "http://localhost:5173"
_FALLBACK_UI_ORIGIN = "http://localhost:8000"
_PROBE_HOST = "localhost"
_PROBE_PORT = 5173
_PROBE_TIMEOUT_S = 0.1
_CACHE_TTL_S = 3600
_CACHE_PATH = Path.home() / ".workbench" / "ui_origin_cache.json"


def _cache_read(path: Path = _CACHE_PATH) -> str | None:
    """Return cached origin if file exists and is within TTL, else None."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(raw)
        origin = data["origin"]
        ts = float(data["ts"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    if time.time() - ts > _CACHE_TTL_S:
        return None
    return str(origin)


def _cache_write(origin: str, path: Path = _CACHE_PATH) -> None:
    """Best-effort cache write. Silently skips on IO errors so a
    read-only HOME never breaks `workbench run`."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"origin": origin, "ts": time.time()}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _probe_dev_server(
    host: str = _PROBE_HOST,
    port: int = _PROBE_PORT,
    timeout: float = _PROBE_TIMEOUT_S,
) -> bool:
    """TCP-probe the FE dev server. Returns True iff a connection opens
    inside the timeout. Hard cap prevents firewalled hosts from hanging
    the CLI."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _resolve_ui_origin() -> str:
    """Pick the FE origin for `_lineage_url`. Priority:
    1. `WORKBENCH_UI_ORIGIN` env var (explicit override).
    2. Cached result from a recent probe (1 h TTL).
    3. Live TCP probe of localhost:5173 → use it if open.
    4. Fall back to localhost:8000 (the backend serves a usable URL
       even without the Vite dev server).
    """
    env = os.environ.get("WORKBENCH_UI_ORIGIN")
    if env:
        return env.rstrip("/")
    # Resolve the cache path lazily so test code can monkeypatch
    # `_CACHE_PATH` to redirect it to a tmp dir.
    cache_path = _CACHE_PATH
    cached = _cache_read(cache_path)
    if cached is not None:
        return cached
    origin = _DEFAULT_UI_ORIGIN if _probe_dev_server() else _FALLBACK_UI_ORIGIN
    _cache_write(origin, cache_path)
    return origin


def _lineage_url(project_root: Path, run_id: str) -> str:
    """Build the frontend URL that lands directly on the Lineage tab
    of a run. Used by `workbench run` to print a copyable link after
    the run completes. P0 of the V1.5.0 product path: a CLI user
    should be one click away from the lineage view.
    """
    origin = _resolve_ui_origin()
    return (
        f"{origin}/runs/{quote(run_id, safe='')}"
        f"?project_root={quote(str(project_root.resolve()), safe='')}"
        f"&tab=lineage"
    )


@app.callback()
def main() -> None:
    pass


@app.command()
def create(parent: Path, name: str) -> None:
    project = create_project(parent, name)
    typer.echo(str(project.root))


# ---------------------------------------------------------------------------
# Generated commands (V1812-CLI-FROM-CATALOG).
#
# `run` takes the POST /runs fields (run_request.RUN_REQUEST_FIELDS),
# `postestimation <op>` the post-estimation step contracts, and `export-script`
# the script-export languages; each executes through the same service as the
# API or the Agent (cli_commands). Built on first use, so start-up imports
# neither the statistics libraries nor the web stack.
# ---------------------------------------------------------------------------


def _fail(exc: Exception) -> None:
    from .cli_commands import CommandError

    if isinstance(exc, CommandError):
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=exc.code)
    raise exc


def _json_value(raw: str | None, option: str) -> Any:
    """A JSON document given inline or as @path."""
    if raw is None:
        return None
    text = raw
    if raw.startswith("@"):
        try:
            text = Path(raw[1:]).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise typer.BadParameter(f"cannot read {raw[1:]}: {exc}", param_hint=option) from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"not valid JSON: {exc}", param_hint=option) from exc


def _option_name(name: str) -> str:
    return "--" + name.replace("_", "-")


def _param(name: str, annotation: Any, info: Any, default: Any = inspect.Parameter.empty) -> inspect.Parameter:
    return inspect.Parameter(
        name, inspect.Parameter.KEYWORD_ONLY, annotation=Annotated[annotation, info], default=default,
    )


def _command(name: str, help_text: str, parameters: list[inspect.Parameter], callback: Callable[..., None]) -> Any:
    """A Typer command whose parameters are given as a generated signature."""
    callback.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
    single = typer.Typer()
    single.command(name, help=help_text)(callback)
    return typer.main.get_command(single)


def _run_command() -> Any:
    from .run_request import RUN_REQUEST_FIELDS, encode_many

    parameters = [
        _param("project_root", Path, typer.Argument(help="Workbench project directory.")),
        _param("data_file", Path, typer.Argument(help="Data file (csv, xlsx, sav, dta, ...).")),
        _param("y", str, typer.Argument(help="Outcome column.")),
    ]
    for field in RUN_REQUEST_FIELDS:
        if field.name == "y":
            continue
        decls = (_option_name(field.name), *field.cli_aliases)
        if field.many:
            parameters.append(_param(field.name, list[str] | None, typer.Option(*decls, help=field.help), None))
        elif isinstance(field.default, bool):
            parameters.append(_param(field.name, bool, typer.Option(*decls, help=field.help), field.default))
        elif isinstance(field.default, int):
            parameters.append(_param(field.name, int, typer.Option(*decls, help=field.help), field.default))
        elif field.encoding == "json":
            parameters.append(_param(
                field.name, str | None, typer.Option(*decls, help=field.help + " Inline JSON or @file."), None,
            ))
        else:
            parameters.append(_param(
                field.name, str | None, typer.Option(*decls, help=field.help, show_default=bool(field.default)),
                field.default,
            ))

    def callback(project_root: Path, data_file: Path, y: str, **options: Any) -> None:
        values: dict[str, Any] = {"y": y}
        for field in RUN_REQUEST_FIELDS:
            if field.name == "y":
                continue
            value = options[field.name]
            if field.many:
                values[field.name] = encode_many(field, list(value or ()))
            elif field.encoding == "json":
                document = _json_value(value, _option_name(field.name))
                values[field.name] = field.default if document is None else json.dumps(document)
            elif value is not None:
                values[field.name] = value
        from .cli_commands import submit_run

        def progress(event: dict) -> None:
            if event.get("step") and str(event.get("event", "")).startswith("step_"):
                typer.echo(f"{event['event']:<14} {event['step']:<18} {event.get('message', '')}", err=True)

        try:
            run_id, status = submit_run(project_root, data_file, values, on_event=progress)
        except Exception as exc:  # noqa: BLE001 - refusals are reported, anything else re-raised
            _fail(exc)
            return
        # stdout: machine-readable run_id only — the long-standing
        # `RUN_ID=$(workbench run ...)` shell contract.
        typer.echo(run_id)
        typer.echo(f"Lineage: {_lineage_url(project_root, run_id)}", err=True)
        if status != "completed":
            typer.echo(f"run {run_id} {status}", err=True)
            raise typer.Exit(code=1)

    return _command(
        "run", "Fit a model: the fields of POST /runs, submitted through the same service.", parameters, callback,
    )


_JSON_FIELD_TYPES = frozenset({"list", "object"})


def _postestimation_group() -> Any:
    from .contracts.model.postestimation_steps import STEP_SHAPES

    group = typer.Typer(name="postestimation")

    @group.callback()
    def _postestimation() -> None:
        """Post-estimation on a completed model (one subcommand per registered operation)."""

    for operation, (summary, fields, required, types) in STEP_SHAPES.items():
        parameters = [
            _param("project_root", Path, typer.Argument(help="Workbench project directory.")),
            _param("run_id", str, typer.Argument(help="The run holding the model.")),
        ]
        for name, help_text in fields.items():
            kind = types.get(name, "string")
            extra = " JSON (inline or @file)." if kind in _JSON_FIELD_TYPES else ""
            info = typer.Option(_option_name(name), help=help_text + extra)
            annotation = float if kind == "number" else str
            if name in required:
                parameters.append(_param(name, annotation, info))
            else:
                parameters.append(_param(name, annotation | None, info, None))

        def callback(project_root: Path, run_id: str, _operation: str = operation,
                     _types: Mapping[str, str] = types, **options: Any) -> None:
            spec: dict[str, Any] = {}
            for name, value in options.items():
                if value is None:
                    continue
                spec[name] = _json_value(value, _option_name(name)) if _types.get(name) in _JSON_FIELD_TYPES else value
            from .cli_commands import run_postestimation

            try:
                result = run_postestimation(project_root, run_id, _operation, spec)
            except Exception as exc:  # noqa: BLE001
                _fail(exc)
                return
            typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))

        # A fresh function per operation; Typer reads the generated signature.
        callback.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
        group.command(operation, help=summary)(callback)
    return typer.main.get_command(group)


def _export_script_command() -> Any:
    from .script_export.plan import LANGUAGES

    language_choice = enum.Enum("Language", {language: language for language in LANGUAGES}, type=str)

    def callback(project_root: Path, run_id: str, target: str, language: Any,
                 require_native: bool, output: Path | None) -> None:
        from .cli_commands import export_script

        try:
            result = export_script(project_root, run_id, target, str(language.value),
                                   require_native=require_native, output=output)
        except Exception as exc:  # noqa: BLE001
            _fail(exc)
            return
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return _command(
        "export-script",
        "Export a reproducible script bundle, as the Export menu does.",
        [
            _param("project_root", Path, typer.Argument(help="Workbench project directory.")),
            _param("run_id", str, typer.Argument()),
            _param("target", str, typer.Option(
                "--target", help="What to reproduce: model:<id> or artifact:<id> (see export-targets).",
            )),
            _param("language", language_choice, typer.Option("--language"), language_choice("stata")),
            _param("require_native", bool, typer.Option(
                "--require-native", help="Refuse unless the script runs natively in the language (no Python fallback).",
            ), False),
            _param("output", Path | None, typer.Option(
                "--output", help="Also write the bundle here (a file path or a directory).",
            ), None),
        ],
        callback,
    )


def _export_targets_command() -> Any:
    def callback(project_root: Path, run_id: str, model: str) -> None:
        from .cli_commands import export_targets

        try:
            result = export_targets(project_root, run_id, model)
        except Exception as exc:  # noqa: BLE001
            _fail(exc)
            return
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))

    return _command(
        "export-targets",
        "List what a run's model can be exported with (the model, and its post-estimation results).",
        [
            _param("project_root", Path, typer.Argument(help="Workbench project directory.")),
            _param("run_id", str, typer.Argument()),
            _param("model", str, typer.Option("--model", help="Model node, e.g. model:negative_binomial_1.")),
        ],
        callback,
    )


def _models_command() -> Any:
    def callback(model_type: str | None) -> None:
        from .cli_commands import catalog

        try:
            result = catalog(model_type)
        except Exception as exc:  # noqa: BLE001
            _fail(exc)
            return
        if model_type is None:
            for entry in result["model_types"]:
                typer.echo(f"{entry['key']:<26} {entry.get('group', ''):<12} {entry.get('label', '')}")
            return
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return _command(
        "models",
        "List the capability catalog; with MODEL_TYPE, its parameters and model_options fields.",
        [_param("model_type", str | None, typer.Argument(), None)],
        callback,
    )


_GENERATED_COMMANDS: dict[str, Callable[[], Any]] = {
    "run": _run_command,
    "postestimation": _postestimation_group,
    "export-script": _export_script_command,
    "export-targets": _export_targets_command,
    "models": _models_command,
}


run_family_app = typer.Typer(help="Run-family identity maintenance.")
app.add_typer(run_family_app, name="run-family")


@run_family_app.command("migrate")
def run_family_migrate(project_root: Path) -> None:
    """Persist every existing run's family, keeping each id byte-identical.

    After this the project is strict: a newly created run that declares no
    family is refused instead of silently deriving one from ancestry.
    """

    from .lineage.run_family import migrate_project_families

    result = migrate_project_families(project_root)
    created = result["created_families"]
    typer.echo(
        f"migrated {len(result['migrated_run_ids'])} run(s), "
        f"{len(created)} new family record(s)"
    )
    for family_id in created:
        typer.echo(f"  + {family_id}")
    typer.echo(f"project is now strict (cutover {result['migrated_at']})", err=True)


@run_family_app.command("verify")
def run_family_verify(project_root: Path) -> None:
    """Report runs whose persisted family disagrees with their ancestry.

    Read-only. A divergence is never repaired automatically: two sources
    disagree about which analysis line a run belongs to, and guessing would
    silently rewrite lineage that other records already point at.
    """

    from .lineage.run_family import verify_project_families

    errors = verify_project_families(project_root)
    runs_root = Path(project_root) / "runs"
    checked = len([p for p in runs_root.iterdir() if p.is_dir()]) if runs_root.is_dir() else 0
    if not errors:
        typer.echo(f"ok: {checked} run(s) consistent")
        return
    typer.echo(f"{len(errors)} inconsistency/ies across {checked} run(s):")
    for error in errors:
        typer.echo(f"  ! {error}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
