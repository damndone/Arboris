from __future__ import annotations

import math
from pathlib import Path
import re

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

from .artifacts import register_artifact, write_json

# Cap how many panels a grid figure shows, so a wide dataset can't produce a
# gigantic unreadable (and slow) figure.
_MAX_GRID_COLUMNS = 12
# Numeric columns with <= this many distinct values are treated as categorical
# (e.g. a 0/1 outcome), so we draw counts/grouped boxes instead of a histogram.
_DEFAULT_CAT_MAX_LEVELS = 10
# Cap category levels drawn in a bar/group plot.
_MAX_CATEGORY_LEVELS = 12


def create_figures(
    frame: pd.DataFrame,
    run_root: Path,
    *,
    numeric_columns: list[str],
    time_column: str | None,
    model_results: list[tuple[str, dict]] | None = None,
    outcome_column: str | None = None,
    regressors: list[str] | None = None,
    model_type: str | None = None,
    entity_column: str | None = None,
    iv_endog: list[str] | None = None,
    iv_instruments: list[str] | None = None,
    did_event_study: dict | None = None,
    exposure_column: str | None = None,
    cat_max_levels: int = _DEFAULT_CAT_MAX_LEVELS,
) -> dict[str, str]:
    """Produce diagnostic/EDA figures for a run.

    v1.6.6 V — role- and model-aware. Distribution/relationship plots are drawn
    ONLY for the modelled variables (outcome ∪ regressors), so ID / entity /
    unused columns are never plotted. Each variable's plots match its type
    (continuous → histogram/KDE/box/scatter; categorical → counts/grouped box),
    and each model type adds its own diagnostic plots. Everything registers as
    an ordinary `figure` artifact, so the Table's generic gallery shows them
    all (including any plot type added here later) with no frontend change.
    """
    figures_dir = run_root / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    figures: dict[str, str] = {}

    modeled = _modeled_columns(
        frame, outcome_column, regressors, exposure_column, numeric_columns
    )
    continuous, categorical = _classify_columns(frame, modeled, cat_max_levels)
    outcome_is_continuous = outcome_column in continuous
    mt = _resolve_model_type(model_type, model_results)

    # ── role-aware base (modelled variables only) ───────────────────────
    _plot_histograms(frame, continuous, figures_dir, run_root, figures)
    _plot_kde(frame, continuous, figures_dir, run_root, figures)
    _plot_boxplots(frame, continuous, figures_dir, run_root, figures)
    _plot_correlation_heatmap(frame, continuous, figures_dir, run_root, figures)
    _plot_category_counts(frame, categorical, figures_dir, run_root, figures)
    if outcome_is_continuous:
        x_continuous = [c for c in continuous if c != outcome_column]
        x_categorical = [c for c in categorical if c != outcome_column]
        _plot_scatter(
            frame, outcome_column, x_continuous, mt, figures_dir, run_root, figures
        )
        _plot_group_boxplots(
            frame, outcome_column, x_categorical, figures_dir, run_root, figures
        )
    _plot_time_trend(frame, continuous, time_column, figures_dir, run_root, figures)

    # ── model-fit diagnostics (any model exposing residuals/coefficients) ─
    _plot_model_diagnostics(model_results, figures_dir, run_root, figures)
    _plot_predictor_diagnostics(
        frame,
        regressors or [],
        model_results,
        figures_dir,
        run_root,
        figures,
    )

    # ── model-type-specific plots ───────────────────────────────────────
    _plot_model_specific(
        frame,
        figures_dir,
        run_root,
        figures,
        mt=mt,
        outcome_column=outcome_column,
        model_results=model_results,
        entity_column=entity_column,
        time_column=time_column,
        iv_endog=iv_endog,
        iv_instruments=iv_instruments,
        did_event_study=did_event_study,
    )

    variable_labels = frame.attrs.get("variable_labels", {})
    if isinstance(variable_labels, dict) and variable_labels and "scatter_plots" in figures:
        x_columns = [column for column in continuous if column != outcome_column]
        if x_columns and outcome_column:
            x_column = x_columns[0]
            write_json(
                figures_dir / "figure_labels.json",
                {
                    "scatter_plots": {
                        "x_label": _label_for(frame, x_column),
                        "y_label": _label_for(frame, outcome_column),
                        "title": f"{_label_for(frame, outcome_column)} versus {_label_for(frame, x_column)}",
                    }
                },
            )

    return figures


