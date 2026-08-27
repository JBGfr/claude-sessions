"""Einstellungsdatei: tolerant lesen, atomar schreiben, Werte klemmen.

Kein Test fasst die echte Datei des Nutzers an — `CS_SETTINGS_PATH` zeigt
überall auf ein Wegwerf-Verzeichnis.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_sessions import einstellungen  # noqa: E402


class PfadTest(unittest.TestCase):
    """Woher der Ort der Datei kommt."""

    def test_umgebungsvariable_schlaegt_alles(self) -> None:
        with mock.patch.dict(os.environ, {"CS_SETTINGS_PATH": "/tmp/x/y.json",
                                          "XDG_CONFIG_HOME": "/tmp/cfg"}):
            self.assertEqual(Path("/tmp/x/y.json"), einstellungen.pfad())

    def test_leere_variable_zaehlt_wie_nicht_gesetzt(self) -> None:
        with mock.patch.dict(os.environ, {"CS_SETTINGS_PATH": "  ",
                                          "XDG_CONFIG_HOME": "/tmp/cfg"}):
            self.assertEqual(Path("/tmp/cfg/claude-sessions/settings.json"),
                             einstellungen.pfad())

    def test_ohne_xdg_unter_config(self) -> None:
        umgebung = {k: v for k, v in os.environ.items()
                    if k not in ("CS_SETTINGS_PATH", "XDG_CONFIG_HOME")}
        with mock.patch.dict(os.environ, umgebung, clear=True):
            self.assertEqual(
                Path.home() / ".config" / "claude-sessions" / "settings.json",
                einstellungen.pfad())


class _MitDatei(unittest.TestCase):
    """Basis: ein leeres Verzeichnis und CS_SETTINGS_PATH darauf."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.datei = Path(self.tmp.name) / "settings.json"
        patcher = mock.patch.dict(os.environ,
                                  {"CS_SETTINGS_PATH": str(self.datei)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def schreibe(self, text: str) -> None:
        self.datei.write_text(text, encoding="utf-8")


class LadenTest(_MitDatei):
    """Lesen darf nie scheitern — im Zweifel die Vorgaben."""

    def test_ohne_datei_die_vorgaben(self) -> None:
        self.assertEqual(einstellungen.VORGABEN, einstellungen.laden())

    def test_kaputtes_json(self) -> None:
        self.schreibe("{ das ist kein JSON")
        self.assertEqual(einstellungen.VORGABEN, einstellungen.laden())

    def test_leere_datei(self) -> None:
        self.schreibe("")
        self.assertEqual(einstellungen.VORGABEN, einstellungen.laden())

    def test_liste_statt_objekt(self) -> None:
        self.schreibe('["language", "de"]')
        self.assertEqual(einstellungen.VORGABEN, einstellungen.laden())

    def test_verzeichnis_an_der_stelle_der_datei(self) -> None:
        self.datei.mkdir()
        self.assertEqual(einstellungen.VORGABEN, einstellungen.laden())

    def test_unbekannte_schluessel_fliegen_raus(self) -> None:
        self.schreibe(json.dumps({"language": "de", "hintertuer": "rm -rf",
                                  "42": None}))
        werte = einstellungen.laden()
        self.assertEqual("de", werte["language"])
        self.assertEqual(set(einstellungen.VORGABEN), set(werte))

    def test_fehlende_schluessel_bekommen_die_vorgabe(self) -> None:
        self.schreibe(json.dumps({"language": "en"}))
        werte = einstellungen.laden()
        self.assertEqual("en", werte["language"])
        self.assertEqual(einstellungen.VORGABEN["refresh_seconds"],
                         werte["refresh_seconds"])


class WertepruefungTest(unittest.TestCase):
    """`pruefen()` allein — ohne Datei, damit die Regeln scharf sichtbar sind."""

    def pruefe(self, **roh):
        return einstellungen.pruefen(roh)

    def test_sprache_nur_aus_der_liste(self) -> None:
        self.assertEqual("de", self.pruefe(language="de")["language"])
        self.assertEqual("en", self.pruefe(language=" EN ")["language"])
        self.assertEqual("auto", self.pruefe(language="klingonisch")["language"])
        self.assertEqual("auto", self.pruefe(language=7)["language"])

    def test_zahlen_werden_geklemmt(self) -> None:
        self.assertEqual(2, self.pruefe(refresh_seconds=0)["refresh_seconds"])
        self.assertEqual(60, self.pruefe(refresh_seconds=9999)["refresh_seconds"])
        self.assertEqual(6, self.pruefe(refresh_seconds=6)["refresh_seconds"])
        self.assertEqual(5, self.pruefe(max_stored_rows=1)["max_stored_rows"])
        self.assertEqual(500, self.pruefe(max_stored_rows=10_000)["max_stored_rows"])
        self.assertEqual(0, self.pruefe(wd_notify_max_per_hour=-3)
                         ["wd_notify_max_per_hour"])
        self.assertEqual(100, self.pruefe(wd_notify_max_per_hour=999)
                         ["wd_notify_max_per_hour"])

    def test_zahl_aus_text_und_komma(self) -> None:
        self.assertEqual(12, self.pruefe(refresh_seconds="12")["refresh_seconds"])
        self.assertEqual(10, self.pruefe(refresh_seconds=9.7)["refresh_seconds"])

    def test_unsinn_faellt_auf_die_vorgabe(self) -> None:
        self.assertEqual(6, self.pruefe(refresh_seconds="bald")["refresh_seconds"])
        self.assertEqual(6, self.pruefe(refresh_seconds=None)["refresh_seconds"])
        self.assertEqual(40, self.pruefe(max_stored_rows=[1])["max_stored_rows"])

    def test_wahrheitswert_ist_keine_zahl(self) -> None:
        """`True` ist in Python eine 1 — als Takt wäre das eine Sekunde."""
        self.assertEqual(6, self.pruefe(refresh_seconds=True)["refresh_seconds"])

    def test_schalter(self) -> None:
        self.assertFalse(self.pruefe(show_greeting=False)["show_greeting"])
        self.assertFalse(self.pruefe(wd_notify="false")["wd_notify"])
        self.assertTrue(self.pruefe(wd_notify="ja")["wd_notify"])
        self.assertTrue(self.pruefe(show_greeting="vielleicht")["show_greeting"])

    def test_name_wird_gesaeubert(self) -> None:
        self.assertEqual("Ada", self.pruefe(greet_name="  Ada \n")["greet_name"])
        self.assertEqual("", self.pruefe(greet_name=42)["greet_name"])
        lang = "A" * (einstellungen.NAME_MAXLEN + 20)
        self.assertEqual(einstellungen.NAME_MAXLEN,
                         len(self.pruefe(greet_name=lang)["greet_name"]))

    def test_ohne_eingabe_die_vorgaben(self) -> None:
        self.assertEqual(einstellungen.VORGABEN, einstellungen.pruefen(None))


class SpeichernTest(_MitDatei):
    def test_hin_und_zurueck(self) -> None:
        einstellungen.speichern({"language": "de", "greet_name": "Ada",
                                 "refresh_seconds": 12, "wd_notify": False})
        werte = einstellungen.laden()
        self.assertEqual("de", werte["language"])
        self.assertEqual("Ada", werte["greet_name"])
        self.assertEqual(12, werte["refresh_seconds"])
        self.assertFalse(werte["wd_notify"])

    def test_geschrieben_wird_der_gepruefte_wert(self) -> None:
        einstellungen.speichern({"refresh_seconds": 9999, "language": "xx"})
        roh = json.loads(self.datei.read_text(encoding="utf-8"))
        self.assertEqual(60, roh["refresh_seconds"])
        self.assertEqual("auto", roh["language"])
        self.assertEqual(set(einstellungen.VORGABEN), set(roh))

    def test_legt_das_verzeichnis_an(self) -> None:
        tief = Path(self.tmp.name) / "a" / "b" / "settings.json"
        einstellungen.speichern({"language": "de"}, tief)
        self.assertTrue(tief.exists())

    def test_aktualisieren_laesst_den_rest_stehen(self) -> None:
        einstellungen.speichern({"language": "de", "greet_name": "Ada"})
        einstellungen.aktualisieren(refresh_seconds=30)
        werte = einstellungen.laden()
        self.assertEqual("Ada", werte["greet_name"])
        self.assertEqual("de", werte["language"])
        self.assertEqual(30, werte["refresh_seconds"])

    def test_ersetzt_statt_zu_ueberschreiben(self) -> None:
        """Die alte Datei wird nie in place beschrieben (Inode-Regel)."""
        einstellungen.speichern({"refresh_seconds": 10})
        alt = self.datei.stat().st_ino
        einstellungen.speichern({"refresh_seconds": 20})
        self.assertNotEqual(alt, self.datei.stat().st_ino)

    def test_offener_leser_sieht_den_alten_stand_ganz(self) -> None:
        """Wer die Datei offen hat, bekommt keine halbe Fassung serviert."""
        einstellungen.speichern({"refresh_seconds": 10})
        with self.datei.open(encoding="utf-8") as fh:
            einstellungen.speichern({"refresh_seconds": 30})
            alt = json.loads(fh.read())
        self.assertEqual(10, alt["refresh_seconds"])
        self.assertEqual(30, einstellungen.laden()["refresh_seconds"])

    def test_keine_tempdateien_bleiben_liegen(self) -> None:
        einstellungen.speichern({"refresh_seconds": 10})
        einstellungen.speichern({"refresh_seconds": 20})
        self.assertEqual([self.datei],
                         sorted(Path(self.tmp.name).iterdir()))

    def test_gescheitertes_schreiben_laesst_den_alten_stand(self) -> None:
        if os.geteuid() == 0:
            self.skipTest("als root greifen Verzeichnisrechte nicht")
        einstellungen.speichern({"refresh_seconds": 10})
        ordner = Path(self.tmp.name)
        ordner.chmod(stat.S_IRUSR | stat.S_IXUSR)
        self.addCleanup(ordner.chmod, stat.S_IRWXU)
        with self.assertRaises(OSError):
            einstellungen.speichern({"refresh_seconds": 20})
        ordner.chmod(stat.S_IRWXU)
        self.assertEqual(10, einstellungen.laden()["refresh_seconds"])


class GreetNameTest(_MitDatei):
    """Die Kette: Datei → Umgebungsvariable → leer."""

    def test_datei_schlaegt_umgebung(self) -> None:
        einstellungen.speichern({"greet_name": "Ada"})
        with mock.patch.dict(os.environ, {"CS_GREET_NAME": "Grace"}):
            self.assertEqual("Ada", einstellungen.greet_name())

    def test_umgebung_wenn_die_datei_schweigt(self) -> None:
        einstellungen.speichern({"greet_name": ""})
        with mock.patch.dict(os.environ, {"CS_GREET_NAME": " Grace "}):
            self.assertEqual("Grace", einstellungen.greet_name())

    def test_ohne_datei_und_ohne_variable_leer(self) -> None:
        umgebung = {k: v for k, v in os.environ.items()
                    if k != "CS_GREET_NAME"}
        with mock.patch.dict(os.environ, umgebung, clear=True):
            self.assertEqual("", einstellungen.greet_name())

    def test_sprache_kommt_aus_der_datei(self) -> None:
        einstellungen.speichern({"language": "de"})
        self.assertEqual("de", einstellungen.sprache())


if __name__ == "__main__":
    unittest.main()
