"""Sprachschicht: Grundsprache, Auto-Erkennung und Vollständigkeit.

Der wichtigste Test steht ganz unten: die beiden Texttabellen werden
**gegeneinander** geprüft. Eine Übersetzung, die einen Schlüssel vergisst,
und ein englischer Text, den niemand übersetzt hat, fallen damit beide auf —
sonst merkt man so etwas erst an einer halb deutschen Oberfläche.
"""
from __future__ import annotations

import os
import re
import string
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_sessions import einstellungen, texte  # noqa: E402

#: Alle Sprachen, deren Tabellen es gibt (Grundsprache eingeschlossen).
ALLE = ("en",) + tuple(texte.UEBERSETZUNGEN)


def platzhalter(text: str) -> set[str]:
    """Die Namen der `{…}`-Platzhalter eines Textes, ohne Formatangabe."""
    namen = set()
    for _lit, feld, _spec, _konv in string.Formatter().parse(text):
        if feld:
            namen.add(feld)
    return namen


class _MitEigenerDatei(unittest.TestCase):
    """Eigene Einstellungsdatei und aufgeräumte Sprachmerkung je Test."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.datei = Path(self.tmp.name) / "settings.json"
        patcher = mock.patch.dict(os.environ,
                                  {"CS_SETTINGS_PATH": str(self.datei)})
        patcher.start()
        self.addCleanup(patcher.stop)
        # Nach jedem Test die gemerkte Sprache verwerfen, damit kein Test
        # den nächsten (oder ein anderes Testmodul) faerbt.
        self.addCleanup(texte.set_sprache, None)
        texte.set_sprache(None)

    def umgebung(self, **werte: str):
        """Locale-Variablen setzen; nicht genannte werden entfernt."""
        rest = {k: v for k, v in os.environ.items()
                if k not in ("LANG", "LC_ALL", "LC_MESSAGES", "LANGUAGE")}
        rest.update(werte)
        patcher = mock.patch.dict(os.environ, rest, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class GrundspracheTest(_MitEigenerDatei):
    def test_englisch_ist_die_vorgabe(self) -> None:
        self.umgebung(LANG="C")
        texte.set_sprache(None)
        self.assertEqual("en", texte.sprache())
        self.assertEqual("Open", texte.t("knopf.oeffnen"))

    def test_ohne_locale_ebenfalls_englisch(self) -> None:
        self.umgebung()
        texte.set_sprache(None)
        self.assertEqual("en", texte.sprache())

    def test_deutsch_aus_den_einstellungen(self) -> None:
        self.umgebung(LANG="C")
        einstellungen.speichern({"language": "de"})
        texte.set_sprache(None)
        self.assertEqual("de", texte.sprache())
        self.assertEqual("Öffnen", texte.t("knopf.oeffnen"))

    def test_englisch_aus_den_einstellungen_schlaegt_die_locale(self) -> None:
        self.umgebung(LANG="de_DE.UTF-8")
        einstellungen.speichern({"language": "en"})
        texte.set_sprache(None)
        self.assertEqual("en", texte.sprache())

    def test_kaputte_einstellungen_hindern_nicht(self) -> None:
        self.umgebung(LANG="de_DE.UTF-8")
        self.datei.parent.mkdir(parents=True, exist_ok=True)
        self.datei.write_text("{kaputt", encoding="utf-8")
        texte.set_sprache(None)
        self.assertEqual("de", texte.sprache())  # auto → Locale


class AutoTest(_MitEigenerDatei):
    """„auto" folgt der Locale der Sitzung."""

    def setUp(self) -> None:
        super().setUp()
        einstellungen.speichern({"language": "auto"})

    def pruefe(self, erwartet: str, **umgebung: str) -> None:
        self.umgebung(**umgebung)
        texte.set_sprache(None)
        self.assertEqual(erwartet, texte.sprache())

    def test_deutsche_locale(self) -> None:
        self.pruefe("de", LANG="de_DE.UTF-8")

    def test_englische_locale(self) -> None:
        self.pruefe("en", LANG="en_US.UTF-8")

    def test_fremde_locale_faellt_auf_englisch(self) -> None:
        self.pruefe("en", LANG="fr_FR.UTF-8")

    def test_lc_all_schlaegt_lang(self) -> None:
        self.pruefe("en", LC_ALL="C", LANG="de_DE.UTF-8")
        self.pruefe("de", LC_ALL="de_AT.UTF-8", LANG="en_US.UTF-8")


