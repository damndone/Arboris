"""Peak physical memory of this process as the macOS kernel accounts it.

ru_maxrss on macOS also counts pages malloc has freed and marked reusable but the
kernel has not yet reclaimed; how many stay resident depends on system memory
pressure, not on the program. The 2026-11-04 OLS diagnostic saw 0.89 GB of such
pages inside a 1.48 GB RSS peak. ri_lifetime_max_phys_footprint is the kernel's
own high-water mark of the process footprint (dirty anonymous plus compressed
memory, reusable pages excluded); Activity Monitor and jetsam use the same
account. It is exact, not sampled.
"""
from __future__ import annotations

import ctypes as C
import os
import sys

_RUSAGE_INFO_V4 = 4
_RUSAGE_FIELDS = 35  # ri_user_time .. ri_runnable_time, all uint64
_LIFETIME_MAX_PHYS_FOOTPRINT = 28  # index after ri_uuid, SDK sys/resource.h
_TASK_VM_INFO = 22
_TASK_VM_INFO_REV1_COUNT = 38
_REUSABLE_PEAK = 9  # index of reusable_peak after virtual_size, region_count, page_size
_COMPRESSED_PEAK = 14  # compressed_peak: pages the kernel compressed, counted in the footprint


class _RUsageV4(C.Structure):
    _fields_ = [("ri_uuid", C.c_uint8 * 16), ("values", C.c_uint64 * _RUSAGE_FIELDS)]


class _VMInfoRev1(C.Structure):
    _layout_, _pack_ = 'ms', 4
    _fields_ = [("virtual_size", C.c_uint64), ("region_count", C.c_int32), ("page_size", C.c_int32),
                ("values", C.c_uint64 * 17)]


def memory_accounting() -> dict[str, int | None]:
    """Kernel peak footprint, peak reusable and peak compressed bytes of this process; None off macOS.

    A footprint outlier with compressed pages is the kernel compressing under host memory
    pressure (2026-11-10: 391-427 MiB in every outlier, 0-26 in normal runs, equal malloc use).
    """
    if sys.platform != "darwin":
        return {"footprint_bytes": None, "reusable_peak_bytes": None, "compressed_peak_bytes": None}
    assert C.sizeof(_RUsageV4) == 296 and C.sizeof(_VMInfoRev1) == 152
    usage = _RUsageV4()
    libproc = C.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    libproc.proc_pid_rusage.argtypes = [C.c_int, C.c_int, C.c_void_p]
    if libproc.proc_pid_rusage(os.getpid(), _RUSAGE_INFO_V4, C.byref(usage)) != 0:
        raise OSError(C.get_errno(), "proc_pid_rusage failed")
    system = C.CDLL("/usr/lib/libSystem.B.dylib")
    system.mach_task_self.restype = C.c_uint32
    system.task_info.argtypes = [C.c_uint32, C.c_uint32, C.c_void_p, C.POINTER(C.c_uint32)]
    info, count = _VMInfoRev1(), C.c_uint32(_TASK_VM_INFO_REV1_COUNT)
    if system.task_info(system.mach_task_self(), _TASK_VM_INFO, C.byref(info), C.byref(count)) != 0 \
            or count.value < _TASK_VM_INFO_REV1_COUNT:
        raise OSError("task_info TASK_VM_INFO rev1 failed")
    return {"footprint_bytes": int(usage.values[_LIFETIME_MAX_PHYS_FOOTPRINT]),
            "reusable_peak_bytes": int(info.values[_REUSABLE_PEAK]),
            "compressed_peak_bytes": int(info.values[_COMPRESSED_PEAK])}