# ─── column roles & typing ──────────────────────────────────────────────


def _modeled_columns(
    frame: pd.DataFrame,
    outcome_column: str | None,
    regressors: list[str] | None,
    exposure_column: str | None,
    numeric_columns: list[str],
) -> list[str]:
    """Ordered, de-duplicated modelled variables (outcome first, then
    regressors), restricted to columns present in the frame and excluding the
    exposure offset. Falls back to numeric_columns only when neither outcome
    nor regressors are known — so ID/unused columns are excluded whenever the
    analysis roles are available."""
    ordered: list[str] = []
    if outcome_column and regressors is not None:
        candidates = [outcome_column, *regressors]
    elif outcome_column or regressors:
        candidates = [outcome_column or "", *(regressors or [])]
    else:
        candidates = list(numeric_columns)
    for col in candidates:
        if not col or col == exposure_column:
            continue
        if col in frame.columns and col not in ordered:
            ordered.append(col)
    return ordered


def _classify_columns(
    frame: pd.DataFrame, columns: list[str], cat_max_levels: int
) -> tuple[list[str], list[str]]:
    """Split modelled columns into (continuous, categorical). Constant columns
    are dropped from both (nothing meaningful to plot)."""
    continuous: list[str] = []
    categorical: list[str] = []
    for col in columns:
        series = frame[col].dropna()
        distinct = series.nunique()
        if distinct <= 1:
            continue  # constant / empty — skip
        if pd.api.types.is_numeric_dtype(series) and distinct > cat_max_levels:
            continuous.append(col)
        else:
            categorical.append(col)
    return continuous[:_MAX_GRID_COLUMNS], categorical[:_MAX_GRID_COLUMNS]


# ─── low-level helpers ──────────────────────────────────────────────────


def _grid_dims(n: int) -> tuple[int, int]:
    """Roughly-square (rows, cols) for an n-panel grid."""
    cols = max(1, math.ceil(math.sqrt(n)))
    rows = max(1, math.ceil(n / cols))
    return rows, cols


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _label_for(frame: pd.DataFrame, column: str) -> str:
    labels = frame.attrs.get("variable_labels", {})
    if isinstance(labels, dict):
        label = labels.get(str(column))
        if isinstance(label, str) and label:
            return label
    return str(column)


def _value_label_for(frame: pd.DataFrame, column: str, value: object) -> str:
    labels = frame.attrs.get("value_labels", {})
    mapping = labels.get(str(column)) if isinstance(labels, dict) else None
    if isinstance(mapping, dict):
        label = mapping.get(str(value))
        if isinstance(label, str) and label:
            return label
    return str(value)


def _save(fig, path: Path, run_root: Path, artifact_id: str, figures: dict[str, str]) -> None:
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    record = register_artifact(run_root, artifact_id, path, "figure", "visualization", [])
    figures[artifact_id] = record.path


def write_statistical_scatter(
    frame: pd.DataFrame,
    path: Path,
    *,
    x_column: str,
    y_column: str,
) -> int:
    """Write one explicit x/y scatter figure and return the plotted N.

    Registration is intentionally owned by the caller so a repeated
    source-bound exploration can use the same idempotent artifact helper as
    its JSON result.
    """
    aligned = pd.concat(
        [
            pd.to_numeric(frame[x_column], errors="coerce").rename("x"),
            pd.to_numeric(frame[y_column], errors="coerce").rename("y"),
        ],
        axis=1,
    ).dropna()
    if aligned.empty:
        raise ValueError("scatter requires at least one complete x/y row")
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    ax.scatter(aligned["x"], aligned["y"], alpha=0.65, s=18, color="#54a24b")
    ax.set_xlabel(_label_for(frame, x_column))
    ax.set_ylabel(_label_for(frame, y_column))
    ax.set_title(f"{_label_for(frame, y_column)} versus {_label_for(frame, x_column)} (N={len(aligned)})")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return int(len(aligned))


