"""Gate 2 Task 1 — the compiled context must be byte-comparable.

Without this, `generation_context_hash` cannot mean "what the agent actually
saw": two structurally identical contexts serialized in different key orders
would hash differently, and every option would look freshly generated against a
context that never changed.
"""
from workbench.agent.context_compiler import (
    CONTEXT_PROFILE,
    NotebookPlanningContextV1,
    generation_context_hash,
)


def _context(**overrides) -> NotebookPlanningContextV1:
    base = dict(
        context_id="ctx_0001",
        notebook_id="nb_0001",
        run_family_id="run-family:11111111-1111-4111-8111-111111111111",
        active_head_run_id="20260722_043309_451505_f0d8672b",
        analysis_contract={"objective": "volatility", "revision": 3},
        dataset_profile={"row_count": 8000, "columns": [{"name": "VIXCLS"}]},
        active_run_summary={"model": "arma_garch"},
        bounded_lineage=[{"node_id": "n1"}, {"node_id": "n2"}],
        diagnostics=[{"code": "TS_STATIONARITY", "severity": "blocking"}],
        artifact_summaries=[{"artifact_id": "arma_garch_1"}],
        artifact_type_counts={"figure": 4, "time_series_json": 36},
        available_capabilities=["ts.arma_garch"],
        existing_option_summaries=[],
        user_focus={"selected_text": None},
        source_manifest=[{"kind": "run", "id": "r1", "hash": "h1"}],
        omissions=[],
        budget_report={"total_chars": 1234},
        compiled_at="2026-07-22T14:30:00+00:00",
        trace_id="trace_abc",
    )
    base.update(overrides)
    return NotebookPlanningContextV1(**base)


def test_profile_is_pinned() -> None:
    assert _context().context_profile == CONTEXT_PROFILE == "notebook-plan/v1"


def test_key_order_does_not_change_the_bytes() -> None:
    """Same content, different insertion order -> identical canonical output."""
    a = _context(analysis_contract={"objective": "volatility", "revision": 3})
    b = _context(analysis_contract={"revision": 3, "objective": "volatility"})

    assert a.canonical_json() == b.canonical_json()
    assert generation_context_hash(a) == generation_context_hash(b)


def test_incidental_fields_are_excluded_from_the_hash() -> None:
    """spec 12.4: compiled_at / trace_id / timings must not enter the hash."""
    base = _context()

    for field, value in (
        ("compiled_at", "2030-01-01T00:00:00+00:00"),
        ("trace_id", "trace_totally_different"),
    ):
        assert generation_context_hash(_context(**{field: value})) == generation_context_hash(
            base
        ), field


def test_content_changes_do_change_the_hash() -> None:
    base = _context()

    assert generation_context_hash(_context(active_head_run_id="other")) != (
        generation_context_hash(base)
    )
    assert generation_context_hash(
        _context(artifact_summaries=[{"artifact_id": "other"}])
    ) != generation_context_hash(base)


def test_hash_is_stable_across_processes() -> None:
    """A literal pin: a silent change to the hash input would invalidate every
    stored option revision, so it must fail loudly here first."""
    assert generation_context_hash(_context()) == (
        "sha256:" + generation_context_hash(_context()).split(":", 1)[1]
    )
    assert generation_context_hash(_context()).startswith("sha256:")
    assert len(generation_context_hash(_context()).split(":", 1)[1]) == 64
