"""Column fingerprints cover date and duration columns (they have no numpy buffer)."""

import numpy as np
import pandas as pd

from workbench.services.completion_products import array_fingerprint, frame_fingerprint


def test_frames_with_dates_and_durations_have_stable_distinct_fingerprints():
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0], "date": pd.date_range("2020-01-01", periods=3),
                          "gap": pd.to_timedelta([1, 2, 3], unit="D"), "label": ["a", "b", "c"]})
    first = frame_fingerprint(frame)
    assert first == frame_fingerprint(frame.copy())
    later = frame.assign(date=frame["date"] + pd.Timedelta(days=1))
    assert frame_fingerprint(later) != first


def test_the_unit_of_a_date_array_is_part_of_its_fingerprint():
    ticks = np.array([1, 2, 3], dtype="i8")
    assert array_fingerprint(ticks.view("M8[s]")) != array_fingerprint(ticks.view("M8[ns]"))
    assert array_fingerprint(ticks.view("M8[s]")) != array_fingerprint(ticks)


def test_plain_fingerprints_are_unchanged():
    # Computed with the code before the date fix: existing identities stay valid.
    assert array_fingerprint(np.array([1.5, -0.0, 2.25])) == "b2307b2da9cc6695291958b2c52abec0f0eb73aeac461177a4f36faef5c2d393"
    assert frame_fingerprint(pd.DataFrame({"x": [1.0, 2.0], "k": [1, 2], "s": ["a", "b"]})) == "334e2f534c3e3feee7fafc954e75ca15c9a79a4a9de457e10633f6468552eb5b"
