"""Tests für `bin/claude-session-open` — ohne Terminal, ohne echte Subprozesse.

Das Programm hat bewusst keine `.py`-Endung (es ist ein Kommando, kein Modul),
deshalb wird es hier über einen `SourceFileLoader` geladen statt importiert.

Geprüft wird nur, was ohne Fenster auskommt: das Auflösen abgekürzter IDs, das
Zerlegen der `claude-session://`-URIs, das Ermitteln des Arbeitsverzeichnisses
aus der Session-Datei und die Terminal-Rückfallkette. `shutil.which` wird dabei
ersetzt, damit das Ergebnis nicht davon abhängt, was auf der Testmaschine
installiert ist.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
import unittest.mock
from importlib.machinery import SourceFileLoader
from pathlib import Path

SKRIPT = Path(__file__).resolve().parent.parent / "bin" / "claude-session-open"


def _zeile(**felder) -> str:
    """Eine Transkriptzeile so schreiben, wie Claude sie schreibt.

    Kompakt, ohne Leerzeichen hinter den Doppelpunkten: `session_cwd` sucht
    aus Geschwindigkeitsgründen erst nach den Bytes `"cwd":"` und liest nur
    die Treffer als JSON. Eine hübsch eingerückte Attrappe würde daran
    vorbeilaufen und der Test damit etwas anderes messen als den Ernstfall.
    """
    return json.dumps(felder, separators=(",", ":"))


def _lade():
    """Das Kommando als Modul laden (es hat keine `.py`-Endung)."""
    lader = SourceFileLoader("claude_session_open", str(SKRIPT))
    spec = importlib.util.spec_from_loader(lader.name, lader)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


cso = _lade()


def _which(*vorhanden: str):
    """Ersatz für `shutil.which`: nur die genannten Namen gelten als da."""
    erlaubt = set(vorhanden)

    def fake(name, *a, **kw):
        return "/usr/bin/" + name if name in erlaubt else None

    return fake


class Basis(unittest.TestCase):
    """Gemeinsames Gerüst: eigenes Zustandsverzeichnis, keine Rückfragen.

    `die()` schreibt ins Ereignislog und würde sonst in das echte
    `~/.local/state/claude-sessions/events.log` des Benutzers schreiben.
    CLAUDE_SESSIONS_AUTONOMOUS unterdrückt zusätzlich `notify-send` — damit
    startet kein Test je einen Prozess.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pfad = Path(self.tmp.name)
        umgebung = unittest.mock.patch.dict(
            os.environ,
            {"XDG_STATE_HOME": str(self.pfad / "state"),
             "CLAUDE_SESSIONS_AUTONOMOUS": "1"})
        umgebung.start()
        self.addCleanup(umgebung.stop)

    def fehler(self, fn, *args, **kw) -> tuple[int, str]:
        """`fn` aufrufen, das erwartete SystemExit fangen: (Code, Meldung)."""
        with unittest.mock.patch("sys.stderr") as stderr:
            with self.assertRaises(SystemExit) as fall:
                fn(*args, **kw)
        text = "".join(str(ruf.args[0]) for ruf in stderr.write.call_args_list)
        return fall.exception.code, text

    def session(self, projekt: str, sid: str, cwd: str | None,
                zeilen: list[str] | None = None) -> Path:
        """Eine Transkript-Attrappe anlegen und ihren Pfad zurückgeben."""
        ordner = self.pfad / "projects" / projekt
        ordner.mkdir(parents=True, exist_ok=True)
        datei = ordner / (sid + ".jsonl")
        inhalt = list(zeilen or [])
        if cwd is not None:
            inhalt.append(_zeile(type="user", cwd=cwd, sessionId=sid))
        datei.write_text("\n".join(inhalt) + "\n", encoding="utf-8")
        return datei

    def wurzel(self) -> None:
        """`find()` auf das Attrappen-Verzeichnis umlenken."""
        patcher = unittest.mock.patch.object(
            cso, "ROOT", str(self.pfad / "projects"))
        patcher.start()
        self.addCleanup(patcher.stop)


