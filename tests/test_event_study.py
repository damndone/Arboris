import numpy as np

from workbench.engine.event_study import EventStudyBundle
from workbench.engine.cs_inference import multiplier_bootstrap


def _bundle():
    N, L = 50, 4
    rng = np.random.default_rng(0)
    return EventStudyBundle(
        estimates=np.arange(L, dtype=float),
        influence_func=rng.standard_normal((N, L)),
        event_times=np.array([-2.0, -1.0, 0.0, 1.0]),
        cluster_ids=np.arange(N),
        n_switchers=np.array([10, 12, 14, 14]),
        aux={"n_total": N, "row_cluster": np.arange(N)},
    )


def test_event_times_is_sole_axis_and_labels_are_derived():
    b = _bundle()
    assert b.labels == ["placebo", "placebo", "effect", "effect"]
    # labels is a derived property, not a stored dataclass field
    assert "labels" not in b.__dataclass_fields__


def test_multiplier_bootstrap_consumes_raw_arrays_not_the_bundle_type():
    b = _bundle()
    # MUST pass arrays — multiplier_bootstrap must not depend on EventStudyBundle.
    out = multiplier_bootstrap(b.influence_func, B=200, alpha=0.05, seed=1,
                               estimates=b.estimates, clusters=b.aux["row_cluster"])
    assert out["uniform_band"].shape == (4, 2)
    assert "uniform_crit" in out
