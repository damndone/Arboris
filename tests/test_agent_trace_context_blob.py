"""Gate 3 Task 4 — a hash proves integrity; it does not return the content.

Storing only `generation_context_hash` would let a future reader verify that two
traces saw the same context, and nothing else. The question that actually gets
asked — "why did the agent suggest that?" — needs the bundle back.
"""
import shutil
from pathlib import Path

import pytest

from workbench.agent.context_compiler import (
    compile_notebook_planning_context,
    generation_context_hash,
)
from workbench.agent.trace import ContextBlobStore, TraceWriter, record_compiled_context

FIXTURE = Path(__file__).parent / "fixtures" / "run_family"
ROOT_RUN = "20260722_043309_451505_f0d8672b"
SCOPE = {
    "project_id": "vix-dofile-repro",
    "notebook_id": "nb_0001",
    "run_family_id": "run-family:11111111-1111-4111-8111-111111111111",
}
VERSIONS = {
    "app_commit": "41b0361",
    "model_id": "deepseek-chat",
    "prompt_version": "notebook-plan/2026-07-22",
    "vocabulary_version": "ts.v3",
    "context_profile": "notebook-plan/v1",
}


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    project_root = tmp_path / "vix-dofile-repro"
    runs = project_root / "runs"
    runs.mkdir(parents=True)
    for run_dir in sorted(FIXTURE.iterdir()):
        shutil.copytree(run_dir, runs / run_dir.name)
    return project_root


def _context(project: Path):
    return compile_notebook_planning_context(
        project,
        notebook_id="nb_0001",
        run_family_id=SCOPE["run_family_id"],
        active_head_run_id=ROOT_RUN,
        analysis_contract={"objective": "VIX volatility", "revision": 3},
        user_focus={"selected_text": "persistent conditional variance"},
    )


def test_the_bundle_comes_back_byte_identical(project: Path) -> None:
    context = _context(project)
    writer = TraceWriter(project, scope=SCOPE, versions=VERSIONS)

    event = record_compiled_context(writer, context)

    restored = ContextBlobStore(project).get(event["payload"]["compiled_context_blob_ref"])
    assert restored["generation_context_hash"] == generation_context_hash(context)
    assert restored["content"] == context.hashable_payload()


def test_the_event_stays_small(project: Path) -> None:
    """Raw project data must not be copied into the JSONL stream (spec §13.4)."""
    import json

    context = _context(project)
    writer = TraceWriter(project, scope=SCOPE, versions=VERSIONS)

    event = record_compiled_context(writer, context)

    assert len(json.dumps(event, ensure_ascii=False)) <= 4096
    # ...and the bundle it points at is genuinely bigger than the event.
    blob = ContextBlobStore(project).get(event["payload"]["compiled_context_blob_ref"])
    assert len(json.dumps(blob, ensure_ascii=False)) > 2000


def test_blobs_are_content_addressed_and_deduplicated(project: Path) -> None:
    store = ContextBlobStore(project)
    context = _context(project)

    first = store.put(context)
    second = store.put(context)

    assert first == second
    assert len(list((project / "agent-context-blobs").glob("*.json"))) == 1


def test_blob_ref_is_verifiable(project: Path) -> None:
    """A tampered blob must not silently pass as the recorded context."""
    store = ContextBlobStore(project)
    ref = store.put(_context(project))
    path = next((project / "agent-context-blobs").glob("*.json"))
    path.write_text('{"content": {"tampered": true}, "generation_context_hash": "sha256:0"}')

    with pytest.raises(ValueError):
        store.get(ref)


def test_blob_store_stays_inside_the_project(project: Path) -> None:
    store = ContextBlobStore(project)
    store.put(_context(project))

    for path in (project / "agent-context-blobs").iterdir():
        assert project in path.parents


def test_no_cleanup_path_deletes_traces_or_blobs() -> None:
    """Gate 3 Task 6 Step 2 — retention, pinned structurally.

    Trace is the one artifact of this version that cannot be recreated after the
    fact. A future cleanup routine that globs a project directory would destroy
    it silently, so the absence of such a routine is asserted rather than assumed.

    ``run_deletion.py`` is exempt for the same reason ``trace.py`` and
    ``events.py`` are: it is not a cleanup routine. Permanent run deletion is a
    user-initiated, two-step confirmed operation that resolves one session id at
    a time. The invariant this test protects is *silent, indiscriminate* erasure,
    which is why the exemption is paired with a check that it never sweeps the
    protected directories wholesale.
    """
    backend = Path(__file__).resolve().parents[1] / "backend" / "workbench"
    protected = ("agent-events", "agent-context-blobs")
    exempt = {"trace.py", "events.py", "run_deletion.py"}
    offenders: list[str] = []
    for path in sorted(backend.rglob("*.py")):
        if path.name in exempt:
            continue
        text = path.read_text(encoding="utf-8")
        if "unlink" not in text and "rmtree" not in text:
            continue
        for name in protected:
            if name in text:
                offenders.append(f"{path.relative_to(backend)} may delete {name}")

    assert offenders == []


def test_confirmed_run_deletion_never_sweeps_the_protected_directories() -> None:
    """The retention exemption is bounded to per-session removal.

    Deleting a run may remove that run's own agent records, but it must never
    glob or recursively drop the protected directories themselves — that would
    turn a confirmed, targeted deletion back into the silent erasure the
    retention invariant exists to prevent.
    """
    source = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "workbench"
        / "services"
        / "run_deletion.py"
    ).read_text(encoding="utf-8")

    for line in source.splitlines():
        if "agent-events" in line or "agent-context-blobs" in line:
            assert "glob" not in line and "rmtree" not in line, line.strip()
