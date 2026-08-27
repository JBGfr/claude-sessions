"""Aktionen: Sessions öffnen, Fenster fokussieren, Watchdog steuern."""
from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Optional

from . import texte
from .data import WATCHDOG_BIN, _pid_is_claude

#: Länge der Elternkette, die beim Fenstersuchen maximal durchlaufen wird.
_MAX_ANCESTORS = 12

#: systemd-User-Units, die die App steuert: der Watchdog-Daemon und sie
#: selbst (letztere für „Übernehmen & neu starten" im Einstellungsdialog).
WATCHDOG_UNIT = "claude-watchdog"
APP_UNIT = "claude-sessions-app"

#: Umgebungsvariablen, die ein neues Fenster zwingend braucht. Die transiente
#: Unit erbt sonst nur die Umgebung des User-Managers; die stimmt hier zwar
#: überein, muss es aber nicht (Start aus einem Terminal, zweite Anzeige).
_PASS_ENV = ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY")

#: Speichergrenzen für aus der Übersicht geöffnete Fenster.
#:
#: Ohne Grenze reisst ein durchgehendes Fenster das ganze System mit: am
#: 2026-07-31 wuchs die Unit einer geöffneten Sitzung auf 27,8 GB und 25,8 GB
#: Swap, worauf der Kernel global aufräumte und ``ollama`` erschlug. Ein
#: zweiter Fall lag bei 28,6 GB. Zum Vergleich: die überwachten Dauer-Sessions
#: erreichten in sieben Tagen höchstens 1,1 GB.
#:
#: ``MemoryHigh`` bremst nur (Reclaim-Druck) und tötet nichts — eine Sitzung,
#: die wirklich mehr braucht, läuft weiter, nur langsamer. Erst ``MemoryMax``
#: greift hart, und dann ausschliesslich innerhalb dieser cgroup. Die
#: Swap-Grenze ist das eigentliche Rettungsseil: die 25,8 GB Swap sind das,
#: was den Rechner unbedienbar macht, lange bevor der Kernel eingreift.
#:
#: ``MemoryHigh`` stand zuerst auf 4G — zu eng. Die Annahme stammte von den
#: überwachten Dauer-Sessions (höchstens 1,1 GB), aber die sind meist untätig.
#: Nachgemessen an den tatsächlich offenen Fenstern am 2026-07-31, 19:55:
#:
#:   Claude-Session 1d9f7778   3502 MB  (nach 5,5 h, +11 MB/min)
#:   Claude-Session 2eb30eac    985 MB  (+30 MB/min)
#:   Claude-Session b1d16112    740 MB
#:   Claude-Session ada0e2cb    373 MB
#:
#: Die erste hätte die Bremse binnen einer Stunde erreicht, obwohl an ihr
#: nichts krank war. 8G liegt gut über allem Beobachteten und immer noch
#: weit unter den 27,8 GB des Ausreissers.
_MEM_LIMITS = (
    "--property=MemoryHigh=8G",
    "--property=MemoryMax=12G",
    "--property=MemorySwapMax=2G",
)


