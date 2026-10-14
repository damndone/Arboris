"""`workbench analyze`: every operation of the catalog from the command line.

The same catalog Analyze shows (GET /operations) and the same server-owned
preview / confirm service (POST /operations/run), so a command gives the
results, records and lineage the interface and the Agent give. Parameters are
the operation's JSON spec, inline or @file, which suits do-file style scripts;
`describe` prints the fields and allowed values. Loaded only on first use.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


import typer
import typer.main

from .cli_commands import CommandError


def _catalog() -> list[dict[str, Any]]:
    from .http.operation_routes import _dedicated_operations
    from .services.operation_catalog import operation_catalog

    return operation_catalog(dedicated_operations=_dedicated_operations())["operations"]


def _find(operation_id: str) -> dict[str, Any]:
    for operation in _catalog():
        if operation["id"] == operation_id:
            return operation
    raise CommandError(f"unknown operation {operation_id!r}; `workbench analyze list` shows them")


def build_analyze_group(json_value: Callable, fail: Callable) -> Any:
    group = typer.Typer(name="analyze")

    @group.callback()
    def analyze() -> None:
        """Run any catalog operation: list, describe, preview with run, then confirm."""

    @group.command("list")
    def list_operations(
        group_name: str | None = typer.Option(None, "--group", help="Only this group (its key or label)."),
        search: str | None = typer.Option(None, "--search", help="Words to look for in titles and descriptions."),
        as_json: bool = typer.Option(False, "--json", help="Machine-readable output."),
    ) -> None:
        """The operations, grouped in the order a study moves in."""
        operations = sorted(_catalog(), key=lambda op: (op.get("group_order", 99), op["name"]))
        if group_name:
            wanted = group_name.lower()
            operations = [op for op in operations if wanted in {str(op.get("group", "")).lower(), str(op.get("group_label", "")).lower()}]
        if search:
            words = search.lower().split()
            operations = [op for op in operations if all(word in f"{op['name']} {op.get('blurb', '')} {op['id']}".lower() for word in words)]
        if as_json:
            typer.echo(json.dumps([{key: op.get(key) for key in ("id", "name", "blurb", "group", "group_label")} | {"runs_here": op["execution"]["kind"] == "workflow"} for op in operations], ensure_ascii=False, indent=2))
            return
        current = None
        for op in operations:
            if op.get("group_label") != current:
                current = op.get("group_label")
                typer.echo(f"\n{current}")
            note = "" if op["execution"]["kind"] == "workflow" else f"  [{op['execution'].get('surface') or op['execution']['kind']}]"
            typer.echo(f"  {op['id']:<44} {op['name']}{note}")

    @group.command("describe")
    def describe(operation_id: str = typer.Argument(help="Operation id, e.g. nonparametric.mann_whitney.")) -> None:
        """Fields, required ones and allowed values of an operation's spec."""
        try:
            op = _find(operation_id)
        except CommandError as exc:
            fail(exc)
            return
        typer.echo(json.dumps({key: op.get(key) for key in ("id", "name", "blurb", "group_label", "summary", "target_requirements", "execution", "spec_schema")}, ensure_ascii=False, indent=2))

    @group.command("run")
    def run(
        operation_id: str = typer.Argument(help="Operation id (see `analyze list`)."),
        project_root: Path = typer.Argument(help="Workbench project directory."),
        run_id: str = typer.Option(..., "--run", help="Run holding the dataset or model."),
        node: str = typer.Option(..., "--node", help="Dataset node id (e.g. stage:cleaned) or model node id (e.g. model:ols_1)."),
        artifact: str | None = typer.Option(None, "--artifact", help="Dataset artifact id; give it for a dataset target, omit it for a model."),
        spec: str = typer.Option("{}", "--spec", help="The operation's parameters as JSON, inline or @file."),
        request_id: str | None = typer.Option(None, "--request-id", help="Override the deterministic request id to request a new operation."),
    ) -> None:
        """Preview an operation; confirm the printed plan with `analyze confirm`."""
        from .cli_commands import preview_operation

        try:
            op = _find(operation_id)
            if op["execution"]["kind"] != "workflow":
                where = op["execution"].get("surface") or "its own view"
                raise CommandError(f"{operation_id} has its own entry ({where}); it is not run through `analyze`")
            target = (
                {"kind": "dataset_node", "run_id": run_id, "node_id": node, "artifact_id": artifact}
                if artifact else {"kind": "model_node", "run_id": run_id, "node_id": node}
            )
            parameters = json_value(spec, "--spec")
            if not isinstance(parameters, dict):
                raise CommandError("--spec must be a JSON object")
            result = preview_operation(project_root, target, operation_id, parameters, request_id=request_id)
        except Exception as exc:  # noqa: BLE001 - shared command refusal handling
            fail(exc)
            return
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))

    @group.command("confirm")
    def confirm(
        project_root: Path = typer.Argument(help="Workbench project directory."),
        request_id: str = typer.Option(..., "--request-id", help="Request id returned by run."),
        preview_id: str = typer.Option(..., "--preview-id", help="Server preview id."),
        fingerprint: str = typer.Option(..., "--fingerprint", help="Exact server preview fingerprint."),
    ) -> None:
        """Run exactly the previewed plan; the server supplies its target and parameters."""
        from .cli_commands import confirm_data_operation

        try:
            result = confirm_data_operation(project_root, request_id, preview_id, fingerprint)
        except Exception as exc:  # noqa: BLE001
            fail(exc)
            return
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "completed":
            typer.echo(f"error: operation {result['status']}: {result.get('error') or 'see step errors'}", err=True)
            raise typer.Exit(code=1)

    return typer.main.get_command(group)
