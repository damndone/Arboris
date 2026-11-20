"""The new headless journal never writes through a replaced directory path."""
from __future__ import annotations

import asyncio
import importlib
import os

import pytest


def test_journal_root_swap_during_fixture_hash_cannot_create_outside_manifest(tmp_path, monkeypatch):
    from workbench import cli_agent

    project = tmp_path / 'project'
    journal = tmp_path / 'journal'
    outside = tmp_path / 'outside'
    for path in (project, journal, outside):
        path.mkdir()
    admitted_path = cli_agent._journal_directory(project, journal, None)
    original = cli_agent._fixture_sha256
    def swap(root):
        digest = original(root)
        journal.rename(tmp_path / 'original-journal')
        journal.symlink_to(outside, target_is_directory=True)
        return digest
    monkeypatch.setattr(cli_agent, '_fixture_sha256', swap)
    async def forbidden():
        raise AssertionError('directory replacement must fail before the turn')
    with pytest.raises((OSError, ValueError)):
        asyncio.run(cli_agent._journaled_turn(forbidden, project_root=project,
            request={'command': 'run'}, journal=admitted_path, replay=False))
    assert not (outside / 'runtime.json').exists()
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize('link', ['symlink', 'hardlink'])
@pytest.mark.parametrize('name', ['runtime.json', 'model.jsonl', 'business.jsonl'])
def test_journal_read_and_hash_refuse_links_without_changing_original(tmp_path, link, name):
    api = importlib.import_module('workbench.agent.headless_journal')
    root = tmp_path / 'journal'
    root.mkdir()
    original = tmp_path / 'complete-prefix'
    prefix = b'{"complete":true}\n'
    original.write_bytes(prefix)
    leaf = root / name
    if link == 'symlink':
        leaf.symlink_to(original)
    else:
        os.link(original, leaf)
    with api.open_headless_journal(root) as journal:
        with pytest.raises((OSError, ValueError)):
            if name == 'runtime.json':
                journal.read_runtime()
            else:
                journal.sha256(name)
    assert original.read_bytes() == prefix


def test_runtime_writer_updates_same_inode_and_refuses_overwriting_complete_prefix(tmp_path):
    api = importlib.import_module('workbench.agent.headless_journal')
    with api.open_headless_journal(tmp_path) as journal:
        with journal.create_runtime(b'{"complete":false}\n') as writer:
            first = (tmp_path / 'runtime.json').stat().st_ino
            writer.save(b'{"complete":true}\n')
            assert (tmp_path / 'runtime.json').stat().st_ino == first
        prefix = journal.read_runtime()
        with pytest.raises((OSError, ValueError)):
            with journal.create_runtime(b'new evidence\n'):
                pytest.fail('existing evidence must not be opened for writing')
        assert journal.read_runtime() == prefix == b'{"complete":true}\n'
