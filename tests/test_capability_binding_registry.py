from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_capability_notebook_binding import _admitted_records, _resolution, _validity
from workbench.capability_factory.notebook_binding import CapabilityResolutionBinding
from workbench.capability_factory.binding_registry import (
    DurableBindingIndex,
    DurableBindingIndexError,
    DurableCapabilityBindingCatalog,
)


def _binding() -> CapabilityResolutionBinding:
    controller, adapter, bundle, assessment, admission = _admitted_records()
    return CapabilityResolutionBinding.from_records(
        admission_controller=controller,
        resolution_binding=_resolution(adapter, _validity()),
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission=admission,
        current_validity=_validity(),
    )


def _projection(capability_id: str = "capability.alpha") -> dict[str, object]:
    return {
        "key": capability_id,
        "label": "Verified capability",
        "model_type": "custom_model",
        "notebook_proposal_adapters": ["model.genesis"],
        "params": [],
        "artifact_types": {"result": "custom_json"},
    }


def test_index_record_is_exact_and_round_trips(tmp_path: Path) -> None:
    index = DurableBindingIndex(tmp_path)
    binding = _binding()
    record = index.append(
        capability_id="capability.alpha",
        binding_ref=binding.content_digest,
        planner_projection=_projection(),
    )

    assert record.sequence == 1
    assert set(record.to_dict()) == {
        "record_type",
        "sequence",
        "capability_id",
        "binding_ref",
        "planner_projection",
        "record_digest",
    }
    assert "entrypoint_ref" not in json.dumps(record.to_dict(), sort_keys=True)
    assert "artifact_ref" not in json.dumps(record.to_dict(), sort_keys=True)
    assert DurableBindingIndex(tmp_path).records() == (record,)


def test_index_is_idempotent_and_rejects_rebind(tmp_path: Path) -> None:
    index = DurableBindingIndex(tmp_path)
    binding = _binding()
    first = index.append(
        capability_id="capability.alpha",
        binding_ref=binding.content_digest,
        planner_projection=_projection(),
    )
    assert index.append(
        capability_id="capability.alpha",
        binding_ref=binding.content_digest,
        planner_projection=_projection(),
    ) == first

    with pytest.raises(DurableBindingIndexError, match="immutable"):
        index.append(
            capability_id="capability.alpha",
            binding_ref="f" * 64,
            planner_projection=_projection(),
        )
    with pytest.raises(DurableBindingIndexError, match="projection"):
        index.append(
            capability_id="capability.alpha",
            binding_ref=binding.content_digest,
            planner_projection={**_projection(), "label": "changed"},
        )


def test_malformed_or_symlinked_journal_fails_closed(tmp_path: Path) -> None:
    index = DurableBindingIndex(tmp_path)
    index.journal_path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(DurableBindingIndexError, match="journal"):
        DurableBindingIndex(tmp_path)

    safe = tmp_path / "safe"
    safe.mkdir()
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    (safe / "capability-binding-index.jsonl").symlink_to(outside)
    with pytest.raises(DurableBindingIndexError):
        DurableBindingIndex(safe)


def test_catalog_registers_durably_before_memory_and_restores_through_loader(tmp_path: Path) -> None:
    binding = _binding()
    index = DurableBindingIndex(tmp_path)
    catalog = DurableCapabilityBindingCatalog(
        verifier=lambda candidate: None,
        index=index,
    )
    digest = catalog.register(
        "capability.alpha",
        binding,
        planner_projection=_projection(),
    )
    assert digest == binding.content_digest
    assert catalog.planner_projection("capability.alpha") == _projection()

    restored = DurableCapabilityBindingCatalog(
        verifier=lambda candidate: None,
        index=DurableBindingIndex(tmp_path),
    )
    calls: list[str] = []

    def loader(reference: str) -> CapabilityResolutionBinding:
        calls.append(reference)
        if reference != binding.content_digest:
            raise KeyError(reference)
        return binding

    restored.restore(loader)
    assert calls == [binding.content_digest]
    assert restored.planner_projection("capability.alpha") == _projection()


def test_restore_rejects_untrusted_or_mismatched_loader_result(tmp_path: Path) -> None:
    binding = _binding()
    index = DurableBindingIndex(tmp_path)
    catalog = DurableCapabilityBindingCatalog(verifier=lambda candidate: None, index=index)
    catalog.register("capability.alpha", binding, planner_projection=_projection())

    restored = DurableCapabilityBindingCatalog(
        verifier=lambda candidate: None,
        index=DurableBindingIndex(tmp_path),
    )
    with pytest.raises(DurableBindingIndexError, match="loader"):
        restored.restore(lambda _reference: object())


def test_catalog_remains_compatible_with_notebook_service_type_boundary(tmp_path: Path) -> None:
    from workbench.agent.notebook.service import NotebookService
    from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalog

    catalog = DurableCapabilityBindingCatalog(
        verifier=lambda candidate: None,
        index=DurableBindingIndex(tmp_path),
    )
    assert isinstance(catalog, CapabilityBindingCatalog)
    assert NotebookService.__init__.__annotations__.get("capability_bindings") is not None


def test_registry_has_no_execution_or_network_surface() -> None:
    import workbench.capability_factory.binding_registry as module

    assert not hasattr(module, "subprocess")
    assert not hasattr(module, "socket")
    assert not hasattr(module, "Popen")
