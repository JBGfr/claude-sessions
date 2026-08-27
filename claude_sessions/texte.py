"""Sprachschicht — alle nutzersichtbaren Wörter der Übersicht an einem Ort.

**Englisch ist die Grundsprache.** `TEXTE` hält den englischen Wortlaut zu
jedem Schlüssel, `UEBERSETZUNGEN["de"]` den deutschen. Fehlt ein Schlüssel in
der Übersetzung, wird der englische genommen; fehlt er überall, kommt der
Schlüssel selbst zurück — dann sieht man den Fehler im Fenster statt einer
leeren Zeile.

Aufruf: `texte.t("knopf.oeffnen")`, mit Einsetzungen
`texte.t("karte.nachrichten", n=12)`. Platzhalter sind benannt und im
`str.format`-Stil geschrieben (`{n}`), damit sie in beiden Sprachen die
Reihenfolge wechseln dürfen.

Die aktive Sprache kommt aus den Einstellungen (`language`); "auto" entscheidet
anhand von `$LC_ALL`/`$LC_MESSAGES`/`$LANG` (`de…` → Deutsch, sonst Englisch).
Sie wird beim ersten Zugriff einmal bestimmt und gemerkt — `set_sprache()`
schaltet zur Laufzeit (Einstellungsdialog) und im Test um.

Das Modul ist GTK-frei und damit ohne Anzeige testbar (Projektregel).
"""
from __future__ import annotations

import os
from typing import Any, Optional

from . import einstellungen

#: Sprachen, für die es eine Tabelle gibt. Englisch ist die Grundsprache und
#: steht deshalb nicht in `UEBERSETZUNGEN`.
SPRACHEN = ("en", "de")


# --------------------------------------------------------------------------
# Grundsprache: Englisch
# --------------------------------------------------------------------------

