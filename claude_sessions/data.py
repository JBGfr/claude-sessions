"""Datenschicht: gespeicherte Sessions, Live-Prozesse und Watchdog-Tasks."""
from __future__ import annotations

import calendar
import json
import os
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import einstellungen, texte

HOME = Path.home()
PROJECTS_DIR = HOME / ".claude" / "projects"


def _pfad_aus_umgebung(name: str, vorgabe: Path) -> Path:
    """Pfad aus einer Umgebungsvariablen, sonst die Vorgabe.

    Ein leerer Wert zählt wie „nicht gesetzt", und `~` wird aufgelöst, damit
    auch `CS_WATCHDOG_DIR=~/wd` funktioniert. Gelesen wird einmal beim Import:
    die Übersicht läuft stundenlang, ein Wechsel mittendrin wäre nur
    verwirrend.
    """
    roh = os.environ.get(name, "").strip()
    return Path(roh).expanduser() if roh else vorgabe


#: Verzeichnis des Claude-Watchdogs — dort liegen seine Datenbank (die nur
#: lesend geöffnet wird) und seine CLI. Der Watchdog ist **optional**: liegt
#: er woanders, setzt man `CS_WATCHDOG_DIR`; fehlt er ganz, ist auch das kein
#: Fehler. `watchdog_tasks()` meldet dann „keine Daten" (ok=False), und die
#: Übersicht kommt ohne Watchdog-Angaben aus.
WATCHDOG_DIR = _pfad_aus_umgebung("CS_WATCHDOG_DIR", HOME / ".claude-watchdog")
WATCHDOG_DB = WATCHDOG_DIR / "state.db"
#: Schreibende Watchdog-Aktionen gehen ausschließlich über dessen CLI.
WATCHDOG_BIN = WATCHDOG_DIR / "bin" / "claude-watchdog"


def _claude_programm() -> Path:
    """Wo liegt die Programmdatei von Claude Code?

    Vorgabe ist der Ort des offiziellen Installers (`~/.local/bin/claude`).
    Liegt dort nichts, entscheidet der Suchpfad — andere Installationen legen
    das Programm etwa nach `/usr/local/bin` oder in ein npm-Präfix. Findet
    sich gar nichts, bleibt es beim Vorgabepfad: `live_agents()` fängt den
    fehlschlagenden Aufruf ab und meldet „keine Live-Daten", statt zu kippen.
    """
    vorgabe = HOME / ".local" / "bin" / "claude"
    if vorgabe.exists():
        return vorgabe
    gefunden = shutil.which("claude")
    return Path(gefunden) if gefunden else vorgabe


CLAUDE_BIN = _claude_programm()

#: Echte Limitwerte, hinterlegt von `tools/statusline.py`. Claude Code reicht
#: `rate_limits` an das Statusleisten-Skript durch — das ist dieselbe Quelle,
#: aus der `/usage` seine Prozente nimmt. Aus den Transkripten ist das nicht
#: herzuleiten: Desktop-App, Browser und andere Geräte belasten dasselbe
#: Kontingent, ohne hier eine Zeile zu hinterlassen.
PLAN_USAGE_FILE = HOME / ".local/state/claude-sessions/usage.json"

#: Ab diesem Alter gilt der hinterlegte Wert als nicht mehr taufrisch und die
#: Anzeige schreibt den Zeitpunkt dazu.
PLAN_USAGE_STALE = 300

#: MCP-Konfigurationen. Claude Code hält seine im User-Scope von `.claude.json`,
#: die Desktop-App eine eigene Datei — beide werden nur gelesen.
MCP_CODE_CONFIG = HOME / ".claude.json"
MCP_DESKTOP_CONFIG = HOME / ".config" / "Claude" / "claude_desktop_config.json"

#: Zeitbudget für `claude agents --json --all` (läuft normal in ~0,2 s).
AGENTS_TIMEOUT = 8

#: Länge des Nutzungsfensters. Ein Fenster beginnt mit der ersten Nachricht
#: und läuft fünf Stunden; die nächste Nachricht danach eröffnet ein neues.
WINDOW_SECONDS = 5 * 3600

#: Wie weit zurück einzelne Nutzungsereignisse vorgehalten werden. Nur für
#: die Fensterrechnung nötig — die Gesamtsumme je Session bleibt davon
#: unberührt. Großzügig genug, dass ein Fenster nie abgeschnitten wird.
USAGE_KEEP_SECONDS = 24 * 3600

#: Gruppen für Sortierung und Abschnitts-Überschriften.
GROUP_LIVE = 0
GROUP_QUEUE = 1
GROUP_STORED = 2



class _Sprachtabelle(Mapping):
    """Nachschlagetabelle, die ihre Wörter erst beim Zugriff übersetzt.

    Nach außen ein ganz normales `dict` (`tabelle[k]`, `.get(k, vorgabe)`,
    `in`, `for`) — nur steht darin nicht der Text, sondern sein Schlüssel in
    `texte`. Deshalb folgt die Anzeige einem Sprachwechsel zur Laufzeit,
    ohne dass irgendwer die Tabelle neu bauen müsste; ein beim Import
    ausgerechnetes `dict` wäre für immer in der Startsprache eingefroren.
    """

    def __init__(self, schluessel: dict[Any, str]) -> None:
        self._schluessel = schluessel

    def __getitem__(self, key: Any) -> str:
        return texte.t(self._schluessel[key])

    def __iter__(self):
        return iter(self._schluessel)

    def __len__(self) -> int:
        return len(self._schluessel)

    def __repr__(self) -> str:
        return repr(dict(self))


