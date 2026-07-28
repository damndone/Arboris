from __future__ import annotations

import io
import zipfile

import pytest


def _wheel(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries:
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_wheel_inspection_is_static_and_accepts_bounded_safe_metadata():
    from workbench.capability_factory.wheel_inspection import inspect_wheel_bytes

    raw = _wheel(
        [
            ("safe_library/__init__.py", b"VALUE = 1\n"),
            ("safe_library-1.2.3.dist-info/METADATA", b"Metadata-Version: 2.3\nName: safe-library\nVersion: 1.2.3\n"),
            ("safe_library-1.2.3.dist-info/WHEEL", b"Wheel-Version: 1.0\n"),
        ]
    )

    report = inspect_wheel_bytes(raw, expected_digest=__import__("hashlib").sha256(raw).hexdigest())

    assert report.status == "safe"
    assert report.member_count == 3
    assert report.distribution == "safe-library"
    assert report.version == "1.2.3"


@pytest.mark.parametrize(
    "entry",
    [
        ("../escape.py", b"x"),
        ("/absolute.py", b"x"),
        ("safe_library/unsafe.pth", b"import os\n"),
        ("safe_library-1.2.3.dist-info/entry_points.txt", b"[console_scripts]\nrun=safe_library:main\n"),
    ],
)
def test_wheel_inspection_rejects_path_escape_and_executable_hooks(entry):
    from workbench.capability_factory.wheel_inspection import WheelInspectionError, inspect_wheel_bytes

    raw = _wheel(
        [
            ("safe_library-1.2.3.dist-info/METADATA", b"Metadata-Version: 2.3\nName: safe-library\nVersion: 1.2.3\n"),
            ("safe_library-1.2.3.dist-info/WHEEL", b"Wheel-Version: 1.0\n"),
            entry,
        ]
    )

    with pytest.raises(WheelInspectionError):
        inspect_wheel_bytes(raw, expected_digest=__import__("hashlib").sha256(raw).hexdigest())
