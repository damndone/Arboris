import pandas as pd
from workbench.variable_roles import infer_variable_roles


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(result, var):
    """Unpack the return dict and return the role list for *var*."""
    return result[var]["roles"]


# ---------------------------------------------------------------------------
# Existing tests (updated for new return format)
# ---------------------------------------------------------------------------

def test_treatment_confirmed_by_name_and_binary_data():
    frame = pd.DataFrame({"x8_treatment": [0, 1, 0, 1, 0, 1, 0, 1]})
    result = infer_variable_roles(frame, ["x8_treatment"])
    role_list = _get(result, "x8_treatment")
    assert any(r["role"] == "treatment" and r["status"] == "confirmed_by_rules" for r in role_list)


def test_treatment_candidate_name_only_if_not_binary():
    frame = pd.DataFrame({"x1_treatment": [0.1, 0.5, 1.2, 3.4, 5.0, 2.1, 0.3, 7.8]})
    result = infer_variable_roles(frame, ["x1_treatment"])
    role_list = _get(result, "x1_treatment")
    treatment_roles = [r for r in role_list if r["role"] == "treatment"]
    assert all(r["status"] == "candidate" for r in treatment_roles)


def test_binary_without_name_hint_is_candidate_treatment():
    frame = pd.DataFrame({"commercial_use": [0, 1, 0, 1, 0, 1, 0, 1]})
    result = infer_variable_roles(frame, ["commercial_use"])
    role_list = _get(result, "commercial_use")
    assert not any(r["role"] == "treatment" and r["status"] == "confirmed_by_rules" for r in role_list)


def test_categorical_confirmed_by_name_and_low_unique():
    frame = pd.DataFrame({"x7_region_code": [1, 2, 3, 4] * 10})
    result = infer_variable_roles(frame, ["x7_region_code"])
    role_list = _get(result, "x7_region_code")
    assert any(r["role"] == "categorical" and r["status"] == "confirmed_by_rules" for r in role_list)


def test_string_column_confirmed_categorical():
    frame = pd.DataFrame({"city": ["NYC", "LA", "SF"] * 10})
    result = infer_variable_roles(frame, ["city"])
    role_list = _get(result, "city")
    cat_roles = [r for r in role_list if r["role"] == "categorical"]
    assert any(r["status"] == "confirmed_by_rules" for r in cat_roles)


def test_binary_excluded_from_categorical():
    frame = pd.DataFrame({"flag": [0, 1, 0, 1, 0, 1]})
    result = infer_variable_roles(frame, ["flag"])
    role_list = _get(result, "flag")
    assert not any(r["role"] == "categorical" and r["status"] != "rejected" for r in role_list)


def test_exposure_candidate_with_name_and_positive_numeric():
    frame = pd.DataFrame({"x2_exposure": [10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0]})
    result = infer_variable_roles(frame, ["x2_exposure"], y_type="count")
    role_list = _get(result, "x2_exposure")
    exposure_roles = [r for r in role_list if r["role"] == "exposure"]
    assert len(exposure_roles) >= 1


def test_id_confirmed_by_name_and_high_unique():
    frame = pd.DataFrame({"firm_id": list(range(100))})
    result = infer_variable_roles(frame, ["firm_id"])
    role_list = _get(result, "firm_id")
    assert any(r["role"] == "id" and r["status"] == "confirmed_by_rules" for r in role_list)


def test_evidence_includes_name_and_data_hints():
    frame = pd.DataFrame({"x7_region_code": [1, 2, 3, 4] * 10})
    result = infer_variable_roles(frame, ["x7_region_code"])
    # Find the categorical role which carries the name hints for "region_code"
    cat_role = next(r for r in _get(result, "x7_region_code") if r["role"] == "categorical")
    assert len(cat_role["evidence"]["name_hints"]) > 0
    assert len(cat_role["evidence"]["data_hints"]) > 0
    assert "unique_count" in cat_role["evidence"]