GROUP_LABELS = _Sprachtabelle({
    GROUP_LIVE: "gruppe.laufend",
    GROUP_QUEUE: "gruppe.warteschlange",
    GROUP_STORED: "gruppe.zuletzt",
})

#: Kurzformen für Watchdog-Status (Werte aus models.Status). Der Name bleibt
#: `WD_STATUS_DE`, weil `app.py` und die Tests daran hängen — der Inhalt ist
#: seit der Sprachschicht zweisprachig.
WD_STATUS_DE = _Sprachtabelle({
    "pending": "wd.status.pending",
    "running": "wd.status.running",
    "stalled": "wd.status.stalled",
    "blocked": "wd.status.blocked",
    "waiting_for_limit": "wd.status.waiting_for_limit",
    "done": "wd.status.done",
    "failed": "wd.status.failed",
    "paused": "wd.status.paused",
})

WD_MODE_DE = _Sprachtabelle({
    "managed": "wd.modus.managed",
    "observed": "wd.modus.observed",
})


@dataclass
class SessionInfo:
    """Eine Zeile der Übersicht — Session, Live-Prozess und Watchdog vereint."""

    id: str
    title: str = ""
    cwd: str = ""
    msgs: int = 0
    #: Letzte Aktivität als Unix-Zeit (Datei-mtime bzw. Prozessstart).
    mtime: float = 0.0
    size: int = 0
    path: str = ""
    group: int = GROUP_STORED
    #: Tokens dieser Session insgesamt (Eingabe + Ausgabe + neuer Cache).
    tokens: int = 0

    live: bool = False
    #: Name des Dauer-Dienstes, falls die Sitzung unter systemd+dtach läuft.
    #: Solche Sitzungen haben kein Fenster — sie werden angehängt, nicht
    #: fokussiert.
    service: Optional[str] = None
    #: Status aus `claude agents`: "busy" oder "idle" (weitere Werte möglich).
    live_status: Optional[str] = None
    pid: Optional[int] = None
    started_at: float = 0.0

    wd_task_id: Optional[str] = None
    wd_mode: Optional[str] = None
    wd_status: Optional[str] = None
    wd_attempts: int = 0
    wd_max_attempts: int = 0
    wd_error: Optional[str] = None

    @property
    def sort_key(self) -> tuple:
        return (self.group, -self.mtime)


@dataclass
class McpServer:
    """Ein konfigurierter MCP-Server, so wie er in der Config steht."""

    name: str
    #: Welcher Client ihn lädt — "Claude Code" oder "Claude Desktop".
    client: str
    #: "http", "sse" oder "stdio".
    transport: str = "stdio"
    #: URL bzw. Startbefehl, gekürzt für die Anzeige.
    detail: str = ""


@dataclass
class Snapshot:
    sessions: list[SessionInfo] = field(default_factory=list)
    n_live: int = 0
    n_busy: int = 0
    n_stored: int = 0
    n_queue: int = 0
    agents_ok: bool = True
    wd_ok: bool = True
    daemon_active: bool = False
    wd_restarts: int = 0
    mcp: list[McpServer] = field(default_factory=list)
    mcp_ok: bool = True
    taken_at: float = 0.0
    #: Laufendes Fünf-Stunden-Fenster über alle Sessions (aus Transkripten).
    window: "TokenWindow" = field(default_factory=lambda: TokenWindow())
    #: Echte Kontingentwerte aus dem Statusleisten-Skript.
    plan: "PlanUsage" = field(default_factory=lambda: PlanUsage())


# --------------------------------------------------------------------------
# Session-Dateien unter ~/.claude/projects
# --------------------------------------------------------------------------

def _line_at(data: bytes, pos: int) -> bytes:
    """Die komplette JSONL-Zeile, in der `pos` liegt."""
    a = data.rfind(b"\n", 0, pos) + 1
    b = data.find(b"\n", pos)
    return data[a:] if b == -1 else data[a:b]


#: Nutzernachrichten, die Claude Code selbst erzeugt, beginnen mit einem
#: solchen Marker — ``<local-command-caveat>``, ``<command-name>/effort…``.
#: Sie sind keine Frage eines Menschen und taugen nicht als Titel.
_KEIN_TITEL_PRAEFIX = "<"


def _titel_ohne_origin(data: bytes) -> Optional[str]:
    """Letzter Notbehelf für Transkripte ganz ohne ``origin``-Marker.

    Der reguläre Weg sucht ``"origin":{"kind":"human"}`` — das Feld gibt es
    aber nicht in jedem Transkript. Gemessen am 2026-07-31: 18 von 57
    Sitzungen führen es nicht; bei zwölf davon rettet der ``ai-title`` den
    Titel, sechs blieben in der Übersicht namenlos. Drei davon hatten sehr
    wohl eine getippte Frage, darunter ``c01d8a87`` mit „Steht ein Skill
    namens obsidian-markdown in deiner Liste…".

    Nur wenn die Datei **überhaupt keinen** solchen Marker enthält, wird
    hier gesucht: sonst wäre dieser lockere Weg eine stille Hintertür an
    der bewussten Filterung vorbei.

    Genommen wird die erste ``user``-Nachricht mit einfachem Text, der
    nicht mit ``<`` beginnt. Diese Grenze ist an den echten Daten
    abgelesen, nicht geraten: die drei brauchbaren Prompts sind schlichte
    Zeichenketten (``hi``, ``Steht ein Skill…``), die zu überspringende
    Boilerplate beginnt ausnahmslos mit ``<``.
    """
    if b'"origin":' in data:
        return None
    p = data.find(b'"type":"user"')
    while p != -1:
        try:
            inhalt = json.loads(_line_at(data, p)).get("message", {}).get("content")
        except (ValueError, AttributeError):
            inhalt = None
        if isinstance(inhalt, str):
            text = inhalt.strip()
            if text and not text.startswith(_KEIN_TITEL_PRAEFIX):
                return text
        p = data.find(b'"type":"user"', p + 1)
    return None


