from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import typer

from .projects import create_project

app = typer.Typer(help="Local econometrics workbench.")

# Default FE dev-server origin. Override with WORKBENCH_UI_ORIGIN when
# running on a non-standard host/port (e.g. CI proxy, remote tunnel).
_DEFAULT_UI_ORIGIN = "http://localhost:5173"


def _lineage_url(project_root: Path, run_id: str) -> str:
    """Build the frontend URL that lands directly on the Lineage tab
    of a run. Used by `workbench run` to print a copyable link after
    the run completes. P0 of the V1.5.0 product path: a CLI user
    should be one click away from the lineage view.
    """
    origin = os.environ.get("WORKBENCH_UI_ORIGIN", _DEFAULT_UI_ORIGIN).rstrip("/")
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
    from .orchestrator import run_workflow

    result = run_workflow(project_root, [data_file], mode=mode, y=y, x=x)
    run_id = result["run_id"]
    # stdout: machine-readable run_id only — preserves the long-standing
    # `RUN_ID=$(workbench run ...)` shell contract.
    typer.echo(run_id)
    # stderr: human-facing copyable URL — visible in terminals, doesn't
    # pollute scripts capturing stdout.
    typer.echo(f"Lineage: {_lineage_url(project_root, run_id)}", err=True)


if __name__ == "__main__":
    app()
