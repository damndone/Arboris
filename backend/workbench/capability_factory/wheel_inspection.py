"""Static, no-import inspection of wheel archive bytes."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass

from .contracts import _digest, _text


class WheelInspectionError(ValueError):
    """Raised when a wheel cannot enter offline quarantine."""


@dataclass(frozen=True, slots=True)
class WheelInspectionReport:
    status: str
    artifact_digest: str
    member_count: int
    distribution: str
    version: str


_METADATA_LINE = re.compile(rb"^Name: ([A-Za-z0-9][A-Za-z0-9._-]*)$", re.MULTILINE)
_VERSION_LINE = re.compile(rb"^Version: ([A-Za-z0-9][A-Za-z0-9._-]*)$", re.MULTILINE)
_FORBIDDEN_SUFFIXES = (".pth", "/entry_points.txt", "\\entry_points.txt", "/setup.py", "/setup.cfg", "/pyproject.toml")
_MAX_MEMBERS = 4096
_MAX_MEMBER_BYTES = 64 * 1024 * 1024


def _safe_name(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name or name.startswith("/"):
        return False
    parts = name.split("/")
    return ".." not in parts and all(part for part in parts)


def inspect_wheel_bytes(raw: bytes, *, expected_digest: str) -> WheelInspectionReport:
    if not isinstance(raw, bytes) or not raw:
        raise WheelInspectionError("wheel bytes must be non-empty")
    actual = hashlib.sha256(raw).hexdigest()
    try:
        expected = _digest(expected_digest, "expected_digest")
    except ValueError as error:
        raise WheelInspectionError(str(error)) from error
    if actual != expected:
        raise WheelInspectionError("wheel digest does not match the lock")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as error:
        raise WheelInspectionError("wheel is not a valid zip archive") from error
    with archive:
        members = archive.infolist()
        if not members or len(members) > _MAX_MEMBERS:
            raise WheelInspectionError("wheel member count is outside the bound")
        metadata_members: list[zipfile.ZipInfo] = []
        wheel_members: list[zipfile.ZipInfo] = []
        for member in members:
            if not _safe_name(member.filename):
                raise WheelInspectionError("wheel contains a path escape or unsafe name")
            if member.file_size > _MAX_MEMBER_BYTES:
                raise WheelInspectionError("wheel member is too large")
            mode = (member.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise WheelInspectionError("wheel contains a symlink")
            lowered = member.filename.lower()
            if lowered.endswith(_FORBIDDEN_SUFFIXES):
                raise WheelInspectionError("wheel contains an executable install hook")
            if lowered.endswith(".dist-info/metadata"):
                metadata_members.append(member)
            if lowered.endswith(".dist-info/wheel"):
                wheel_members.append(member)
        if len(metadata_members) != 1 or len(wheel_members) != 1:
            raise WheelInspectionError("wheel must contain exactly one METADATA and WHEEL file")
        metadata = archive.read(metadata_members[0])
        distribution_match = _METADATA_LINE.search(metadata)
        version_match = _VERSION_LINE.search(metadata)
        if not distribution_match or not version_match:
            raise WheelInspectionError("wheel metadata lacks a bounded Name or Version")
        distribution = _text(distribution_match.group(1).decode("ascii"), "distribution")
        version = _text(version_match.group(1).decode("ascii"), "version")
        return WheelInspectionReport("safe", actual, len(members), distribution, version)


__all__ = ["WheelInspectionError", "WheelInspectionReport", "inspect_wheel_bytes"]