# ---------------------------------------------------------------------------
# BUG-REGRESSION TESTS
# ---------------------------------------------------------------------------

def test_proxy_candidate_by_name():
    """Column named 'x10_interaction_proxy' with continuous data gets a proxy candidate."""
    frame = pd.DataFrame({"x10_interaction_proxy": [1.2, 3.4, 5.6, 7.8] * 25})
    result = infer_variable_roles(frame, ["x10_interaction_proxy"])
    role_list = _get(result, "x10_interaction_proxy")
    proxy_roles = [r for r in role_list if r["role"] == "proxy"]
    assert any(r["status"] == "candidate" for r in proxy_roles)


def test_time_confirmed_by_datetime_dtype():
    """A pd.date_range column is confirmed as time, and NOT a spurious categorical candidate."""
    dates = pd.date_range("2020-01-01", periods=30, freq="D")
    frame = pd.DataFrame({"event_date": dates})
    result = infer_variable_roles(frame, ["event_date"])
    role_list = _get(result, "event_date")

    # time confirmed
    time_roles = [r for r in role_list if r["role"] == "time"]
    assert any(r["status"] == "confirmed_by_rules" for r in time_roles)

    # categorical NOT candidate (BUG 4 regression)
    cat_roles = [r for r in role_list if r["role"] == "categorical"]
    assert not any(r["status"] == "candidate" for r in cat_roles)


def test_empty_frame():
    """0-row DataFrame does not crash.  Existing column is still processed."""
    frame = pd.DataFrame({"a": pd.Series([], dtype="int64")})
    result = infer_variable_roles(frame, ["a"])
    # The column exists so it is processed (all roles rejected), but no crash
    assert "a" in result
    assert isinstance(result["a"]["roles"], list)


def test_missing_column_silently_skipped():
    """Non-existent columns are silently skipped (not in result, no special key)."""
    frame = pd.DataFrame({"x1": [1, 2, 3]})
    result = infer_variable_roles(frame, ["x1", "ghost_column"])
    assert "x1" in result
    assert "ghost_column" not in result


def test_all_nan_column():
    """All-NaN column does not crash."""
    frame = pd.DataFrame({"all_nan": [float("nan")] * 10})
    result = infer_variable_roles(frame, ["all_nan"])
    role_list = _get(result, "all_nan")
    # Should produce some output without error
    assert isinstance(role_list, list)
    assert len(role_list) > 0


def test_empty_x_vars():
    """Empty x_vars list returns empty roles dict."""
    frame = pd.DataFrame({"a": [1, 2, 3]})
    result = infer_variable_roles(frame, [])
    assert result == {}


# ---------------------------------------------------------------------------
# BUG 3: string_dtype detection
# ---------------------------------------------------------------------------

def test_mixed_type_column_not_string_dtype():
    """A column with mixed types is NOT falsely flagged as string_dtype (BUG 3 regression)."""
    frame = pd.DataFrame({"mixed": [1, "two", 3.0, None, "five"]})
    result = infer_variable_roles(frame, ["mixed"])
    role_list = _get(result, "mixed")
    cat_roles = [r for r in role_list if r["role"] == "categorical"]
    # Mixed-type columns should NOT be confirmed_by_rules as categorical
    # (only truly string-typed columns get that)
    assert not any(r["status"] == "confirmed_by_rules" for r in cat_roles)


# ---------------------------------------------------------------------------
# BUG 5: needs_user_confirmation consistency
# ---------------------------------------------------------------------------

