"""Tests für die Aktionen — ohne echte Fenster, ohne echte Subprozesse."""
from __future__ import annotations

import subprocess
import unittest
import unittest.mock
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_sessions import actions  # noqa: E402


class FakeCompleted:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


class SpawnDetachedTest(unittest.TestCase):
    """Aus der App geöffnete Fenster müssen die cgroup des Dienstes verlassen."""

    def setUp(self) -> None:
        self.run_calls: list[list[str]] = []
        self.popen_calls: list[list[str]] = []

    def patch(self, run_result, popen_result=None) -> None:
        def fake_run(argv, **kw):
            self.run_calls.append(list(argv))
            if isinstance(run_result, Exception):
                raise run_result
            return run_result

        def fake_popen(argv, **kw):
            self.popen_calls.append(list(argv))
            if isinstance(popen_result, Exception):
                raise popen_result
            return object()

        for name, fn in (("run", fake_run), ("Popen", fake_popen)):
            patcher = unittest.mock.patch.object(actions.subprocess, name, fn)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_geht_ueber_systemd_run(self) -> None:
        self.patch(FakeCompleted(0))
        self.assertTrue(actions._spawn_detached(["qterminal", "-e", "x"], "Test"))
        argv = self.run_calls[0]
        self.assertEqual(argv[:4],
                         ["systemd-run", "--user", "--collect", "--quiet"])
        self.assertIn("--description=Test", argv)
        # Ohne ExitType=cgroup reisst systemd das Fenster sofort wieder ab,
        # sobald der Starter (claude-session-open, xdg-open) sich beendet:
        # Type=simple wertet 'Hauptprozess weg' als 'Unit fertig'.
        self.assertIn("--property=ExitType=cgroup", argv)
        # Alles hinter '--' ist unveraendert der gewuenschte Befehl.
        self.assertEqual(argv[argv.index("--") + 1:], ["qterminal", "-e", "x"])
        # Kein Direktstart: sonst haette das Fenster wieder unsere cgroup.
        self.assertEqual(self.popen_calls, [])

    def test_anzeige_wird_durchgereicht(self) -> None:
        self.patch(FakeCompleted(0))
        with unittest.mock.patch.dict(
                actions.os.environ,
                {"DISPLAY": ":0", "XAUTHORITY": "/home/user/.Xauthority"},
                clear=True):
            actions._spawn_detached(["true"], "Test")
        argv = self.run_calls[0]
        self.assertIn("--setenv=DISPLAY=:0", argv)
        self.assertIn("--setenv=XAUTHORITY=/home/user/.Xauthority", argv)
        # Nicht gesetzte Variablen tauchen nicht als leere Zuweisung auf.
        self.assertNotIn("--setenv=WAYLAND_DISPLAY=", argv)

    def test_reserve_wenn_systemd_run_scheitert(self) -> None:
        self.patch(FakeCompleted(1))
        self.assertTrue(actions._spawn_detached(["qterminal"], "Test"))
        self.assertEqual(self.popen_calls, [["qterminal"]])

    def test_reserve_wenn_systemd_run_fehlt(self) -> None:
        self.patch(FileNotFoundError("systemd-run"))
        self.assertTrue(actions._spawn_detached(["qterminal"], "Test"))
        self.assertEqual(self.popen_calls, [["qterminal"]])

    def test_timeout_faellt_ebenfalls_zurueck(self) -> None:
        self.patch(subprocess.TimeoutExpired(cmd="systemd-run", timeout=15))
        self.assertTrue(actions._spawn_detached(["qterminal"], "Test"))
        self.assertEqual(self.popen_calls, [["qterminal"]])

    def test_false_wenn_gar_nichts_geht(self) -> None:
        self.patch(FakeCompleted(1), popen_result=OSError("kein qterminal"))
        self.assertFalse(actions._spawn_detached(["qterminal"], "Test"))


