"""Das systemd-Drop-in, mit dem die App die Pop-up-Werte weitergibt.

Zwei Dinge sind hier wichtig genug für eigene Tests:

* **Inhalt.** Der Watchdog liest `CW_NOTIFY` und `CW_NOTIFY_MAX_PER_HOUR`
  aus seiner Umgebung. Steht in der Datei ein Tippfehler, merkt das niemand
  — die Meldungen bleiben einfach aus (oder kommen weiter).
* **Nur bei Änderung schreiben.** Am Schreiben hängt ein Neustart des
  Daemons; wer im Dialog nur die Sprache umstellt, darf keinen laufenden
  Watchdog unterbrechen.

Kein Test fasst die echte Datei des Nutzers an: `CS_WD_DROPIN_PATH` zeigt
überall in ein Wegwerf-Verzeichnis.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_sessions import einstellungen  # noqa: E402


class PfadTest(unittest.TestCase):
    """Woher der Ort des Drop-ins kommt."""

    def test_umgebungsvariable_schlaegt_alles(self) -> None:
        with mock.patch.dict(os.environ,
                             {"CS_WD_DROPIN_PATH": "/tmp/x/eigen.conf",
                              "XDG_CONFIG_HOME": "/tmp/cfg"}):
            self.assertEqual(Path("/tmp/x/eigen.conf"),
                             einstellungen.dropin_pfad())

    def test_leere_variable_zaehlt_wie_nicht_gesetzt(self) -> None:
        with mock.patch.dict(os.environ, {"CS_WD_DROPIN_PATH": "  ",
                                          "XDG_CONFIG_HOME": "/tmp/cfg"}):
            self.assertEqual(
                Path("/tmp/cfg/systemd/user/claude-watchdog.service.d"
                     "/uebersteuerung.conf"),
                einstellungen.dropin_pfad())

    def test_ohne_xdg_unter_config(self) -> None:
        umgebung = {k: v for k, v in os.environ.items()
                    if k not in ("CS_WD_DROPIN_PATH", "XDG_CONFIG_HOME")}
        with mock.patch.dict(os.environ, umgebung, clear=True):
            self.assertEqual(
                Path.home() / ".config" / "systemd" / "user"
                / "claude-watchdog.service.d" / "uebersteuerung.conf",
                einstellungen.dropin_pfad())

    def test_unit_ist_der_nachbar_des_ordners(self) -> None:
        with mock.patch.dict(
                os.environ,
                {"CS_WD_DROPIN_PATH":
                 "/tmp/u/claude-watchdog.service.d/uebersteuerung.conf"}):
            self.assertEqual(Path("/tmp/u/claude-watchdog.service"),
                             einstellungen.wd_unit_pfad())


class _MitDropin(unittest.TestCase):
    """Basis: ein leeres Verzeichnis und `CS_WD_DROPIN_PATH` darauf."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ordner = (Path(self.tmp.name) / "systemd" / "user"
                       / "claude-watchdog.service.d")
        self.datei = self.ordner / "uebersteuerung.conf"
        patcher = mock.patch.dict(os.environ,
                                  {"CS_WD_DROPIN_PATH": str(self.datei)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def unit_anlegen(self) -> Path:
        """Die Watchdog-Unit neben dem `.d`-Ordner anlegen."""
        unit = einstellungen.wd_unit_pfad()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text("[Service]\n", encoding="utf-8")
        return unit

    def zeilen(self) -> list[str]:
        return self.datei.read_text(encoding="utf-8").splitlines()

    def reste(self) -> list[str]:
        """Übrig gebliebene Tempdateien im Zielverzeichnis."""
        return [p.name for p in self.ordner.iterdir()
                if p.name != self.datei.name]


class InhaltTest(_MitDropin):
    """Was in der Datei steht."""

    def test_werte_stehen_als_environment_zeilen_drin(self) -> None:
        einstellungen.dropin_schreiben({"wd_notify": True,
                                        "wd_notify_max_per_hour": 12})
        zeilen = self.zeilen()
        self.assertIn("[Service]", zeilen)
        self.assertIn("Environment=CW_NOTIFY=1", zeilen)
        self.assertIn("Environment=CW_NOTIFY_MAX_PER_HOUR=12", zeilen)

    def test_abgeschaltet_ist_eine_null(self) -> None:
        """`CW_NOTIFY` gilt im Watchdog als aus, wenn dort 0/false/no steht."""
        einstellungen.dropin_schreiben({"wd_notify": False})
        self.assertIn("Environment=CW_NOTIFY=0", self.zeilen())

    def test_kopf_nennt_den_urheber(self) -> None:
        """Wer die Datei später von Hand findet, soll wissen, woher sie ist."""
        einstellungen.dropin_schreiben({})
        erste = self.zeilen()[0]
        self.assertTrue(erste.startswith("#"), erste)
        self.assertIn("Claude-Sessions", erste)

    def test_datei_endet_mit_zeilenumbruch(self) -> None:
        einstellungen.dropin_schreiben({})
        text = self.datei.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))

    def test_werte_werden_geklemmt(self) -> None:
        """Die Grenze gilt auch hier — 999 wäre kein Deckel, sondern Unfug."""
        einstellungen.dropin_schreiben({"wd_notify_max_per_hour": 999})
        oben = einstellungen.GRENZEN["wd_notify_max_per_hour"][1]
        self.assertIn("Environment=CW_NOTIFY_MAX_PER_HOUR=%d" % oben,
                      self.zeilen())

    def test_unsinn_faellt_auf_die_vorgabe(self) -> None:
        einstellungen.dropin_schreiben({"wd_notify_max_per_hour": "viele"})
        self.assertIn("Environment=CW_NOTIFY_MAX_PER_HOUR=%d"
                      % einstellungen.VORGABEN["wd_notify_max_per_hour"],
                      self.zeilen())

    def test_inhalt_haengt_nur_an_den_beiden_werten(self) -> None:
        """Sprache und Takt gehen den Watchdog nichts an."""
        a = einstellungen.dropin_inhalt({"language": "de",
                                         "refresh_seconds": 9,
                                         "wd_notify": True})
        b = einstellungen.dropin_inhalt({"language": "en",
                                         "refresh_seconds": 42,
                                         "wd_notify": True})
        self.assertEqual(a, b)


