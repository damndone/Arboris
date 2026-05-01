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


def test_clean_frame_deduplicates_normalized_column_names_and_empty_fallbacks():
    frame = pd.DataFrame(
        {
            "Firm ID": [1],
            "Firm-ID": [2],
            "!!!": [3],
            "???": [4],
            "Date": ["2020-01-01"],
        }
    )
    cleaned, actions = clean_frame(frame, date_candidates=["date"])
    assert list(cleaned.columns) == ["firm_id", "firm_id_2", "column", "column_2", "date"]
    assert pd.api.types.is_datetime64_any_dtype(cleaned["date"])
    assert any(action["action"] == "deduplicate_column_names" for action in actions)


def test_clean_frame_avoids_generated_suffix_collisions():
    frame = pd.DataFrame([[1, 2, 3]], columns=["Firm ID", "Firm-ID", "firm_id_2"])

    cleaned, actions = clean_frame(frame, date_candidates=[])

    assert list(cleaned.columns) == ["firm_id", "firm_id_2", "firm_id_2_2"]
    assert cleaned.columns.is_unique
    assert any(action["action"] == "deduplicate_column_names" for action in actions)


def test_recommend_merge_uses_directional_overlap_to_avoid_inner_join_row_loss():
    left = pd.DataFrame({"firm_id": [1, 2, 3, 4, 5], "sales": [10, 12, 13, 14, 15]})
    right = pd.DataFrame({"firm_id": [1], "assets": [20]})
    plan = recommend_merge(left, right, WorkbenchConfig(min_join_overlap=0.5))
    assert plan["join_key"] == "firm_id"
    assert plan["join_type"] == "left"
    assert plan["overlap"] == 1.0
    assert plan["left_overlap"] == 0.2
    assert plan["right_overlap"] == 1.0


def test_recommend_merge_ranks_keys_by_directional_overlap():
    left = pd.DataFrame(
        {
            "country": ["US", "CN", "DE", "FR", "JP"],
            "firm_id": [1, 2, 3, 4, 5],
        }
    )
    right = pd.DataFrame(
        {
            "country": ["US", "US", "US", "US"],
            "firm_id": [1, 2, 3, 4],
        }
    )

    plan = recommend_merge(left, right, WorkbenchConfig(min_join_overlap=0.5))

    assert plan["join_key"] == "firm_id"
    assert plan["join_type"] == "inner"
    assert plan["left_overlap"] == 0.8
    assert plan["right_overlap"] == 1.0
