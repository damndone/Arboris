from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path
from urllib.parse import quote

import typer

from .projects import create_project

app = typer.Typer(help="Local econometrics workbench.")

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
    model_type: str = typer.Option("auto", "--model-type"),
) -> None:
    from .orchestrator import run_workflow

    result = run_workflow(
        project_root,
        [data_file],
        mode=mode,
        y=y,
        x=x,
        model_type=model_type,
    )
    run_id = result["run_id"]
    # stdout: machine-readable run_id only — preserves the long-standing
    # `RUN_ID=$(workbench run ...)` shell contract.
    typer.echo(run_id)
    # stderr: human-facing copyable URL — visible in terminals, doesn't
    # pollute scripts capturing stdout.
    typer.echo(f"Lineage: {_lineage_url(project_root, run_id)}", err=True)


if __name__ == "__main__":
    app()
