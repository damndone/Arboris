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


def test_clean_frame_coerces_datetime_column_with_numeric_hint():
    """clean_frame coerces datetime columns with numeric-like names to numeric."""
    frame = pd.DataFrame({
        "policy_years": pd.to_datetime(["1900-01-01", "1900-01-02", "1900-01-03"]),
        "y": [1, 2, 3],
    })
    cleaned, actions = clean_frame(frame, date_candidates=[])
    assert pd.api.types.is_numeric_dtype(cleaned["policy_years"])
    assert any(
        a["action"] == "coerce_to_numeric" and a["column"] == "policy_years"
        for a in actions
    )


def test_clean_frame_leaves_legitimate_date_column():
    """clean_frame does NOT coerce a legitimate date column to numeric."""
    frame = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-01", "2021-06-15", "2022-12-31"]),
        "y": [1, 2, 3],
    })
    cleaned, actions = clean_frame(frame, date_candidates=["date"])
    assert pd.api.types.is_datetime64_any_dtype(cleaned["date"])


def test_clean_frame_skips_date_parsing_for_already_numeric():
    """clean_frame does not re-parse a numeric column as a date candidate."""
    frame = pd.DataFrame({
        "years": [2020, 2021, 2022],
        "y": [1, 2, 3],
    })
    cleaned, actions = clean_frame(frame, date_candidates=["years"])
    assert pd.api.types.is_numeric_dtype(cleaned["years"])
    assert not pd.api.types.is_datetime64_any_dtype(cleaned["years"])