def _scan_bytes(data: bytes) -> dict[str, Any]:
    """Titel, Arbeitsverzeichnis und Nachrichtenzahl aus einem Transkript.

    Nur zwei bis drei Zeilen gehen wirklich durch den JSON-Parser, der Rest
    sind Substring-Scans über den Puffer. Kaputte Zeilen fallen still weg.
    """
    title = None
    p = data.rfind(b'"type":"ai-title"')
    if p != -1:
        try:
            title = json.loads(_line_at(data, p)).get("aiTitle")
        except (ValueError, AttributeError):
            title = None

    if not title:
        # Fallback: erster Prompt, den wirklich ein Mensch getippt hat.
        p = data.find(b'"origin":{"kind":"human"}')
        while p != -1:
            try:
                c = json.loads(_line_at(data, p)).get("message", {}).get("content")
                if isinstance(c, list):
                    # Prompt mit eingefuegtem Bild: content ist eine
                    # Blockliste — nur die Textbloecke einsammeln.
                    c = "\n".join(b.get("text", "") for b in c
                                  if isinstance(b, dict) and b.get("type") == "text")
                if isinstance(c, str) and c.strip():
                    title = c
                    break
            except (ValueError, AttributeError):
                pass
            p = data.find(b'"origin":{"kind":"human"}', p + 1)

    if not title:
        title = _titel_ohne_origin(data)

    cwd = None
    p = data.find(b'"cwd":"')
    if p != -1:
        try:
            cwd = json.loads(_line_at(data, p)).get("cwd")
        except (ValueError, AttributeError):
            cwd = None

    return {
        "title": _tidy(title) if title else "",
        "cwd": cwd or "",
        "msgs": data.count(b'"type":"user"') + data.count(b'"type":"assistant"'),
    }


def _fortschreiben(alt: dict[str, Any], stueck: bytes) -> dict[str, Any]:
    """Vorhandene Angaben um ein angehängtes Stück Transkript ergänzen.

    JSONL wächst nur hinten, also lässt sich alles aus dem neuen Stück
    ableiten, statt die ganze Datei erneut zu durchsuchen:

    * **Nachrichtenzahl** — die Treffer im Stück kommen dazu.
    * **Titel** — ein späterer ``ai-title`` gewinnt (wie ``rfind`` über die
      ganze Datei). Fehlt noch einer, greift weiter der erste von Hand
      getippte Prompt; auch der kann im neuen Stück zum ersten Mal auftauchen.
    * **Arbeitsverzeichnis** — steht schon eines fest, bleibt es. ``cwd``
      wird ohnehin aus der *ersten* Zeile gelesen, die eines nennt.
    """
    neu = _scan_bytes(stueck)
    zusammen = dict(alt)
    zusammen["msgs"] = int(alt.get("msgs") or 0) + neu["msgs"]
    if neu["title"]:
        zusammen["title"] = neu["title"]
    elif not zusammen.get("title"):
        zusammen["title"] = ""
    if not zusammen.get("cwd") and neu["cwd"]:
        zusammen["cwd"] = neu["cwd"]
    return zusammen


def _tidy(s: Any) -> str:
    s = " ".join(str(s).split())
    return "".join(c for c in s if c.isprintable())


def _epoch(ts: str) -> float:
    """'2026-07-30T00:35:01.353Z' → Unix-Zeit. Die Zeitstempel sind UTC.

    Bewusst von Hand zerlegt statt über `strptime`: der erste Scan geht über
    mehrere tausend Zeilen, und `strptime` ist dort der teuerste Einzelposten.
    """
    try:
        return calendar.timegm((
            int(ts[0:4]), int(ts[5:7]), int(ts[8:10]),
            int(ts[11:13]), int(ts[14:16]), int(ts[17:19]), 0, 0, 0))
    except (ValueError, IndexError):
        return 0.0


def _usage_events(chunk: bytes) -> tuple[list[tuple[float, int]], int]:
    """Nutzungsereignisse aus einem Stück Transkript: [(Zeit, Tokens)].

    Gibt zusätzlich zurück, wie viele Bytes davon vollständig verarbeitet
    wurden — eine angefangene letzte Zeile bleibt liegen und wird beim
    nächsten Durchlauf mitgelesen. Genau das macht das Fortschreiben
    möglich: JSONL wächst nur hinten.

    Gezählt werden Eingabe, Ausgabe und neu angelegter Cache. Cache-*Lesen*
    bleibt draußen — das ist um Größenordnungen mehr (hier 167 Mio gegen
    4,9 Mio) und würde die Anzeige unbrauchbar machen.
    """
    ende = chunk.rfind(b"\n")
    if ende == -1:
        return [], 0
    out: list[tuple[float, int]] = []
    for line in chunk[:ende].split(b"\n"):
        # Erst billig aussieben, dann erst der teure JSON-Parser.
        if b'"usage"' not in line or b'"type":"assistant"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        u = (d.get("message") or {}).get("usage")
        if not isinstance(u, dict):
            continue
        try:
            tok = (int(u.get("input_tokens") or 0)
                   + int(u.get("output_tokens") or 0)
                   + int(u.get("cache_creation_input_tokens") or 0))
        except (TypeError, ValueError):
            continue
        ts = _epoch(str(d.get("timestamp") or ""))
        if ts and tok:
            out.append((ts, tok))
    return out, ende + 1