TEXTE: dict[str, str] = {
    # -- Gruppen der Liste (data.GROUP_LABELS) ----------------------------
    "gruppe.laufend": "Running",
    "gruppe.warteschlange": "Watchdog queue",
    "gruppe.zuletzt": "Recently active",

    # -- Watchdog-Status (data.WD_STATUS_DE) ------------------------------
    "wd.status.pending": "waiting to start",
    "wd.status.running": "running",
    "wd.status.stalled": "stalled",
    "wd.status.blocked": "input needed",
    "wd.status.waiting_for_limit": "waiting for limit",
    "wd.status.done": "done",
    "wd.status.failed": "failed",
    "wd.status.paused": "paused",

    # -- Watchdog-Modus (data.WD_MODE_DE) ---------------------------------
    "wd.modus.managed": "managed",
    "wd.modus.observed": "observed",

    # -- Begrüßung (data.gruss) -------------------------------------------
    "gruss.morgen": "Good morning",
    "gruss.tag": "Good afternoon",
    "gruss.abend": "Good evening",
    "gruss.mit_name": "{gruss}, {name}",

    # -- Zeitangaben (data.rel_time) --------------------------------------
    "zeit.unbekannt": "—",
    "zeit.gerade": "just now",
    "zeit.minuten": "{n} min ago",
    "zeit.stunden": "{n} h ago",
    "zeit.gestern": "yesterday",
    "zeit.tage": "{n} days ago",
    "zeit.wochen": "{n} weeks ago",

    # -- Zeitspannen (data.fmt_span) --------------------------------------
    "spanne.stunden": "{h} h {m:02d} min",
    "spanne.minuten": "{m} min",

    # -- Tokenzahlen (data.fmt_tokens) ------------------------------------
    #: Dezimaltrennzeichen der Sprache — „4.90M" gegen „4,90 Mio".
    "zahl.dezimaltrenner": ".",
    "token.mio": "{wert}M",
    "token.tsd": "{wert}K",

    # -- Wochentage (app._wochentag; bewusst nicht über die Locale) -------
    "wochentag.0": "Mon",
    "wochentag.1": "Tue",
    "wochentag.2": "Wed",
    "wochentag.3": "Thu",
    "wochentag.4": "Fri",
    "wochentag.5": "Sat",
    "wochentag.6": "Sun",
    "wochentag.zeit": "{tag}, {uhrzeit}",

    # -- Tooltip des Kontingentblocks (data.usage_tooltip) ----------------
    "tooltip.prozente": ("Percentages: rate_limits from the status-line "
                         "script —\nthe same source /usage draws from."),
    "tooltip.stand": "As of: {zeit} ({rel})",
    "tooltip.ueberholt": ("Since the reset the value is out of date;\n"
                          "the new one arrives with the next session."),
    "tooltip.keine_werte": ("No limit values yet. They appear as soon as a\n"
                            "Claude Code session has run (Pro/Max only)."),
    "tooltip.tokens": ("Tokens: summed from the transcripts (input + output +\n"
                       "new cache, without cache reads). This is NOT the "
                       "quota —\nthe desktop app, the browser and other "
                       "devices draw on it\nwithout leaving a line here."),

    # -- Seitenleiste: Ansichten und Abschnitte ---------------------------
    "nav.live": "Running",
    "nav.queue": "Watchdog",
    "nav.stored": "Recently active",
    "nav.all": "All",
    "nav.abschnitt.sitzungen": "Sessions",
    "nav.abschnitt.watchdog": "Watchdog",

    # -- Kopfzeile der Inhaltsspalte --------------------------------------
    "kopf.laedt": "loading …",
    "kopf.arbeiten": "{n} working",
    "kopf.bereit": "{n} ready",
    "kopf.kein_livestatus": "live status unavailable",
    "kopf.gespeichert": "{n} stored",

    # -- Abschnittsüberschriften der Liste --------------------------------
    "liste.kopf": "{label} ({n})",
    "liste.kopf_teilmenge": "{label} ({gezeigt} of {gesamt})",

    # -- Karte einer Session ----------------------------------------------
    "karte.nachrichten": "{n} messages",
    "karte.tokens": "{wert} tokens",
    "karte.pid": "PID {pid}",
    "karte.watchdog": "Watchdog {modus} · {status}",
    "karte.watchdog_fehler": " · {fehler}",
    "karte.unbekannt": "?",

    # -- Zustands-Pillen ---------------------------------------------------
    "pill.arbeitet": "working",
    "pill.bereit": "ready",

    # -- Knöpfe ------------------------------------------------------------
    "knopf.oeffnen": "Open",
    "knopf.anhaengen": "Attach",
    "knopf.zeigen": "Show",
    "knopf.aktualisieren_tooltip": "Refresh now",
    "knopf.einstellungen_tooltip": "Settings",
    "knopf.live_log": "Live log",
    "knopf.live_log_tooltip": ("journalctl of the persistent services + event "
                               "log in one terminal window"),
    "knopf.daemon_unbekannt": "Daemon …",
    "knopf.daemon_starten": "Start daemon",
    "knopf.daemon_stoppen": "Stop daemon",

    # -- Kontextmenü der Karte ---------------------------------------------
    "menu.wd_beobachten": "Watch with the watchdog",
    "menu.wd_fortsetzen": "Resume watchdog",
    "menu.wd_pausieren": "Pause watchdog",
    "menu.wd_logs": "Show watchdog logs",
    "menu.wd_entfernen_nachfrage": "Remove from the watchdog …",
    "menu.wd_entfernen": "Remove from the watchdog",
    "menu.ordner_oeffnen": "Open project folder",
    "menu.id_kopieren": "Copy session ID",
    "menu.dienst_stoppen": "Stop service …",
    "menu.prozess_beenden": "Terminate process …",

    # -- Kontingentblock ---------------------------------------------------
    "nutzung.sitzung": "Current session",
    "nutzung.woche": "Weekly limits",
    "nutzung.prozent": "{pct} % used",
    "nutzung.leer": "—",
    "nutzung.keine_werte": "no limit values yet",
    "nutzung.zurueckgesetzt": ("Reset at {zeit} — new figures with the next "
                               "session"),
    "nutzung.reset_in": "Resets in {spanne}",
    "nutzung.fenster": "Five-hour window",
    "nutzung.reset_am": "Resets {zeitpunkt}",
    "nutzung.tokens_lokal": "{wert} tokens locally",
    "nutzung.stand": "as of {rel}",

    # -- Platzhalter der leeren Liste --------------------------------------
    "platzhalter.laedt": "loading …",
    "platzhalter.keine_laufenden": "No running sessions",
    "platzhalter.warteschlange_leer": "Nothing in the watchdog queue",
    "platzhalter.keine": "No sessions found",
    "platzhalter.fehler": "Sessions could not be loaded",

    # -- Fußzeile / Watchdog-Block -----------------------------------------
    "fuss.daemon_aktiv": "● Watchdog daemon active",
    "fuss.daemon_inaktiv": "○ Watchdog daemon inactive",
    "fuss.neustarts": " · {n} restarts/1h",
    "fuss.db_unlesbar": " · state.db not readable",
    "fuss.mcp_unlesbar": "· MCP config unreadable",
    "fuss.mcp_keine": "· no MCP servers",
    "fuss.mcp": "· MCP {n}: {namen}",
    "fuss.mcp_hinweis": "Configured according to file — no connection test.",

    # -- Meldungen der Statuszeile (app.flash) -----------------------------
    "meldung.angehaengt": "Attaching to „{dienst}“ — detach with Ctrl+\\",
    "meldung.kein_terminal": "Terminal could not be opened",
    "meldung.kein_fenster": "No window found for PID {pid}",
    "meldung.oeffnet": "Opening session …",
    "meldung.kein_opener": "claude-session-open not found",
    "meldung.kopiert": "Copied: {text}",
    "meldung.refresh_fehler": "Refresh failed — {fehler}",
    "meldung.daemon_gestartet": "Daemon started",
    "meldung.daemon_gestoppt": "Daemon stopped",
    "meldung.ok": "OK",
    "meldung.fehler": "Error",
    "meldung.live_log": "Live log opened",
    "meldung.kein_qterminal": "qterminal not found",
    "meldung.sigterm": "SIGTERM sent to PID {pid}",
    "meldung.kein_prozess": "Process {pid} not found",
    "meldung.dienst_gestoppt": "Service „{dienst}“ stopped",
    "meldung.stoppen_fehlgeschlagen": "Stopping failed",

    # -- Dialoge -----------------------------------------------------------
    "dialog.beenden_titel": "Terminate session?",
    "dialog.beenden_text": ("„{titel}“ (PID {pid}) receives SIGTERM and can "
                            "shut down cleanly."),
    "dialog.dienst_titel": "Stop persistent service „{dienst}“?",
    "dialog.dienst_text": (
        "The session runs under systemd and would come back ten seconds "
        "after a plain SIGTERM.\n\n"
        "“Stop” ends the service and takes it out of the autostart at the "
        "same time — after the next system start it is gone. Bring it back "
        "with:  claude-sessionctl start {dienst}"),
    "dialog.wd_entfernen_titel": "Task is still running — remove anyway?",
    "dialog.wd_entfernen_text": ("The Claude process keeps running; only the "
                                 "watchdog's supervision ends."),

    # -- Einstellungsdialog ------------------------------------------------
    "einst.titel": "Settings",
    "einst.sprache": "Language",
    "einst.sprache.auto": "Automatic (system)",
    "einst.sprache.en": "English",
    "einst.sprache.de": "Deutsch",
    "einst.name": "Name in the greeting",
    "einst.name_platzhalter": "e.g. Ada",
    "einst.begruessung": "Show greeting",
    "einst.takt": "Refresh every … seconds",
    "einst.zeilen": "Rows under “Recently active”",
    "einst.wd_notify": "Notify on watchdog events",
    "einst.wd_notify_max": "Notifications per hour (0 = unlimited)",
    "einst.speichern": "Save",
    "einst.abbrechen": "Cancel",
    "einst.uebernehmen": "Apply & restart",
    "einst.gespeichert": "Settings saved",
    "einst.nicht_gespeichert": "Settings could not be saved",
    "einst.gruppe.anzeige": "Display",
    "einst.gruppe.aktualisierung": "Refreshing",
    "einst.gruppe.popups": "Pop-ups",
    "einst.wd_hinweis": ("Applies to the watchdog daemon. It is restarted "
                         "with the new values — but never started if it is "
                         "stopped."),
    "einst.neustart_hinweis": ("Language, refresh interval and row count take "
                               "effect the next time the overview starts."),
    "einst.neustart_laeuft": "Settings saved — the overview is restarting …",
    "einst.neustart_fehlgeschlagen": ("Restart could not be triggered — please "
                                      "restart the overview yourself"),
    "einst.wd_neugestartet": "Watchdog restarted with the new pop-up settings",
    "einst.wd_fehler": "Watchdog could not be restarted — {fehler}",

    # -- Desktop-Eintrag (tools/install-desktop.sh) ------------------------
    # Beschriftung des Menue-Eintrags. Sie steht hier und nicht im
    # Installationsskript, damit auch dieser Text nur einen Ort hat; das
    # Skript holt beide Sprachen ab und schreibt sie als "GenericName"/
    # "GenericName[de]" in die .desktop-Datei.
    "desktop.gattung": "Session overview",
    "desktop.zweck": "Overview of all Claude Code sessions",
}


