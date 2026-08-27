"""Tests für die Datenschicht — ohne Netz, ohne echte Subprozesse."""
from __future__ import annotations

import importlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_sessions import data, texte  # noqa: E402


def write_session(root: Path, project: str, sid: str, lines: list[dict]) -> Path:
    d = root / project
    d.mkdir(parents=True, exist_ok=True)
    p = d / (sid + ".jsonl")
    p.write_text("\n".join(json.dumps(x, separators=(",", ":")) for x in lines))
    return p


AI_TITLE = {"type": "ai-title", "aiTitle": "Watchdog-GUI bauen"}
USER_LINE = {
    "type": "user", "cwd": "/home/user/Desktop",
    "origin": {"kind": "human"},
    "message": {"role": "user", "content": "baue mir eine kleine app"},
}
ASSISTANT_LINE = {"type": "assistant", "message": {"role": "assistant"}}

#: Dieselben Zeilen als JSONL-Text, für die Fortschreibe-Tests.
USER_LINE_S = json.dumps(USER_LINE, separators=(",", ":"))
ASSISTANT_LINE_S = json.dumps(ASSISTANT_LINE, separators=(",", ":"))


class ScannerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_titel_aus_ai_title(self) -> None:
        write_session(self.root, "-home-user-Desktop", "aaa",
                      [USER_LINE, ASSISTANT_LINE, AI_TITLE])
        out = data.Scanner(self.root).collect()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "Watchdog-GUI bauen")
        self.assertEqual(out[0]["cwd"], "/home/user/Desktop")
        self.assertEqual(out[0]["msgs"], 2)

    def test_titel_fallback_erster_menschlicher_prompt(self) -> None:
        write_session(self.root, "-home-user-Desktop", "bbb",
                      [USER_LINE, ASSISTANT_LINE])
        out = data.Scanner(self.root).collect()
        self.assertEqual(out[0]["title"], "baue mir eine kleine app")

    def test_titel_fallback_blockliste_mit_bild(self) -> None:
        line = {"type": "user", "cwd": "/x", "origin": {"kind": "human"},
                "message": {"role": "user", "content": [
                    {"type": "text", "text": "schau dir das Bild an"},
                    {"type": "image", "source": {"data": "…"}}]}}
        write_session(self.root, "-x", "img", [line])
        out = data.Scanner(self.root).collect()
        self.assertEqual(out[0]["title"], "schau dir das Bild an")

    def test_kaputte_zeilen_fallen_still_weg(self) -> None:
        d = self.root / "-x"
        d.mkdir()
        (d / "ccc.jsonl").write_text('{"type":"ai-title", kaputt\nkein json\n')
        out = data.Scanner(self.root).collect()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["title"], "")

    def test_cache_invalidiert_bei_aenderung(self) -> None:
        p = write_session(self.root, "-x", "ddd", [USER_LINE])
        sc = data.Scanner(self.root)
        self.assertEqual(sc.collect()[0]["msgs"], 1)
        lines = [USER_LINE, ASSISTANT_LINE]
        p.write_text("\n".join(
            json.dumps(x, separators=(",", ":")) for x in lines))
        os.utime(p, (time.time() + 5, time.time() + 5))
        self.assertEqual(sc.collect()[0]["msgs"], 2)

    def test_cache_liefert_ohne_aenderung_dasselbe(self) -> None:
        write_session(self.root, "-x", "eee", [USER_LINE])
        sc = data.Scanner(self.root)
        first = sc.collect()
        second = sc.collect()
        self.assertEqual(first[0]["title"], second[0]["title"])


def make_wd_db(path: Path, rows: list[dict]) -> None:
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT, cwd TEXT,"
        " session_id TEXT, mode TEXT, status TEXT, pid INTEGER,"
        " attempts INTEGER DEFAULT 0, max_attempts INTEGER DEFAULT 5,"
        " last_error_class TEXT, updated_at REAL, next_retry_at REAL)")
    db.execute("CREATE TABLE restarts (ts REAL, task_id TEXT)")
    for r in rows:
        db.execute(
            "INSERT INTO tasks (id, title, cwd, session_id, mode, status,"
            " attempts, max_attempts, last_error_class, updated_at, next_retry_at)"
            " VALUES (:id, :title, :cwd, :session_id, :mode, :status,"
            " :attempts, :max_attempts, :last_error_class, :updated_at,"
            " :next_retry_at)",
            {"attempts": 0, "max_attempts": 5, "last_error_class": None,
             "next_retry_at": None,
             "updated_at": time.time(), "title": "t", "cwd": "/tmp", **r})
    db.execute("INSERT INTO restarts VALUES (?, 'x')", (time.time(),))
    db.execute("INSERT INTO restarts VALUES (?, 'x')", (time.time() - 7200,))
    db.commit()
    db.close()


