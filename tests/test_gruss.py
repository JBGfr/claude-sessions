"""Begrüßung: Tageszeit, Sprache und Name aus Datei bzw. Umgebung."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claude_sessions import data, einstellungen, texte  # noqa: E402


class GrussTest(unittest.TestCase):
    """Prüft den deutschen Wortlaut — die Sprache wird dafür festgenagelt.

    Ohne das hinge das Ergebnis an der Locale des Rechners, auf dem die Tests
    laufen: seit der Sprachschicht ist Englisch die Grundsprache.
    """

    def setUp(self) -> None:
        # Eigene Einstellungsdatei, damit weder die echte Datei des Nutzers
        # noch ein dort eingetragener Name hereinspielt.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(
            os.environ,
            {"CS_SETTINGS_PATH": str(Path(self.tmp.name) / "settings.json")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(texte.set_sprache, None)
        texte.set_sprache("de")

    def test_tageszeiten(self):
        self.assertEqual("Guten Morgen", data.gruss(7))
        self.assertEqual("Guten Tag", data.gruss(12))
        self.assertEqual("Guten Abend", data.gruss(20))
        self.assertEqual("Guten Abend", data.gruss(3))

    def test_mit_name(self):
        self.assertEqual("Guten Tag, Ada", data.gruss(12, "Ada"))

    def test_auf_englisch(self):
        texte.set_sprache("en")
        self.assertEqual("Good morning", data.gruss(7))
        self.assertEqual("Good evening, Ada", data.gruss(20, "Ada"))

    def test_name_aus_der_umgebung(self):
        with mock.patch.dict(os.environ, {"CS_GREET_NAME": " Ada "}):
            self.assertEqual("Ada", data.gruss_name())

    def test_name_aus_der_einstellungsdatei_schlaegt_die_umgebung(self):
        einstellungen.speichern({"greet_name": "Ada"})
        with mock.patch.dict(os.environ, {"CS_GREET_NAME": "Grace"}):
            self.assertEqual("Ada", data.gruss_name())

    def test_ohne_name(self):
        with mock.patch.dict(os.environ, {"CS_GREET_NAME": ""}):
            self.assertIsNone(data.gruss_name())
        umgebung = {k: v for k, v in os.environ.items() if k != "CS_GREET_NAME"}
        with mock.patch.dict(os.environ, umgebung, clear=True):
            self.assertIsNone(data.gruss_name())


if __name__ == "__main__":
    unittest.main()
