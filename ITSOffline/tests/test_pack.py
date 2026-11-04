import tempfile
import unittest
from pathlib import Path

from its_offline.pack import build_pack, parse_pack_catalog, unpack_pack


class PackTests(unittest.TestCase):
    def test_roundtrip_and_filters(self) -> None:
        good = b"hello-its"
        bad_body = b"tampered"
        # Build pack with three entries; then corrupt MD5 of the second in the blob.
        raw = build_pack(
            [
                ("ok.txt", good),
                ("bad.txt", bad_body),
                ("nested/..\\escape.txt", b"nope"),
            ]
        )
        # Corrupt MD5 for second record (offset HEADER + RECORD).
        raw = bytearray(raw)
        # second record md5 starts at 308 + 284 + 12
        start = 308 + 284 + 12
        raw[start : start + 16] = b"\x00" * 16
        raw = bytes(raw)

        catalog = parse_pack_catalog(raw)
        self.assertEqual(len(catalog.entries), 3)

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            # Write a pack that only has good + escape (valid MD5) to test path refuse.
            safe_pack = build_pack(
                [
                    ("ok.txt", good),
                    ("..\\escape.txt", b"evil"),
                    ("dir/ok2.txt", b"two"),
                ]
            )
            written, reasons = unpack_pack(
                self._write(tmp, "safe.pack", safe_pack), dest
            )
            self.assertEqual(written, 2)
            self.assertTrue(any("escapes" in r for r in reasons))
            self.assertTrue((dest / "ok.txt").is_file())
            self.assertTrue((dest / "dir" / "ok2.txt").is_file())
            self.assertFalse((dest / "escape.txt").exists())

        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            written, reasons = unpack_pack(self._write(tmp, "bad.pack", raw), dest)
            self.assertEqual(written, 0)
            self.assertTrue(any("MD5 mismatch" in r for r in reasons))
            self.assertFalse(dest.exists() and any(dest.iterdir()))

    @staticmethod
    def _write(tmp: str, name: str, data: bytes) -> Path:
        path = Path(tmp) / name
        path.write_bytes(data)
        return path


if __name__ == "__main__":
    unittest.main()