class WatchdogTest(unittest.TestCase):
    def test_tasks_und_neustarts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dbp = Path(tmp) / "state.db"
            make_wd_db(dbp, [{"id": "t1", "session_id": "abc",
                              "mode": "observed", "status": "running"}])
            rows, restarts, ok = data.watchdog_tasks(dbp)
            self.assertTrue(ok)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["session_id"], "abc")
            self.assertEqual(restarts, 1)

    def test_fehlende_db_ist_kein_fehler(self) -> None:
        rows, restarts, ok = data.watchdog_tasks(Path("/nirgends/state.db"))
        self.assertEqual(rows, [])
        self.assertFalse(ok)


class WatchdogPfadTest(unittest.TestCase):
    """Der Watchdog ist optional und muss nicht in `~/.claude-watchdog` liegen.

    Die Pfade sind Modulkonstanten und werden beim Import einmal gelesen. Zum
    Prüfen wird das Modul deshalb mit veränderter Umgebung neu geladen — und
    im Anschluss wieder auf die Vorgabewerte zurück, damit kein anderer Test
    die verbogenen Pfade erbt.
    """

    def tearDown(self) -> None:
        importlib.reload(data)

    def _laden(self, wert):
        with unittest.mock.patch.dict(os.environ):
            os.environ.pop("CS_WATCHDOG_DIR", None)
            if wert is not None:
                os.environ["CS_WATCHDOG_DIR"] = wert
            return importlib.reload(data)

    def test_vorgabe_ist_das_home_verzeichnis(self) -> None:
        m = self._laden(None)
        self.assertEqual(m.WATCHDOG_DIR, m.HOME / ".claude-watchdog")
        self.assertEqual(m.WATCHDOG_DB, m.HOME / ".claude-watchdog" / "state.db")

    def test_umgebungsvariable_verschiebt_datenbank_und_cli(self) -> None:
        m = self._laden("/opt/watchdog")
        self.assertEqual(m.WATCHDOG_DIR, Path("/opt/watchdog"))
        self.assertEqual(m.WATCHDOG_DB, Path("/opt/watchdog/state.db"))
        self.assertEqual(m.WATCHDOG_BIN,
                         Path("/opt/watchdog/bin/claude-watchdog"))

    def test_leerer_wert_zaehlt_als_ungesetzt(self) -> None:
        m = self._laden("   ")
        self.assertEqual(m.WATCHDOG_DIR, m.HOME / ".claude-watchdog")

    def test_tilde_wird_aufgeloest(self) -> None:
        m = self._laden("~/woanders/watchdog")
        self.assertEqual(m.WATCHDOG_DIR, m.HOME / "woanders" / "watchdog")

    def test_fehlendes_verzeichnis_ist_kein_fehler(self) -> None:
        """Bei Fremden gibt es den Watchdog gar nicht — die App läuft trotzdem.

        Kein Absturz, keine Ausnahme: nur eine Übersicht ohne Watchdog-Daten.
        """
        with tempfile.TemporaryDirectory() as tmp:
            m = self._laden(str(Path(tmp) / "gibtsnicht"))
            self.assertFalse(m.WATCHDOG_DB.exists())
            # Ohne Argument, damit wirklich die Modulkonstante zum Zug kommt.
            self.assertEqual(m.watchdog_tasks(), ([], 0, False))
            snap = m.snapshot(m.Scanner(Path(tmp) / "leer"),
                              agents={}, wd=m.watchdog_tasks(),
                              mcp=([], True), with_daemon=False)
        self.assertEqual(snap.sessions, [])
        self.assertFalse(snap.wd_ok)
        self.assertEqual(snap.wd_restarts, 0)


class SnapshotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def snap(self, agents=None, wd=None) -> data.Snapshot:
        return data.snapshot(
            data.Scanner(self.root),
            agents=agents or {}, agents_ok=True,
            wd=wd or ([], 0, True), with_daemon=False)

    def test_live_session_kommt_nach_oben(self) -> None:
        write_session(self.root, "-x", "alt-lebt", [USER_LINE, AI_TITLE])
        write_session(self.root, "-x", "neu-tot", [USER_LINE])
        os.utime(self.root / "-x" / "neu-tot.jsonl",
                 (time.time() + 10, time.time() + 10))
        agents = {"alt-lebt": {"pid": os.getpid(), "cwd": "/x",
                               "status": "busy", "startedAt": time.time() * 1000}}
        # Der eigene PID ist kein claude-Prozess — der Filter würde ihn
        # verwerfen. Für den Test direkt einspeisen heißt: der Filter in
        # live_agents ist hier bewusst nicht Teil des Prüflings.
        snap = self.snap(agents=agents)
        self.assertEqual(snap.sessions[0].id, "alt-lebt")
        self.assertTrue(snap.sessions[0].live)
        self.assertEqual(snap.sessions[0].group, data.GROUP_LIVE)
        self.assertEqual(snap.n_live, 1)
        self.assertEqual(snap.n_busy, 1)

    def test_watchdog_wird_der_session_zugeordnet(self) -> None:
        write_session(self.root, "-x", "sess1", [USER_LINE, AI_TITLE])
        wd_rows = [{"id": "T1", "title": "t", "cwd": "/x", "session_id": "sess1",
                    "mode": "observed", "status": "stalled", "pid": None,
                    "attempts": 2, "max_attempts": 5,
                    "last_error_class": "NONE", "updated_at": time.time()}]
        snap = self.snap(wd=(wd_rows, 3, True))
        s = snap.sessions[0]
        self.assertEqual(s.wd_task_id, "T1")
        self.assertEqual(s.wd_status, "stalled")
        self.assertIsNone(s.wd_error)
        self.assertEqual(snap.wd_restarts, 3)

    def test_wd_fehler_bei_done_ist_historisch(self) -> None:
        write_session(self.root, "-x", "sess2", [USER_LINE, AI_TITLE])
        wd_rows = [{"id": "T9", "title": "t", "cwd": "/x", "session_id": "sess2",
                    "mode": "managed", "status": "done", "pid": None,
                    "attempts": 1, "max_attempts": 5,
                    "last_error_class": "USAGE_LIMIT",
                    "updated_at": time.time()}]
        snap = self.snap(wd=(wd_rows, 0, True))
        self.assertIsNone(snap.sessions[0].wd_error)

    def test_wd_fehler_bei_failed_bleibt_sichtbar(self) -> None:
        write_session(self.root, "-x", "sess3", [USER_LINE, AI_TITLE])
        wd_rows = [{"id": "TA", "title": "t", "cwd": "/x", "session_id": "sess3",
                    "mode": "managed", "status": "failed", "pid": None,
                    "attempts": 5, "max_attempts": 5,
                    "last_error_class": "API_ERROR",
                    "updated_at": time.time()}]
        snap = self.snap(wd=(wd_rows, 0, True))
        self.assertEqual(snap.sessions[0].wd_error, "API_ERROR")

    def test_wd_task_ohne_session_wird_warteschlange(self) -> None:
        wd_rows = [{"id": "T2", "title": "Nachtlauf", "cwd": "/x",
                    "session_id": None, "mode": "managed", "status": "pending",
                    "pid": None, "attempts": 0, "max_attempts": 5,
                    "last_error_class": None, "updated_at": time.time()}]
        snap = self.snap(wd=(wd_rows, 0, True))
        self.assertEqual(snap.n_queue, 1)
        self.assertEqual(snap.sessions[0].group, data.GROUP_QUEUE)
        self.assertEqual(snap.sessions[0].title, "Nachtlauf")

    def test_fertiger_wd_task_ohne_session_verschwindet(self) -> None:
        wd_rows = [{"id": "T3", "title": "t", "cwd": "/x", "session_id": None,
                    "mode": "managed", "status": "done", "pid": None,
                    "attempts": 1, "max_attempts": 5,
                    "last_error_class": None, "updated_at": time.time()}]
        snap = self.snap(wd=(wd_rows, 0, True))
        self.assertEqual(len(snap.sessions), 0)

    def test_live_ohne_transkript_wird_angezeigt(self) -> None:
        agents = {"frisch": {"pid": 1, "cwd": "/y", "status": "idle",
                             "name": "frische-session",
                             "startedAt": time.time() * 1000}}
        snap = self.snap(agents=agents)
        self.assertEqual(snap.sessions[0].title, "frische-session")
        self.assertEqual(snap.sessions[0].cwd, "/y")


