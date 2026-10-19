"""The v1.9.1 entry points must delegate to bounded responsibility owners."""
from pathlib import Path


def test_remaining_agent_entries_are_under_800_lines():
    root = Path(__file__).parents[1] / "backend/workbench"
    entries = ("http/agent_routes.py", "agent/orchestrator.py", "agent/notebook/service.py")
    sizes = {name: len((root / name).read_text().splitlines()) for name in entries}
    assert all(size < 800 for size in sizes.values()), sizes
