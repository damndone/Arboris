# tests/test_focal_x_persistence.py
from workbench.api import (
    _inject_focal_x_control,
    _parse_focal_x,
    _STRUCTURAL_FOCAL_FAMILIES,
)


def test_parse_focal_x_canonicalizes_against_x():
    assert _parse_focal_x("income, education", ["age", "education", "income"]) == [
        "education", "income",
    ]


def test_parse_focal_x_empty():
    assert _parse_focal_x("", ["a"]) == []


def test_parse_focal_x_drops_tokens_not_in_x():
    # a focal token that is not a regressor is dropped (case-sensitive)
    assert _parse_focal_x("Education", ["education"]) == []


def test_structural_focal_families_listed():
    # focal_x is cleared for these families (focal/treatment is structural)
    assert _STRUCTURAL_FOCAL_FAMILIES == {"iv_2sls", "did", "cs_did", "sa_did", "dcdh"}
    # panel and poisson are user-focal, so NOT in the structural set
    assert "panel_ols" not in _STRUCTURAL_FOCAL_FAMILIES
    assert "poisson_rate" not in _STRUCTURAL_FOCAL_FAMILIES


def test_inject_focal_x_control_adds_multiselect_for_user_focal_family():
    schema = [{"key": "model_type", "kind": "select", "label": "Model", "value": "ols"}]
    form = {"x": "age, education, income", "focal_x": "education"}
    out = _inject_focal_x_control(schema, form, "ols")
    control = next(c for c in out if c["key"] == "focal_x")
    assert control["kind"] == "multiselect"
    assert control["options"] == ["age", "education", "income"]
    assert control["value"] == ["education"]
    # original schema is not mutated in place
    assert all(c["key"] != "focal_x" for c in schema)


def test_inject_focal_x_control_omitted_for_structural_family():
    schema = [{"key": "model_type", "kind": "select", "label": "Model", "value": "did"}]
    form = {"x": "age, treat, post", "focal_x": "treat"}
    out = _inject_focal_x_control(schema, form, "did")
    assert all(c["key"] != "focal_x" for c in out)


def test_inject_focal_x_control_noop_without_x_columns():
    schema = [{"key": "model_type", "kind": "select", "label": "Model", "value": "ols"}]
    out = _inject_focal_x_control(schema, {"x": ""}, "ols")
    assert all(c["key"] != "focal_x" for c in out)


def test_inject_focal_x_control_idempotent():
    schema = [
        {"key": "focal_x", "kind": "multiselect", "label": "Focal X",
         "options": ["a"], "value": []},
    ]
    out = _inject_focal_x_control(schema, {"x": "a, b"}, "ols")
    assert sum(1 for c in out if c["key"] == "focal_x") == 1


def test_post_runs_endpoint_persists_focal_x_into_run_inputs(tmp_path):
    """Regression: the POST /runs HTTP endpoint must forward the focal_x form
    field into run_inputs. The Form param + form-dict wiring was missing in the
    first v1.6.5 cut, so the run-form focal declaration silently did nothing
    end-to-end even though _submit_run/_parse_focal_x were correct."""
    import json
    import time

    from fastapi.testclient import TestClient

    from workbench.api import app

    client = TestClient(app)
    csv = tmp_path / "input.csv"
    rows = "\n".join(f"{1 + 2 * i},{i},{i % 3},{i + 1}" for i in range(40))
    csv.write_text("wage,education,age,exper\n" + rows + "\n", encoding="utf-8")

    with csv.open("rb") as fh:
        resp = client.post(
            "/runs",
            data={
                "project_root": str(tmp_path),
                "mode": "auto",
                "model_type": "ols",
                "y": "wage",
                "x": "education,age,exper",
                "focal_x": "education",
            },
            files={"file": ("input.csv", fh, "text/csv")},
        )
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    terminal = {"completed", "failed", "cancelled", "interrupted", "partial"}
    for _ in range(100):
        status = client.get(
            f"/runs/{run_id}", params={"project_root": str(tmp_path)}
        ).json().get("status")
        if status in terminal:
            break
        time.sleep(0.1)
    assert status == "completed", status

    inputs = json.loads(
        (tmp_path / "runs" / run_id / "run_inputs.json").read_text(encoding="utf-8")
    )
    assert inputs["form"].get("focal_x") == "education"