class HelperTest(unittest.TestCase):
    """Deutsche Zeitangaben — die Sprache wird dafür ausdrücklich gesetzt.

    Grundsprache der Anzeige ist seit der Sprachschicht Englisch; ohne dieses
    setUp hinge das Ergebnis an der Locale des Rechners.
    """

    def setUp(self) -> None:
        self.addCleanup(texte.set_sprache, None)
        texte.set_sprache("de")

    def test_rel_time(self) -> None:
        now = 1_000_000.0
        self.assertEqual(data.rel_time(now - 10, now), "gerade")
        self.assertEqual(data.rel_time(now - 300, now), "vor 5 Min")
        self.assertEqual(data.rel_time(now - 7200, now), "vor 2 Std")
        self.assertEqual(data.rel_time(0, now), "—")

    def test_short_path(self) -> None:
        home = str(data.HOME)
        self.assertEqual(data.short_path(home), "~")
        self.assertEqual(data.short_path(home + "/Desktop"), "~/Desktop")
        self.assertEqual(data.short_path(""), "?")
        self.assertEqual(data.short_path("/opt/x"), "/opt/x")


if __name__ == "__main__":
    unittest.main()


class McpServersTest(unittest.TestCase):
    """MCP-Konfigurationen lesen, ohne echte Dateien im Home anzufassen."""

    def _write(self, name, payload):
        p = Path(self.tmp.name) / name
        p.write_text(json.dumps(payload))
        return p

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_liest_beide_clients(self):
        code = self._write("code.json", {"mcpServers": {
            "github": {"type": "http", "url": "https://example.invalid/mcp/"},
            "playwright": {"command": "npx", "args": ["@playwright/mcp", "--headless"]},
        }})
        desk = self._write("desk.json", {"mcpServers": {
            "filesystem": {"command": "npx", "args": ["-y", "server-filesystem", "/tmp"]},
        }})
        servers, ok = data.mcp_servers(code, desk)
        self.assertTrue(ok)
        self.assertEqual([s.name for s in servers],
                         ["github", "playwright", "filesystem"])
        self.assertEqual(servers[0].transport, "http")
        self.assertEqual(servers[1].transport, "stdio")
        self.assertEqual(servers[1].detail, "npx @playwright/mcp --headless")
        self.assertEqual(servers[2].client, "Claude Desktop")

    def test_fehlende_datei_ist_kein_fehler(self):
        missing = Path(self.tmp.name) / "gibtsnicht.json"
        servers, ok = data.mcp_servers(missing, missing)
        self.assertTrue(ok)
        self.assertEqual(servers, [])

    def test_kaputtes_json_meldet_fehler(self):
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text("{ das ist kein json")
        servers, ok = data.mcp_servers(bad, bad)
        self.assertFalse(ok)
        self.assertEqual(servers, [])

    def test_eintrag_ohne_command_und_url_faellt_weg(self):
        p = self._write("x.json", {"mcpServers": {
            "kaputt": {"type": "http"},
            "gut": {"command": "echo"},
        }})
        servers, _ = data.mcp_servers(p, p.with_name("fehlt.json"))
        self.assertEqual([s.name for s in servers], ["gut"])

    def test_snapshot_reicht_mcp_durch(self):
        snap = data.snapshot(
            data.Scanner(Path(self.tmp.name)),
            agents={}, wd=([], 0, True),
            mcp=([data.McpServer("github", "Claude Code", "http", "u")], True),
            with_daemon=False,
        )
        self.assertEqual([s.name for s in snap.mcp], ["github"])
        self.assertTrue(snap.mcp_ok)