@dataclass
class TokenWindow:
    """Das laufende Fünf-Stunden-Fenster über alle Sessions."""

    #: Beginn des Fensters (erste Nachricht darin).
    start: float = 0.0
    #: Zeitpunkt der Zurücksetzung (`start` + fünf Stunden).
    reset: float = 0.0
    tokens: int = 0
    msgs: int = 0
    #: False, wenn gerade kein Fenster läuft (länger als fünf Stunden Ruhe).
    active: bool = False

    @property
    def elapsed(self) -> float:
        """Anteil des verbrauchten Fensters, 0.0 bis 1.0."""
        if not self.active:
            return 0.0
        return min(1.0, max(0.0, (time.time() - self.start) / WINDOW_SECONDS))

    @property
    def remaining(self) -> float:
        """Sekunden bis zur Zurücksetzung (nie negativ)."""
        return max(0.0, self.reset - time.time()) if self.active else 0.0


def token_window(events: list[tuple[float, int]],
                 now: Optional[float] = None) -> TokenWindow:
    """Aus allen Nutzungsereignissen das gerade laufende Fenster bestimmen.

    Ein Fenster beginnt mit einer Nachricht und endet fünf Stunden später;
    die erste Nachricht danach eröffnet das nächste. Deshalb wird die Kette
    von vorne durchlaufen — der letzte so gefundene Beginn ist der aktuelle.
    """
    now = now if now is not None else time.time()
    start: Optional[float] = None
    for ts, _ in sorted(events):
        if start is None or ts >= start + WINDOW_SECONDS:
            start = ts
    if start is None:
        return TokenWindow()
    reset = start + WINDOW_SECONDS
    if now >= reset:
        # Fenster ist abgelaufen, ein neues beginnt erst mit der nächsten
        # Nachricht. Zeitpunkte trotzdem mitgeben, die Anzeige blendet ab.
        return TokenWindow(start=start, reset=reset, active=False)
    drin = [(ts, tok) for ts, tok in events if start <= ts < reset]
    return TokenWindow(start=start, reset=reset,
                       tokens=sum(tok for _, tok in drin),
                       msgs=len(drin), active=True)


@dataclass
class PlanUsage:
    """Die echten Kontingentwerte, so wie `/usage` sie zeigt."""

    #: Auslastung des Fünf-Stunden-Fensters in Prozent, oder None.
    five_pct: Optional[float] = None
    five_reset: float = 0.0
    #: Auslastung des Sieben-Tage-Fensters in Prozent, oder None.
    week_pct: Optional[float] = None
    week_reset: float = 0.0
    #: Wann das Statusleisten-Skript die Werte zuletzt hinterlegt hat.
    written_at: float = 0.0

    @property
    def ok(self) -> bool:
        return self.five_pct is not None or self.week_pct is not None

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.written_at) if self.written_at else 0.0

    @property
    def stale(self) -> bool:
        return self.ok and self.age > PLAN_USAGE_STALE

    @property
    def expired(self) -> bool:
        """Ist der hinterlegte Wert durch die Zurücksetzung überholt?

        Die Werte kommen nur herein, solange eine Sitzung läuft. Passiert der
        Reset-Zeitpunkt ohne offene Sitzung, beschreibt der gespeicherte
        Prozentsatz ein Fenster, das es nicht mehr gibt. Wie hoch der neue
        Stand ist, weiß hier niemand — die Anzeige darf dann keine Zahl mehr
        behaupten.
        """
        return bool(self.five_reset) and time.time() >= self.five_reset


def plan_usage(path: Path = PLAN_USAGE_FILE) -> PlanUsage:
    """Die von `tools/statusline.py` hinterlegten Limitwerte lesen.

    Fehlt die Datei, war seit dem Einrichten noch keine Sitzung offen (oder
    das Abo liefert keine `rate_limits`). Dann bleibt alles None und die
    Anzeige sagt das auch — lieber keine Zahl als eine erfundene.
    """
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return PlanUsage()
    if not isinstance(d, dict):
        return PlanUsage()
    limits = d.get("rate_limits")
    limits = limits if isinstance(limits, dict) else {}

    def teil(name: str) -> tuple[Optional[float], float]:
        block = limits.get(name)
        if not isinstance(block, dict):
            return None, 0.0
        try:
            pct = float(block["used_percentage"])
        except (KeyError, TypeError, ValueError):
            pct = None
        try:
            reset = float(block.get("resets_at") or 0)
        except (TypeError, ValueError):
            reset = 0.0
        return pct, reset

    fuenf, fuenf_reset = teil("five_hour")
    woche, woche_reset = teil("seven_day")
    try:
        geschrieben = float(d.get("written_at") or 0)
    except (TypeError, ValueError):
        geschrieben = 0.0
    return PlanUsage(five_pct=fuenf, five_reset=fuenf_reset,
                     week_pct=woche, week_reset=woche_reset,
                     written_at=geschrieben)


def _lesen(path: Path, ab: int) -> Optional[bytes]:
    """Die Datei ab Byte `ab` lesen; None, wenn sie nicht lesbar ist.

    JSONL wächst ausschliesslich hinten. Ist der Anfang schon ausgewertet,
    braucht ihn niemand mehr — ein `seek` spart bei der grössten Sitzung
    hier 78 MB Lesen und Zuteilen pro Aktualisierung.
    """
    try:
        with path.open("rb") as fh:
            if ab:
                fh.seek(ab)
            return fh.read()
    except OSError:
        return None


