# tests/test_term_parser.py
from workbench.term_parser import parse_term, ParsedTerm, is_q_quoted_dummy


def test_plain_term():
    p = parse_term("income")
    assert p == ParsedTerm(
        raw="income",
        display_term="income",
        source_id="income",
        reference_level=None,
        is_dummy=False,
        is_interaction=False,
        transformation_op=None,
        components=("income",),
    )


def test_intercept():
    p = parse_term("Intercept")
    assert p.source_id == "Intercept"
    assert p.is_dummy is False
    assert p.transformation_op is None


def test_c_quoted_single_dummy_with_level():
    p = parse_term("C(Q('region'))[T.north]")
    assert p.source_id == "region"
    assert p.reference_level is None  # parser cannot infer reference from term alone
    assert p.is_dummy is True
    assert p.transformation_op == "C"
    assert p.display_term == "region = north"
    assert p.components == ("region",)


def test_c_quoted_double_dummy_with_level():
    p = parse_term('C(Q("edu"))[T.bachelor]')
    assert p.source_id == "edu"
    assert p.is_dummy is True
    assert p.transformation_op == "C"
    assert p.display_term == "edu = bachelor"


def test_c_unquoted_dummy_with_level():
    p = parse_term("C(region)[T.north]")
    assert p.source_id == "region"
    assert p.is_dummy is True
    assert p.transformation_op == "C"
    assert p.display_term == "region = north"


def test_c_categorical_without_level_marker():
    p = parse_term("C(region)")
    assert p.source_id == "region"
    assert p.is_dummy is False
    assert p.transformation_op == "C"


def test_log_transform():
    p = parse_term("np.log(income)")
    assert p.source_id == "income"
    assert p.transformation_op == "log"
    assert p.display_term == "log(income)"
    assert p.is_dummy is False
    assert p.components == ("income",)


def test_log_with_offset():
    p = parse_term("np.log(income + 1)")
    assert p.source_id == "income"
    assert p.transformation_op == "log"
    assert p.display_term == "log(income + 1)"


def test_sqrt_transform():
    p = parse_term("np.sqrt(age)")
    assert p.source_id == "age"
    assert p.transformation_op == "sqrt"
    assert p.display_term == "sqrt(age)"


def test_interaction_two_continuous():
    p = parse_term("income:age")
    assert p.is_interaction is True
    assert p.components == ("income", "age")
    assert p.source_id == "income:age"
    assert p.transformation_op is None
    assert p.display_term == "income × age"


def test_interaction_with_dummy():
    p = parse_term("C(region)[T.north]:income")
    assert p.is_interaction is True
    assert p.components == ("region", "income")
    assert p.is_dummy is True
    assert p.display_term == "region = north × income"


def test_unknown_form_falls_back_to_raw():
    p = parse_term("some_weird_thing()")
    assert p.raw == "some_weird_thing()"
    assert p.source_id == "some_weird_thing()"
    assert p.display_term == "some_weird_thing()"
    assert p.transformation_op is None
    assert p.is_dummy is False


def test_with_reference_level_arg():
    p = parse_term("C(Q('region'))[T.north]", reference_level="south")
    assert p.reference_level == "south"
