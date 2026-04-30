from __future__ import annotations

from pathlib import Path

import typer

from .orchestrator import run_workflow
from .projects import create_project

app = typer.Typer(help="Local econometrics workbench.")


@app.callback()
def main() -> None:
    pass


@app.command()
def create(parent: Path, name: str) -> None:
    project = create_project(parent, name)
    typer.echo(str(project.root))


@app.command()
def run(
    project_root: Path,
    data_file: Path,
    y: str,
    x: list[str] = typer.Option(
        ...,
        "--x",
        help="Regressor column. Repeat for multiple columns.",
    ),
    mode: str = typer.Option("auto", "--mode"),
) -> None:
    result = run_workflow(project_root, [data_file], mode=mode, y=y, x=x)
    typer.echo(result["run_id"])