@dataclass
class _Entry:
    """Was der Scanner sich zu einer Transkriptdatei merkt."""

    mtime: float
    size: int
    info: dict[str, Any]
    #: Bis hierhin sind die Nutzungsdaten ausgewertet (Byte-Offset).
    scanned: int = 0
    #: [(Zeit, Tokens)] der jüngeren Vergangenheit, für die Fensterrechnung.
    events: list[tuple[float, int]] = field(default_factory=list)
    #: Tokens der gesamten Session — wird durch das Ausdünnen nicht kleiner.
    tokens: int = 0


class Scanner:
    """Liest Session-Dateien und cacht die Ergebnisse je (mtime, size).

    Damit kostet ein Refresh nur für tatsächlich veränderte Dateien einen
    vollen Dateiscan — wichtig, weil die Übersicht alle paar Sekunden neu lädt.

    Die Nutzungsdaten werden zusätzlich **fortgeschrieben**: JSONL wächst nur
    hinten, also geht bei einer gewachsenen Datei nur der neue Teil durch den
    JSON-Parser. Ohne das würde die aktive Session bei jedem Takt komplett neu
    geparst — bei zweistelligen Megabyte pro Datei ist das der Unterschied
    zwischen unmerklich und spürbar.
    """

    def __init__(self, root: Path = PROJECTS_DIR):
        self.root = root
        self._cache: dict[str, _Entry] = {}

    def collect(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        cutoff = time.time() - USAGE_KEEP_SECONDS

        # Sub-Agenten zuerst: sie liegen unter <projekt>/<session-id>/subagents/
        # und bekommen bewusst **keine** eigene Zeile — es sind Helfer eines
        # Laufs, keine Sessions. Ihre Tokens gehören aber zur aufrufenden
        # Session; ohne sie fehlt ein gutes Viertel (gemessen: 2,07 von
        # 8,13 Mio in einem Fünf-Stunden-Fenster).
        # `**` deckt beide Formen ab: direkt unter subagents/ und die tiefer
        # liegenden Workflow-Läufe (subagents/workflows/wf_<id>/…).
        von_agenten: dict[str, int] = {}
        for path in self.root.glob("*/*/subagents/**/*.jsonl"):
            teile = path.parts
            try:
                # Die Session-ID steht immer direkt vor 'subagents'.
                sid = teile[teile.index("subagents") - 1]
            except (ValueError, IndexError):
                continue
            entry = self._entry(path, seen, cutoff)
            if entry is None:
                continue
            von_agenten[sid] = von_agenten.get(sid, 0) + entry.tokens

        for path in self.root.glob("*/*.jsonl"):
            entry = self._entry(path, seen, cutoff)
            if entry is None:
                continue
            st_mtime, st_size = entry.mtime, entry.size
            out.append({
                "id": path.stem,
                "path": str(path),
                "mtime": st_mtime,
                "size": st_size,
                "tokens": entry.tokens + von_agenten.get(path.stem, 0),
                **entry.info,
            })
        # Verschwundene Dateien aus dem Cache räumen.
        for gone in set(self._cache) - seen:
            del self._cache[gone]
        return out

    def _entry(self, path: Path, seen: set[str],
               cutoff: float) -> Optional[_Entry]:
        """Zwischenstand zu einer Datei holen, bei Bedarf fortschreiben."""
        p = str(path)
        try:
            st = path.stat()
        except OSError:
            return None
        seen.add(p)
        entry = self._cache.get(p)
        if not (entry and entry.mtime == st.st_mtime
                and entry.size == st.st_size):
            # Der Anhang-Fall steht **vor** dem Lesen fest, sonst läse jede
            # Änderung die ganze Datei ein und schnitte erst danach das neue
            # Stück heraus — bei der grössten Sitzung hier 78 MB je Takt.
            angehaengt = (entry is not None
                          and st.st_size >= entry.size
                          and entry.scanned <= st.st_size)
            raw = _lesen(path, entry.scanned if angehaengt else 0)
            if raw is None:
                return None
            entry = self._update(entry, raw, st, angehaengt)
            self._cache[p] = entry
        # Alte Ereignisse fallen lassen; `tokens` bleibt die Gesamtsumme.
        if entry.events and entry.events[0][0] < cutoff:
            entry.events = [e for e in entry.events if e[0] >= cutoff]
        return entry

    def _update(self, entry: Optional[_Entry], raw: bytes,
                st: os.stat_result, angehaengt: bool) -> _Entry:
        """Eintrag neu aufbauen oder — wenn nur angehängt wurde — ergänzen.

        Im Anhang-Fall enthält `raw` **nur** den Teil ab `entry.scanned`,
        sonst die ganze Datei.
        """
        if angehaengt:
            neu, verbraucht = _usage_events(raw)
            entry.events.extend(neu)
            entry.tokens += sum(tok for _, tok in neu)
            entry.scanned += verbraucht
            # Auch Titel, Verzeichnis und Zahl nur aus dem neuen Stück
            # fortschreiben. Ein vollständiger Scan kostete bei der grössten
            # Transkriptdatei hier 53 ms je Aktualisierung und las dafür
            # 74,5 MB in den Speicher — bei 6 s Takt rund ein Prozent CPU
            # für eine einzige aktive Sitzung (gemessen am 2026-07-31).
            entry.info = _fortschreiben(entry.info, raw[:verbraucht])
        else:
            # Datei geschrumpft oder ersetzt: alles noch einmal lesen.
            events, verbraucht = _usage_events(raw)
            entry = _Entry(mtime=0.0, size=0, info={}, scanned=verbraucht,
                           events=events,
                           tokens=sum(tok for _, tok in events))
            entry.info = _scan_bytes(raw)
        entry.mtime = st.st_mtime
        entry.size = st.st_size
        return entry

    def usage_events(self) -> list[tuple[float, int]]:
        """Alle vorgehaltenen Nutzungsereignisse über sämtliche Sessions."""
        out: list[tuple[float, int]] = []
        for entry in self._cache.values():
            out.extend(entry.events)
        return out


# --------------------------------------------------------------------------
# Live-Prozesse über `claude agents --json --all`
# --------------------------------------------------------------------------

#: Vorlagen-Unit der dauerhaften Sessions, also der Sitzungen, die als
#: systemd-User-Dienst laufen. Eine Sitzung darunter hängt in einem
#: dtach-Socket statt in einem Terminalfenster. Gibt es solche Dienste auf
#: dem Rechner nicht, findet die Erkennung schlicht nichts.
DAUER_UNIT_PREFIX = "claude-session@"


def dauer_dienst(pid: Optional[int]) -> Optional[str]:
    """Name des Dauer-Dienstes, unter dem die PID läuft — sonst None.

    Solche Sitzungen haben **kein Fenster**: die Elternkette endet bei
    systemd (claude ← bash ← dtach ← runner ← systemd). „Zeigen" konnte dort
    also nie etwas finden und meldete nur „Kein Fenster zu PID … gefunden"
    (nachgemessen am 2026-07-31 an beiden Dauer-Diensten). Wer sie sehen
    will, hängt sich an ihren dtach-Socket.

    Die letzte Wegkomponente der cgroup-Zeile ist der Unit-Name, etwa
    ``claude-session@zsh-menu.service``. Gleiche Erkennung wie im Watchdog,
    damit beide dasselbe meinen.
    """
    if not pid:
        return None
    try:
        with open("/proc/%d/cgroup" % pid, "r", encoding="utf-8") as fh:
            roh = fh.read()
    except OSError:
        return None
    for zeile in roh.splitlines():
        name = zeile.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
        if name.startswith(DAUER_UNIT_PREFIX) and name.endswith(".service"):
            return name[len(DAUER_UNIT_PREFIX):-len(".service")]
    return None


def _ist_claude_programm(exe: str) -> bool:
    """Zeigt dieser Programmpfad auf Claude Code?

    Zwei Schreibweisen kommen vor: der native Build liegt unter
    ``…/share/claude/versions/<version>``, ältere Installationen haben eine
    Datei, die schlicht ``claude`` heißt.
    """
    return "/claude/versions/" in exe or os.path.basename(exe) == "claude"


def _pid_is_claude(pid: int) -> bool:
    """Steckt hinter dieser PID wirklich eine Claude-Code-Sitzung?

    Schützt vor allem `actions.terminate()`: zwischen Momentaufnahme und
    Klick kann die PID neu vergeben worden sein.

    **`comm` allein reicht nicht.** Es kommt aus ``argv[0]`` und lautet je
    nach Aufruf ``claude`` (über den Wrapper) oder ``2.1.220`` (nativer Build,
    direkt gestartet) — obwohl beide dieselbe Programmdatei benutzen.
    Sitzungen der zweiten Sorte galten dadurch als tot: sie fehlten unter
    „Laufend", und „Prozess beenden" verweigerte bei ihnen den Dienst
    (beobachtet am 2026-07-31 an zwei laufenden Sitzungen). Die Programmdatei
    ist eindeutig, deshalb hat sie Vorrang; `comm` bleibt als Rückfallebene,
    falls ``/proc/<pid>/exe`` nicht lesbar ist.
    """
    try:
        return _ist_claude_programm(os.readlink("/proc/%d/exe" % pid))
    except OSError:
        pass
    try:
        with open("/proc/%d/comm" % pid, "rb") as f:
            return f.read().strip() == b"claude"
    except OSError:
        return False


def live_agents() -> tuple[dict[str, dict[str, Any]], bool]:
    """sessionId -> Eintrag der laufenden Sessions laut CLI-Registry.

    Einträge, deren PID nicht mehr lebt oder kein claude-Prozess ist,
    werden verworfen — die Registry kann kurzzeitig nachhängen.
    """
    try:
        proc = subprocess.run(
            [str(CLAUDE_BIN), "agents", "--json", "--all"],
            capture_output=True, text=True, timeout=AGENTS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return {}, False
    if proc.returncode != 0:
        return {}, False
    try:
        entries = json.loads(proc.stdout or "[]")
    except ValueError:
        return {}, False
    out: dict[str, dict[str, Any]] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        sid, pid = e.get("sessionId"), e.get("pid")
        if not sid or not isinstance(pid, int) or not _pid_is_claude(pid):
            continue
        out[str(sid)] = e
    return out, True


# --------------------------------------------------------------------------
# Watchdog: state.db nur lesend, Daemon-Status über systemd
# --------------------------------------------------------------------------

def _retry_ueberfaellig(wert: Any, now: Optional[float] = None) -> bool:
    """Ist ein Wiederanlauf-Termin gesetzt und bereits verstrichen?

    Nur ein *gesetzter* Termin taugt als Beleg. Fehlt er, liefert die
    Funktion False — dann bleibt eine Fehlermeldung lieber stehen.
    """
    if wert is None:
        return False
    try:
        return float(wert) <= (now if now is not None else time.time())
    except (TypeError, ValueError):
        return False


def watchdog_tasks(db_path: Path = WATCHDOG_DB) -> tuple[list[dict[str, Any]], int, bool]:
    """Alle Tasks aus der Watchdog-Datenbank plus Neustarts der letzten Stunde."""
    if not db_path.exists():
        return [], 0, False
    db = None
    try:
        db = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=1.0)
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT id, title, cwd, session_id, mode, status, pid, attempts,"
            "       max_attempts, last_error_class, updated_at, next_retry_at"
            "  FROM tasks"
        ).fetchall()
        restarts = db.execute(
            "SELECT count(*) FROM restarts WHERE ts > ?", (time.time() - 3600,)
        ).fetchone()[0]
    except sqlite3.Error:
        return [], 0, False
    finally:
        if db is not None:
            db.close()
    return [dict(r) for r in rows], int(restarts), True


