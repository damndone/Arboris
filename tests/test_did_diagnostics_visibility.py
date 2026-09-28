from __future__ import annotations

from workbench.engine.stages.diagnostics import _promote_did_warnings


def test_did_warnings_are_aggregated_into_structured_guardrail_issues() -> None:
    issues: list[dict] = []
    _promote_did_warnings(
        {
            "warnings": [
                "Event time -6 is supported by a single cohort.",
                "Event time 5 is supported by a single cohort.",
                "Cell (g=2020, t=2021) omitted: no valid control.",
            ]
        },
        model_type="cs_did",
        artifact_id="cs_did",
        issue_dicts=issues,
    )

    assert [issue["code"] for issue in issues] == [
        "DID_DYNAMIC_THIN_SUPPORT",
        "DID_CELL_OMITTED",
    ]
    assert issues[0]["severity"] == "WARNING"
    assert issues[0]["evidence"]["artifact_id"] == "cs_did"
    assert "Event time -6" in issues[0]["message"]
    assert "Cell (g=2020, t=2021)" in issues[1]["message"]
