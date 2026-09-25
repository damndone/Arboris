import base64
import hashlib
import json
from copy import deepcopy

import pytest

from workbench.canonical import canonical_json_v1
from workbench.contracts.evidence.result_pages import (
    ResultPageError, ResultPageV1, ResultPageAccumulatorV1, pack_result_page,
)


def binding():
    return dict(source_ref="evidence:r1", source_digest="a" * 64,
                section_id="section:statistics", consumer_id="agent", destination="local")


def pages(data, budget=1100, reserve=80):
    offset = 0
    while offset < len(data):
        page = pack_result_page(data, binding=binding(), offset=offset,
                                max_wire_bytes=budget, envelope_reserve_bytes=reserve)
        assert len(canonical_json_v1(page.to_dict()).encode()) + reserve <= budget
        yield page
        offset = page.to_dict()["next_offset"] or len(data)


def test_unicode_large_section_roundtrip_and_partial_is_not_complete():
    data = canonical_json_v1({"labels": ["统计🧪"] * 2000, "p_value": 1.25e-24}).encode()
    acc = ResultPageAccumulatorV1(binding(), max_total_bytes=len(data))
    chunks = list(pages(data))
    assert len(chunks) > 2
    for page in chunks[:-1]:
        acc.add(page)
        assert not acc.transport_complete
        with pytest.raises(ResultPageError):
            acc.finish()
    acc.add(chunks[-1])
    assert acc.transport_complete
    assert acc.finish() == data


@pytest.mark.parametrize("attack", ["duplicate", "gap", "mixed", "changed_total", "last_only"])
def test_accumulator_rejects_incomplete_or_mixed_stream(attack):
    data = b"abcdef" * 500
    chunks = list(pages(data))
    acc = ResultPageAccumulatorV1(binding(), max_total_bytes=10000)
    if attack == "last_only":
        with pytest.raises(ResultPageError): acc.add(chunks[-1])
        return
    acc.add(chunks[0])
    item = chunks[0] if attack == "duplicate" else chunks[2] if attack == "gap" else chunks[1]
    if attack in {"mixed", "changed_total"}:
        wire = item.to_dict()
        if attack == "mixed": wire["binding"]["source_digest"] = "b" * 64
        else: wire["total_bytes"] += 1
        wire["page_digest"] = digest(wire)
        item = ResultPageV1.from_dict(wire)
    with pytest.raises(ResultPageError): acc.add(item)


def digest(wire):
    return hashlib.sha256(canonical_json_v1({k: v for k, v in wire.items() if k != "page_digest"}).encode()).hexdigest()


@pytest.mark.parametrize("key,value", [("schema_version", 2), ("offset", True), ("offset", -1),
    ("total_bytes", 0), ("payload_base64", "!?"), ("bundle_digest", "x"), ("extra", 3)])
def test_invalid_wire_rejected(key, value):
    wire = next(pages(b"abcdef" * 500)).to_dict()
    wire[key] = value
    with pytest.raises(ResultPageError): ResultPageV1.from_dict(wire)


def test_corruption_and_false_completion_rejected_even_with_page_hash():
    data = b"abcdef"
    wire = next(pages(data)).to_dict()
    wire["payload_base64"] = base64.b64encode(b"xxxxxx").decode()
    wire["page_digest"] = digest(wire)
    acc = ResultPageAccumulatorV1(binding(), max_total_bytes=100)
    with pytest.raises(ResultPageError): acc.add(ResultPageV1.from_dict(wire))
    assert not acc.transport_complete


def test_bounds_and_defensive_binding():
    original = binding()
    page = pack_result_page(b"data", binding=original, offset=0, max_wire_bytes=1100)
    original["source_ref"] = "changed"
    wire = page.to_dict(); wire["binding"]["source_ref"] = "changed"
    assert page.to_dict()["binding"] == binding()
    with pytest.raises(ResultPageError):
        pack_result_page(b"data", binding=binding(), offset=0, max_wire_bytes=20)
    acc = ResultPageAccumulatorV1(binding(), max_total_bytes=3)
    with pytest.raises(ResultPageError): acc.add(page)


def test_decomposed_binding_survives_real_canonical_wire_roundtrip():
    selected = binding(); selected["source_ref"] = "evidence:cafe\u0301"
    page = pack_result_page(b"data", binding=selected, offset=0, max_wire_bytes=1100)
    parsed = ResultPageV1.from_dict(json.loads(canonical_json_v1(page.to_dict())))
    acc = ResultPageAccumulatorV1(selected, max_total_bytes=10)
    acc.add(parsed)
    assert acc.finish() == b"data"


@pytest.mark.parametrize("invalid", [None, [], [("source_ref", "unexpected")]])
def test_corrupted_memory_binding_rejected_before_conversion(invalid):
    page = next(pages(b"data"))
    object.__setattr__(page, "binding", invalid)
    acc = ResultPageAccumulatorV1(binding(), max_total_bytes=100)
    with pytest.raises(ResultPageError): acc.add(page)
    assert acc.received_bytes == 0


@pytest.mark.parametrize("attack", ["replace", "extend"])
def test_finished_buffer_is_revalidated_at_read_boundary(attack):
    acc = ResultPageAccumulatorV1(binding(), max_total_bytes=8)
    acc.add(next(pages(b"original")))
    if attack == "replace":
        acc._data[0] = ord("X")
    else:
        acc._data.extend(b"extra")
    assert not acc.transport_complete
    with pytest.raises(ResultPageError):
        acc.finish()


def test_reusable_pager_hashes_immutable_bundle_only_once(monkeypatch):
    from workbench.contracts.evidence import result_pages
    data = b"large bundle" * 6000
    original = hashlib.sha256
    scans = []
    def tracked(value=b"", *args, **kwargs):
        if value is data:
            scans.append(len(value))
        return original(value, *args, **kwargs)
    monkeypatch.setattr(result_pages.hashlib, "sha256", tracked)
    pager = result_pages.ResultBundlePagerV1(data, binding=binding())
    offset = 0
    while offset is not None:
        page = pager.page(offset=offset, max_wire_bytes=1100)
        offset = page.next_offset
    assert scans == [len(data)]


@pytest.mark.parametrize("data", [b"", bytearray(b"mutable"), "not bytes"])
def test_pager_requires_nonempty_immutable_bytes(data):
    from workbench.contracts.evidence.result_pages import ResultBundlePagerV1
    with pytest.raises(ResultPageError):
        ResultBundlePagerV1(data, binding=binding())


@pytest.mark.parametrize("reserve", [True, -1, 1101, 1100])
def test_invalid_or_exhausted_framing_reserve_rejects(reserve):
    with pytest.raises(ResultPageError):
        pack_result_page(b"data", binding=binding(), offset=0,
                         max_wire_bytes=1100, envelope_reserve_bytes=reserve)


def test_receiver_checks_total_ceiling_before_accepting_first_chunk():
    acc = ResultPageAccumulatorV1(binding(), max_total_bytes=100)
    page = next(pages(b"x" * 2000))
    with pytest.raises(ResultPageError):
        acc.add(page)
    assert acc.received_bytes == 0
    assert acc.total_bytes is None