class SpeichergrenzeTest(unittest.TestCase):
    """Ein durchgehendes Fenster darf nicht den ganzen Rechner mitnehmen.

    Am 2026-07-31 wuchs die Unit einer aus der Uebersicht geoeffneten
    Sitzung auf 27,8 GB und 25,8 GB Swap; der Kernel raeumte daraufhin
    global auf und erschlug ollama. Ein zweiter Fall lag bei 28,6 GB.

    Die Bremse stand zuerst auf 4G. Diese Annahme kam von den ueberwachten
    Dauer-Sessions (hoechstens 1,1 GB) — die sind aber meist untaetig. An
    den tatsaechlich offenen Fenstern nachgemessen (19:55): 373 MB, 740 MB,
    985 MB und 3502 MB. Die letzte laeuft seit 5,5 Stunden voellig gesund
    und waere binnen einer Stunde in die Bremse gelaufen. Daher 8G — gut
    ueber allem Beobachteten und weiterhin weit unter dem Ausreisser.
    """

    def setUp(self) -> None:
        self.calls: list[list[str]] = []

        def fake_run(argv, **kw):
            self.calls.append(list(argv))
            return FakeCompleted(0)

        patcher = unittest.mock.patch.object(actions.subprocess, "run", fake_run)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_grenzen_gehen_mit(self) -> None:
        actions._spawn_detached(["qterminal"], "Test")
        argv = self.calls[0]
        for grenze in ("MemoryHigh=8G", "MemoryMax=12G", "MemorySwapMax=2G"):
            self.assertIn("--property=" + grenze, argv)

    def test_grenzen_stehen_vor_dem_trenner(self) -> None:
        """Alles hinter '--' ist der Befehl — dort haetten sie keine Wirkung."""
        actions._spawn_detached(["qterminal", "-e", "x"], "Test")
        argv = self.calls[0]
        trenner = argv.index("--")
        for i, teil in enumerate(argv):
            if teil.startswith("--property=Memory"):
                self.assertLess(i, trenner, teil)

    def test_swap_ist_begrenzt(self) -> None:
        """Die Swap-Grenze ist der eigentliche Schutz vor dem Einfrieren.

        25,8 GB Swap machen den Rechner unbedienbar, lange bevor der
        Kernel ueberhaupt eingreift.
        """
        actions._spawn_detached(["qterminal"], "Test")
        self.assertIn("--property=MemorySwapMax=2G", self.calls[0])


class SpawnCallerTest(unittest.TestCase):
    """Alle fensteröffnenden Aktionen müssen über den Helfer laufen."""

    def setUp(self) -> None:
        self.calls: list[tuple[list[str], str]] = []
        patcher = unittest.mock.patch.object(
            actions, "_spawn_detached",
            lambda argv, desc: (self.calls.append((argv, desc)), True)[1])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_open_session(self) -> None:
        self.assertTrue(actions.open_session("abc123def456"))
        self.assertEqual(self.calls[0][0], ["claude-session-open", "abc123def456"])

    def test_open_folder(self) -> None:
        actions.open_folder("/home/user/Projekte")
        self.assertEqual(self.calls[0][0], ["xdg-open", "/home/user/Projekte"])

    def test_live_log(self) -> None:
        self.assertTrue(actions.show_live_log())
        self.assertEqual(self.calls[0][0][:2], ["qterminal", "-e"])

    def test_watchdog_logs_maskiert_die_task_id(self) -> None:
        actions.show_watchdog_logs("task; rm -rf ~")
        script = self.calls[0][0][-1]
        self.assertIn("'task; rm -rf ~'", script)



class InteractiveMarkerTest(unittest.TestCase):
    """Fenster aus der App muessen sich als vom Menschen ausgeloest ausweisen."""

    def test_marker_geht_mit(self) -> None:
        calls = []

        def fake_run(argv, **kw):
            calls.append(list(argv))
            return FakeCompleted(0)

        with unittest.mock.patch.object(actions.subprocess, "run", fake_run):
            actions._spawn_detached(["claude-session-open", "abc"], "Test")
        # Ohne diesen Marker haelt claude-session-open den Aufruf fuer
        # unbeaufsichtigt (die transiente Unit setzt INVOCATION_ID) und
        # unterdrueckt jede Fehlermeldung — ein gescheitertes Oeffnen bliebe
        # dann voellig unsichtbar.
        self.assertIn("--setenv=CLAUDE_SESSIONS_INTERACTIVE=1", calls[0])