def test_candidate_always_needs_confirmation():
    """Every role entry with status='candidate' has needs_user_confirmation=True."""
    n = 9
    frame = pd.DataFrame({
        "treatment_var": [0, 1, 0, 1, 0, 1, 0, 1, 0],
        "proxy_var": [0.5, 1.2, 3.4, 5.6, 7.8, 9.0, 1.1, 2.2, 3.0],
        "city": ["NYC", "LA", "SF"] * 3,
    })
    # Rename columns to trigger proxy name hints
    frame = frame.rename(columns={"proxy_var": "x1_interaction_proxy"})
    result = infer_variable_roles(frame, ["treatment_var", "x1_interaction_proxy", "city"])
    for var in ["treatment_var", "x1_interaction_proxy", "city"]:
        for role_entry in _get(result, var):
            if role_entry["status"] == "candidate":
                assert role_entry["needs_user_confirmation"] is True, (
                    f"{var} / {role_entry['role']} candidate missing needs_user_confirmation"
                )
            else:
                assert role_entry["needs_user_confirmation"] is False, (
                    f"{var} / {role_entry['role']} {role_entry['status']} should not need confirmation"
                )


# ---------------------------------------------------------------------------
# BUG 6: rejected status present for every role
# ---------------------------------------------------------------------------

def test_rejected_status_for_all_roles():
    """A plain continuous column with no hinting keywords gets rejected for every role."""
    # Use >20 unique values so categorical is rejected, not candidate
    frame = pd.DataFrame({"plain": list(range(30))})
    # make it float to avoid integer hint complications
    frame["plain"] = frame["plain"].astype(float)
    result = infer_variable_roles(frame, ["plain"])
    role_list = _get(result, "plain")
    role_names = {r["role"] for r in role_list}
    expected_roles = {"treatment", "categorical", "proxy", "exposure", "id", "time"}
    assert role_names == expected_roles
    for r in role_list:
        assert r["status"] == "rejected", f"{r['role']} should be rejected, got {r['status']}"


# ---------------------------------------------------------------------------
# BUG 1: non-string x_vars
# ---------------------------------------------------------------------------

def test_non_string_x_var_does_not_crash():
    """Passing non-string column names (int, float) does not crash (BUG 1 regression)."""
    frame = pd.DataFrame({0: [1, 2, 3], 1: [0, 1, 0], "city": ["NYC", "LA", "SF"]})
    result = infer_variable_roles(frame, [0, 1, "city"])
    assert 0 in result
    assert 1 in result
    assert "city" in result


# ---------------------------------------------------------------------------
# New tests: exposure confidence vs y_type
# ---------------------------------------------------------------------------

def test_exposure_confidence_vs_y_type():
    """Exposure confidence is 0.85 for y_type='count', 0.55 otherwise."""
    frame = pd.DataFrame({"x2_exposure": [10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0]})

    result_count = infer_variable_roles(frame, ["x2_exposure"], y_type="count")
    exposure_count = [r for r in _get(result_count, "x2_exposure") if r["role"] == "exposure"]
    assert len(exposure_count) >= 1
    assert exposure_count[0]["confidence"] == 0.85

    result_cont = infer_variable_roles(frame, ["x2_exposure"], y_type="continuous")
    exposure_cont = [r for r in _get(result_cont, "x2_exposure") if r["role"] == "exposure"]
    assert len(exposure_cont) >= 1
    assert exposure_cont[0]["confidence"] == 0.55


# ---------------------------------------------------------------------------
# New tests: categorical nunique boundary
# ---------------------------------------------------------------------------

def test_categorical_nunique_boundary():
    """nunique=21 without name hints should NOT be confirmed categorical (needs <=20)."""
    # 21 unique values (above threshold), no name hints -- cannot be confirmed
    frame = pd.DataFrame({"plain": list(range(21))})
    result = infer_variable_roles(frame, ["plain"])
    cat_role = next(r for r in _get(result, "plain") if r["role"] == "categorical")
    assert cat_role["status"] != "confirmed_by_rules"

    # 20 unique values WITH name hint should be confirmed
    frame2 = pd.DataFrame({"x7_region_code": list(range(20))})
    result2 = infer_variable_roles(frame2, ["x7_region_code"])
    cat_role2 = next(r for r in _get(result2, "x7_region_code") if r["role"] == "categorical")
    assert cat_role2["status"] == "confirmed_by_rules"
