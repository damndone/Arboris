"""Lossless transport values, not source authority or complete statistical facts.

The caller must admit the source before packing and validate the reconstructed
bundle after finishing. Offsets and hashes never grant access to evidence.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from workbench.canonical import canonical_json_v1

MAX_PAGE_BYTES = 262144
MAX_BUNDLE_BYTES = 16 * 1024 * 1024
_KEYS = frozenset({"schema_version", "binding", "bundle_digest", "offset", "total_bytes",
                   "next_offset", "payload_base64", "page_digest"})
_BINDING_KEYS = frozenset({"source_ref", "source_digest", "section_id", "consumer_id", "destination"})


class ResultPageError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


def _fail(message, code="RESULT_PAGE_INVALID"):
    raise ResultPageError(code, message)


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("integer is outside the declared range")
    return value


def _hash(value):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail("expected a canonical SHA-256 digest")
    return value


def _binding(value):
    if not isinstance(value, Mapping) or len(value) != len(_BINDING_KEYS) or set(value) != _BINDING_KEYS:
        _fail("binding fields differ from the page declaration")
    for item in value.values():
        if type(item) is not str or not item or len(item) > 4096 or "\x00" in item:
            _fail("binding text is invalid")
        try:
            if len(item.encode("utf-8")) > 4096:
                _fail("binding text exceeds its byte limit")
        except UnicodeError:
            _fail("binding contains invalid Unicode")
    _hash(value["source_digest"])
    if value["destination"] not in {"local", "remote"}:
        _fail("unknown page destination")
    return MappingProxyType({key: unicodedata.normalize("NFC", item) for key, item in value.items()})


def _wire_bytes(value):
    return canonical_json_v1(value).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_wire_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ResultPageV1:
    binding: Mapping[str, str]
    bundle_digest: str
    offset: int
    total_bytes: int
    next_offset: int | None
    payload_base64: str
    page_digest: str

    def __post_init__(self):
        object.__setattr__(self, "binding", _binding(self.binding))
        _hash(self.bundle_digest); _hash(self.page_digest)
        _integer(self.total_bytes, 1, MAX_BUNDLE_BYTES)
        _integer(self.offset, 0, self.total_bytes - 1)
        if type(self.payload_base64) is not str or not self.payload_base64 or len(self.payload_base64) > MAX_PAGE_BYTES:
            _fail("page payload is empty or exceeds the transport ceiling")
        try:
            payload = base64.b64decode(self.payload_base64, validate=True)
        except (binascii.Error, ValueError):
            _fail("invalid base64 payload")
        if base64.b64encode(payload).decode("ascii") != self.payload_base64:
            _fail("noncanonical base64 payload")
        end = self.offset + len(payload)
        if not payload or end > self.total_bytes:
            _fail("payload does not fit its declared interval")
        if self.next_offset is not None:
            _integer(self.next_offset, 1, self.total_bytes - 1)
        if self.next_offset != (None if end == self.total_bytes else end):
            _fail("continuation differs from the exact byte interval")
        raw = self.to_dict()
        if len(_wire_bytes(raw)) > MAX_PAGE_BYTES:
            _fail("page exceeds the transport ceiling")
        raw.pop("page_digest")
        if _digest(raw) != self.page_digest:
            _fail("page digest mismatch")

    def to_dict(self):
        return dict(schema_version=1, binding=dict(_binding(self.binding)), bundle_digest=self.bundle_digest,
                    offset=self.offset, total_bytes=self.total_bytes, next_offset=self.next_offset,
                    payload_base64=self.payload_base64, page_digest=self.page_digest)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, Mapping) or len(value) != len(_KEYS) or set(value) != _KEYS:
            _fail("page fields differ from the versioned declaration")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            _fail("unknown page version", "UNSUPPORTED_VERSION")
        return cls(**{k: value[k] for k in _KEYS if k != "schema_version"})


def pack_result_page(bundle_bytes, *, binding, offset, max_wire_bytes, envelope_reserve_bytes=0):
    """Produce a fitting page; the service must recheck its FINAL wrapped wire."""
    return ResultBundlePagerV1(bundle_bytes, binding=binding).page(
        offset=offset, max_wire_bytes=max_wire_bytes, envelope_reserve_bytes=envelope_reserve_bytes)


@dataclass(frozen=True, init=False)
class ResultBundlePagerV1:
    """Reusable transport encoder, NOT an admission or authority capability.

    The service must revalidate source dependencies for every delivery, even
    when this immutable byte snapshot and its internally computed hash persist.
    """
    _data: bytes
    _binding: Mapping[str, str]
    _digest: str

    def __init__(self, bundle_bytes, *, binding):
        if type(bundle_bytes) is not bytes or not 0 < len(bundle_bytes) <= MAX_BUNDLE_BYTES:
            _fail("bundle is empty or outside the reassembly ceiling")
        object.__setattr__(self, "_data", bundle_bytes)
        object.__setattr__(self, "_binding", _binding(binding))
        object.__setattr__(self, "_digest", hashlib.sha256(bundle_bytes).hexdigest())

    def page(self, *, offset, max_wire_bytes, envelope_reserve_bytes=0):
        return _pack_page(self._data, self._binding, self._digest, offset,
                          max_wire_bytes, envelope_reserve_bytes)


def _pack_page(bundle_bytes, bound, digest, offset, max_wire_bytes, envelope_reserve_bytes):
    total = len(bundle_bytes)
    _integer(offset, 0, total - 1)
    _integer(max_wire_bytes, 1, MAX_PAGE_BYTES)
    _integer(envelope_reserve_bytes, 0, max_wire_bytes)

    def candidate(size):
        end = offset + size
        wire = dict(schema_version=1, binding=dict(bound), bundle_digest=digest, offset=offset,
                    total_bytes=total, next_offset=None if end == total else end,
                    payload_base64=base64.b64encode(bundle_bytes[offset:end]).decode("ascii"))
        wire["page_digest"] = _digest(wire)
        return wire

    # Never encode a whole bundle to discover it exceeds a single page.
    low, high, best = 1, min(total - offset, max_wire_bytes * 3 // 4), None
    while low <= high:
        size = (low + high) // 2
        wire = candidate(size)
        if len(_wire_bytes(wire)) + envelope_reserve_bytes <= max_wire_bytes:
            best, low = wire, size + 1
        else:
            high = size - 1
    if best is None:
        _fail("required page identity cannot fit the delivery budget", "RESULT_PAGE_BUDGET_EXCEEDED")
    return ResultPageV1.from_dict(best)


class ResultPageAccumulatorV1:
    """A bounded transport accumulator; COMPLETE evidence needs schema admission."""
    def __init__(self, binding, *, max_total_bytes):
        self._binding = _binding(binding)
        self._limit = _integer(max_total_bytes, 1, MAX_BUNDLE_BYTES)
        self._data = bytearray()
        self._total = None
        self._digest = None
        self._complete = False

    @property
    def transport_complete(self):
        return (self._complete and self._total == len(self._data) <= self._limit
                and hashlib.sha256(self._data).hexdigest() == self._digest)

    @property
    def received_bytes(self):
        return len(self._data)

    @property
    def total_bytes(self):
        return self._total

    def add(self, page):
        if type(page) is not ResultPageV1:
            _fail("expected a validated page value")
        # Re-parse at ingress; a value object is not a trust capability.
        page = ResultPageV1.from_dict(page.to_dict())
        if self._complete or page.binding != self._binding or page.offset != len(self._data):
            _fail("mixed binding, duplicate or noncontiguous page")
        if page.total_bytes > self._limit:
            _fail("declared bundle exceeds the receiver ceiling")
        if self._total is not None and (self._total != page.total_bytes or self._digest != page.bundle_digest):
            _fail("bundle identity changed between pages")
        payload = base64.b64decode(page.payload_base64, validate=True)
        if page.next_offset is None:
            checksum = hashlib.sha256(self._data)
            checksum.update(payload)
            if checksum.hexdigest() != page.bundle_digest:
                _fail("complete byte coverage has a different bundle digest")
        self._data.extend(payload)
        self._total, self._digest = page.total_bytes, page.bundle_digest
        self._complete = page.next_offset is None

    def finish(self):
        if not self.transport_complete:
            _fail("transport coverage is partial", "RESULT_PAGE_INCOMPLETE")
        return bytes(self._data)
