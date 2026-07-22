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
    imputation: str = typer.Option("", "--imputation"),
    entity_col: str = typer.Option(
        "", "--entity-col", help="Panel entity (unit id) column."
    ),
    time_col: str = typer.Option(
        "", "--time-col", help="Panel time-period column."
    ),
    covariance: str = typer.Option(
        "", "--covariance",
        help="Covariance estimator: robust | clustered | unadjusted. Default: robust.",
    ),
    iv_endog: list[str] = typer.Option(
        [], "--iv-endog", help="Endogenous regressor. Repeat for multiple."
    ),
    iv_instruments: list[str] = typer.Option(
        [], "--iv-instruments", help="Instrument column. Repeat for multiple."
    ),
    did_mode: str = typer.Option(
        "", "--did-mode",
        help="DID design: cohort | two_by_two | status. Default: cohort.",
    ),
    did_cohort_col: str = typer.Option(
        "", "--did-cohort-col",
        help="Cohort (first-treatment period) column; required for mode 'cohort'.",
    ),
    did_treat_col: str = typer.Option(
        "", "--did-treat-col",
        help="Treated-group dummy column; required for mode 'two_by_two'.",
    ),
    did_post_col: str = typer.Option(
        "", "--did-post-col",
        help="Post-period dummy column; required for mode 'two_by_two'.",
    ),
    did_status_col: str = typer.Option(
        "", "--did-status-col",
        help="Per-period treatment-status column; required for mode 'status'.",
    ),
    did_treatment_path: str = typer.Option(
        "", "--did-treatment-path",
        help="Treatment-path column for dCDH (non-absorbing/switching treatment).",
    ),
    cs_control_group: str = typer.Option(
        "", "--cs-control-group",
        help="Callaway-Sant'Anna control group: never | not_yet. Default: never.",
    ),
    cs_est_method: str = typer.Option(
        "", "--cs-est-method",
        help="Callaway-Sant'Anna estimation method: dr | reg | ipw. Default: dr.",
    ),
    cs_base_period: str = typer.Option(
        "", "--cs-base-period",
        help="Callaway-Sant'Anna base period: varying | universal. Default: varying.",
    ),
    cs_cluster_var: str = typer.Option(
        "", "--cs-cluster-var",
        help="Cluster column for Callaway-Sant'Anna inference.",
    ),
    cs_anticipation: int = typer.Option(
        0, "--cs-anticipation",
        help="Anticipation periods for Callaway-Sant'Anna. Default: 0.",
    ),
    honest_did: bool = typer.Option(
        False, "--honest-did",
        help="Run Rambachan-Roth honest-DID sensitivity analysis (slow, opt-in).",
    ),
    prediction_model_type: str = typer.Option(
        "", "--prediction-model-type",
        help="Prediction model: prediction_lasso | prediction_ridge | prediction_random_forest.",
    ),
    prediction_cv_folds: int = typer.Option(
        0, "--prediction-cv-folds",
        help="Cross-validation folds for the prediction model. 0 = engine default.",
    ),
    prediction_sampling_method: str = typer.Option(
        "", "--prediction-sampling-method",
        help="Class-imbalance resampling: smote | oversample | undersample.",
    ),
) -> None:
    from .orchestrator import parse_imputation_request, run_workflow

    result = run_workflow(
        project_root,
        [data_file],
        mode=mode,
        y=y,
        x=x,
        model_type=model_type,
        imputation=parse_imputation_request(imputation),
        entity_col=entity_col,
        time_col=time_col,
        covariance=covariance,
        # Orchestrator gates the IV path on a plain falsy check
        # (`iv_endog or []`), so an empty list is equivalent to None —
        # default invocations never enter the IV path. Mirror the API
        # layer, which passes lists straight through.
        iv_endog=list(iv_endog),
        iv_instruments=list(iv_instruments),
        did_mode=did_mode,
        did_cohort_col=did_cohort_col,
        did_treat_col=did_treat_col,
        did_post_col=did_post_col,
        did_status_col=did_status_col,
        did_treatment_path=did_treatment_path,
        cs_control_group=cs_control_group,
        cs_est_method=cs_est_method,
        cs_base_period=cs_base_period,
        cs_cluster_var=cs_cluster_var,
        cs_anticipation=cs_anticipation,
        honest_did=honest_did,
        prediction_model_type=prediction_model_type,
        prediction_cv_folds=prediction_cv_folds,
        prediction_sampling_method=prediction_sampling_method,
    )
    run_id = result["run_id"]
    # stdout: machine-readable run_id only — preserves the long-standing
    # `RUN_ID=$(workbench run ...)` shell contract.
    typer.echo(run_id)
    # stderr: human-facing copyable URL — visible in terminals, doesn't
    # pollute scripts capturing stdout.
    typer.echo(f"Lineage: {_lineage_url(project_root, run_id)}", err=True)


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
