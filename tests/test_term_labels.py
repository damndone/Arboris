from __future__ import annotations

import pytest

from workbench.report_view_model import build_regression_table
from workbench.term_labels import term_display_label

VARIABLES = {"region": "地区", "educ": "受教育年限", "experience": "工作经验", "gender": "性别"}
VALUES = {"region": {"1": "北方", "2": "南方", "3": "西部"}, "gender": {"1": "男", "2": "女"}}


@pytest.mark.parametrize(
    ("term", "expected"),
    [
        ("C(Q('region'))[T.2]", "地区: 南方"),
        ('C(Q("region"))[T.3.0]', "地区: 西部"),
        ("C(region)[T.2]", "地区: 南方"),
        ("C(region, Treatment(reference=1))[T.3]", "地区: 西部"),
        ("C(Q('region'))[T.9]", "地区: 9"),
        ("Q('educ')", "受教育年限"),
        ("educ", "受教育年限"),
        ("experience_pow2", "工作经验²"),
        ("I(experience ** 3)", "工作经验³"),
        ("region_2", "地区: 南方"),
        ("educ:C(Q('gender'))[T.2]", "受教育年限 × 性别: 女"),
        ("Intercept", "Intercept"),
        ("unlabelled_column", "unlabelled_column"),
    ],
)
def test_terms_render_with_the_users_labels(term: str, expected: str) -> None:
    assert term_display_label(term, variable_labels=VARIABLES, value_labels=VALUES) == expected


def test_a_term_without_labels_is_shown_as_is() -> None:
    assert term_display_label("C(Q('region'))[T.2]") == "region: 2"


def test_the_regression_table_keeps_the_raw_term_and_adds_the_label() -> None:
    table = build_regression_table(
        [("ols_1", {"model_type": "ols", "coefficients": {"C(Q('region'))[T.2]": {"estimate": 1.0, "p_value": 0.01}}})],
        variable_labels=VARIABLES,
        value_labels=VALUES,
    )
    row = table["rows"][0]
    assert row["term"] == "C(Q('region'))[T.2]"
    assert row["label"] == "地区: 南方"


def test_run_detail_serves_term_labels_from_declared_labels(tmp_path) -> None:
    import io
    import json
    import time

    import numpy as np
    import pandas as pd
    from fastapi.testclient import TestClient

    from workbench.api import app
    from workbench.projects import create_project

    rng = np.random.default_rng(3)
    n = 180
    frame = pd.DataFrame(
        {
            "wage": rng.normal(20, 4, n).round(3),
            "educ": rng.integers(9, 20, n),
            "region": rng.integers(1, 4, n),
        }
    )
    project = create_project(tmp_path, "labelled")
    client = TestClient(app)
    labels = {
        "variable_labels": {"educ": "受教育年限", "region": "地区"},
        "value_labels": {"region": {"1": "北方", "2": "南方", "3": "西部"}},
        "measurement_level": {"region": "nominal"},
    }
    created = client.post(
        "/runs",
        data={
            "project_root": str(project.root), "mode": "auto", "model_type": "ols",
            "y": "wage", "x": "educ,region", "labels": json.dumps(labels, ensure_ascii=False),
        },
        files={"file": ("d.csv", io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["run_id"]
    for _ in range(300):
        detail = client.get(f"/runs/{run_id}", params={"project_root": str(project.root)}).json()
        if detail.get("status") in {"completed", "failed"}:
            break
        time.sleep(0.1)
    assert detail["status"] == "completed"

    term_labels = detail["term_labels"]
    assert term_labels["educ"] == "受教育年限"
    assert sorted(label for term, label in term_labels.items() if "region" in term) == [
        "地区: 南方",
        "地区: 西部",
    ]


@pytest.mark.parametrize("column", ["arm", "arm:label", "o'brien", 'say "hi"', "back\\slash"])
def test_lmm_treatment_interactions_preserve_quoted_columns(column):
    from workbench.formula_terms import quote_column

    left = f"C({quote_column(column)}, Treatment(reference='a'))[T.b:later]"
    right = quote_column("time:visit")
    term = f"{left}:{right}"
    assert term_display_label(term) == f"{column}: b:later × time:visit"
    assert term_display_label(f"{left}:C(Q('site'))[T.south]") == f"{column}: b:later × site: south"


def test_lmm_labels_do_not_merge_terms_or_change_report_evidence():
    terms = ["C(Q('arm'), Treatment(reference='a'))[T.b]", "C(Q('cohort'), Treatment(reference='a'))[T.b]"]
    coefficients = {term: {"estimate": i + .25, "source_id": f"kernel.params.{term}"} for i, term in enumerate(terms)}
    table = build_regression_table([( "m", {"coefficients": coefficients})], variable_labels={"arm": "Group", "cohort": "Group"})
    assert [row["label"] for row in table["rows"]] == ["Group: b", "Group: b"]
    assert [row["term"] for row in table["rows"]] == terms
    for row in table["rows"]:
        for key, value in coefficients[row["term"]].items():
            assert row["models"]["m"][key] == value
