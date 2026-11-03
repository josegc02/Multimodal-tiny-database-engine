"""RSS/HWM Linux, sin confundir el cliente psycopg con el servidor."""

import subprocess
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
    return parse_status(Path("/proc/self/status").read_text())


def backend_memory(container, pid):
    if type(pid) is not int or pid < 1:
        raise ValueError("PID inválido")
    result = subprocess.run(["docker", "exec", container, "cat", f"/proc/{pid}/status"],
                            capture_output=True, text=True, check=True, timeout=15)
    return parse_status(result.stdout)
