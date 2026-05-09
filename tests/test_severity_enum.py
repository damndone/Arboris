from workbench.domain import Severity


def test_severity_has_four_levels():
    assert Severity.BLOCKER == Severity.BLOCKER
    assert Severity.WARNING == Severity.WARNING
    assert Severity.CAUTION == Severity.CAUTION
    assert Severity.INFO == Severity.INFO
    assert len(Severity) == 4


def test_severity_ordering():
    levels = [Severity.BLOCKER, Severity.WARNING, Severity.CAUTION, Severity.INFO]
    assert levels == sorted(levels, key=lambda s: ["BLOCKER", "WARNING", "CAUTION", "INFO"].index(s.value))


def test_caution_value_is_caution():
    assert Severity.CAUTION.value == "CAUTION"