# --------------------------------------------------------------------------
# MCP-Server: nur die Konfigurationsdateien lesen
# --------------------------------------------------------------------------

def _mcp_entry(name: str, client: str, cfg: Any) -> Optional[McpServer]:
    """Einen Rohwert aus `mcpServers` in einen Eintrag übersetzen."""
    if not isinstance(cfg, dict):
        return None
    url = cfg.get("url")
    if url:
        return McpServer(name=name, client=client,
                         transport=str(cfg.get("type") or "http"),
                         detail=str(url))
    command = cfg.get("command")
    if not command:
        # Ohne `command` und ohne `url` ist der Eintrag unbrauchbar — genau
        # das verwirft auch die Desktop-App beim Laden.
        return None
    args = cfg.get("args")
    if isinstance(args, list):
        detail = " ".join([str(command)] + [str(a) for a in args])
    else:
        detail = str(command)
    return McpServer(name=name, client=client, transport="stdio", detail=detail)


def _mcp_from_file(path: Path, client: str) -> tuple[list[McpServer], bool]:
    """`mcpServers` aus einer JSON-Datei. Fehlt die Datei, ist das kein Fehler."""
    try:
        raw = json.loads(path.read_bytes())
    except FileNotFoundError:
        return [], True
    except (OSError, ValueError):
        return [], False
    servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers, dict):
        return [], True
    out = []
    for name, cfg in sorted(servers.items()):
        entry = _mcp_entry(str(name), client, cfg)
        if entry is not None:
            out.append(entry)
    return out, True


