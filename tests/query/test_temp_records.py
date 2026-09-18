import io
import struct
import unittest

from engine.query._temp_records import read_header, read_record, write_header, write_record


class TestTemporaryRecords(unittest.TestCase):
    def test_round_trip_multiple_records_and_integer_boundaries(self):
        rows = [{"min": -(1 << 63), "max": (1 << 63) - 1, "x": -2.5,
                 "text": "á\x00😀", "null": None, "empty": ""}, {}, {"k": 7}]
        fh = io.BytesIO()
        write_header(fh)
        for row in rows:
            write_record(fh, row)
        fh.seek(0)
        read_header(fh)
        self.assertEqual([read_record(fh) for _ in rows], rows)
        self.assertEqual(fh.read(), b"")

    def test_format_is_explicit_big_endian_struct(self):
        fh = io.BytesIO()
        write_header(fh)
        write_record(fh, {"k": 42})
        self.assertEqual(fh.getvalue(), b"EXT1" + struct.pack(">II", 1, 1) + b"k" + struct.pack(">Bq", 1, 42))

    def test_rejects_truncated_or_invalid_data(self):
        for data in [b"", b"EXT", b"BAD1"]:
            with self.assertRaises(ValueError):
                read_header(io.BytesIO(data))
        fh = io.BytesIO()
        write_record(fh, {"k": "texto"})
        for length in range(len(fh.getvalue())):
            with self.assertRaises(ValueError):
                read_record(io.BytesIO(fh.getvalue()[:length]))
        with self.assertRaises(ValueError):
            read_record(io.BytesIO(struct.pack(">II", 1, 1) + b"k" + b"\xff"))

    def test_rejects_unsupported_values_and_integer_overflow(self):
        for row in [{"k": []}, {"k": True}, {1: "value"}]:
            with self.assertRaises(TypeError):
                write_record(io.BytesIO(), row)
        for value in [1 << 63, -(1 << 63) - 1]:
            with self.assertRaises(ValueError):
                write_record(io.BytesIO(), {"k": value})


if __name__ == "__main__":
    unittest.main()