class StaleErrorTest(unittest.TestCase):
    """Ein ueberwundener Fehler darf nicht als Warnung kleben bleiben."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "state.db"
        self.sid = "22222222-3333-4444-5555-666666666666"

    def snap(self, **task) -> data.SessionInfo:
        make_wd_db(self.db, [dict(
            {"id": "t1", "session_id": self.sid, "mode": "observed",
             "status": "running"}, **task)])
        s = data.snapshot(data.Scanner(self.root / "leer"),
                          agents={}, wd=data.watchdog_tasks(self.db),
                          mcp=([], True), with_daemon=False)
        return s.sessions[0]

    def test_verstrichener_termin_bei_laufender_session(self) -> None:
        """Genau der beobachtete Fall: RATE_LIMIT von 00:08, laeuft seit 01:18."""
        i = self.snap(last_error_class="RATE_LIMIT",
                      next_retry_at=time.time() - 4000)
        self.assertIsNone(i.wd_error)

    def test_kuenftiger_termin_bleibt_eine_warnung(self) -> None:
        i = self.snap(last_error_class="RATE_LIMIT",
                      next_retry_at=time.time() + 600)
        self.assertEqual(i.wd_error, "RATE_LIMIT")

    def test_ohne_termin_bleibt_die_warnung_stehen(self) -> None:
        """Kein Termin = keine Evidenz fuer 'ueberwunden' — konservativ."""
        i = self.snap(last_error_class="API_ERROR", next_retry_at=None)
        self.assertEqual(i.wd_error, "API_ERROR")

    def test_nur_bei_status_running(self) -> None:
        i = self.snap(last_error_class="RATE_LIMIT", status="waiting_for_limit",
                      next_retry_at=time.time() - 10)
        self.assertEqual(i.wd_error, "RATE_LIMIT")

    def test_muellwert_im_termin_aendert_nichts(self) -> None:
        i = self.snap(last_error_class="API_ERROR", next_retry_at="bald")
        self.assertEqual(i.wd_error, "API_ERROR")


class RetryUeberfaelligTest(unittest.TestCase):
    def test_faelle(self) -> None:
        for wert, jetzt, soll in ((None, 100.0, False), (50.0, 100.0, True),
                                  (150.0, 100.0, False), (100.0, 100.0, True),
                                  ("kaputt", 100.0, False)):
            with self.subTest(wert=wert):
                self.assertIs(data._retry_ueberfaellig(wert, jetzt), soll)


class PidIstClaudeTest(unittest.TestCase):
    """Die Pruefung darf nicht an argv[0] haengen.

    Der native Build heisst je nach Aufruf 'claude' oder '2.1.220' — beides
    ist dieselbe Programmdatei. Haengt die Pruefung an comm, gelten laufende
    Sitzungen als tot: sie fehlen unter 'Laufend', und 'Prozess beenden'
    verweigert bei ihnen den Dienst.
    """

    def test_nativer_build_wird_erkannt(self) -> None:
        self.assertTrue(data._ist_claude_programm(
            "/home/user/.local/share/claude/versions/2.1.220"))

    def test_wrapper_wird_erkannt(self) -> None:
        self.assertTrue(data._ist_claude_programm("/home/user/.local/bin/claude"))

    def test_fremdes_programm_nicht(self) -> None:
        for exe in ("/usr/bin/python3", "/usr/bin/qterminal", "/bin/bash",
                    "/home/user/claudeless/tool", ""):
            with self.subTest(exe=exe):
                self.assertFalse(data._ist_claude_programm(exe))

    def test_eigene_pid_ist_kein_claude(self) -> None:
        self.assertFalse(data._pid_is_claude(os.getpid()))

    def test_unbekannte_pid_ist_kein_claude(self) -> None:
        self.assertFalse(data._pid_is_claude(2 ** 30))


class DauerDienstTest(unittest.TestCase):
    """Erkennung der Sitzungen ohne Fenster."""

    def test_ohne_pid(self) -> None:
        self.assertIsNone(data.dauer_dienst(None))
        self.assertIsNone(data.dauer_dienst(0))

    def test_unbekannte_pid(self) -> None:
        self.assertIsNone(data.dauer_dienst(2 ** 30))

    def test_eigener_prozess_ist_kein_dauerdienst(self) -> None:
        self.assertIsNone(data.dauer_dienst(os.getpid()))


class FortschreibenTest(unittest.TestCase):
    """Angaben aus dem angehängten Stück ergänzen, statt alles neu zu lesen."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dir = self.root / "-home-user-Desktop"
        self.dir.mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def datei(self, zeilen: list[str]) -> Path:
        p = self.dir / "aaa.jsonl"
        p.write_text("\n".join(zeilen) + "\n")
        return p

    def anhaengen(self, p: Path, zeilen: list[str]) -> None:
        with p.open("a") as fh:
            fh.write("\n".join(zeilen) + "\n")

    def test_nachrichtenzahl_waechst_mit(self) -> None:
        p = self.datei([USER_LINE_S, ASSISTANT_LINE_S])
        sc = data.Scanner(self.root)
        self.assertEqual(sc.collect()[0]["msgs"], 2)
        self.anhaengen(p, [USER_LINE_S, ASSISTANT_LINE_S, ASSISTANT_LINE_S])
        self.assertEqual(sc.collect()[0]["msgs"], 5)

    def test_spaeterer_ai_title_gewinnt(self) -> None:
        p = self.datei([USER_LINE_S])
        sc = data.Scanner(self.root)
        self.assertEqual(sc.collect()[0]["title"], "baue mir eine kleine app")
        self.anhaengen(p, [json.dumps({"type": "ai-title",
                                       "aiTitle": "Neuer Titel"},
                                      separators=(",", ":"))])
        self.assertEqual(sc.collect()[0]["title"], "Neuer Titel")

    def test_titel_bleibt_wenn_das_stueck_keinen_hat(self) -> None:
        p = self.datei([json.dumps({"type": "ai-title", "aiTitle": "Bleibt"},
                                   separators=(",", ":"))])
        sc = data.Scanner(self.root)
        self.assertEqual(sc.collect()[0]["title"], "Bleibt")
        self.anhaengen(p, [ASSISTANT_LINE_S])
        self.assertEqual(sc.collect()[0]["title"], "Bleibt")

    def test_titel_kann_spaeter_erstmals_auftauchen(self) -> None:
        p = self.datei([ASSISTANT_LINE_S])
        sc = data.Scanner(self.root)
        self.assertEqual(sc.collect()[0]["title"], "")
        self.anhaengen(p, [USER_LINE_S])
        self.assertEqual(sc.collect()[0]["title"], "baue mir eine kleine app")

    def test_verzeichnis_bleibt_das_erste(self) -> None:
        p = self.datei([USER_LINE_S])
        sc = data.Scanner(self.root)
        self.assertEqual(sc.collect()[0]["cwd"], "/home/user/Desktop")
        spaeter = json.dumps({"type": "user", "cwd": "/woanders",
                              "origin": {"kind": "human"},
                              "message": {"role": "user", "content": "x"}},
                             separators=(",", ":"))
        self.anhaengen(p, [spaeter])
        self.assertEqual(sc.collect()[0]["cwd"], "/home/user/Desktop")

    def test_ergebnis_deckt_sich_mit_dem_vollscan(self) -> None:
        """Die eigentliche Zusicherung: fortgeschrieben == frisch gelesen."""
        p = self.datei([USER_LINE_S, ASSISTANT_LINE_S])
        sc = data.Scanner(self.root)
        sc.collect()
        self.anhaengen(p, [ASSISTANT_LINE_S, USER_LINE_S])
        fortgeschrieben = sc.collect()[0]
        frisch = data.Scanner(self.root).collect()[0]
        for feld in ("title", "cwd", "msgs", "tokens"):
            self.assertEqual(fortgeschrieben[feld], frisch[feld], feld)

    def test_gelesen_wird_nur_das_neue_stueck(self) -> None:
        """Der bereits ausgewertete Anfang darf nicht noch einmal durch.

        Ohne das kostet jede Änderung ein vollständiges Lesen — bei der
        grössten Sitzung hier 78 MB je Takt, alle sechs Sekunden.
        """
        p = self.datei([USER_LINE_S, ASSISTANT_LINE_S])
        vorher = p.stat().st_size
        sc = data.Scanner(self.root)
        sc.collect()

        gelesen: list[int] = []
        echt = data._lesen

        def merken(pfad, ab):
            gelesen.append(ab)
            return echt(pfad, ab)

        with unittest.mock.patch.object(data, "_lesen", merken):
            self.anhaengen(p, [ASSISTANT_LINE_S])
            sc.collect()
        self.assertEqual(gelesen, [vorher])

    def test_geschrumpfte_datei_wird_ganz_neu_gelesen(self) -> None:
        """Wird das Transkript ersetzt, stimmt der Offset nicht mehr."""
        p = self.datei([USER_LINE_S, ASSISTANT_LINE_S])
        sc = data.Scanner(self.root)
        sc.collect()
        p.write_text(ASSISTANT_LINE_S + "\n")

        gelesen: list[int] = []
        echt = data._lesen

        def merken(pfad, ab):
            gelesen.append(ab)
            return echt(pfad, ab)

        with unittest.mock.patch.object(data, "_lesen", merken):
            ergebnis = sc.collect()[0]
        self.assertEqual(gelesen, [0])
        self.assertEqual(ergebnis["msgs"], 1)
        self.assertEqual(ergebnis, data.Scanner(self.root).collect()[0])


