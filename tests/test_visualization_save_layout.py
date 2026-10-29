"""Real-renderer regressions for saving an already laid-out PNG figure."""

import matplotlib
from matplotlib.layout_engine import PlaceHolderLayoutEngine
from matplotlib.text import Text
import numpy as np
from PIL import Image
import pytest

from workbench import visualization as viz
from workbench.projects import create_project, create_run


DEFAULT_RC = {
    "figure.autolayout": False,
    "figure.constrained_layout.use": False,
    "savefig.bbox": None,
    "savefig.dpi": "figure",
    "figure.dpi": 100,
}


def _run(tmp_path):
    project = create_project(tmp_path, "layout")
    return create_run(project.root, mode="auto")


def _array(values):
    if values is None:
        return None
    array = np.asarray(values)
    return array.shape, array.dtype.str, array.tobytes()


def _figure_state(fig):
    """Compare source artists and their final layout, excluding renderer caches."""
    axes = []
    for ax in fig.axes:
        legend = ax.get_legend()
        axes.append({
            "bounds": tuple(ax.get_position().bounds),
            "limits": (ax.get_xlim(), ax.get_ylim()),
            "scales": (ax.get_xscale(), ax.get_yscale()),
            "labels": (ax.get_title(), ax.get_xlabel(), ax.get_ylabel()),
            "lines": [(_array(line.get_xdata()), _array(line.get_ydata()),
                       line.get_label(), line.get_color(), line.get_linestyle(),
                       line.get_marker(), line.get_linewidth()) for line in ax.lines],
            "collections": [
                (type(collection).__name__, _array(collection.get_offsets()),
                 tuple((_array(path.vertices), _array(path.codes)) for path in collection.get_paths()),
                 _array(collection.get_array()), _array(collection.get_facecolors()),
                 _array(collection.get_edgecolors()), _array(collection.get_linewidths()),
                 collection.get_clim(), collection.get_cmap().name)
                for collection in ax.collections
            ],
            "images": [(_array(image.get_array()), tuple(image.get_extent()),
                        image.get_clim(), image.get_cmap().name) for image in ax.images],
            "patches": [(_array(patch.get_path().vertices), _array(patch.get_path().codes),
                         _array(patch.get_patch_transform().get_matrix()),
                         patch.get_facecolor(), patch.get_edgecolor()) for patch in ax.patches],
            "texts": [(text.get_text(), text.get_position(), text.get_rotation(),
                       text.get_fontsize(), text.get_ha(), text.get_va(), text.get_visible())
                      for text in ax.findobj(Text)],
            "legend": None if legend is None else (
                legend.get_title().get_text(), tuple(text.get_text() for text in legend.get_texts()),
                tuple(legend.get_window_extent().bounds)),
        })
    return {"size_inches": tuple(fig.get_size_inches()), "dpi": fig.dpi, "axes": axes}


def _figure(kind):
    # Explicitly start without an engine so rc guard tests also cover the
    # public None API's ability to re-enable a different automatic engine.
    fig, ax = viz.plt.subplots(layout="none")
    if kind == "legend":
        ax.plot([0, 1, 2], [0.5, 1.5, -1], label="Estimated relationship")
        ax.scatter([0, 1, 2], [0.4, 1.6, -0.9], label="Observed values")
        ax.legend(title="Model and data")
        ax.set_xlabel("Completed education (years)")
        ax.set_ylabel("Hourly earnings (USD)")
    elif kind == "colorbar":
        image = ax.imshow(np.array([[1.0, 0.3], [0.3, 1.0]]), vmin=-1, vmax=1)
        ax.set_xticks([0, 1], ["Education (years)", "Weekly hours"], rotation=45, ha="right")
        ax.set_yticks([0, 1], ["Education (years)", "Weekly hours"])
        fig.colorbar(image, ax=ax)
    elif kind == "coefficients":
        ax.errorbar([0.8, 0.2, -0.4], [0, 1, 2], xerr=[0.12, 0.08, 0.2], fmt="o")
        ax.axvline(0, color="#8a94a6")
        ax.set_yticks([0, 1, 2], ["Education (years)", "Potential experience (years)", "Group indicator"])
        ax.set_xlabel("Estimate")
    else:
        raise ValueError(kind)
    ax.set_title("Small rendering fixture")
    return fig