def _new_grid(n: int):
    rows, cols = _grid_dims(n)
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 3.2, rows * 2.6), squeeze=False)
    return fig, axes, rows, cols


def _hide_unused(axes, used: int, rows: int, cols: int) -> None:
    for j in range(used, rows * cols):
        axes[j // cols][j % cols].axis("off")


# ─── role-aware base plots ──────────────────────────────────────────────


def _plot_histograms(frame, columns, figures_dir, run_root, figures) -> None:
    if not columns:
        return
    fig, axes, rows, cols = _new_grid(len(columns))
    drew = False
    for i, column in enumerate(columns):
        ax = axes[i // cols][i % cols]
        data = _numeric_series(frame, column)
        if len(data) > 0:
            bins = min(30, max(5, int(len(data) ** 0.5)))
            ax.hist(data, bins=bins, color="#4c78a8")
            drew = True
        ax.set_title(column, fontsize=9)
    _hide_unused(axes, len(columns), rows, cols)
    if drew:
        _save(fig, figures_dir / "histograms.png", run_root, "histograms", figures)
    else:
        plt.close(fig)


def _plot_kde(frame, columns, figures_dir, run_root, figures) -> None:
    if not columns:
        return
    fig, axes, rows, cols = _new_grid(len(columns))
    plotted = 0
    for i, column in enumerate(columns):
        ax = axes[i // cols][i % cols]
        ax.set_title(column, fontsize=9)
        data = _numeric_series(frame, column)
        try:
            if len(data) >= 2 and float(data.std()) > 0:
                kde = stats.gaussian_kde(data.to_numpy())
                xs = np.linspace(float(data.min()), float(data.max()), 200)
                ys = kde(xs)
                ax.plot(xs, ys, color="#e45756")
                ax.fill_between(xs, ys, alpha=0.3, color="#e45756")
                plotted += 1
        except Exception:
            pass  # degenerate column — leave panel empty rather than fail
    _hide_unused(axes, len(columns), rows, cols)
    if plotted > 0:
        _save(fig, figures_dir / "kde_plots.png", run_root, "kde_plots", figures)
    else:
        plt.close(fig)


def _plot_boxplots(frame, columns, figures_dir, run_root, figures) -> None:
    pairs = [(c, _numeric_series(frame, c)) for c in columns]
    pairs = [(c, s) for c, s in pairs if len(s) > 0]
    if not pairs:
        return
    fig, ax = plt.subplots(figsize=(max(6.0, len(pairs) * 0.9), 4.0))
    ax.boxplot([s.to_numpy() for _, s in pairs])
    ax.set_xticklabels([c for c, _ in pairs], rotation=45, ha="right")
    _save(fig, figures_dir / "boxplots.png", run_root, "boxplots", figures)


def _plot_correlation_heatmap(frame, columns, figures_dir, run_root, figures) -> None:
    if len(columns) < 2:
        return
    correlation = frame[columns].corr(numeric_only=True)
    fig, ax = plt.subplots()
    image = ax.imshow(correlation, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(correlation.columns)), correlation.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(correlation.index)), correlation.index)
    fig.colorbar(image, ax=ax)
    _save(fig, figures_dir / "correlation_heatmap.png", run_root, "correlation_heatmap", figures)


def _plot_category_counts(frame, columns, figures_dir, run_root, figures) -> None:
    if not columns:
        return
    fig, axes, rows, cols = _new_grid(len(columns))
    drew = False
    for i, column in enumerate(columns):
        ax = axes[i // cols][i % cols]
        counts = frame[column].dropna().value_counts().head(_MAX_CATEGORY_LEVELS)
        if len(counts) > 0:
            labels = [_value_label_for(frame, column, idx) for idx in counts.index]
            ax.bar(labels, counts.to_numpy(), color="#72b7b2")
            ax.tick_params(axis="x", labelrotation=45, labelsize=8)
            drew = True
        ax.set_title(_label_for(frame, column), fontsize=9)
    _hide_unused(axes, len(columns), rows, cols)
    if drew:
        _save(fig, figures_dir / "category_counts.png", run_root, "category_counts", figures)
    else:
        plt.close(fig)


def _plot_scatter(frame, outcome, x_continuous, mt, figures_dir, run_root, figures) -> None:
    if not outcome or not x_continuous:
        return
    add_regline = _is_linear(mt)
    fig, axes, rows, cols = _new_grid(len(x_continuous))
    drew = False
    for i, xcol in enumerate(x_continuous):
        ax = axes[i // cols][i % cols]
        aligned = pd.concat(
            [
                pd.to_numeric(frame[xcol], errors="coerce").rename("x"),
                pd.to_numeric(frame[outcome], errors="coerce").rename("y"),
            ],
            axis=1,
        ).dropna()
        if len(aligned) > 0:
            ax.scatter(aligned["x"], aligned["y"], alpha=0.6, s=14, color="#54a24b")
            drew = True
            if add_regline and len(aligned) >= 2 and float(aligned["x"].std()) > 0:
                slope, intercept = np.polyfit(aligned["x"], aligned["y"], 1)
                xs = np.linspace(aligned["x"].min(), aligned["x"].max(), 50)
                ax.plot(xs, slope * xs + intercept, color="#b279a2", linewidth=1.5)
        ax.set_xlabel(_label_for(frame, xcol), fontsize=8)
        ax.set_ylabel(_label_for(frame, outcome), fontsize=8)
    _hide_unused(axes, len(x_continuous), rows, cols)
    if drew:
        _save(fig, figures_dir / "scatter_plots.png", run_root, "scatter_plots", figures)
    else:
        plt.close(fig)


def _plot_group_boxplots(frame, outcome, x_categorical, figures_dir, run_root, figures) -> None:
    if not outcome or not x_categorical:
        return
    fig, axes, rows, cols = _new_grid(len(x_categorical))
    drew = False
    for i, xcol in enumerate(x_categorical):
        ax = axes[i // cols][i % cols]
        sub = frame[[xcol, outcome]].copy()
        sub[outcome] = pd.to_numeric(sub[outcome], errors="coerce")
        sub = sub.dropna()
        levels = sub[xcol].value_counts().head(_MAX_CATEGORY_LEVELS).index.tolist()
        groups = [sub.loc[sub[xcol] == lvl, outcome].to_numpy() for lvl in levels]
        groups = [(str(lvl), g) for lvl, g in zip(levels, groups) if len(g) > 0]
        if groups:
            ax.boxplot([g for _, g in groups])
            ax.set_xticklabels([_value_label_for(frame, xcol, lvl) for lvl, _ in groups], rotation=45, ha="right", fontsize=8)
            ax.set_ylabel(_label_for(frame, outcome), fontsize=8)
            ax.set_title(_label_for(frame, xcol), fontsize=9)
            drew = True
    _hide_unused(axes, len(x_categorical), rows, cols)
    if drew:
        _save(fig, figures_dir / "group_boxplots.png", run_root, "group_boxplots", figures)
    else:
        plt.close(fig)


def _plot_time_trend(frame, continuous, time_column, figures_dir, run_root, figures) -> None:
    if not time_column or time_column not in frame.columns or not continuous:
        return
    plot_frame = frame.sort_values(time_column)
    fig, ax = plt.subplots()
    for column in continuous:
        ax.plot(plot_frame[time_column], plot_frame[column], label=column)
    ax.set_xlabel(time_column)
    ax.legend()
    fig.autofmt_xdate()
    _save(fig, figures_dir / "time_trend.png", run_root, "time_trend", figures)


# ─── model-fit diagnostics (unchanged behaviour) ────────────────────────


def _plot_model_diagnostics(model_results, figures_dir, run_root, figures) -> None:
    model_result = _first_model_result(model_results or [])
    if model_result is None:
        return
    residuals, total = _model_diagnostic_sample(model_result, "residuals")
    fitted, _fitted_total = _model_diagnostic_sample(model_result, "fitted_values")
    if residuals and fitted and len(residuals) == len(fitted):
        scope = (
            f"N={total}" if len(residuals) >= total else f"first {len(residuals)} of {total}"
        )
        fig, ax = plt.subplots()
        ax.scatter(fitted, residuals, alpha=0.75)
        ax.axhline(0, color="#8a94a6", linewidth=1)
        ax.set_xlabel("Fitted values")
        ax.set_ylabel("Residuals")
        ax.set_title(f"Residuals vs fitted values ({scope})")
        _save(fig, figures_dir / "residuals_fitted.png", run_root, "residuals_fitted", figures)

        fig, ax = plt.subplots()
        stats.probplot(residuals, dist="norm", plot=ax)
        ax.set_title(f"Residual Q-Q plot ({scope})")
        _save(fig, figures_dir / "qq_residuals.png", run_root, "qq_residuals", figures)

    coefficient_rows = _coefficient_rows(model_result)
    if coefficient_rows:
        labels = [row[0] for row in coefficient_rows]
        estimates = [row[1] for row in coefficient_rows]
        errors = [1.96 * row[2] for row in coefficient_rows]
        fig, ax = plt.subplots()
        y_positions = range(len(labels))
        ax.errorbar(estimates, y_positions, xerr=errors, fmt="o")
        ax.axvline(0, color="#8a94a6", linewidth=1)
        ax.set_yticks(list(y_positions), labels)
        ax.set_xlabel("Estimate")
        _save(fig, figures_dir / "coef_plot.png", run_root, "coef_plot", figures)


def _plot_predictor_diagnostics(
    frame: pd.DataFrame,
    regressors: list[str],
    model_results,
    figures_dir: Path,
    run_root: Path,
    figures: dict[str, str],
) -> None:
    """Plot model residuals/fitted values against the model predictors.

    The model result preview is aligned through ``analysis_sample.row_order``
    when the OLS contract provides it.  This keeps a missing-value drop from
    silently pairing a residual with the wrong source row; a positional
    fallback is retained for older model results that predate that contract.
    """
    model_result = _first_model_result(model_results or [])
    if model_result is None:
        return
    residuals, residual_total = _model_diagnostic_sample(model_result, "residuals")
    fitted, _fitted_total = _model_diagnostic_sample(model_result, "fitted_values")
    if not residuals or not fitted:
        return
    n = min(len(residuals), len(fitted), len(frame))
    if n == 0:
        return
    aligned = _align_model_preview_frame(frame, model_result, n)
    residual_values = residuals[:n]
    fitted_values = fitted[:n]
    for predictor in dict.fromkeys(regressors):
        if predictor not in aligned.columns:
            continue
        values = pd.to_numeric(aligned[predictor], errors="coerce")
        plot_frame = pd.DataFrame(
            {
                predictor: values.to_numpy(),
                "residuals": residual_values,
                "fitted_values": fitted_values,
            }
        ).dropna()
        if plot_frame.empty:
            continue
        _save_predictor_diagnostic(
            plot_frame,
            predictor,
            "residuals",
            figures_dir,
            run_root,
            figures,
            y_label="Residuals",
            artifact_prefix="residuals_vs",
            analysis_rows=residual_total,
        )
        _save_predictor_diagnostic(
            plot_frame,
            predictor,
            "fitted_values",
            figures_dir,
            run_root,
            figures,
            y_label="Fitted values",
            artifact_prefix="fitted_vs",
            analysis_rows=residual_total,
        )


def _align_model_preview_frame(
    frame: pd.DataFrame,
    model_result: dict,
    n: int,
) -> pd.DataFrame:
    sample = model_result.get("analysis_sample")
    row_order = sample.get("row_order") if isinstance(sample, dict) else None
    if isinstance(row_order, list) and len(row_order) >= n:
        positions = {str(value): position for position, value in enumerate(frame.index)}
        selected = [positions.get(str(value)) for value in row_order[:n]]
        if all(position is not None for position in selected):
            return frame.iloc[[int(position) for position in selected]]
    return frame.iloc[:n]


def _save_predictor_diagnostic(
    plot_frame: pd.DataFrame,
    predictor: str,
    y_column: str,
    figures_dir: Path,
    run_root: Path,
    figures: dict[str, str],
    *,
    y_label: str,
    artifact_prefix: str,
    analysis_rows: int | None = None,
) -> None:
    artifact_suffix = _safe_artifact_suffix(predictor)
    artifact_id = f"{artifact_prefix}_{artifact_suffix}"
    fig, ax = plt.subplots()
    ax.scatter(plot_frame[predictor], plot_frame[y_column], alpha=0.75)
    if y_column == "residuals":
        ax.axhline(0, color="#8a94a6", linewidth=1)
    ax.set_xlabel(predictor)
    ax.set_ylabel(y_label)
    plotted = len(plot_frame)
    total = analysis_rows if isinstance(analysis_rows, int) and analysis_rows > 0 else plotted
    ax.set_title(_diagnostic_title(y_label, predictor, plotted, total))
    _save(
        fig,
        figures_dir / f"{artifact_id}.png",
        run_root,
        artifact_id,
        figures,
    )


def _safe_artifact_suffix(column: str) -> str:
    suffix = re.sub(r"[^0-9A-Za-z_]+", "_", str(column)).strip("_")
    return suffix or "predictor"


# ─── model-type-specific plots ──────────────────────────────────────────


def _plot_model_specific(
    frame,
    figures_dir,
    run_root,
    figures,
    *,
    mt: str,
    outcome_column: str | None,
    model_results,
    entity_column: str | None,
    time_column: str | None,
    iv_endog: list[str] | None,
    iv_instruments: list[str] | None,
    did_event_study: dict | None,
) -> None:
    if _is_binary(mt):
        _plot_pred_prob_by_class(frame, outcome_column, model_results, figures_dir, run_root, figures)
    if _is_count(mt) and outcome_column and outcome_column in frame.columns:
        _plot_outcome_counts(frame, outcome_column, figures_dir, run_root, figures)
    if _is_panel(mt):
        _plot_entity_trends(frame, outcome_column, entity_column, time_column, figures_dir, run_root, figures)
    if _is_iv(mt):
        _plot_iv_first_stage(frame, iv_endog, iv_instruments, figures_dir, run_root, figures)
    if did_event_study:
        _plot_event_study(did_event_study, figures_dir, run_root, figures)


def _plot_pred_prob_by_class(frame, outcome, model_results, figures_dir, run_root, figures) -> None:
    if not outcome or outcome not in frame.columns:
        return
    model_result = _first_model_result(model_results or [])
    if model_result is None:
        return
    fitted = _model_numeric_list(model_result, "fitted_values_preview", "fitted_values")
    if not fitted:
        return
    actual = pd.to_numeric(frame[outcome], errors="coerce").tolist()
    n = min(len(fitted), len(actual))
    if n == 0:
        return
    probs = np.asarray(fitted[:n], dtype=float)
    labels = np.asarray(actual[:n], dtype=float)
    pos = probs[labels == 1.0]
    neg = probs[labels == 0.0]
    if len(pos) == 0 and len(neg) == 0:
        return
    fig, ax = plt.subplots()
    if len(neg) > 0:
        ax.hist(neg, bins=20, alpha=0.6, label="actual = 0", color="#4c78a8")
    if len(pos) > 0:
        ax.hist(pos, bins=20, alpha=0.6, label="actual = 1", color="#e45756")
    ax.set_xlabel("Predicted probability")
    ax.set_ylabel("Count")
    ax.legend()
    _save(fig, figures_dir / "pred_prob_by_class.png", run_root, "pred_prob_by_class", figures)


def _plot_outcome_counts(frame, outcome, figures_dir, run_root, figures) -> None:
    data = _numeric_series(frame, outcome)
    if len(data) == 0:
        return
    fig, ax = plt.subplots()
    hi = int(data.max())
    lo = int(data.min())
    bins = np.arange(lo, hi + 2) - 0.5 if (hi - lo) <= 50 else 30
    ax.hist(data, bins=bins, color="#f58518")
    ax.set_xlabel(outcome)
    ax.set_ylabel("Count")
    ax.set_title("Outcome count distribution", fontsize=10)
    _save(fig, figures_dir / "outcome_counts.png", run_root, "outcome_counts", figures)


def _plot_entity_trends(frame, outcome, entity_column, time_column, figures_dir, run_root, figures) -> None:
    if not (outcome and entity_column and time_column):
        return
    if not {outcome, entity_column, time_column}.issubset(frame.columns):
        return
    sub = frame[[entity_column, time_column, outcome]].copy()
    sub[outcome] = pd.to_numeric(sub[outcome], errors="coerce")
    sub = sub.dropna()
    if sub.empty:
        return
    entities = sub[entity_column].drop_duplicates().head(20).tolist()
    fig, ax = plt.subplots()
    drew = False
    for ent in entities:
        line = sub.loc[sub[entity_column] == ent].sort_values(time_column)
        if len(line) >= 2:
            ax.plot(line[time_column], line[outcome], alpha=0.5, linewidth=0.9)
            drew = True
    ax.set_xlabel(time_column)
    ax.set_ylabel(outcome)
    ax.set_title(f"{outcome} over time by entity (sample)", fontsize=10)
    if drew:
        _save(fig, figures_dir / "entity_trends.png", run_root, "entity_trends", figures)
    else:
        plt.close(fig)


def _plot_iv_first_stage(frame, iv_endog, iv_instruments, figures_dir, run_root, figures) -> None:
    endog = [c for c in (iv_endog or []) if c in frame.columns]
    instruments = [c for c in (iv_instruments or []) if c in frame.columns]
    if not endog or not instruments:
        return
    pairs = [(instr, en) for en in endog for instr in instruments][:_MAX_GRID_COLUMNS]
    fig, axes, rows, cols = _new_grid(len(pairs))
    drew = False
    for i, (instr, en) in enumerate(pairs):
        ax = axes[i // cols][i % cols]
        aligned = pd.concat(
            [
                pd.to_numeric(frame[instr], errors="coerce").rename("x"),
                pd.to_numeric(frame[en], errors="coerce").rename("y"),
            ],
            axis=1,
        ).dropna()
        if len(aligned) > 0:
            ax.scatter(aligned["x"], aligned["y"], alpha=0.6, s=14, color="#54a24b")
            drew = True
        ax.set_xlabel(f"instrument: {instr}", fontsize=8)
        ax.set_ylabel(f"endog: {en}", fontsize=8)
    _hide_unused(axes, len(pairs), rows, cols)
    if drew:
        _save(fig, figures_dir / "iv_first_stage.png", run_root, "iv_first_stage", figures)
    else:
        plt.close(fig)


def _plot_event_study(event_study: dict, figures_dir, run_root, figures) -> None:
    # Accepts both the TWFE shape ({event_time, coef, se}) and the CS/SA/dCDH
    # dynamic-aggregation shape ({event_time, estimate, se}); values may be
    # python lists or numpy arrays.
    raw_coef = event_study.get("coef")
    if raw_coef is None:
        raw_coef = event_study.get("estimate")
    try:
        event_time = list(np.asarray(event_study.get("event_time"), dtype=float))
        coef = list(np.asarray(raw_coef, dtype=float))
    except (TypeError, ValueError):
        return
    if len(event_time) == 0 or len(event_time) != len(coef):
        return
    errors = None
    se = event_study.get("se")
    if se is not None:
        try:
            se_arr = np.asarray(se, dtype=float)
            if len(se_arr) == len(coef):
                errors = [1.96 * float(s) for s in se_arr]
        except (TypeError, ValueError):
            errors = None
    fig, ax = plt.subplots()
    ax.errorbar(event_time, coef, yerr=errors, fmt="o-", capsize=3, color="#4c78a8")
    ax.axhline(0, color="#8a94a6", linewidth=1)
    ax.axvline(-0.5, color="#b279a2", linewidth=1, linestyle="--")
    ax.set_xlabel("Event time")
    ax.set_ylabel("Estimate")
    ax.set_title("Event study", fontsize=10)
    _save(fig, figures_dir / "event_study.png", run_root, "event_study", figures)


# ─── model-type predicates ──────────────────────────────────────────────


def _resolve_model_type(model_type: str | None, model_results) -> str:
    # The requested type may be "auto" (infer from y) — that hides the real
    # family, so prefer the fitted model's actual model_type in that case.
    requested = str(model_type or "").lower()
    if requested and requested != "auto":
        return requested
    mr = _first_model_result(model_results or [])
    if mr:
        return str(mr.get("model_type", "")).lower()
    return requested


def _is_linear(mt: str) -> bool:
    return mt in {"", "ols", "ols_robust", "continuous", "panel_ols"} or "ols" in mt


def _is_binary(mt: str) -> bool:
    return any(k in mt for k in ("logit", "probit", "binomial"))


def _is_count(mt: str) -> bool:
    return any(k in mt for k in ("poisson", "negbin", "negative_binomial"))


def _is_panel(mt: str) -> bool:
    return "panel" in mt


def _is_iv(mt: str) -> bool:
    return "iv" in mt or "2sls" in mt


# ─── model_result parsing helpers (unchanged) ───────────────────────────


def _first_model_result(model_results: list[tuple[str, dict]]) -> dict | None:
    for _, result in model_results:
        if isinstance(result, dict):
            return result
    return None


def _numeric_list(values: object) -> list[float]:
    if not isinstance(values, list):
        return []
    numeric: list[float] = []
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return []
        if pd.isna(parsed):
            return []
        numeric.append(parsed)
    return numeric


def _model_numeric_list(model_result: dict, *keys: str) -> list[float]:
    for key in keys:
        values = _numeric_list(model_result.get(key))
        if values:
            return values
    return []


def _model_diagnostic_sample(model_result: dict, name: str) -> tuple[list[float], int]:
    """Return the plottable vector plus the model's own analysis-sample size.

    The full vector is preferred so a diagnostic plot describes the estimated
    model.  When only the bounded preview exists the caller still learns the
    true ``nobs``, so the figure can say it is showing a prefix instead of
    presenting 500 points as if they were the sample.
    """
    values = _model_numeric_list(model_result, name, f"{name}_preview")
    total = model_result.get("nobs")
    if not isinstance(total, int) or isinstance(total, bool) or total < len(values):
        total = len(values)
    return values, total


def _diagnostic_title(y_label: str, predictor: str, plotted: int, total: int) -> str:
    scope = f"N={total}" if plotted >= total else f"first {plotted} of {total}"
    return f"{y_label} vs {predictor} ({scope})"


def _coefficient_rows(model_result: dict) -> list[tuple[str, float, float]]:
    coefficients = model_result.get("coefficients", {})
    if not isinstance(coefficients, dict):
        return []
    rows: list[tuple[str, float, float]] = []
    for term, values in coefficients.items():
        if term == "Intercept" or str(term).startswith("C("):
            continue
        if not isinstance(values, dict):
            continue
        estimate = values.get("estimate")
        std_error = values.get("std_error")
        try:
            parsed_estimate = float(estimate)
            parsed_std_error = float(std_error)
        except (TypeError, ValueError):
            continue
        if pd.isna(parsed_estimate) or pd.isna(parsed_std_error):
            continue
        rows.append((str(term), parsed_estimate, parsed_std_error))
    return rows