class TitelOhneOriginTest(unittest.TestCase):
    """Transkripte ganz ohne `origin`-Marker sollen trotzdem einen Titel haben.

    Der reguläre Weg sucht `"origin":{"kind":"human"}`. Gemessen am
    2026-07-31: 18 von 57 Sitzungen führen dieses Feld nicht; sechs davon
    blieben in der Übersicht namenlos, obwohl drei sehr wohl eine getippte
    Frage enthielten — genau der Fall im ersten Test unten.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dir = self.root / "-home-user-Desktop"
        self.dir.mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)

    def datei(self, zeilen: list[dict]) -> Path:
        p = self.dir / "aaa.jsonl"
        p.write_text("\n".join(json.dumps(z, separators=(",", ":"))
                               for z in zeilen) + "\n")
        return p

    def titel(self) -> str:
        return data.Scanner(self.root).collect()[0]["title"]

    def test_erster_prompt_ohne_origin_wird_titel(self) -> None:
        self.datei([{"type": "user", "cwd": "/x",
                     "message": {"role": "user", "content": "Steht ein Skill bereit?"}}])
        self.assertEqual(self.titel(), "Steht ein Skill bereit?")

    def test_boilerplate_wird_uebersprungen(self) -> None:
        """`<local-command-caveat>` und `<command-name>` sind keine Fragen."""
        self.datei([
            {"type": "user", "cwd": "/x", "message": {"role": "user",
             "content": "<local-command-caveat>Caveat: …</local-command-caveat>"}},
            {"type": "user", "cwd": "/x", "message": {"role": "user",
             "content": "<command-name>/effort</command-name>"}},
        ])
        self.assertEqual(self.titel(), "")

    def test_echte_frage_nach_boilerplate_gewinnt(self) -> None:
        self.datei([
            {"type": "user", "cwd": "/x", "message": {"role": "user",
             "content": "<local-command-caveat>Caveat: …</local-command-caveat>"}},
            {"type": "user", "cwd": "/x", "message": {"role": "user",
             "content": "Wie geht das?"}},
        ])
        self.assertEqual(self.titel(), "Wie geht das?")

    def test_mit_origin_bleibt_der_strenge_weg(self) -> None:
        """Gibt es den Marker, darf der Notbehelf nicht danebengreifen.

        Sonst wäre er eine stille Hintertür an der bewussten Filterung
        vorbei: hier ist die einzige Nachricht MIT Marker die zweite.
        """
        self.datei([
            {"type": "user", "cwd": "/x", "message": {"role": "user",
             "content": "vom Werkzeug erzeugt"}},
            {"type": "user", "cwd": "/x", "origin": {"kind": "human"},
             "message": {"role": "user", "content": "vom Menschen getippt"}},
        ])
        self.assertEqual(self.titel(), "vom Menschen getippt")

    def test_ai_title_schlaegt_den_notbehelf(self) -> None:
        self.datei([
            {"type": "user", "cwd": "/x",
             "message": {"role": "user", "content": "erste Frage"}},
            {"type": "ai-title", "aiTitle": "Vergebener Titel"},
        ])
        self.assertEqual(self.titel(), "Vergebener Titel")

    def test_ohne_nutzernachricht_bleibt_leer(self) -> None:
        self.datei([{"type": "system", "cwd": "/x", "subtype": "init"}])
        self.assertEqual(self.titel(), "")
