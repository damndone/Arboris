import pytest

from workbench.engine.iv_spec import validate_iv_spec, IVSpecError


def test_valid_spec_passes():
    # 1 endog, 2 instruments (over-identified), no overlap
    validate_iv_spec(y="wage", exog=["age"], endog=["educ"],
                     instruments=["dist", "momeduc"])


def test_empty_endog_raises():
    with pytest.raises(IVSpecError) as exc:
        validate_iv_spec(y="wage", exog=["age"], endog=[], instruments=["dist"])
    assert "endogenous" in str(exc.value).lower()


def test_empty_instruments_raises():
    with pytest.raises(IVSpecError):
        validate_iv_spec(y="wage", exog=["age"], endog=["educ"], instruments=[])


def test_order_condition_violation_raises():
    # 2 endog, 1 instrument => under-identified
    with pytest.raises(IVSpecError) as exc:
        validate_iv_spec(y="wage", exog=[], endog=["educ", "exp"],
                         instruments=["dist"])
    assert "identif" in str(exc.value).lower()


def test_overlap_between_buckets_raises():
    with pytest.raises(IVSpecError) as exc:
        validate_iv_spec(y="wage", exog=["educ"], endog=["educ"],
                         instruments=["dist"])
    assert "educ" in str(exc.value)


def test_y_in_a_bucket_raises():
    with pytest.raises(IVSpecError):
        validate_iv_spec(y="wage", exog=["wage"], endog=["educ"],
                         instruments=["dist"])


def test_duplicate_instrument_within_bucket_raises():
    with pytest.raises(IVSpecError) as exc:
        validate_iv_spec(y="wage", exog=[], endog=["educ"],
                         instruments=["dist", "dist"])
    assert "dist" in str(exc.value)


def test_duplicate_endog_within_bucket_raises():
    with pytest.raises(IVSpecError):
        validate_iv_spec(y="wage", exog=[], endog=["educ", "educ"],
                         instruments=["z1", "z2"])