class AttachSessionTest(unittest.TestCase):
    """Dauer-Dienste werden angehaengt, nicht fokussiert."""

    def test_ruft_sessionctl_attach(self) -> None:
        calls = []
        with unittest.mock.patch.object(
                actions, "_spawn_detached",
                lambda argv, desc: (calls.append((argv, desc)), True)[1]):
            self.assertTrue(actions.attach_session("zsh-menu"))
        argv, desc = calls[0]
        self.assertEqual(argv[:2], ["qterminal", "-e"])
        self.assertIn("claude-sessionctl attach zsh-menu", argv[-1])
        self.assertIn("zsh-menu", desc)

    def test_name_wird_maskiert(self) -> None:
        calls = []
        with unittest.mock.patch.object(
                actions, "_spawn_detached",
                lambda argv, desc: (calls.append(argv), True)[1]):
            actions.attach_session("boes; rm -rf ~")
        self.assertIn("'boes; rm -rf ~'", calls[0][-1])


class StopServiceTest(unittest.TestCase):
    """Ein Dauer-Dienst wird ueber sessionctl gestoppt, nicht per SIGTERM."""

    def lauf(self, rc, out="", err=""):
        calls = []

        class R:
            returncode = rc
            stdout = out
            stderr = err

        def fake_run(argv, **kw):
            calls.append(list(argv))
            return R()

        with unittest.mock.patch.object(actions.subprocess, "run", fake_run):
            ergebnis = actions.stop_service("zsh-menu")
        return calls, ergebnis

    def test_ruft_sessionctl_stop(self):
        calls, (ok, _) = self.lauf(0, out="Gestoppt: zsh-menu\n")
        self.assertEqual(calls[0], ["claude-sessionctl", "stop", "zsh-menu"])
        self.assertTrue(ok)

    def test_meldet_erste_zeile_zurueck(self):
        _, (ok, meldung) = self.lauf(0, out="Gestoppt: zsh-menu\nnoch was")
        self.assertEqual(meldung, "Gestoppt: zsh-menu")

    def test_fehlschlag_wird_gemeldet(self):
        _, (ok, meldung) = self.lauf(2, err="Kein Projekt 'zsh-menu'")
        self.assertFalse(ok)
        self.assertIn("Kein Projekt", meldung)

    def test_fehlendes_programm_wirft_nicht(self):
        def kaputt(argv, **kw):
            raise FileNotFoundError("claude-sessionctl")
        with unittest.mock.patch.object(actions.subprocess, "run", kaputt):
            ok, meldung = actions.stop_service("zsh-menu")
        self.assertFalse(ok)
        self.assertIn("claude-sessionctl", meldung)


if __name__ == "__main__":
    unittest.main()


class TerminalKetteTest(unittest.TestCase):
    """Kein fest verdrahtetes qterminal mehr — der Knopf muss überall ein Fenster öffnen."""

    def _mit(self, vorhanden):
        return unittest.mock.patch.object(actions.shutil, "which",
                                 side_effect=lambda n: "/usr/bin/%s" % n if n in vorhanden else None)

    def test_erster_vorhandener_gewinnt(self):
        with self._mit({"konsole", "xterm"}):
            argv = actions.terminal_command("echo hi")
        self.assertEqual(["konsole", "-e", "sh", "-c", "echo hi"], argv)

    def test_xterm_als_letzte_reserve(self):
        with self._mit({"xterm"}):
            self.assertEqual("xterm", actions.terminal_command("x")[0])

    def test_xfce4_bekommt_eine_zeichenkette(self):
        """xfce4-terminal nimmt --command als EIN Argument, nicht als Liste."""
        with self._mit({"xfce4-terminal"}):
            argv = actions.terminal_command("echo 'a b'")
        self.assertEqual("xfce4-terminal", argv[0])
        self.assertEqual("--command", argv[1])
        self.assertEqual(3, len(argv))
        self.assertIn("sh -c", argv[2])

    def test_keins_da_heisst_none(self):
        with self._mit(set()):
            self.assertIsNone(actions.terminal_command("x"))

    def test_anhaengen_meldet_fehlschlag_statt_zu_knallen(self):
        with self._mit(set()):
            self.assertFalse(actions.attach_session("probe"))

    def test_live_log_meldet_fehlschlag(self):
        with self._mit(set()):
            self.assertFalse(actions.show_live_log())