class SessionIdTest(Basis):
    """Argument oder URI zerlegen — jede Sackgasse mit eigener Meldung."""

    def test_blanke_id(self) -> None:
        self.assertEqual(cso.session_id("11111111"), "11111111")

    def test_leerzeichen_fallen_weg(self) -> None:
        # Aus der Zwischenablage kommt gern ein Zeilenumbruch mit.
        self.assertEqual(cso.session_id("  11111111\n"), "11111111")

    def test_uri_mit_wert_im_netloc(self) -> None:
        voll = "11111111-2222-3333-4444-555555555555"
        self.assertEqual(cso.session_id("claude-session://" + voll), voll)

    def test_uri_mit_wert_im_pfad(self) -> None:
        # 'schema:///wert' — manche Absender schreiben drei Schrägstriche.
        voll = "11111111-2222-3333-4444-555555555555"
        self.assertEqual(cso.session_id("claude-session:///" + voll), voll)

    def test_uri_mit_schlusspflock(self) -> None:
        voll = "11111111-2222-3333-4444-555555555555"
        self.assertEqual(cso.session_id("claude-session://%s/" % voll), voll)

    def test_uri_prozentkodiert(self) -> None:
        self.assertEqual(cso.session_id("claude-session://%31%31111111"),
                         "11111111")

    def test_uri_ohne_wert(self) -> None:
        code, text = self.fehler(cso.session_id, "claude-session://")
        self.assertEqual(code, 2)
        self.assertIn("no session id", text)

    def test_pfad_statt_id(self) -> None:
        # Ein versehentlich übergebener Pfad darf nicht als leere ID
        # durchrutschen, sonst kommt "no session id given" heraus.
        code, text = self.fehler(cso.session_id, "/home/user/code/shop-api")
        self.assertEqual(code, 2)
        self.assertIn("path", text)

    def test_leeres_argument_bleibt_leer(self) -> None:
        # Der leere Fall gehört find() — dort steht der Hinweis auf die Liste.
        self.assertEqual(cso.session_id("   "), "")


class FindTest(Basis):
    """Abgekürzte IDs auflösen: eindeutig, mehrdeutig, unbekannt."""

    def setUp(self) -> None:
        super().setUp()
        self.wurzel()

    def test_eindeutige_abkuerzung(self) -> None:
        datei = self.session("-home-user-code-shop-api",
                             "11111111-2222-3333-4444-555555555555", "/tmp")
        self.session("-home-user-code-shop-api",
                     "99999999-8888-7777-6666-555555555555", "/tmp")
        self.assertEqual(cso.find("1111"), str(datei))

    def test_volle_id(self) -> None:
        sid = "11111111-2222-3333-4444-555555555555"
        datei = self.session("-home-user-code-shop-api", sid, "/tmp")
        self.assertEqual(cso.find(sid), str(datei))

    def test_projektuebergreifend(self) -> None:
        # Die Suche läuft über alle Projektordner, nicht nur den aktuellen.
        datei = self.session("-home-user-notizen",
                             "11111111-2222-3333-4444-555555555555", "/tmp")
        self.assertEqual(cso.find("11111111"), str(datei))

    def test_mehrdeutig(self) -> None:
        self.session("-home-user-a", "11111111-2222-3333-4444-555555555555",
                     "/tmp")
        self.session("-home-user-b", "11111111-9999-8888-7777-666666666666",
                     "/tmp")
        code, text = self.fehler(cso.find, "1111")
        self.assertEqual(code, 2)
        self.assertIn("ambiguous", text)
        self.assertIn("2 sessions", text)

    def test_unbekannt(self) -> None:
        self.session("-home-user-a", "11111111-2222-3333-4444-555555555555",
                     "/tmp")
        code, text = self.fehler(cso.find, "abcdef")
        self.assertEqual(code, 2)
        self.assertIn("no session starts with", text)

    def test_ohne_id(self) -> None:
        code, text = self.fehler(cso.find, "")
        self.assertEqual(code, 2)
        self.assertIn("no session id given", text)

    def test_nur_transkripte_zaehlen(self) -> None:
        # Neben den .jsonl liegen dort auch andere Dateien; die dürfen eine
        # ID weder auflösen noch mehrdeutig machen.
        datei = self.session("-home-user-a",
                             "11111111-2222-3333-4444-555555555555", "/tmp")
        (self.pfad / "projects" / "-home-user-a" / "11111111.txt").write_text(
            "kein Transkript\n", encoding="utf-8")
        self.assertEqual(cso.find("11111111"), str(datei))

    def test_treffer_muss_am_anfang_stehen(self) -> None:
        self.session("-home-user-a", "11111111-2222-3333-4444-555555555555",
                     "/tmp")
        code, _ = self.fehler(cso.find, "2222")
        self.assertEqual(code, 2)


