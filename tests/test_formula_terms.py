"""Column references in model formulas round-trip exactly (V1811-PUBLIC-TERM-QUOTE).

Formulas reference a column as ``Q(<Python string literal>)``: ``Q('x')``, or
``Q("o'brien")`` when the name holds a single quote, with backslash escapes
when it holds both quotes or a backslash. Until v1.8.12 seven readers undid
this by hand and only for the plain single-quoted form, so a column name with
a quote came back with its escapes, or not at all -- and the egress redactor
did not recognise the double-quoted form, so a protected column's category
levels went out unredacted. Every reader now goes through
``workbench.formula_terms``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.formula_terms import quote_column, unquote_column

NAMES = [
    "x",
    "o'brien",
    'say "hi"',
    """both ' and " quotes""",
    "back\\slash",
    "tab\there",
    "收入 (元)",
    "ratio: a/b",
    "a)b(c",
    "",
]


@pytest.mark.parametrize("name", NAMES)
def test_quote_and_unquote_round_trip(name: str) -> None:
    assert unquote_column(quote_column(name)) == name


@pytest.mark.parametrize("text", ["x", "Q(x)", "Q('x') + 1", "C(Q('x'))[T.a]", "Q(1)", "Q('x'"])
def test_only_a_whole_column_reference_unquotes(text: str) -> None:
    assert unquote_column(text) is None


@pytest.mark.parametrize("name", NAMES[:-1])
def test_every_reader_recovers_the_column(name: str) -> None:
    from workbench.checks.context import public_column, term_label
    from workbench.diagnostic_summary import _term_base_name
    from workbench.econometrics.normalize import _public_term
    from workbench.term_labels import term_display_label
    from workbench.term_parser import parse_term

    quoted = quote_column(name)
    dummy = f"C({quoted})[T.level 1]"
    assert _public_term(quoted) == name
    assert term_label(quoted) == name
    assert public_column(dummy) == f"{name}[level 1]"
    assert _term_base_name(dummy) == name
    assert term_display_label(quoted, variable_labels={name: "Label"}) == "Label"
    assert term_display_label(dummy, value_labels={name: {"level 1": "One"}}) == f"{name}: One"
    parsed = parse_term(dummy)
    assert (parsed.source_id, parsed.is_dummy, parsed.display_term) == (name, True, f"{name} = level 1")


@pytest.mark.parametrize("name", NAMES[:-1])
def test_the_exported_python_script_recovers_the_column(name: str) -> None:
    from workbench.script_export.exporters.models import PY_MODEL_HELPER

    namespace: dict = {}
    exec(PY_MODEL_HELPER.split("def wb_model", 1)[0], namespace)
    assert namespace["wb_public"](quote_column(name)) == name
    assert namespace["wb_public"]("Intercept") == "Intercept"


@pytest.mark.parametrize("name", ["o'brien", """both ' and " quotes"""])
def test_a_protected_columns_levels_are_withheld_whatever_its_quoting(monkeypatch, tmp_path: Path, name: str) -> None:
    from test_egress import REMOTE, _conversation, _send, _tool_content

    from workbench.egress import EgressPolicy, egress_project, save_policy

    term = f"C({quote_column(name)})[T.Alice]"
    save_policy(tmp_path, EgressPolicy(columns={name: "restricted"}))
    with egress_project(tmp_path):
        body = _send(
            monkeypatch,
            _conversation("inspect_data_schema", {"ok": True, "output": {"terms": [term, "age"]}}),
            REMOTE,
        )
    assert "Alice" not in json.dumps(body, ensure_ascii=False)
    assert _tool_content(body)["output"]["terms"] == [f"C({quote_column(name)})[withheld]", "age"]


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(8)
    n = 120
    group = np.repeat(["a", "b", "c"], n // 3)
    x = rng.normal(size=n)
    y = 1 + 0.5 * x + (group == "b") * 0.8 + rng.normal(size=n)
    return pd.DataFrame({"y'out": y, "o'brien": x, 'say "g"': group})


def test_ols_reports_the_users_column_names() -> None:
    from workbench.econometrics.runner import run_ols

    result, _ = run_ols(_frame(), "y'out", ["o'brien", 'say "g"'], False, "model", categorical_x={'say "g"'})
    assert "o'brien" in result["coefficients"]


def test_anova_fits_and_reports_quoted_factor_names() -> None:
    from workbench.engine.packs.anova.estimation import fit_anova

    result = fit_anova(
        _frame(), y="y'out", x=['say "g"', "o'brien"],
        options={"sums_of_squares": 2, "categorical": ['say "g"']}, model_id="anova_1",
    )
    assert {row["term"] for row in result["anova_table"]} == {'say "g"', "o'brien", "Residuals"}


@pytest.mark.parametrize("name", NAMES)
def test_the_json_quoted_form_manova_records_reads_back(name: str) -> None:
    # MANOVA records its formula with JSON-quoted names (part of its result envelope).
    assert unquote_column(f"Q({json.dumps(name, ensure_ascii=False)})") == name


# A literal the pattern matches but Python cannot decode (`\N` with no name).
MALFORMED = "Q('bad\\N')"


def test_an_undecodable_literal_is_not_a_column() -> None:
    from workbench.formula_terms import categorical_level, public_term

    assert unquote_column(MALFORMED) is None
    assert public_term(MALFORMED) == MALFORMED
    assert categorical_level(f"C({MALFORMED})[T.a]") is None


def test_an_undecodable_term_level_is_withheld_not_sent(monkeypatch, tmp_path: Path) -> None:
    from test_egress import REMOTE, _conversation, _send, _tool_content

    from workbench.egress import EgressPolicy, egress_project, read_audit, save_policy

    save_policy(tmp_path, EgressPolicy(columns={"name": "restricted"}))
    with egress_project(tmp_path):
        body = _send(
            monkeypatch,
            _conversation("inspect_data_schema", {"ok": True, "output": {"terms": [f"C({MALFORMED})[T.Alice]"]}}),
            REMOTE,
        )
    assert "Alice" not in json.dumps(body, ensure_ascii=False)
    assert _tool_content(body)["output"]["terms"] == [f"C({MALFORMED})[withheld]"]
    assert read_audit(tmp_path)[0]["redacted_columns"] == ["'bad\\N'"]
