#!/usr/bin/env python3
"""Choose a useful Clang process count for the host without exhausting small systems."""

import ctypes
import os
import platform
import subprocess
from pathlib import Path


GIB = 1024 ** 3
PER_COMPILER = 3 * GIB // 2
SYSTEM_RESERVE = 2 * GIB


def cpu_count():
    if hasattr(os, "sched_getaffinity"):
        cpus = max(1, len(os.sched_getaffinity(0)))
    else:
        cpus = max(1, os.cpu_count() or 1)
    if platform.system() == "Linux":
        quota_path = Path("/sys/fs/cgroup/cpu.max")
        if quota_path.is_file():
            quota, period = quota_path.read_text().split()
            if quota != "max":
                cpus = min(cpus, max(1, (int(quota) + int(period) - 1) // int(period)))
    return cpus


def memory_bytes():
    system = platform.system()
    if system == "Darwin":
        result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                text=True, check=True)
        return int(result.stdout.strip())
    if system == "Linux":
        total = next((int(line.split()[1]) * 1024 for line in
                      Path("/proc/meminfo").read_text().splitlines()
                      if line.startswith("MemTotal:")), None)
        limit_path = Path("/sys/fs/cgroup/memory.max")
        if limit_path.is_file():
            limit = limit_path.read_text().strip()
            if limit != "max":
                total = min(total, int(limit)) if total else int(limit)
        return total
    if system == "Windows":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                        ("total_physical", ctypes.c_ulonglong),
                        ("available_physical", ctypes.c_ulonglong),
                        ("total_page_file", ctypes.c_ulonglong),
                        ("available_page_file", ctypes.c_ulonglong),
                        ("total_virtual", ctypes.c_ulonglong),
                        ("available_virtual", ctypes.c_ulonglong),
                        ("available_extended_virtual", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError("GlobalMemoryStatusEx failed")
        return status.total_physical
    return None


def choose_jobs(cpus, total_memory):
    cpus = max(1, cpus)
    if total_memory is None:
        return cpus
    memory_jobs = max(1, (total_memory - SYSTEM_RESERVE) // PER_COMPILER)
    return min(cpus, memory_jobs)


if __name__ == "__main__":
    print(choose_jobs(cpu_count(), memory_bytes()))
