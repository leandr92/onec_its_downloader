import unittest
from pathlib import Path

from its_offline.iscf import parse_iscf

CAB_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "data" / "_aboutits_out" / "Storage" / "Data.cab",
    Path(__file__).resolve().parents[1] / "data" / "_v8_data.cab",
]


class IscfCatalogTests(unittest.TestCase):
    def test_catalog_maps_gif_and_css_names(self) -> None:
        cab_path = next((p for p in CAB_CANDIDATES if p.is_file()), None)
        if cab_path is None:
            self.skipTest("no local Data.cab fixture")
        data = cab_path.read_bytes()
        folders, files = parse_iscf(data)
        self.assertTrue(folders)
        self.assertTrue(files)
        by_path = {f.path.replace("\\", "/").lower(): f for f in files}
        gif = by_path.get("src/btn-bcg-gr.gif")
        if gif is not None:
            self.assertEqual(gif.offset, 0)
            self.assertEqual(gif.size, 414)


if __name__ == "__main__":
    unittest.main()