# --------------------------------------------------------------------------
# Übersetzungen
# --------------------------------------------------------------------------

UEBERSETZUNGEN: dict[str, dict[str, str]] = {
    "de": {
        "gruppe.laufend": "Laufend",
        "gruppe.warteschlange": "Watchdog-Warteschlange",
        "gruppe.zuletzt": "Zuletzt aktiv",

        "wd.status.pending": "wartet auf Start",
        "wd.status.running": "läuft",
        "wd.status.stalled": "hängt",
        "wd.status.blocked": "Eingabe nötig",
        "wd.status.waiting_for_limit": "wartet auf Limit",
        "wd.status.done": "fertig",
        "wd.status.failed": "gescheitert",
        "wd.status.paused": "pausiert",

        "wd.modus.managed": "verwaltet",
        "wd.modus.observed": "beobachtet",

        "gruss.morgen": "Guten Morgen",
        "gruss.tag": "Guten Tag",
        "gruss.abend": "Guten Abend",
        "gruss.mit_name": "{gruss}, {name}",

        "zeit.unbekannt": "—",
        "zeit.gerade": "gerade",
        "zeit.minuten": "vor {n} Min",
        "zeit.stunden": "vor {n} Std",
        "zeit.gestern": "gestern",
        "zeit.tage": "vor {n} Tagen",
        "zeit.wochen": "vor {n} Wochen",

        "spanne.stunden": "{h} h {m:02d} min",
        "spanne.minuten": "{m} min",

        "zahl.dezimaltrenner": ",",
        "token.mio": "{wert} Mio",
        "token.tsd": "{wert} Tsd",

        "wochentag.0": "Mo.",
        "wochentag.1": "Di.",
        "wochentag.2": "Mi.",
        "wochentag.3": "Do.",
        "wochentag.4": "Fr.",
        "wochentag.5": "Sa.",
        "wochentag.6": "So.",
        "wochentag.zeit": "{tag}, {uhrzeit}",

        "tooltip.prozente": ("Prozentwerte: rate_limits aus dem "
                             "Statusleisten-Skript —\ndieselbe Quelle, aus "
                             "der /usage schöpft."),
        "tooltip.stand": "Stand: {zeit} ({rel})",
        "tooltip.ueberholt": ("Seit der Zurücksetzung ist der Wert überholt;\n"
                              "der neue Stand kommt mit der nächsten Sitzung."),
        "tooltip.keine_werte": ("Noch keine Limitwerte. Sie erscheinen, sobald "
                                "eine\nClaude-Code-Sitzung gelaufen ist (nur "
                                "Pro/Max)."),
        "tooltip.tokens": ("Tokens: aus den Transkripten summiert (Eingabe + "
                           "Ausgabe +\nneuer Cache, ohne Cache-Lesen). Das ist "
                           "NICHT das Kontingent —\nDesktop-App, Browser und "
                           "andere Geräte belasten es mit, ohne\nhier eine "
                           "Zeile zu hinterlassen."),

        "nav.live": "Laufend",
        "nav.queue": "Watchdog",
        "nav.stored": "Zuletzt aktiv",
        "nav.all": "Alle",
        "nav.abschnitt.sitzungen": "Sitzungen",
        "nav.abschnitt.watchdog": "Watchdog",

        "kopf.laedt": "lade …",
        "kopf.arbeiten": "{n} arbeiten",
        "kopf.bereit": "{n} bereit",
        "kopf.kein_livestatus": "Live-Status nicht verfügbar",
        "kopf.gespeichert": "{n} gespeichert",

        "liste.kopf": "{label} ({n})",
        "liste.kopf_teilmenge": "{label} ({gezeigt} von {gesamt})",

        "karte.nachrichten": "{n} Nachrichten",
        "karte.tokens": "{wert} Tokens",
        "karte.pid": "PID {pid}",
        "karte.watchdog": "Watchdog {modus} · {status}",
        "karte.watchdog_fehler": " · {fehler}",
        "karte.unbekannt": "?",

        "pill.arbeitet": "arbeitet",
        "pill.bereit": "bereit",

        "knopf.oeffnen": "Öffnen",
        "knopf.anhaengen": "Anhängen",
        "knopf.zeigen": "Zeigen",
        "knopf.aktualisieren_tooltip": "Jetzt aktualisieren",
        "knopf.einstellungen_tooltip": "Einstellungen",
        "knopf.live_log": "Live-Log",
        "knopf.live_log_tooltip": ("journalctl der Dauer-Dienste + Ereignislog "
                                   "in einem Terminalfenster"),
        "knopf.daemon_unbekannt": "Daemon …",
        "knopf.daemon_starten": "Daemon starten",
        "knopf.daemon_stoppen": "Daemon stoppen",

        "menu.wd_beobachten": "Vom Watchdog beobachten",
        "menu.wd_fortsetzen": "Watchdog fortsetzen",
        "menu.wd_pausieren": "Watchdog pausieren",
        "menu.wd_logs": "Watchdog-Logs anzeigen",
        "menu.wd_entfernen_nachfrage": "Aus dem Watchdog entfernen …",
        "menu.wd_entfernen": "Aus dem Watchdog entfernen",
        "menu.ordner_oeffnen": "Projektordner öffnen",
        "menu.id_kopieren": "Session-ID kopieren",
        "menu.dienst_stoppen": "Dienst stoppen …",
        "menu.prozess_beenden": "Prozess beenden …",

        "nutzung.sitzung": "Aktuelle Sitzung",
        "nutzung.woche": "Wöchentliche Limits",
        "nutzung.prozent": "{pct} % verwendet",
        "nutzung.leer": "—",
        "nutzung.keine_werte": "noch keine Limitwerte",
        "nutzung.zurueckgesetzt": ("Zurückgesetzt um {zeit} — neuer Stand mit "
                                   "der nächsten Sitzung"),
        "nutzung.reset_in": "Zurücksetzung in {spanne}",
        "nutzung.fenster": "Fünf-Stunden-Fenster",
        "nutzung.reset_am": "Zurücksetzung {zeitpunkt}",
        "nutzung.tokens_lokal": "{wert} Tokens lokal",
        "nutzung.stand": "Stand {rel}",

        "platzhalter.laedt": "lade …",
        "platzhalter.keine_laufenden": "Keine laufenden Sessions",
        "platzhalter.warteschlange_leer": "Nichts in der Watchdog-Warteschlange",
        "platzhalter.keine": "Keine Sessions gefunden",
        "platzhalter.fehler": "Sessions konnten nicht geladen werden",

        "fuss.daemon_aktiv": "● Watchdog-Daemon aktiv",
        "fuss.daemon_inaktiv": "○ Watchdog-Daemon inaktiv",
        "fuss.neustarts": " · {n} Neustarts/1h",
        "fuss.db_unlesbar": " · state.db nicht lesbar",
        "fuss.mcp_unlesbar": "· MCP-Config unlesbar",
        "fuss.mcp_keine": "· keine MCP-Server",
        "fuss.mcp": "· MCP {n}: {namen}",
        "fuss.mcp_hinweis": "Konfiguriert laut Datei — kein Verbindungstest.",

        "meldung.angehaengt": "Hänge an „{dienst}“ an — lösen mit Strg+\\",
        "meldung.kein_terminal": "Terminal ließ sich nicht öffnen",
        "meldung.kein_fenster": "Kein Fenster zu PID {pid} gefunden",
        "meldung.oeffnet": "Session wird geöffnet …",
        "meldung.kein_opener": "claude-session-open nicht gefunden",
        "meldung.kopiert": "Kopiert: {text}",
        "meldung.refresh_fehler": "Aktualisierung fehlgeschlagen — {fehler}",
        "meldung.daemon_gestartet": "Daemon gestartet",
        "meldung.daemon_gestoppt": "Daemon gestoppt",
        "meldung.ok": "OK",
        "meldung.fehler": "Fehler",
        "meldung.live_log": "Live-Log geöffnet",
        "meldung.kein_qterminal": "qterminal nicht gefunden",
        "meldung.sigterm": "SIGTERM an PID {pid} geschickt",
        "meldung.kein_prozess": "Prozess {pid} nicht gefunden",
        "meldung.dienst_gestoppt": "Dienst „{dienst}“ gestoppt",
        "meldung.stoppen_fehlgeschlagen": "Stoppen fehlgeschlagen",

        "dialog.beenden_titel": "Session beenden?",
        "dialog.beenden_text": ("„{titel}“ (PID {pid}) bekommt SIGTERM und "
                                "kann sich sauber beenden."),
        "dialog.dienst_titel": "Dauer-Dienst „{dienst}“ stoppen?",
        "dialog.dienst_text": (
            "Die Sitzung läuft unter systemd und käme nach einem bloßen "
            "SIGTERM in zehn Sekunden wieder.\n\n"
            "„Stoppen“ beendet den Dienst und nimmt ihn zugleich aus dem "
            "Autostart — nach dem nächsten Systemstart ist er nicht mehr da. "
            "Zurückholen mit:  claude-sessionctl start {dienst}"),
        "dialog.wd_entfernen_titel": "Task läuft noch — trotzdem entfernen?",
        "dialog.wd_entfernen_text": ("Der Claude-Prozess läuft weiter; nur die "
                                     "Überwachung durch den Watchdog endet."),

        "einst.titel": "Einstellungen",
        "einst.sprache": "Sprache",
        "einst.sprache.auto": "Automatisch (System)",
        "einst.sprache.en": "English",
        "einst.sprache.de": "Deutsch",
        "einst.name": "Name in der Begrüßung",
        "einst.name_platzhalter": "z. B. Ada",
        "einst.begruessung": "Begrüßung anzeigen",
        "einst.takt": "Alle … Sekunden aktualisieren",
        "einst.zeilen": "Zeilen unter „Zuletzt aktiv“",
        "einst.wd_notify": "Bei Watchdog-Ereignissen benachrichtigen",
        "einst.wd_notify_max": "Benachrichtigungen je Stunde (0 = unbegrenzt)",
        "einst.speichern": "Speichern",
        "einst.abbrechen": "Abbrechen",
        "einst.uebernehmen": "Übernehmen & neu starten",
        "einst.gespeichert": "Einstellungen gespeichert",
        "einst.nicht_gespeichert": "Einstellungen konnten nicht gespeichert werden",
        "einst.gruppe.anzeige": "Anzeige",
        "einst.gruppe.aktualisierung": "Aktualisierung",
        "einst.gruppe.popups": "Pop-ups",
        "einst.wd_hinweis": ("Gilt für den Watchdog-Daemon. Er wird mit den "
                             "neuen Werten neu gestartet — aber nie "
                             "gestartet, wenn er gerade steht."),
        "einst.neustart_hinweis": ("Sprache, Takt und Zeilenzahl greifen erst "
                                   "beim nächsten Start der Übersicht."),
        "einst.neustart_laeuft": ("Einstellungen gespeichert — die Übersicht "
                                  "startet neu …"),
        "einst.neustart_fehlgeschlagen": ("Neustart ließ sich nicht auslösen — "
                                          "bitte die Übersicht selbst neu "
                                          "starten"),
        "einst.wd_neugestartet": ("Watchdog mit den neuen Pop-up-Einstellungen "
                                  "neu gestartet"),
        "einst.wd_fehler": "Watchdog ließ sich nicht neu starten — {fehler}",

        "desktop.gattung": "Session-Übersicht",
        "desktop.zweck": "Übersicht über alle Claude-Code-Sessions",
    },
}