def mcp_servers(
    code_config: Path = MCP_CODE_CONFIG,
    desktop_config: Path = MCP_DESKTOP_CONFIG,
) -> tuple[list[McpServer], bool]:
    """Alle konfigurierten MCP-Server beider Clients.

    Bewusst nur ein Dateilesen statt `claude mcp list`: dessen Health-Check
    dauert mehrere Sekunden und würde den Refresh-Takt sprengen. Angezeigt
    wird deshalb, was konfiguriert ist — nicht, was gerade verbunden ist.
    """
    code, ok_code = _mcp_from_file(code_config, "Claude Code")
    desktop, ok_desktop = _mcp_from_file(desktop_config, "Claude Desktop")
    return code + desktop, ok_code and ok_desktop


def daemon_active() -> bool:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", "claude-watchdog"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.stdout.strip() == "active"


# --------------------------------------------------------------------------
# Zusammenführung
# --------------------------------------------------------------------------

def snapshot(
    scanner: Scanner,
    *,
    agents: Optional[dict[str, dict[str, Any]]] = None,
    agents_ok: bool = True,
    wd: Optional[tuple[list[dict[str, Any]], int, bool]] = None,
    mcp: Optional[tuple[list[McpServer], bool]] = None,
    with_daemon: bool = True,
) -> Snapshot:
    """Alles einsammeln und über die Session-ID zusammenführen.

    `agents`, `wd` und `mcp` sind für Tests injizierbar; ohne Angabe werden
    die echten Quellen befragt.
    """
    if agents is None:
        agents, agents_ok = live_agents()
    if wd is None:
        wd = watchdog_tasks()
    if mcp is None:
        mcp = mcp_servers()
    mcp_list, mcp_ok = mcp
    wd_rows, wd_restarts, wd_ok = wd

    infos: dict[str, SessionInfo] = {}
    for s in scanner.collect():
        infos[s["id"]] = SessionInfo(
            id=s["id"], title=s["title"], cwd=s["cwd"], msgs=s["msgs"],
            mtime=s["mtime"], size=s["size"], path=s["path"],
            tokens=s.get("tokens", 0), group=GROUP_STORED,
        )

    for sid, e in agents.items():
        started = float(e.get("startedAt") or 0) / 1000.0
        info = infos.get(sid)
        if info is None:
            # Läuft laut Registry, hat aber (noch) kein Transkript.
            info = SessionInfo(id=sid, cwd=str(e.get("cwd") or ""))
            infos[sid] = info
        info.live = True
        info.group = GROUP_LIVE
        info.live_status = str(e.get("status") or "") or None
        info.pid = e.get("pid")
        info.service = dauer_dienst(info.pid)
        info.started_at = started
        info.mtime = max(info.mtime, started)
        if not info.title:
            info.title = _tidy(e.get("name") or "")
        if not info.cwd:
            info.cwd = str(e.get("cwd") or "")

    for t in wd_rows:
        status = str(t.get("status") or "")
        sid = t.get("session_id")
        info = infos.get(sid) if sid else None
        if info is None:
            # Task ohne (bekannte) Session: nur zeigen, solange er aktiv ist.
            if status in ("done", "failed"):
                continue
            info = SessionInfo(
                id="wd:%s" % t["id"],
                title=_tidy(t.get("title") or ""),
                cwd=str(t.get("cwd") or ""),
                mtime=float(t.get("updated_at") or 0),
                group=GROUP_QUEUE,
            )
            infos[info.id] = info
        info.wd_task_id = str(t["id"])
        info.wd_mode = str(t.get("mode") or "") or None
        info.wd_status = status or None
        info.wd_attempts = int(t.get("attempts") or 0)
        info.wd_max_attempts = int(t.get("max_attempts") or 0)
        info.wd_error = t.get("last_error_class") or None
        if info.wd_error == "NONE" or status == "done":
            # 'NONE' ist der Enum-Leerwert; bei 'done' ist last_error_class
            # ein historischer, ueberwundener Zwischenstand — kein aktueller
            # Fehler, also keine Warn-Pille dafuer.
            info.wd_error = None
        elif status == "running" and _retry_ueberfaellig(t.get("next_retry_at")):
            # Ein gesetzter, aber laengst verstrichener Wiederanlauf-Termin bei
            # laufender Session heisst: der Fehler wurde ueberwunden. Ohne diese
            # Regel klebt ein RATE_LIMIT von 00:08 noch Stunden spaeter als
            # Warnung an einer Zeile, die nachweislich Fortschritt macht
            # (beobachtet am 2026-07-31). Ist kein Termin gesetzt, bleibt die
            # Warnung bewusst stehen — dann fehlt die Evidenz.
            info.wd_error = None

    sessions = sorted(infos.values(), key=lambda i: i.sort_key)
    snap = Snapshot(
        sessions=sessions,
        n_live=sum(1 for i in sessions if i.group == GROUP_LIVE),
        n_busy=sum(1 for i in sessions if i.live_status == "busy"),
        n_stored=sum(1 for i in sessions if i.group == GROUP_STORED),
        n_queue=sum(1 for i in sessions if i.group == GROUP_QUEUE),
        agents_ok=agents_ok,
        wd_ok=wd_ok,
        daemon_active=daemon_active() if with_daemon else False,
        wd_restarts=wd_restarts,
        mcp=mcp_list,
        mcp_ok=mcp_ok,
        taken_at=time.time(),
        window=token_window(scanner.usage_events()),
        plan=plan_usage(),
    )
    return snap


