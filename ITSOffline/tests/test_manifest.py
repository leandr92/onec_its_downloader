import unittest
from pathlib import Path

from its_offline.manifest import (
    access_has_code,
    filter_databases,
    parse_manifest_xml,
    resolve_kit_codes,
)

FIXTURE = Path(__file__).parent / "fixtures" / "latest.xml"


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = parse_manifest_xml(FIXTURE.read_text(encoding="utf-8"))

    def test_https_base(self) -> None:
        self.assertTrue(self.manifest.base.startswith("https://"))

    def test_access_exact_token(self) -> None:
        only16 = next(db for db in self.manifest.databases if db.name == "Only16")
        self.assertTrue(access_has_code(only16.access, "16"))
        # ``161`` must not match as a substring of ``16`` or ``165``
        self.assertFalse(access_has_code(only16.access, "161"))
        techno = next(db for db in self.manifest.databases if db.name == "Techno")
        self.assertTrue(access_has_code(techno.access, "160"))
        self.assertFalse(access_has_code(techno.access, "16"))
        self.assertFalse(access_has_code(techno.access, "161"))

    def test_filter_prof_includes_shared_and_161(self) -> None:
        codes = resolve_kit_codes(["prof"])
        selected = filter_databases(self.manifest.databases, kit_codes=codes)
        names = [db.name for db in selected]
        self.assertEqual(names, ["Shared", "ProfAndMed"])

    def test_filter_medicine(self) -> None:
        codes = resolve_kit_codes(["medicine"])
        selected = filter_databases(self.manifest.databases, kit_codes=codes)
        names = [db.name for db in selected]
        self.assertEqual(names, ["Shared", "ProfAndMed"])

    def test_filter_techno(self) -> None:
        codes = resolve_kit_codes(["techno"])
        selected = filter_databases(self.manifest.databases, kit_codes=codes)
        names = [db.name for db in selected]
        self.assertEqual(names, ["Shared", "Techno"])

    def test_all(self) -> None:
        selected = filter_databases(self.manifest.databases, all_kits=True)
        self.assertEqual(len(selected), 4)

    def test_database_narrow(self) -> None:
        selected = filter_databases(
            self.manifest.databases, all_kits=True, database_name="Techno"
        )
        self.assertEqual([db.name for db in selected], ["Techno"])


if __name__ == "__main__":
    unittest.main()