# --------------------------------------------------------------------------
# Aktive Sprache
# --------------------------------------------------------------------------

#: Einmal bestimmte Sprache. `None` heißt „noch nicht nachgesehen" — der
#: nächste Zugriff liest dann die Einstellungen. Absichtlich gemerkt: `t()`
#: läuft pro Aktualisierung dutzendfach, und dabei jedes Mal eine Datei zu
#: öffnen wäre Unfug.
_sprache: Optional[str] = None


def _aus_der_umgebung() -> str:
    """Sprache der Sitzung: `de…` → Deutsch, alles andere → Englisch.

    Reihenfolge wie in POSIX: `LC_ALL` schlägt `LC_MESSAGES`, das schlägt
    `LANG`. Ist nichts gesetzt (oder steht dort `C`/`POSIX`), bleibt es bei
    der Grundsprache Englisch.
    """
    for name in ("LC_ALL", "LC_MESSAGES", "LANG"):
        wert = os.environ.get(name, "").strip()
        if wert:
            return "de" if wert.lower().startswith("de") else "en"
    return "en"


def _bestimmen() -> str:
    """Sprache aus den Einstellungen ableiten, „auto" über die Umgebung."""
    try:
        gewaehlt = einstellungen.sprache()
    except OSError:  # unerreichbare Einstellungsdatei darf nichts kosten
        gewaehlt = "auto"
    if gewaehlt in SPRACHEN:
        return gewaehlt
    return _aus_der_umgebung()