class UmschaltenTest(_MitEigenerDatei):
    def test_set_sprache(self) -> None:
        self.assertEqual("de", texte.set_sprache("de"))
        self.assertEqual("Öffnen", texte.t("knopf.oeffnen"))
        self.assertEqual("en", texte.set_sprache("EN"))
        self.assertEqual("Open", texte.t("knopf.oeffnen"))

    def test_auto_geht_ueber_die_locale(self) -> None:
        self.umgebung(LANG="de_DE.UTF-8")
        self.assertEqual("de", texte.set_sprache("auto"))

    def test_unsinn_landet_bei_der_ableitung(self) -> None:
        self.umgebung(LANG="C")
        self.assertIn(texte.set_sprache("klingonisch"), texte.SPRACHEN)


class NachschlagenTest(_MitEigenerDatei):
    def setUp(self) -> None:
        super().setUp()
        texte.set_sprache("de")

    def test_einsetzungen(self) -> None:
        self.assertEqual("vor 5 Min", texte.t("zeit.minuten", n=5))
        self.assertEqual("PID 42", texte.t("karte.pid", pid=42))

    def test_unbekannter_schluessel_wird_sichtbar(self) -> None:
        self.assertEqual("gibt.es.nicht", texte.t("gibt.es.nicht"))

    def test_falsche_einsetzung_stuerzt_nicht_ab(self) -> None:
        """Lieber eine krumme Zeile als ein Fenster, das nicht aufgeht."""
        self.assertEqual(texte.text("zeit.minuten"),
                         texte.t("zeit.minuten", falsch=1))

    def test_fehlende_uebersetzung_faellt_auf_englisch(self) -> None:
        texte.TEXTE["test.nur_englisch"] = "only english"
        self.addCleanup(texte.TEXTE.pop, "test.nur_englisch", None)
        self.assertEqual("only english", texte.t("test.nur_englisch"))


class VollstaendigkeitTest(unittest.TestCase):
    """Beide Tabellen gegeneinander — in beide Richtungen."""

    def test_jeder_deutsche_schluessel_hat_ein_englisches_original(self) -> None:
        fehlend = sorted(set(texte.UEBERSETZUNGEN["de"]) - set(texte.TEXTE))
        self.assertEqual([], fehlend,
                         "ohne englischen Text in TEXTE: %s" % fehlend)

    def test_jeder_englische_schluessel_ist_uebersetzt(self) -> None:
        fehlend = sorted(set(texte.TEXTE) - set(texte.UEBERSETZUNGEN["de"]))
        self.assertEqual([], fehlend,
                         "ohne deutsche Übersetzung: %s" % fehlend)

    def test_gleiche_platzhalter_in_beiden_sprachen(self) -> None:
        """Ein vergessenes `{n}` bliebe sonst bis zur Anzeige unbemerkt."""
        for schluessel, englisch in texte.TEXTE.items():
            deutsch = texte.UEBERSETZUNGEN["de"].get(schluessel, englisch)
            self.assertEqual(platzhalter(englisch), platzhalter(deutsch),
                             "Platzhalter weichen ab: %s" % schluessel)

    def test_keine_leeren_texte(self) -> None:
        for sprache in ALLE:
            for schluessel, wert in texte.tabelle(sprache).items():
                self.assertTrue(wert.strip(),
                                "leerer Text: %s/%s" % (sprache, schluessel))

    def test_kein_prozent_platzhalter_uebrig(self) -> None:
        """Die Schicht formatiert mit `str.format`, nicht mit `%`."""
        muster = re.compile(r"%[-#0-9. ]*[sdif]")
        for sprache in ALLE:
            for schluessel, wert in texte.tabelle(sprache).items():
                self.assertIsNone(muster.search(wert),
                                  "%%-Platzhalter in %s/%s" % (sprache,
                                                               schluessel))


if __name__ == "__main__":
    unittest.main()
