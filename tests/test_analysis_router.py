import pandas as pd

from workbench.domain import DatasetKind
from workbench.router import classify_dataset


def test_classifies_cross_section_without_time():
    result = classify_dataset(
        pd.DataFrame({"firm_id": [1, 2, 3], "sales": [10, 12, 9]}),
        id_candidates=["firm_id"],
        time_candidates=[],
    )
    assert result["kind"] == DatasetKind.CROSS_SECTION.value


def test_classifies_unbalanced_panel():
    frame = pd.DataFrame(
        {"firm_id": [1, 1, 2], "year": [2020, 2021, 2020], "sales": [10, 11, 20]}
    )
    result = classify_dataset(frame, id_candidates=["firm_id"], time_candidates=["year"])
    assert result["kind"] == DatasetKind.PANEL.value
    assert "panel_unbalanced" in result["secondary_labels"]


def test_classifies_repeated_cross_section():
    frame = pd.DataFrame({"year": [2020, 2020, 2021, 2021], "sales": [1, 2, 3, 4]})
    result = classify_dataset(frame, id_candidates=[], time_candidates=["year"])
    assert result["kind"] == DatasetKind.REPEATED_CROSS_SECTION.value