class SessionCwdTest(Basis):
    """Das Arbeitsverzeichnis kommt aus der Datei, nicht aus dem Ordnernamen."""

    def test_ordnername_ist_nicht_umkehrbar(self) -> None:
        # Der Kern der Sache: Claude kodiert '/' als '-', und ein '-' im Pfad
        # bleibt ebenfalls '-'. Aus '-home-user-code-shop-api' liesse sich
        # '/home/user/code/shop/api' zurückrechnen — falsch. Die Datei weiss es.
        echt = "/home/user/code/shop-api"
        datei = self.session("-home-user-code-shop-api",
                             "11111111-2222-3333-4444-555555555555", echt)
        self.assertEqual(cso.session_cwd(str(datei)), echt)
        naiv = "/" + datei.parent.name.lstrip("-").replace("-", "/")
        self.assertNotEqual(naiv, echt)

    def test_erste_zeile_mit_cwd_gewinnt(self) -> None:
        datei = self.session(
            "-home-user-a", "11111111-2222-3333-4444-555555555555", None,
            zeilen=[_zeile(type="summary", summary="ohne Angabe"),
                    _zeile(type="user", cwd="/home/user/code/eins"),
                    _zeile(type="user", cwd="/home/user/code/zwei")])
        self.assertEqual(cso.session_cwd(str(datei)), "/home/user/code/eins")

    def test_kaputte_zeile_wird_uebersprungen(self) -> None:
        # Ein abgeschnittener Schreibvorgang darf die Suche nicht beenden.
        datei = self.session(
            "-home-user-a", "11111111-2222-3333-4444-555555555555", None,
            zeilen=['{"cwd":"/home/user/abgeschnitten"',
                    _zeile(type="user", cwd="/home/user/code/gut")])
        self.assertEqual(cso.session_cwd(str(datei)), "/home/user/code/gut")

    def test_ohne_cwd_kommt_none(self) -> None:
        datei = self.session(
            "-home-user-a", "11111111-2222-3333-4444-555555555555", None,
            zeilen=[_zeile(type="summary", summary="leer")])
        self.assertIsNone(cso.session_cwd(str(datei)))

    def test_leeres_transkript(self) -> None:
        datei = self.pfad / "leer.jsonl"
        datei.write_text("", encoding="utf-8")
        self.assertIsNone(cso.session_cwd(str(datei)))

    def test_verschwundene_datei_hat_eigene_meldung(self) -> None:
        # Zwischen find() und dem Lesen gelöscht: die Meldung muss von der
        # fehlenden Datei sprechen, nicht vom fehlenden Arbeitsverzeichnis.
        code, text = self.fehler(cso.session_cwd, str(self.pfad / "weg.jsonl"))
        self.assertEqual(code, 1)
        self.assertIn("session file is gone", text)

    def test_kein_utf8_bricht_nicht(self) -> None:
        # Gelesen wird byteweise; eine kaputte Zeile davor darf nicht stören.
        datei = self.pfad / "roh.jsonl"
        datei.write_bytes(b'\xff\xfe kein JSON\n'
                          + _zeile(cwd="/home/user/code/roh").encode()
                          + b"\n")
        self.assertEqual(cso.session_cwd(str(datei)), "/home/user/code/roh")


class TerminalCmdTest(Basis):
    """Rückfallkette: der erste vorhandene Emulator gewinnt, keiner ist Pflicht."""

    def kette(self, *vorhanden: str):
        patcher = unittest.mock.patch.object(cso.shutil, "which",
                                             _which(*vorhanden))
        patcher.start()
        self.addCleanup(patcher.stop)
        return cso.terminal_cmd(["claude", "--resume", "11111111"])

    def test_reihenfolge_wird_eingehalten(self) -> None:
        cmd = self.kette(*cso.TERMINALS)
        self.assertEqual(cmd[0], cso.TERMINALS[0])

    def test_jeder_kandidat_reicht_allein(self) -> None:
        # Keiner der Namen ist stille Voraussetzung — auch der letzte allein
        # ergibt einen vollständigen Befehl.
        for name in cso.TERMINALS:
            with self.subTest(terminal=name):
                cmd = self.kette(name)
                self.assertIsNotNone(cmd)
                self.assertEqual(cmd[0], name)
                self.assertGreaterEqual(len(cmd), 3)

    def test_zweite_wahl_wenn_erste_fehlt(self) -> None:
        cmd = self.kette(*cso.TERMINALS[1:])
        self.assertEqual(cmd[0], cso.TERMINALS[1])

    def test_argumentliste_hinter_e(self) -> None:
        cmd = self.kette("xterm")
        self.assertEqual(cmd, ["xterm", "-e", "claude", "--resume", "11111111"])

    def test_xfce4_bekommt_eine_kommandozeile(self) -> None:
        # xfce4-terminal nimmt hinter --command eine einzige Zeile; sie muss
        # zitiert sein, sonst zerfällt ein Pfad mit Leerzeichen.
        patcher = unittest.mock.patch.object(cso.shutil, "which",
                                             _which("xfce4-terminal"))
        patcher.start()
        self.addCleanup(patcher.stop)
        cmd = cso.terminal_cmd(["/opt/mein ordner/claude", "--resume", "1111"])
        self.assertEqual(cmd[:2], ["xfce4-terminal", "--command"])
        self.assertEqual(len(cmd), 3)
        self.assertIn("'/opt/mein ordner/claude'", cmd[2])

    def test_ohne_terminal_kommt_none(self) -> None:
        self.assertIsNone(self.kette())


