import sys
import unittest
from unittest.mock import patch

from benchmarks.text_memory import process_memory


class TestProcessMemory(unittest.TestCase):
    @unittest.skipUnless(sys.platform in ("linux", "win32"), "requiere Linux o Windows")
    def test_native_memory_reports_resident_bytes_and_peak(self):
        allocation = bytearray(8 * 1024 * 1024)
        # Tocar las páginas para que la reserva se refleje en memoria residente.
        for offset in range(0, len(allocation), 4096):
            allocation[offset] = 1
        memory = process_memory()
        self.assertIsInstance(memory["VmRSS"], int)
        self.assertIsInstance(memory["VmHWM"], int)
        self.assertGreaterEqual(memory["VmRSS"], len(allocation))
        self.assertGreaterEqual(memory["VmHWM"], memory["VmRSS"])

    def test_linux_reads_proc_and_converts_kib_to_bytes(self):
        with patch("benchmarks.text_memory.sys.platform", "linux"), \
             patch("benchmarks.text_memory.Path.read_text",
                   return_value="VmRSS: 12 kB\nVmHWM: 24 kB\n") as read:
            self.assertEqual(process_memory(), {"VmRSS": 12288, "VmHWM": 24576})
            read.assert_called_once_with()
