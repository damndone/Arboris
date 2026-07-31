"""Gate 2 Task 5 — the compiler must be the only way in.

A bounded context that can be bypassed provides no bound. These tests pin two
things: the compiled bundle is what actually reaches the model, and no other
module in the agent layer reads the raw sources behind the compiler's back.
"""
import shutil
from pathlib import Path

import pytest

from workbench.agent.context_compiler import (
    CONTEXT_PROFILE,
    compile_notebook_planning_context,
    generation_context_hash,
    notebook_planning_workbench_context,
)

FIXTURE = Path(__file__).parent / "fixtures" / "run_family"
ROOT_RUN = "20260722_043309_451505_f0d8672b"
AGENT_DIR = Path(__file__).resolve().parents[1] / "backend" / "workbench" / "agent"

# Sources the compiler owns. Any other agent module reading these is a bypass:
# it would put unbounded, unrecorded content in front of the model.
COMPILER_OWNED_SOURCES = ("artifacts_index.json", "graph.json", "data_profile.json")

# Modules allowed to read those sources directly. `context_tools.py` earns its
# place because it is the bounded-inspection surface itself: it truncates what
# it extracts and every tool it registers declares a `max_output_budget` the
# registry enforces. That budget, not this string scan, is what actually keeps
# a 22 KB index away from an 8192-byte tool result -- so the exemption is
# paired with `test_every_inspect_tool_declares_an_output_budget`.
COMPILER_SOURCE_READERS = {"context_compiler.py", "evidence.py", "context_tools.py"}


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    project_root = tmp_path / "vix-dofile-repro"
    runs = project_root / "runs"
    runs.mkdir(parents=True)
    for run_dir in sorted(FIXTURE.iterdir()):
        shutil.copytree(run_dir, runs / run_dir.name)
    return project_root


def _compile(project: Path):
    return compile_notebook_planning_context(
        project,
        notebook_id="nb_0001",
        run_family_id="run-family:11111111-1111-4111-8111-111111111111",
        active_head_run_id=ROOT_RUN,
        analysis_contract={"objective": "VIX volatility", "revision": 3},
        user_focus={"selected_text": "persistent conditional variance"},
    )


def test_model_facing_payload_declares_its_profile_and_hash(project: Path) -> None:
    context = _compile(project)

    payload = notebook_planning_workbench_context(context)

    assert payload["context_profile"] == CONTEXT_PROFILE
    assert payload["context_id"] == context.context_id
    assert payload["generation_context_hash"] == generation_context_hash(context)


def test_model_sees_the_omissions(project: Path) -> None:
    """The agent must know it is looking at 5 of 59, not at everything."""
    payload = notebook_planning_workbench_context(_compile(project))

    dropped = [o for o in payload["omissions"] if o["section"] == "artifact_summaries"]
    assert dropped[0]["available_count"] == 59
    assert payload["artifact_type_counts"]["time_series_json"] == 36


def test_payload_carries_no_compilation_metadata_into_the_hash(project: Path) -> None:
    context = _compile(project)
    payload = notebook_planning_workbench_context(context)

    # context_id is present for correlation but must not have entered the hash.
    assert payload["context_id"]
    assert "compiled_at" not in payload["content"]


def test_no_agent_module_reads_compiler_owned_sources(project: Path) -> None:
    """Structural guard, in the spirit of Gate 1 Task 6 Step 2.

    That step caught `ensure_chain_root()` deriving a family on a write path.
    The equivalent failure here is a module quietly reading artifacts_index.json
    to 'just add a bit of context', which is how the 22 KB index reached a
    tool budget of 8192 in the first place.
    """
    offenders: list[str] = []
    for path in sorted(AGENT_DIR.rglob("*.py")):
        if path.name in COMPILER_SOURCE_READERS:
            continue
        text = path.read_text(encoding="utf-8")
        for source in COMPILER_OWNED_SOURCES:
            if source in text:
                offenders.append(f"{path.relative_to(AGENT_DIR)} reads {source}")

    assert offenders == []


def test_every_inspect_tool_declares_an_output_budget() -> None:
    """The real bound on context_tools.py, which the string guard cannot express.

    ``context_tools.py`` legitimately reads compiler-owned sources: its whole
    job is answering bounded questions about a run, and it truncates what it
    extracts. What must never regress is the enforcement -- a tool that reads
    those sources without declaring ``max_output_budget`` would hand the model
    an unbounded payload, which is the failure the exemption could otherwise
    hide. The registry truncates and then errors with
    ``tool_output_budget_exceeded``, so a declared budget is the protection.
    """
    source = (AGENT_DIR / "context_tools.py").read_text(encoding="utf-8")
    registered = source.count("ToolDefinition(")
    declared = source.count("max_output_budget=")

    assert registered > 0, "no tools registered; the guard would be vacuous"
    # Every ToolDefinition this module builds carries an explicit budget.
    assert declared >= registered, (
        f"{registered} tool definitions but only {declared} declared budgets"
    )