def sprache() -> str:
    """Die gerade aktive Sprache („en" oder „de")."""
    global _sprache
    if _sprache is None:
        _sprache = _bestimmen()
    return _sprache


def set_sprache(code: Optional[str]) -> str:
    """Sprache umschalten und die neue zurückgeben.

    * `"en"`/`"de"` setzen sie direkt (Test, Einstellungsdialog),
    * `"auto"` bestimmt sie erneut aus `$LC_ALL`/`$LC_MESSAGES`/`$LANG`,
    * `None` vergisst die Merkung: der nächste Zugriff liest wieder die
      Einstellungsdatei (so kehrt man im Test zum Ausgangszustand zurück).
    """
    global _sprache
    if code is None:
        _sprache = None
        return _bestimmen()
    code = str(code).strip().lower()
    if code in SPRACHEN:
        _sprache = code
    elif code == "auto":
        _sprache = _aus_der_umgebung()
    else:
        _sprache = _bestimmen()
    return _sprache


def tabelle(code: Optional[str] = None) -> dict[str, str]:
    """Die Texttabelle einer Sprache (ohne Rückfall auf Englisch)."""
    code = sprache() if code is None else code
    return TEXTE if code == "en" else UEBERSETZUNGEN.get(code, {})


# --------------------------------------------------------------------------
# Nachschlagen
# --------------------------------------------------------------------------

def text(schluessel: str, code: Optional[str] = None) -> str:
    """Rohtext ohne Einsetzungen: Sprache, sonst Englisch, sonst Schlüssel."""
    code = sprache() if code is None else code
    if code != "en":
        gefunden = UEBERSETZUNGEN.get(code, {}).get(schluessel)
        if gefunden is not None:
            return gefunden
    return TEXTE.get(schluessel, schluessel)


def t(schluessel: str, **einsetzungen: Any) -> str:
    """Übersetzten Text holen und die Platzhalter füllen.

    Passt eine Einsetzung nicht zum Text (falscher Name, falscher Typ), kommt
    der unausgefüllte Text zurück statt einer Ausnahme: eine krumme Zeile in
    der Anzeige ist ärgerlich, ein Absturz mitten im Aufbau des Fensters ist
    schlimmer.
    """
    roh = text(schluessel)
    if not einsetzungen:
        return roh
    try:
        return roh.format(**einsetzungen)
    except (KeyError, IndexError, ValueError, TypeError):
        return roh