def _legacy_save(fig, path):
    """The existing layout/save prefix, using the same real backend and DPI."""
    fig.tight_layout()
    fig.savefig(path)
    state = _figure_state(fig)
    engine = type(fig.get_layout_engine())
    viz._close_figure(fig)
    return state, engine


def _save_and_observe(fig, path, run_root, monkeypatch):
    observed = []
    close = viz._close_figure

    def observe_and_close(saved):
        observed.append((_figure_state(saved), type(saved.get_layout_engine())))
        close(saved)

    figures = {}
    with monkeypatch.context() as observer:
        observer.setattr(viz, "_close_figure", observe_and_close)
        viz._save(fig, path, run_root, "candidate", figures)
    assert len(observed) == 1
    assert not fig.axes
    assert figures["candidate"] == str(path.relative_to(run_root))
    return observed[0]


def _png(path):
    with Image.open(path) as image:
        return image.size, image.mode, image.info.copy(), image.convert("RGBA").tobytes()


def test_default_png_save_does_not_repeat_completed_layout(tmp_path):
    with matplotlib.rc_context(DEFAULT_RC):
        run = _run(tmp_path)
        fig = _figure("colorbar")
        draws = []
        fig.canvas.mpl_connect("draw_event", lambda event: draws.append(event.name))
        viz._save(fig, run.root / "figure.png", run.root, "figure", {})

    # Real Agg draw events include the non-raster layout prepass if it occurs.
    assert draws == ["draw_event"]


@pytest.mark.parametrize("kind", ["legend", "colorbar", "coefficients"])
def test_default_png_preserves_pixels_artists_and_metadata(tmp_path, monkeypatch, kind):
    rc_before = {key: matplotlib.rcParams[key] for key in DEFAULT_RC}
    with matplotlib.rc_context(DEFAULT_RC):
        run = _run(tmp_path)
        baseline = run.root / "baseline.png"
        candidate = run.root / "candidate.png"
        old_state, old_engine = _legacy_save(_figure(kind), baseline)
        new_state, new_engine = _save_and_observe(_figure(kind), candidate, run.root, monkeypatch)

        assert old_engine is PlaceHolderLayoutEngine
        assert new_engine is type(None)
        assert new_state == old_state
        assert candidate.read_bytes() == baseline.read_bytes()
        assert _png(candidate) == _png(baseline)
        assert {key: matplotlib.rcParams[key] for key in DEFAULT_RC} == DEFAULT_RC
    assert {key: matplotlib.rcParams[key] for key in DEFAULT_RC} == rc_before


@pytest.mark.parametrize(
    "overrides,suffix",
    [
        pytest.param({"figure.autolayout": True}, ".png", id="automatic-tight"),
        pytest.param({"figure.constrained_layout.use": True}, ".png", id="automatic-constrained"),
        pytest.param({"figure.autolayout": True, "figure.constrained_layout.use": True}, ".png", id="both-automatic"),
        pytest.param({"savefig.bbox": "tight"}, ".png", id="tight-cropping"),
        pytest.param({}, ".svg", id="vector-svg"),
    ],
)
def test_nondefault_save_retains_existing_layout_behavior(tmp_path, monkeypatch, overrides, suffix):
    expected_rc = {**DEFAULT_RC, **overrides}
    rc_before = {key: matplotlib.rcParams[key] for key in DEFAULT_RC}
    with matplotlib.rc_context(expected_rc):
        run = _run(tmp_path)
        baseline = run.root / f"baseline{suffix}"
        candidate = run.root / f"candidate{suffix}"
        old_state, old_engine = _legacy_save(_figure("colorbar"), baseline)
        new_state, new_engine = _save_and_observe(_figure("colorbar"), candidate, run.root, monkeypatch)

        assert old_engine is PlaceHolderLayoutEngine
        assert new_engine is old_engine
        assert new_state == old_state
        if suffix == ".png":
            assert candidate.read_bytes() == baseline.read_bytes()
            assert _png(candidate) == _png(baseline)
        assert {key: matplotlib.rcParams[key] for key in DEFAULT_RC} == expected_rc
    assert {key: matplotlib.rcParams[key] for key in DEFAULT_RC} == rc_before