# --------------------------------------------------------------------------
# Anzeige-Helfer
# --------------------------------------------------------------------------

def gruss(stunde: int, name: str | None = None) -> str:
    """Begrüßung wie in der Claude-Desktop-App: „Guten Abend, Adam".

    Der Wortlaut kommt aus `texte`: auf Deutsch „Guten Abend, Adam", auf
    Englisch „Good evening, Adam". Woher der Name stammt, steht in
    `gruss_name()`.
    """
    if 5 <= stunde < 11:
        gruesse = texte.t("gruss.morgen")
    elif 11 <= stunde < 18:
        gruesse = texte.t("gruss.tag")
    else:
        gruesse = texte.t("gruss.abend")
    if not name:
        return gruesse
    return texte.t("gruss.mit_name", gruss=gruesse, name=name)


def gruss_name() -> str | None:
    """Name für die Begrüßung, sonst `None`.

    Die Kette liegt in `einstellungen.greet_name()`: Einstellungsdatei →
    `CS_GREET_NAME` → leer. Hier wird der leere Fall nur noch in `None`
    übersetzt, weil `gruss()` das seit jeher so erwartet.
    """
    return einstellungen.greet_name() or None


def rel_time(ts: float, now: Optional[float] = None) -> str:
    """Relative Zeitangabe wie in `-claude --code`."""
    if ts <= 0:
        return texte.t("zeit.unbekannt")
    now = time.time() if now is None else now
    d = max(0.0, now - ts)
    if d < 90:
        return texte.t("zeit.gerade")
    if d < 3600:
        return texte.t("zeit.minuten", n=int(d / 60))
    if d < 86400:
        return texte.t("zeit.stunden", n=int(d / 3600))
    days = d / 86400
    if days < 2:
        return texte.t("zeit.gestern")
    if days < 14:
        return texte.t("zeit.tage", n=int(days))
    return texte.t("zeit.wochen", n=int(days / 7))


def fmt_tokens(n: int) -> str:
    """Tokenzahl kurz: '4,90 Mio' / '812 Tsd' auf Deutsch, '4.90M' / '812K'
    auf Englisch. Auch das Dezimaltrennzeichen kommt aus der Sprachtabelle.
    """
    if n >= 1_000_000:
        wert = ("%.2f" % (n / 1_000_000)).replace(
            ".", texte.t("zahl.dezimaltrenner"))
        return texte.t("token.mio", wert=wert)
    if n >= 1_000:
        return texte.t("token.tsd", wert=round(n / 1000))
    return str(n)


def fmt_span(seconds: float) -> str:
    """Zeitspanne als '2 h 03 min' bzw. '47 min'."""
    seconds = max(0.0, seconds)
    stunden, rest = divmod(int(seconds), 3600)
    minuten = rest // 60
    if stunden:
        return texte.t("spanne.stunden", h=stunden, m=minuten)
    return texte.t("spanne.minuten", m=minuten)


def usage_tooltip(p: "PlanUsage", w: "TokenWindow") -> str:
    """Herkunft jeder Zahl der Kopfzeile im Klartext.

    Bewusst hier und nicht in `app.py`: reine Textformatierung, damit die
    Tests ohne GTK auskommen (Projektregel).
    """
    zeilen = []
    if p.ok:
        zeilen.append(texte.t("tooltip.prozente"))
        if p.written_at:
            zeilen.append(texte.t(
                "tooltip.stand",
                zeit=time.strftime("%H:%M:%S", time.localtime(p.written_at)),
                rel=rel_time(p.written_at)))
        if p.expired:
            zeilen.append(texte.t("tooltip.ueberholt"))
    else:
        zeilen.append(texte.t("tooltip.keine_werte"))
    if w.tokens:
        zeilen.append(texte.t("tooltip.tokens"))
    return "\n\n".join(zeilen)


def short_path(cwd: str) -> str:
    home = str(HOME)
    if not cwd:
        return "?"
    if cwd == home:
        return "~"
    if cwd.startswith(home + "/"):
        return "~" + cwd[len(home):]
    return cwd
