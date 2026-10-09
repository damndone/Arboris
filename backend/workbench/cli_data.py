"""Data CLI generated from the live declarations; loaded only on first use."""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Callable

import typer
import typer.main


def build_data_group(param: Callable, json_value: Callable, fail: Callable) -> Any:
    from .agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
    from .data_operation_registry import data_operation_declarations

    group = typer.Typer(name="data")

    @group.callback()
    def data() -> None:
        """Preview declared data operations, then confirm their server-pinned plan."""

    def register(name: str, operation_id: str, declaration: Any) -> None:
        parameters = [
            param("project_root", Path, typer.Argument(help="Workbench project directory.")),
            param("run_id", str, typer.Argument(help="Run holding the source dataset.")),
            param("source_node", str, typer.Option("--source-node", help="Explicit source graph node id.")),
            param("source_artifact", str, typer.Option("--source-artifact", help="Explicit registered source artifact id.")),
            param("request_id", str | None, typer.Option("--request-id", help="Override the deterministic request id to request a new operation."), None),
        ]
        json_fields = set()
        for field, description in declaration.fields.items():
            schema = declaration.field_schemas.get(field, {})
            kind = declaration.field_types.get(field, schema.get("type", "string"))
            # Structured/union values remain schema-owned JSON. Scalar number
            # parsing is Typer's job; semantic/range validation stays shared.
            if isinstance(kind, list) or kind in {"list", "array", "object", "boolean", "any"} or "anyOf" in schema:
                annotation = str
                json_fields.add(field)
                description += " JSON (inline or @file)."
            else:
                annotation = {"integer": int, "number": float}.get(kind, str)
            choices = declaration.field_enums.get(field) or schema.get("enum")
            if choices:
                description += " Choices: " + ", ".join(map(str, choices)) + "."
            option = typer.Option("--" + field.replace("_", "-"), help=description)
            if field in declaration.required:
                parameters.append(param(field, annotation, option))
            else:
                parameters.append(param(field, annotation | None, option, None))

        def callback(project_root: Path, run_id: str, source_node: str, source_artifact: str,
                     request_id: str | None, **options: Any) -> None:
            from .cli_commands import preview_data_operation

            spec = {field: json_value(value, "--" + field.replace("_", "-")) if field in json_fields else value
                    for field, value in options.items() if value is not None}
            try:
                result = preview_data_operation(project_root, run_id, source_node, source_artifact,
                                                operation_id, spec, request_id=request_id)
            except Exception as exc:  # noqa: BLE001 - shared command refusal handling
                fail(exc)
                return
            typer.echo(json.dumps(result, ensure_ascii=False, indent=2))

        callback.__signature__ = inspect.Signature(parameters)
        group.command(name, help=declaration.summary)(callback)

    for declaration in data_operation_declarations():
        register(declaration.operation, declaration.workflow_operation_id, declaration)
    # The existing file-upload `run` command remains compatible. This entry
    # preserves an explicit transformed dataset's identity when fitting.
    register("fit", "model.genesis", WORKFLOW_STEP_SPEC_CONTRACTS["model.genesis"])

    @group.command("confirm")
    def confirm(
        project_root: Path = typer.Argument(help="Workbench project directory."),
        request_id: str = typer.Option(..., "--request-id", help="Request id returned by preview."),
        preview_id: str = typer.Option(..., "--preview-id", help="Server preview id."),
        fingerprint: str = typer.Option(..., "--fingerprint", help="Exact server preview fingerprint."),
    ) -> None:
        """Confirm a saved preview; the server supplies its target and parameters."""
        from .cli_commands import confirm_data_operation

        try:
            result = confirm_data_operation(project_root, request_id, preview_id, fingerprint)
        except Exception as exc:  # noqa: BLE001
            fail(exc)
            return
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "completed":
            typer.echo(f"error: data operation {result['status']}: {result.get('error') or 'see step errors'}", err=True)
            raise typer.Exit(code=1)

    return typer.main.get_command(group)