class KeinTerminalTest(Basis):
    """Fehlt jeder Emulator, muss das Programm es sagen und rot enden."""

    def test_meldung_nennt_die_kandidaten(self) -> None:
        self.wurzel()
        sid = "11111111-2222-3333-4444-555555555555"
        self.session("-home-user-a", sid, str(self.pfad))
        claude = self.pfad / "claude"
        claude.write_text("#!/bin/sh\n", encoding="utf-8")

        def which(name, *a, **kw):
            return str(claude) if name == "claude" else None

        with unittest.mock.patch.object(cso.shutil, "which", which):
            with unittest.mock.patch.object(cso.sys, "argv",
                                            ["claude-session-open", "11111111"]):
                code, text = self.fehler(cso.main)
        self.assertNotEqual(code, 0)
        self.assertIn("no terminal emulator found", text)
        for name in cso.TERMINALS:
            self.assertIn(name, text)

    def test_ohne_argument(self) -> None:
        with unittest.mock.patch.object(cso.sys, "argv",
                                        ["claude-session-open"]):
            code, text = self.fehler(cso.main)
        self.assertEqual(code, 2)
        self.assertIn("usage:", text)


class SpawnOhneSystemdTest(Basis):
    """Ohne `systemd-run` startet das Fenster direkt statt zu scheitern."""

    def setUp(self) -> None:
        super().setUp()
        self.laeufe: list[list[str]] = []
        self.fenster: list[tuple[list[str], dict]] = []

        def fake_run(argv, **kw):
            self.laeufe.append(list(argv))
            raise AssertionError("systemd-run darf hier nicht laufen")

        def fake_popen(argv, **kw):
            self.fenster.append((list(argv), kw))
            return object()

        for name, fn in (("run", fake_run), ("Popen", fake_popen)):
            patcher = unittest.mock.patch.object(cso.subprocess, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_direkter_start_ohne_systemd_run(self) -> None:
        with unittest.mock.patch.object(cso.shutil, "which", _which("xterm")):
            eigen = cso.spawn(["xterm", "-e", "claude"], str(self.pfad),
                              {"PATH": "/usr/bin"}, "Claude session 11111111")
        self.assertFalse(eigen)          # kein eigener cgroup-Rahmen
        self.assertEqual(self.laeufe, [])  # gar nicht erst versucht
        self.assertEqual(len(self.fenster), 1)
        argv, kw = self.fenster[0]
        self.assertEqual(argv, ["xterm", "-e", "claude"])
        self.assertEqual(kw["cwd"], str(self.pfad))
        self.assertTrue(kw["start_new_session"])

    def test_hinweis_landet_im_log(self) -> None:
        with unittest.mock.patch.object(cso.shutil, "which", _which("xterm")):
            cso.spawn(["xterm"], str(self.pfad), {}, "Claude session 11111111")
        log = Path(cso.log_file()).read_text(encoding="utf-8")
        self.assertIn("systemd-run not found", log)


class StateDirTest(Basis):
    """Der Logpfad bleibt, ist aber über XDG_STATE_HOME verschiebbar."""

    def test_xdg_state_home_wird_beachtet(self) -> None:
        with unittest.mock.patch.dict(os.environ,
                                      {"XDG_STATE_HOME": "/var/tmp/zustand"}):
            self.assertEqual(cso.state_dir(), "/var/tmp/zustand/claude-sessions")
            self.assertEqual(cso.log_file(),
                             "/var/tmp/zustand/claude-sessions/events.log")

    def test_vorgabe_ohne_xdg(self) -> None:
        umgebung = dict(os.environ)
        umgebung.pop("XDG_STATE_HOME", None)
        with unittest.mock.patch.dict(os.environ, umgebung, clear=True):
            erwartet = os.path.join(os.path.expanduser("~"), ".local", "state",
                                    "claude-sessions")
            self.assertEqual(cso.state_dir(), erwartet)

    def test_relativer_wert_wird_ignoriert(self) -> None:
        # Die XDG-Spezifikation verlangt absolute Pfade; ein Log an
        # wechselnden Orten wäre schlimmer als gar keins.
        with unittest.mock.patch.dict(os.environ, {"XDG_STATE_HOME": "zustand"}):
            self.assertTrue(cso.state_dir().startswith(os.path.expanduser("~")))


class AutonomTest(Basis):
    """Ohne Aufsicht darf nichts erscheinen, worauf jemand klicken müsste."""

    def umgebung(self, **werte: str) -> None:
        neu = {k: v for k, v in os.environ.items()
               if k not in ("DISPLAY", "INVOCATION_ID",
                            "CLAUDE_SESSIONS_AUTONOMOUS",
                            "CLAUDE_SESSIONS_INTERACTIVE")}
        neu.update(werte)
        patcher = unittest.mock.patch.dict(os.environ, neu, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ohne_anzeige(self) -> None:
        self.umgebung()
        self.assertTrue(cso.autonomous())

    def test_mit_anzeige(self) -> None:
        self.umgebung(DISPLAY=":0")
        self.assertFalse(cso.autonomous())

    def test_unter_systemd(self) -> None:
        self.umgebung(DISPLAY=":0", INVOCATION_ID="x")
        self.assertTrue(cso.autonomous())

    def test_uebersicht_hebelt_systemd_aus(self) -> None:
        # Die Übersicht startet ihre Fenster als transiente Unit; ohne diese
        # Ausnahme sähe der Benutzer nach einem Klick schlicht nichts.
        self.umgebung(DISPLAY=":0", INVOCATION_ID="x",
                      CLAUDE_SESSIONS_INTERACTIVE="1")
        self.assertFalse(cso.autonomous())

    def test_schalter_schlaegt_alles(self) -> None:
        self.umgebung(DISPLAY=":0", CLAUDE_SESSIONS_INTERACTIVE="1",
                      CLAUDE_SESSIONS_AUTONOMOUS="1")
        self.assertTrue(cso.autonomous())


class MeldungsspracheTest(unittest.TestCase):
    """Grundsprache des Repos ist Englisch — auch in diesem Kommando.

    Kommentare und Docstrings bleiben Deutsch (Projektkonvention), die
    Ausgaben nicht. Gesammelt werden deshalb über den Syntaxbaum genau die
    Zeichenketten, die in `die()`, `log()` oder auf stderr landen — an einer
    Textsuche über die ganze Datei hinge sonst jeder deutsche Kommentar mit
    drin.
    """

    #: Wörter, an denen eine vergessene deutsche Meldung auffällt.
    DEUTSCH = ("nicht", "keine", "kein ", "gefunden", "Datei", "Sitzung",
               "Fehler", "ä", "ö", "ü", "ß")

    def meldungen(self) -> list[str]:
        import ast

        baum = ast.parse(SKRIPT.read_text(encoding="utf-8"))
        gefunden: list[str] = []
        for knoten in ast.walk(baum):
            if not isinstance(knoten, ast.Call):
                continue
            ziel = knoten.func
            name = (ziel.id if isinstance(ziel, ast.Name)
                    else ziel.attr if isinstance(ziel, ast.Attribute) else "")
            if name not in ("die", "log", "write"):
                continue
            for teil in ast.walk(knoten):
                if isinstance(teil, ast.Constant) and isinstance(teil.value, str):
                    gefunden.append(teil.value)
        return gefunden

    def test_meldungen_sind_englisch(self) -> None:
        self.assertTrue(self.meldungen(), "keine Meldungen gefunden — "
                        "die Sammelstelle greift nicht mehr")
        for text in self.meldungen():
            for wort in self.DEUTSCH:
                self.assertNotIn(wort, text,
                                 "deutsche Meldung: %r" % text)

    def test_hinweistext_ist_englisch(self) -> None:
        # HINT hängt an mehreren Meldungen und wird oben nicht miterfasst.
        for wort in self.DEUTSCH:
            self.assertNotIn(wort, cso.HINT)

    def test_kein_maschinenspezifischer_pfad(self) -> None:
        # Dieselbe Regel wie in tools/leak-check.py: '/home/user' ist als
        # Beispiel erlaubt, jeder echte Benutzername nicht.
        import re

        muster = re.compile(r"/home/(?!user\b)[a-z][a-z0-9_.-]*")
        for nr, zeile in enumerate(SKRIPT.read_text(encoding="utf-8")
                                   .splitlines(), 1):
            self.assertIsNone(muster.search(zeile),
                              "Zeile %d nennt einen echten Heimatpfad" % nr)


if __name__ == "__main__":
    unittest.main()
