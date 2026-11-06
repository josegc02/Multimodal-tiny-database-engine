"""Memoria residente actual y pico, separando cliente psycopg y servidor."""

import subprocess
import sys
from pathlib import Path


def parse_status(text):
    values = {}
    for line in text.splitlines():
        if line.startswith(("VmRSS:", "VmHWM:")):
            key, value, unit = line.split()
            if unit != "kB":
                raise ValueError("Unidad desconocida en /proc")
            values[key.rstrip(":")] = int(value) * 1024
    if set(values) != {"VmRSS", "VmHWM"}:
        raise ValueError("RSS/HWM no disponibles")
    return values


def process_memory():
    if sys.platform == "win32":
        return _windows_process_memory()
    return parse_status(Path("/proc/self/status").read_text())


def _windows_process_memory():
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(),
                                      ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    # Windows ya devuelve bytes; mantenemos las claves usadas por los workers.
    return {"VmRSS": counters.WorkingSetSize, "VmHWM": counters.PeakWorkingSetSize}


def backend_memory(container, pid):
    if type(pid) is not int or pid < 1:
        raise ValueError("PID inválido")
    result = subprocess.run(["docker", "exec", container, "cat", f"/proc/{pid}/status"],
                            capture_output=True, text=True, check=True, timeout=15)
    return parse_status(result.stdout)
