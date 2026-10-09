"""Keep bounded context tools modular without changing their public facade."""
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1] / 'backend' / 'workbench' / 'agent'


def test_context_tools_modules_stay_within_the_approved_size_budget():
    files = [AGENT / 'context_tools.py', *(AGENT / 'context_tools_support').glob('*.py')]
    oversized = {str(p.relative_to(AGENT)): len(p.read_text().splitlines())
                 for p in files if len(p.read_text().splitlines()) > 2000}
    assert not oversized, f'Context tool responsibilities must be split, not relocated: {oversized}'