def _spawn_detached(argv: list[str], description: str) -> bool:
    """Ein Fenster starten, das von der App vollständig abgelöst ist.

    ``start_new_session=True`` löst den Prozess nur von der Prozessgruppe,
    **nicht von der cgroup**: aus der App geöffnete Terminals blieben bisher
    dauerhaft in der cgroup des App-Dienstes hängen. Sichtbar wurde das als
    „Found left-over process … (claude) in control group" bei jedem Start.
    ``KillMode=process`` hat sie beim Stoppen zwar verschont, aber sie wären
    beim Abmelden oder bei einem ``systemctl --user kill`` mitgerissen worden
    — also genau die Sessions, die überleben sollen.

    ``systemd-run`` hängt sie stattdessen als eigene transiente Unit unter
    den User-Manager: eigene cgroup, eigener Elternprozess, kein Bezug mehr
    zur Übersicht. ``--collect`` räumt die Unit nach dem Ende selbst weg.

    ``ExitType=cgroup`` ist dabei nicht optional. Eine transiente Unit ist
    ``Type=simple``: sie gilt als beendet, sobald ihr **Hauptprozess** weg
    ist, und nimmt dann die restliche cgroup mit. ``claude-session-open``
    und ``xdg-open`` schicken ihr Fenster aber nur los und enden sofort —
    ohne diese Eigenschaft riss systemd das gerade geöffnete Terminal
    unmittelbar wieder ab (gemessen: Unit sofort ``inactive/success``, kein
    ``claude``-Prozess, kein Fenster). Mit ``ExitType=cgroup`` läuft die
    Unit, solange noch **irgendein** Prozess darin lebt. Braucht systemd
    ≥ 250; hier läuft 261.

    Dazu kommen die Speichergrenzen aus ``_MEM_LIMITS``: eine eigene cgroup
    nützt wenig, wenn ein durchgehendes Fenster trotzdem den gesamten
    Arbeitsspeicher des Rechners aufbraucht.
    """
    setenv = ["--setenv=%s=%s" % (k, v)
              for k in _PASS_ENV if (v := os.environ.get(k))]
    # Ausdruecklich als vom Menschen ausgeloest kennzeichnen. Die transiente
    # Unit setzt INVOCATION_ID, und `claude-session-open` haelt sich daran
    # sonst fuer unbeaufsichtigt und unterdrueckt jede Fehlermeldung — ein
    # gescheitertes „Öffnen" bliebe dann unsichtbar.
    setenv.append("--setenv=CLAUDE_SESSIONS_INTERACTIVE=1")
    try:
        proc = subprocess.run(
            ["systemd-run", "--user", "--collect", "--quiet",
             "--property=ExitType=cgroup", *_MEM_LIMITS,
             "--description=" + description, *setenv, "--", *argv],
            capture_output=True, timeout=15,
        )
        if proc.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    # Reserve: ohne erreichbaren systemd lieber ein Fenster in der eigenen
    # cgroup als gar keins.
    try:
        subprocess.Popen(
            argv,
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


#: Terminal-Emulatoren in der Reihenfolge, in der sie probiert werden —
#: dieselbe Liste wie in bin/claude-session-open. QTerminal war hier fest
#: verdrahtet; auf jeder Nicht-LXQt-Kiste war damit "Anhängen" ein Knopf,
#: der nie ein Fenster öffnete (Prüferbefund 2026-08-21).
TERMINALS = (
    ("qterminal", ("-e",)),
    ("x-terminal-emulator", ("-e",)),
    ("xfce4-terminal", ("--command",)),
    ("konsole", ("-e",)),
    ("gnome-terminal", ("--",)),
    ("xterm", ("-e",)),
)


def terminal_command(script: str) -> Optional[list[str]]:
    """Kommandozeile, die `script` in einem neuen Terminalfenster startet.

    None, wenn kein Terminal auffindbar ist — der Aufrufer meldet das dann
    in der Statuszeile, statt still zu scheitern. xfce4-terminal nimmt das
    Kommando als EINE Zeichenkette, die anderen als Argumentliste.
    """
    for name, flags in TERMINALS:
        if shutil.which(name):
            if name == "xfce4-terminal":
                return [name, *flags, "sh -c %s" % shlex.quote(script)]
            return [name, *flags, "sh", "-c", script]
    return None


def open_session(session_id: str) -> bool:
    """Gespeicherte Session in einem neuen Terminalfenster fortsetzen."""
    return _spawn_detached(["claude-session-open", session_id],
                           "Claude-Session %s" % session_id[:8])


def attach_session(name: str) -> bool:
    """Dauer-Session in einem neuen Terminal anhängen.

    Sitzungen unter `claude-session@<name>.service` laufen in einem
    dtach-Socket und haben **kein Fenster** — `focus_session_window` konnte
    dort nie etwas finden. Angehängt wird über `claude-sessionctl attach`,
    das auch den Hinweis zum Lösen (Strg+\\) ausgibt.
    """
    quoted = shlex.quote(name)
    script = ('printf "\\033]0;Claude-Session %s\\007";'
              ' exec claude-sessionctl attach %s' % (quoted, quoted))
    argv = terminal_command(script)
    if argv is None:
        return False
    return _spawn_detached(argv, "Claude-Session %s (angehängt)" % name)


def _ppid(pid: int) -> Optional[int]:
    """Eltern-PID aus /proc/<pid>/stat (Feld 4, hinter der letzten ')')."""
    try:
        with open("/proc/%d/stat" % pid, "rb") as f:
            d = f.read()
        return int(d[d.rfind(b")") + 2:].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def _managed_windows() -> list[tuple[str, int]]:
    """(Fenster-ID, PID) aller vom Window-Manager verwalteten Fenster."""
    try:
        proc = subprocess.run(["wmctrl", "-lp"], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in proc.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) >= 3 and parts[2].isdigit():
            out.append((parts[0], int(parts[2])))
    return out


def focus_session_window(pid: int) -> bool:
    """Das Terminalfenster der Session in den Vordergrund holen.

    Der claude-Prozess selbst hat kein Fenster; deshalb die Elternkette
    (zsh -> qterminal -> …) hochlaufen und das erste verwaltete Fenster
    einer dieser PIDs aktivieren. Bewusst wmctrl statt xdotool: dessen
    'search --onlyvisible' uebersieht Fenster auf anderen Workspaces
    (xfwm unmappt sie), wmctrl -ia wechselt beim Aktivieren auch dorthin.
    """
    chain = []
    p: Optional[int] = pid
    for _ in range(_MAX_ANCESTORS):
        if not p or p <= 1:
            break
        chain.append(p)
        p = _ppid(p)
    windows = _managed_windows()
    for cand in chain:
        for wid, wpid in windows:
            if wpid != cand:
                continue
            try:
                subprocess.run(["wmctrl", "-ia", wid],
                               capture_output=True, timeout=5)
                return True
            except (OSError, subprocess.SubprocessError):
                return False
    return False


def terminate(pid: int) -> bool:
    """Den claude-Prozess sauber beenden (SIGTERM, kein KILL).

    Zwischen Snapshot und Klick (Menue/Dialog koennen beliebig lange offen
    stehen) kann die PID neu vergeben worden sein — vor dem Signal deshalb
    pruefen, dass dahinter noch ein claude-Prozess steckt.
    """
    if not _pid_is_claude(pid):
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


def stop_service(name: str) -> tuple[bool, str]:
    """Einen Dauer-Dienst wirklich beenden; (ok, erste Ausgabezeile).

    Bei diesen Sitzungen reicht ein SIGTERM an den claude-Prozess nicht: der
    Runner reicht dessen Exit-Code durch (143), und die Unit hat
    ``Restart=on-failure`` mit ``RestartPreventExitStatus=77 78 127`` — 143
    steht dort nicht drin. systemd startet die Sitzung also nach zehn
    Sekunden wieder. „Beenden" waere eine kurze Unterbrechung, kein Ende.

    ``claude-sessionctl stop`` beendet den Dienst und nimmt ihn zugleich aus
    dem Autostart (``disable --now``) — genau das ist hier gemeint.
    """
    try:
        proc = subprocess.run(["claude-sessionctl", "stop", name],
                              capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    text = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode == 0, (text.splitlines()[0] if text else "")


def open_folder(cwd: str) -> None:
    _spawn_detached(["xdg-open", cwd], "Ordner %s" % cwd)


def watchdog(*args: str) -> tuple[bool, str]:
    """Ein Watchdog-CLI-Kommando ausführen; (ok, erste Ausgabezeile)."""
    try:
        proc = subprocess.run(
            [str(WATCHDOG_BIN), *args],
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    text = (proc.stdout or proc.stderr or "").strip()
    first = text.splitlines()[0] if text else ""
    return proc.returncode == 0, first


def show_watchdog_logs(task_id: str) -> None:
    """Logs eines Tasks in einem neuen Terminalfenster anzeigen."""
    script = (
        '%s logs %s --lines 60; printf "\\n[Enter schliesst]"; read _x'
        % (shlex.quote(str(WATCHDOG_BIN)), shlex.quote(task_id))
    )
    argv = terminal_command(script)
    if argv is not None:
        _spawn_detached(argv, "Watchdog-Logs %s" % task_id)


def show_live_log() -> bool:
    """Live-Log aller Dauer-Dienste in einem neuen Terminalfenster.

    journalctl folgt allen Instanzen der Template-Unit; das Ereignislog
    daneben zeigt Start/Stopp/Neustart im Klartext.
    """
    events = Path.home() / ".local/state/claude-sessions/events.log"
    script = (
        "printf '\\033]0;Claude-Sessions Live-Log\\007';"
        "journalctl --user -u 'claude-session@*' -n 40 -f --no-hostname &"
        " tail -n 20 -f %s; wait" % shlex.quote(str(events))
    )
    argv = terminal_command(script)
    if argv is None:
        return False
    return _spawn_detached(argv,
                           "Claude-Sessions Live-Log")


def set_daemon(active: bool) -> tuple[bool, str]:
    """Watchdog-Daemon über die systemd-User-Unit starten/stoppen."""
    verb = "start" if active else "stop"
    try:
        proc = subprocess.run(
            ["systemctl", "--user", verb, WATCHDOG_UNIT],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if proc.returncode == 0:
        return True, texte.t("meldung.daemon_gestartet" if active
                             else "meldung.daemon_gestoppt")
    return False, ((proc.stderr or "").strip().splitlines()[0]
                   if proc.stderr else texte.t("meldung.fehler"))


def reload_watchdog() -> tuple[bool, str]:
    """Ein geändertes Drop-in beim Watchdog wirksam machen; (ok, Fehlertext).

    Zwei Schritte, beide nötig: `daemon-reload` liest die Unit samt Drop-ins
    neu ein, und erst ein Neustart des Dienstes gibt dem laufenden Prozess
    die neue Umgebung — `CW_NOTIFY` wird im Watchdog beim Start gelesen.

    Bewusst `try-restart` und nicht `restart`: `restart` würde einen
    Watchdog-Daemon **starten**, den der Nutzer selbst gestoppt hat. Eine
    Einstellung für Pop-ups darf keinen Dienst hochfahren; steht er, greift
    die neue Umgebung beim nächsten Start von selbst.

    Blockiert (zwei Subprozesse) — gehört wie `set_daemon` in einen
    Hintergrund-Thread, nie in den Mainthread.
    """
    for argv in (["systemctl", "--user", "daemon-reload"],
                 ["systemctl", "--user", "try-restart", WATCHDOG_UNIT]):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)
        if proc.returncode != 0:
            meldung = (proc.stderr or proc.stdout or "").strip()
            return False, (meldung.splitlines()[0] if meldung
                           else "%s: %d" % (argv[2], proc.returncode))
    return True, ""


def restart_app() -> bool:
    """Die Übersicht selbst neu starten (Einstellungsdialog).

    Der Neustart muss **außerhalb** der eigenen cgroup laufen: `systemctl
    --user restart` beendet dabei genau den Dienst, in dem dieser Prozess
    steckt. Läge der Aufruf in derselben cgroup, würde er mit abgeräumt,
    bevor er den Dienst wieder hochfahren kann. `_spawn_detached` hängt ihn
    als eigene transiente Unit unter den User-Manager — deshalb überlebt er
    das Stoppen und startet die App danach wieder.

    Kehrt sofort zurück (kein Warten auf den Neustart im Mainthread).
    """
    return _spawn_detached(["systemctl", "--user", "restart", APP_UNIT],
                           "Claude Sessions neu starten")


def copy_to_clipboard_fallback(text: str) -> None:
    """Nur als Reserve; die App nutzt normalerweise Gtk.Clipboard."""
    try:
        subprocess.run(["xclip", "-selection", "clipboard"],
                       input=text.encode(), timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
