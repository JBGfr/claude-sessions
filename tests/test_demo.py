"""Demo-Modus: erfundene Daten, keine echten — und nur auf Ansage."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from claude_sessions import demo  # noqa: E402


class SchalterTest(unittest.TestCase):
    def test_aus_ohne_variable(self):
        umgebung = {k: v for k, v in os.environ.items() if k != "CS_DEMO"}
        with mock.patch.dict(os.environ, umgebung, clear=True):
            self.assertFalse(demo.aktiv())

    def test_werte_die_aus_bedeuten(self):
        for wert in ("", "0", "false", "no", "  "):
            with mock.patch.dict(os.environ, {"CS_DEMO": wert}):
                self.assertFalse(demo.aktiv(), wert)

    def test_an(self):
        for wert in ("1", "true", "ja"):
            with mock.patch.dict(os.environ, {"CS_DEMO": wert}):
                self.assertTrue(demo.aktiv(), wert)


class DatenTest(unittest.TestCase):
    def setUp(self):
        self.snap = demo.snapshot()

    def test_zaehler_passen_zu_den_zeilen(self):
        """Sonst zeigt der Screenshot Zahlen, die zur Liste nicht passen."""
        from claude_sessions import data
        live = [s for s in self.snap.sessions if s.group == data.GROUP_LIVE]
        gespeichert = [s for s in self.snap.sessions
                       if s.group == data.GROUP_STORED]
        self.assertEqual(len(live), self.snap.n_live)
        self.assertEqual(len(gespeichert), self.snap.n_stored)
        self.assertEqual(len([s for s in live if s.live_status == "busy"]),
                         self.snap.n_busy)

    def test_keine_echten_pfade(self):
        """Nichts aus einem echten Home darf im Bild landen."""
        for s in self.snap.sessions:
            self.assertFalse(s.cwd.startswith("/home/"), s.cwd)
            self.assertNotIn("kali", s.cwd.lower())
            self.assertNotIn("Projekte", s.cwd)

    def test_kennungen_sind_erfunden(self):
        """Dieselbe Regel wie im Leck-Gate: jede Gruppe ein Zeichen."""
        for s in self.snap.sessions:
            teile = s.id.split("-")
            self.assertEqual(5, len(teile), s.id)
            for teil in teile:
                self.assertEqual(1, len(set(teil.lower())), s.id)

    def test_zwei_laeufe_sind_gleich(self):
        zweiter = demo.snapshot()
        self.assertEqual([s.title for s in self.snap.sessions],
                         [s.title for s in zweiter.sessions])


if __name__ == "__main__":
    unittest.main()