class SchreibenTest(_MitDropin):
    """Wann geschrieben wird — und wie."""

    def test_ordner_wird_angelegt(self) -> None:
        self.assertFalse(self.ordner.exists())
        self.assertTrue(einstellungen.dropin_schreiben({}))
        self.assertTrue(self.datei.exists())

    def test_unveraendert_wird_nicht_neu_geschrieben(self) -> None:
        werte = {"wd_notify": True, "wd_notify_max_per_hour": 3}
        self.assertTrue(einstellungen.dropin_schreiben(werte))
        vorher = self.datei.stat()
        # Zweiter Lauf mit denselben Werten: kein Schreiben, kein neuer Inode
        # — daran hängt, ob der Watchdog neu gestartet wird.
        self.assertFalse(einstellungen.dropin_schreiben(dict(werte)))
        nachher = self.datei.stat()
        self.assertEqual(vorher.st_ino, nachher.st_ino)
        self.assertEqual(vorher.st_mtime_ns, nachher.st_mtime_ns)

    def test_geaenderter_wert_wird_geschrieben(self) -> None:
        einstellungen.dropin_schreiben({"wd_notify_max_per_hour": 3})
        self.assertTrue(
            einstellungen.dropin_schreiben({"wd_notify_max_per_hour": 4}))
        self.assertIn("Environment=CW_NOTIFY_MAX_PER_HOUR=4", self.zeilen())

    def test_kaputte_datei_wird_ersetzt(self) -> None:
        """Was da steht, ist unlesbar — dann eben neu schreiben."""
        self.ordner.mkdir(parents=True)
        self.datei.write_bytes(b"\xff\xfe kein UTF-8")
        self.assertTrue(einstellungen.dropin_schreiben({}))
        self.assertIn("[Service]", self.zeilen())

    def test_atomar_ersetzt_statt_ueberschrieben(self) -> None:
        """Ein offener Leser darf nie eine halbe Datei sehen.

        `os.replace()` hängt einen **neuen** Inode an den Namen; wer die alte
        Datei offen hat, liest sie unverändert zu Ende. Würde in place
        geschrieben, stünde bei einem Abbruch Bruchstückwerk darin — und
        systemd liest sie ohne Vorwarnung genau dann.
        """
        einstellungen.dropin_schreiben({"wd_notify_max_per_hour": 1})
        alt_ino = self.datei.stat().st_ino
        with self.datei.open(encoding="utf-8") as offen:
            einstellungen.dropin_schreiben({"wd_notify_max_per_hour": 2})
            self.assertIn("CW_NOTIFY_MAX_PER_HOUR=1", offen.read())
        self.assertNotEqual(alt_ino, self.datei.stat().st_ino)
        self.assertIn("CW_NOTIFY_MAX_PER_HOUR=2",
                      self.datei.read_text(encoding="utf-8"))

    def test_keine_tempdateien_bleiben_liegen(self) -> None:
        einstellungen.dropin_schreiben({})
        einstellungen.dropin_schreiben({"wd_notify": False})
        self.assertEqual([], self.reste())

    def test_pfad_als_argument_schlaegt_die_umgebung(self) -> None:
        anders = Path(self.tmp.name) / "woanders.conf"
        self.assertTrue(einstellungen.dropin_schreiben({}, anders))
        self.assertTrue(anders.exists())
        self.assertFalse(self.datei.exists())

    def test_unbeschreibbarer_ort_meldet_sich(self) -> None:
        """Der Fehlerpfad muss auslösen können — sonst prüft er nichts.

        Die App fängt den `OSError` und zeigt ihn an; still verschlucken
        würde bedeuten, dass eine Einstellung sichtbar gespeichert ist, aber
        nirgends ankommt.
        """
        block = Path(self.tmp.name) / "keinordner"
        block.write_text("ich bin eine Datei\n", encoding="utf-8")
        with self.assertRaises(OSError):
            einstellungen.dropin_schreiben({}, block / "drop.conf")


class UnitVorhandenTest(_MitDropin):
    """Ohne Watchdog-Unit überspringt die App den Watchdog-Teil still."""

    def test_ohne_unit_nicht_vorhanden(self) -> None:
        self.assertFalse(einstellungen.wd_unit_vorhanden())

    def test_mit_unit_vorhanden(self) -> None:
        self.unit_anlegen()
        self.assertTrue(einstellungen.wd_unit_vorhanden())

    def test_toter_symlink_zaehlt_als_vorhanden(self) -> None:
        """Ein Symlink ins Leere heißt „woanders installiert", nicht „weg"."""
        unit = einstellungen.wd_unit_pfad()
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.symlink_to(Path(self.tmp.name) / "gibt-es-nicht.service")
        self.assertFalse(unit.exists())          # Ziel fehlt wirklich
        self.assertTrue(einstellungen.wd_unit_vorhanden())


if __name__ == "__main__":
    unittest.main()
