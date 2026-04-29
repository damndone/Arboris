import pandas as pd

from workbench.cleaning import clean_frame
from workbench.config import WorkbenchConfig
from workbench.merge import recommend_merge


def test_recommend_merge_uses_overlap_and_uniqueness():
    left = pd.DataFrame({"firm_id": [1, 2, 3], "sales": [10, 12, 13]})
    right = pd.DataFrame({"firm_id": [1, 2, 4], "assets": [20, 30, 40]})
    plan = recommend_merge(left, right, WorkbenchConfig(min_join_overlap=0.5))
    assert plan["join_key"] == "firm_id"
    assert plan["join_type"] == "inner"
    assert plan["confidence"] >= 0.5


def test_clean_frame_normalizes_columns_and_records_actions():
    frame = pd.DataFrame({"Firm ID": [1, 1, 2], "Year": ["2020", "2020", "2021"], "Sales": [10.0, 10.0, None]})
    cleaned, actions = clean_frame(frame, date_candidates=["year"])
    assert list(cleaned.columns) == ["firm_id", "year", "sales"]
    assert len(cleaned) == 2
    assert any(action["action"] == "drop_duplicate_rows" for action in actions)
