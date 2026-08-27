# Claude Sessions

> English version: [README.md](README.md)

Kleine dunkle GTK3-Desktop-App: eine Übersicht über alle Claude-Code-Sessions
des eigenen Rechners — laufende, gespeicherte und die Warteschlange des
[Claude Watchdog](https://github.com/JBGfr/claude-watchdog). Sie liest
ausschliesslich lokale Dateien und die Claude-Code-CLI und öffnet keine
Netzverbindung. Als App-Icon dient das Block-Art-Maskottchen aus dem
Claude-Code-Terminal-Header, pixelgenau dekodiert (`tools/make_icons.py`).

## Was sie zeigt

| Abschnitt | Quelle | Inhalt |
|---|---|---|
| **Laufend** | `claude agents --json --all` | Titel, Projekt, PID, Status (arbeitet/bereit) |
| **Watchdog-Warteschlange** | `state.db` des Watchdogs (nur lesend) | managed-Tasks ohne gestartete Session |
| **Zuletzt aktiv** | `~/.claude/projects/*/*.jsonl` | die letzten 40 gespeicherten Sessions |

Sessions, die der Watchdog kennt, tragen eine Pill mit Modus und Status
(z. B. „Watchdog beobachtet · hängt"). Die Fußzeile zeigt den Zustand des
Watchdog-Daemons und kann ihn per Knopf starten/stoppen (systemd-User-Unit).

Daneben steht die MCP-Pille, z. B. „· MCP 3: github, playwright, filesystem".
Der Tooltip listet je Client Name, Transport und URL bzw. Startbefehl:

| Client | Quelle |
|---|---|
| **Claude Code** | `~/.claude.json` → `mcpServers` (User-Scope) |
| **Claude Desktop** | `~/.config/Claude/claude_desktop_config.json` → `mcpServers` |

Gelesen werden nur die Dateien, nicht `claude mcp list` — dessen Health-Check
braucht mehrere Sekunden und würde den Refresh-Takt sprengen. Die Pille sagt
deshalb „konfiguriert", **nicht** „verbunden". Zugangsdaten landen nie in der
Anzeige: Felder wie `headersHelper` oder `env` werden gar nicht erst gelesen.

## Kontingent-Anzeige

Über der Liste steht die Auslastung des Fünf-Stunden-Fensters — dieselben
Zahlen, die `/usage` in einer Sitzung anzeigt, samt Zurücksetzungszeit und
Wochenwert.

**Diese Zahlen kommen nicht aus den Transkripten.** Aus denen ist das
Kontingent grundsätzlich nicht herzuleiten: Claude Desktop, claude.ai im
Browser und andere Geräte belasten dasselbe Konto, ohne hier eine Zeile zu
hinterlassen. Ein Versuch, es zu rekonstruieren, lag beim Reset-Zeitpunkt
13 Minuten daneben.

Stattdessen liefert Claude Code die Werte selbst — an das Statusleisten-Skript,
unter `rate_limits`. `tools/statusline.py` schreibt sie nach
`~/.local/state/claude-sessions/usage.json`, die App liest von dort. Das läuft
rein lokal und kostet keine Tokens ([Doku][statusline]).

Einrichten in `~/.claude/settings.json` — der Pfad zeigt auf den eigenen Klon,
`~/Projekte` wird nirgends vorausgesetzt:

```json
"statusLine": {
  "type": "command",
  "command": "/pfad/zu/claude-sessions/tools/statusline.py",
  "padding": 0
}
```

Das Skript zeigt zusätzlich unten in jeder Sitzung Modell, Verzeichnis,
Git-Zweig sowie Limit, Reset und Kontextfüllung an. Es läuft in ~22 ms, ruft
keine Subprozesse auf (der Zweig kommt direkt aus `.git/HEAD`) und schluckt
jeden Fehler — eine Statusleiste darf niemals eine Sitzung stören.

Ohne die Datei zeigt die Kopfzeile „noch keine Limitwerte" statt einer
erfundenen Zahl. Dasselbe gilt, wenn der Reset-Zeitpunkt verstreicht, während
keine Sitzung offen ist: der gespeicherte Prozentsatz beschreibt dann ein
Fenster, das es nicht mehr gibt, und die Anzeige sagt „Fenster zurückgesetzt
um HH:MM" statt ihn weiter zu behaupten. `rate_limits` liefert Claude Code nur
für Pro-/Max-Abos und erst nach der ersten API-Antwort einer Sitzung. Die je
Zeile angezeigten Tokens stammen dagegen direkt aus dem jeweiligen Transkript
(Eingabe + Ausgabe + neu angelegter Cache, ohne Cache-Lesen) —
**einschliesslich der Sub-Agenten** dieser Session, die unter
`<projekt>/<session-id>/subagents/` liegen (auch verschachtelt unter
`workflows/wf_*/`). Eine eigene Zeile bekommen sie nicht: es sind Helfer eines
Laufs, keine Sessions.

[statusline]: https://code.claude.com/docs/en/statusline

## Voraussetzungen

- Linux mit X11-Sitzung. Das Fokussieren nutzt `wmctrl`, die systemd-Unit
  prüft mit `xdotool`, ob es überhaupt eine Anzeige gibt.
- Python 3 aus der Distribution. Entwickelt und geprüft mit 3.13 — das läuft
  auch in der CI; ältere Fassungen sind ungetestet.
- PyGObject und GTK 3 **aus den Distributionspaketen** (Debian/Ubuntu/Kali:
  `python3-gi`, `python3-gi-cairo`, `gir1.2-gtk-3.0`). Kein pip-Paket, kein
  venv, keine Fremdabhängigkeit: importiert werden stdlib und `gi`.
- `systemd --user` — aus der App geöffnete Fenster laufen in einer eigenen
  transienten Unit, die App selbst kann als User-Dienst laufen.
- Die Claude-Code-CLI. Gesucht wird zuerst `~/.local/bin/claude`, sonst
  entscheidet `PATH`.
- Ein Terminal-Emulator. `claude-session-open` nimmt den ersten, den es im
  `PATH` findet: `qterminal`, `x-terminal-emulator`, `xfce4-terminal`,
  `konsole`, `xterm`. Unter Debian/Ubuntu heißen die Pakete genauso — außer
  `x-terminal-emulator`, das ist der Alternatives-Verweis auf das jeweils
  installierte Terminal. Die Log-Fenster und **Anhängen** gehen ausdrücklich in
  `qterminal` auf.
- Optional `dtach` (Debian/Ubuntu: `apt install dtach`) für die Dauer-Sitzungen
  weiter unten. Ohne es läuft alles andere weiter; nur `claude-sessionctl`
  weigert sich, eine zu starten oder anzuhängen — und sagt auch, warum.
- Optional der [Claude Watchdog](https://github.com/JBGfr/claude-watchdog).
  Fehlt er, bleibt sein Abschnitt leer und die Fußzeile meldet den Daemon als
  inaktiv — das ist kein Fehler.

Zwei der Zeilen-Aktionen und die ganzen Dauer-Sitzungen erledigt nicht das
Fenster selbst, sondern Hilfsprogramme — und die liegen **in** diesem Repo,
siehe [Helfer](#helfer). Von außen wird nur noch `qterminal` beim Namen
vorausgesetzt. Fehlt ein Helfer oder dieses Terminal, meldet genau diese eine
Aktion einen Fehlschlag in der Statuszeile; die Übersicht arbeitet weiter.

## Helfer

Drei Kommandozeilenwerkzeuge in `bin/` erledigen, was ein Terminal oder einen
eigenen Dienst braucht. Es sind gewöhnliche Programme: sie laufen auch, ohne
dass die Übersicht je offen war, und sie geben ihre Meldungen selbst aus statt
über das Fenster. `install-desktop.sh` verlinkt alle drei nach `~/.local/bin`.

### `claude-session-open` — gespeicherte Sitzung wieder öffnen

```sh
claude-session-open 11111111
claude-session-open claude-session://11111111-2222-3333-4444-555555555555
```

Das steckt hinter **Öffnen** in einer gespeicherten Zeile: Das Werkzeug sucht
die Session unter `~/.claude/projects`, öffnet ein Terminalfenster und startet
darin `claude --resume`. Die ID darf abgekürzt werden, solange sie eindeutig
bleibt — die acht Zeichen, die die Übersicht anzeigt, reichen also. Die
URI-Form ist die, die ein Desktop-Handler durchreicht.

Das Arbeitsverzeichnis kommt aus dem Transkript, nicht aus dem
Verzeichnisnamen: Claude bildet den Namen, indem es jedes Zeichen des Pfades,
das kein Buchstabe und keine Ziffer ist, durch `-` ersetzt — das ist nicht
umkehrbar. Das ist keine Feinheit: `claude --resume` findet eine Session nur
aus dem Verzeichnis heraus, zu dem sie gehört. Gibt es das nicht mehr, sagt das
Werkzeug genau das, statt im Heimatverzeichnis zu starten und dort
unverständlich zu scheitern.

Das Terminal ist der erste von `qterminal`, `x-terminal-emulator`,
`xfce4-terminal`, `konsole` und `xterm`, den der `PATH` hergibt — eine
Vorliebe, keine Bedingung. Ist keiner davon da, passiert nicht etwa
stillschweigend nichts: Das Werkzeug endet mit einem Fehlercode und nennt jeden
Namen, den es gesucht hat. Damit ist klar, welches Paket fehlt — oder unter
welchem Namen das eigene Terminal in den `PATH` gehört.

Gemeldet wird in `~/.local/state/claude-sessions/events.log`, auf einem Desktop
mit Benachrichtigungsdienst kommt ein Fehlschlag zusätzlich als Pop-up. Genau
deshalb gibt es diese Datei: Ein Programm, das per Klick startet, hat sonst
keinen Ort für eine Meldung. Rückgabewerte: `2` bei falscher oder fehlender
Session-ID, `1` bei kaputter Umgebung (kein Terminal, kein `claude`), `0`, wenn
ein Fenster aufgegangen ist.

### `claude-sessionctl` — Sitzungen, die ihr Terminal überleben

Eine gewöhnliche Claude-Code-Sitzung stirbt mit dem Terminal, in dem sie läuft:
Fenster zu, abgemeldet oder neu gestartet — weg ist sie. `claude-sessionctl`
betreibt eine Sitzung stattdessen als **systemd-User-Dienst**, ihr Terminal
hält `dtach` offen. Die meiste Zeit hängt niemand daran; man verbindet sich,
wenn man nachsehen will, und löst sich mit `Ctrl+\` wieder; die Sitzung läuft
weiter. Weil `start` den Dienst zugleich `enable`t, kommt sie auch wieder hoch,
sobald der User-Manager neu startet — bei der nächsten Anmeldung, mit Linger
schon beim Systemstart.

```sh
claude-sessionctl new mytool ~/code/mytool   # Projekt anlegen und starten
claude-sessionctl status                     # rein lesende Übersicht
claude-sessionctl attach mytool              # ans laufende Terminal andocken
claude-sessionctl log mytool -f              # Log mitlesen
claude-sessionctl stop mytool                # anhalten und aus dem Autostart nehmen
```

`new` schreibt `~/.config/claude-sessions/<name>.conf` — Arbeitsverzeichnis,
Modell, Effort, erster Prompt, zusätzliche Argumente — und startet
`claude-session@<name>.service`. Alle Unterbefehle außer `new`, `start`,
`stop`, `restart` und `rm` sind rein lesend; `rm` lässt die Logs liegen.
Fehlende Voraussetzungen stehen vor der ersten Änderung fest: Ohne `dtach` oder
ohne systemd-User-Instanz endet der Aufruf mit 127 und benennt, was fehlt —
statt einen Dienst zu hinterlassen, der aus Gründen nicht anläuft, die nur im
Journal stehen.

Das sind die Sitzungen, für die die Übersicht **Anhängen** anbietet statt
**Zeigen**: Sie haben kein eigenes Fenster, es gibt also nichts in den
Vordergrund zu holen — der Knopf öffnet ein Terminal, das sich an die laufende
Sitzung hängt. Das Beenden aus dem `⋮`-Menü geht aus verwandtem Grund über
`claude-sessionctl stop`: Ein bloßes `SIGTERM` ließe systemd die Sitzung zehn
Sekunden später wieder starten.

Dahinter stehen zwei weitere Dateien, die man nicht selbst aufruft:
`bin/claude-session-runner` ist das `ExecStart=` der Unit, und
`systemd/claude-session@.service` ist die Vorlage, aus der sie gestartet wird.
Die Unit gibt jeder Sitzung eine Speicherobergrenze, startet sie nach einem
Absturz neu, **nicht** aber nach einem sauberen Ende, und bleibt nach fünf
Fehlstarts in zehn Minuten liegen, statt im Kreis zu laufen. Warum jeweils so
und was die Erkenntnis gekostet hat, steht in den Dateien selbst.

## Aktionen je Zeile

- **Zeigen** (laufend): holt das Terminalfenster der Session in den Vordergrund
  (`wmctrl` über die Prozess-Elternkette — nicht `xdotool search
  --onlyvisible`, das übersieht Fenster auf anderen Arbeitsflächen).
- **Anhängen** (Dauer-Dienst): solche Sitzungen haben kein Fenster, sie werden
  in einem neuen Terminal angehängt.
- **Öffnen** (gespeichert): setzt die Session über `claude-session-open` in
  einem neuen Terminalfenster fort.
- **⋮**: Watchdog attach/pause/resume/entfernen, Logs anzeigen, Projektordner
  öffnen, Session-ID kopieren, Prozess beenden (SIGTERM, mit Rückfrage).

Die Titel sind die im Transkript hinterlegten `aiTitle`; fehlt einer, dient der
erste von Hand getippte Prompt als Ersatz. Aktualisiert wird alle 6 s in
einem Hintergrund-Thread — und nur, solange ein Fenster sichtbar ist; ist es zu
oder minimiert, wird gar nicht geladen. Transkripte werden nur bei Änderung neu
gelesen (Cache über mtime+size), Nutzungsdaten dabei nur für die angehängten
Bytes ausgewertet. Kosten gemessen: 0,33 % einer CPU, Erstscan 233 ms über
102 Dateien, danach 1 ms.

## Installation

```sh
git clone https://github.com/JBGfr/claude-sessions.git
cd claude-sessions
./tools/install-desktop.sh
```

Das Skript leitet den Repo-Pfad aus seinem **eigenen Ort** ab — der Klon darf
also liegen, wo man will; `~/Projekte` wird nirgends vorausgesetzt, und
Leerzeichen im Pfad stören weder beim Klon noch im Heimatverzeichnis. Es
arbeitet rein additiv: es löscht nichts, ruft kein `enable` auf, startet
nichts, braucht kein `sudo` und meldet jede Datei, die es ersetzt — aber nur,
wenn sich der Inhalt wirklich ändert. Ein zweiter Lauf über eine unveränderte
Installation meldet keine Ersetzungen.

Angelegt werden:

- hicolor-Icons unter `$XDG_DATA_HOME/icons/hicolor/*/apps/`,
- `~/.local/bin/claude-sessions` als Symlink auf `bin/claude-sessions`,
- ein Menü-Eintrag in `$XDG_DATA_HOME/applications/` und, falls es einen
  Desktop-Ordner gibt, ein Desktop-Starter (unter XFCE gleich als
  vertrauenswürdig markiert),
- `$XDG_CONFIG_HOME/systemd/user/claude-sessions-app.service` als Symlink auf
  die Unit im Repo,
- `~/.local/bin/claude-session-open`, `~/.local/bin/claude-sessionctl` und
  `~/.local/bin/claude-session-runner` als Symlinks auf die drei Helfer in
  `bin/` — ohne diese Namen im `PATH` bleiben **Öffnen** und **Anhängen**
  wirkungslos, und die Unit-Vorlage findet ihren Runner nicht,
- `$XDG_CONFIG_HOME/systemd/user/claude-session@.service` als Symlink auf die
  Unit-Vorlage. Sie wird nur hingelegt: nie gestartet, nie `enable`d. Eine
  Vorlage lässt sich ohne Instanznamen ohnehin nicht starten, und die Instanzen
  legt `claude-sessionctl new` an.

Genau diese vier Verweise überschreibt das Skript **nicht**. Zeigt so ein Name
schon woanders hin, meldet es den Verweis und lässt ihn liegen — er kann aus
einer älteren oder einer anderen Installation stammen, aus der gerade Dienste
laufen. Wer umhängen will, entfernt den Verweis selbst und lässt das Skript
erneut laufen. Fehlt `dtach`, sagt das Skript das am Ende; installiert wird
nichts im Namen des Nutzers.

`$XDG_DATA_HOME` und `$XDG_CONFIG_HOME` sind ohne Zutun `~/.local/share` und
`~/.config`; ein Wert, der kein absoluter Pfad ist, wird verworfen, wie es die
Spezifikation verlangt. Für `~/.local/bin` gibt es keine solche Variable.

Schritte, deren Hilfsprogramm fehlt (`gio`, `sha256sum`,
`gtk-update-icon-cache`, `update-desktop-database`, `systemctl`,
`xdg-user-dir`), werden mit einem Hinweis übersprungen; die
Installation gilt trotzdem als gelungen. Dasselbe gilt für ein Hilfsprogramm,
das zwar da ist, aber nicht durchkommt: ohne Sitzungsbus kann `gio` die
XFCE-Vertrauensmarke nicht setzen, und das Skript sagt es, statt ein
unmarkiertes Icon zurückzulassen.

Ohne jede Installation geht es auch:

```sh
bin/claude-sessions
```

`bin/claude-sessions` ist ein `/bin/sh`-Wrapper: er löst seinen eigenen Ort
über die Symlink-Kette auf, setzt `PYTHONPATH` auf das Projektverzeichnis und
startet `python3 -m claude_sessions.app`.

Danach: Menü → „Claude Sessions" oder das Desktop-Icon.

## Konfiguration

### Einstellungen

Das Zahnrad in der Kopfleiste öffnet die **Einstellungen**:

| Einstellung | Wirkung | Vorgabe |
|---|---|---|
| Sprache | `Automatisch (System)`, `English`, `Deutsch`. Automatisch folgt `$LC_ALL` / `$LC_MESSAGES` / `$LANG` (`de…` → Deutsch, sonst Englisch) | automatisch |
| Begrüßung anzeigen | Die Begrüßungszeile mit dem Sonnenrad. Aus heißt: die Zeile wird gar nicht erst gebaut, nicht „leer gelassen" | an |
| Name in der Begrüßung | „Guten Abend, Ada". Leer grüßt ohne Namen | leer |
| Alle … Sekunden aktualisieren | 2–60 | 6 |
| Zeilen unter „Zuletzt aktiv" | 5–500 | 40 |
| Bei Watchdog-Ereignissen benachrichtigen | Desktop-Meldungen des **Watchdog**-Daemons | an |
| Benachrichtigungen je Stunde | Deckel dafür, 0 = unbegrenzt | 0 |

Die Werte liegen in `~/.config/claude-sessions/settings.json`
(`$XDG_CONFIG_HOME` wird beachtet; `CS_SETTINGS_PATH` verlegt die ganze Datei
— genau das nutzen die Tests). Das Lesen kann nicht scheitern: eine fehlende,
kaputte oder fremde Datei endet in den Vorgaben, Zahlen außerhalb des
Bereichs werden geklemmt, unbekannte Schlüssel fliegen raus. Geschrieben wird
über eine Tempdatei im selben Verzeichnis und `os.replace()` — ein Abbruch
mittendrin lässt entweder den alten oder den neuen Stand zurück, nie eine
halbe Datei.

Das Fenster liest die Datei **einmal beim Start**. Sprache, Takt und
Zeilenzahl greifen deshalb erst nach einem Neustart — der Dialog sagt das,
und „Übernehmen & neu starten" erledigt ihn (`systemctl --user restart
claude-sessions-app`, abgelöst gestartet, damit der Befehl das Stoppen der
App überlebt).

Der Name für die Begrüßung wird der Reihe nach gesucht: `settings.json` →
`$CS_GREET_NAME` → nichts.

### Pop-ups gehen an den Watchdog

Die beiden Pop-up-Einstellungen wirken gar nicht in dieser App — sie gehören
dem [Watchdog](https://github.com/JBGfr/claude-watchdog)-Daemon, der
`CW_NOTIFY` und `CW_NOTIFY_MAX_PER_HOUR` aus seiner Umgebung liest. Beim
Speichern schreibt die Übersicht deshalb ein Drop-in neben dessen Unit:

```ini
# ~/.config/systemd/user/claude-watchdog.service.d/uebersteuerung.conf
[Service]
Environment=CW_NOTIFY=1
Environment=CW_NOTIFY_MAX_PER_HOUR=0
```

danach `systemctl --user daemon-reload` und `try-restart`. Drei Absichten
stecken darin: geschrieben wird nur, wenn sich der Inhalt wirklich ändert
(sonst unterbräche das Speichern der Sprache einen laufenden Watchdog),
`try-restart` **startet** keinen Daemon, der gerade steht, und fehlt die
Watchdog-Unit, wird der ganze Schritt still übersprungen — die Übersicht
läuft auch ohne Watchdog. `CS_WD_DROPIN_PATH` verlegt das Drop-in (wieder:
Tests).

### Watchdog-Verzeichnis

**Watchdog-Verzeichnis.** Vorgabe ist `~/.claude-watchdog`; dort liegen
`state.db` und `bin/claude-watchdog`. Die Umgebungsvariable `CS_WATCHDOG_DIR`
verschiebt beides:

```sh
CS_WATCHDOG_DIR=~/woanders/claude-watchdog bin/claude-sessions
```

Ein leerer Wert zählt wie „nicht gesetzt", `~` wird aufgelöst, und gelesen wird
einmal beim Import. Fehlt das Verzeichnis, ist auch das kein Fehler: der
Watchdog-Abschnitt bleibt leer und die Fußzeile vermerkt, dass `state.db` nicht
lesbar ist.

Für den Dienst gehört die Variable in ein Drop-in
(`systemctl --user edit claude-sessions-app.service`):

```ini
[Service]
Environment=CS_WATCHDOG_DIR=%h/woanders/claude-watchdog
```

**Refresh-Takt.** `REFRESH_SECONDS` und `MAX_STORED_ROWS` am Kopf von
`claude_sessions/app.py` sind die Rückfallwerte hinter den beiden
Einstellungen oben: sie gelten, solange in `settings.json` nichts anderes
steht. `IDLE_POLL_SECONDS = 2` — das Nachsehen, ob das Fenster wieder
sichtbar wurde — ist nicht einstellbar und bleibt im Quelltext. Schneller als
6 s ist messbar teuer: bei 3 s lag die Dauerlast bei rund 9 % einer CPU, ohne
dass jemand hinsieht. Deshalb hört der Dialog bei 2 s auf.

## Als Dienst der Desktop-Sitzung

`install-desktop.sh` legt zusätzlich `claude-sessions-app.service` an. Sie sorgt
für sauberes Logging und eine eigene cgroup — **nicht** dafür, dass die App von
selbst aufgeht.

```sh
systemctl --user start claude-sessions-app     # jetzt starten
systemctl --user stop  claude-sessions-app     # beenden
journalctl --user -u claude-sessions-app -f    # mitlesen
```

Die Übersicht geht **ausschließlich auf Anweisung** auf: Desktop-Icon, Menü
oder `systemctl start`. Deshalb hat die Unit **keinen Autostart**, kein
`Restart` und kein `[Install]` — sie lässt sich gar nicht erst `enable`n, und
auch ein Absturz holt kein Fenster zurück. Ein Fenster, das von selbst aufgeht,
ist ausdrücklich nicht gewollt; das ist eine Entwurfsentscheidung und kein
fehlendes Feature.

Drei Eigenheiten stecken in der Unit:

- `ExecCondition` fragt per `xdotool getdisplaygeometry`, ob es überhaupt eine
  Anzeige gibt. Fehlt sie, gilt der Dienst als übersprungen statt als
  gescheitert — kein Fehlerzustand, keine Neustartschleife. Fehlt `xdotool`
  selbst, läuft der Dienst trotzdem an.
- `KillMode=process` beendet nur die App selbst. Sonst würde jedes Stoppen die
  aus der Übersicht geöffneten Terminals mitreißen.
- Der Launcher ruft `bin/claude-sessions --service` auf, damit es genau **einen**
  Startweg gibt. Startete das Icon die App am Dienst vorbei, meldete ein
  späteres `systemctl start` „Started" und sofort „Deactivated successfully",
  während das Fenster offen steht (`Gtk.Application` mit fester ID).

Aus der App geöffnete Fenster (Terminal, Ordner, Logs) laufen in einer eigenen
transienten Unit über `systemd-run --user --collect
--property=ExitType=cgroup`. `start_new_session=True` allein genügt nicht — das
löst nur von der Prozessgruppe, nicht von der cgroup, und ohne `ExitType=cgroup`
räumt systemd das frisch geöffnete Fenster sofort wieder ab, sobald der Starter
sich beendet.

## Schrift und Farben

Die Palette und alle Maße — Farben, Abstände, Schriftgrößen — stammen aus der
Claude-Desktop-App. Deren Schriften nicht: „Anthropic Sans" und „Anthropic
Serif" gehören zu jener Anwendung und liegen aus Lizenzgründen **nicht** in
diesem Repo. Die CSS-Kette nennt sie zuerst und fällt dann zurück:
`"Anthropic Sans", Inter, "Noto Sans", Cantarell, sans-serif` für die
Oberfläche, `"Anthropic Serif", Georgia, serif` für die Begrüßung. Wer die
Schriften installiert hat, sieht dieselbe Typografie wie im Vorbild; alle
anderen sehen dieselben Farben und dasselbe Raster in der Systemschrift.

## Was auf dem Bildschirm steht

Das Fenster zeigt Sitzungstitel und Projektpfade. Ein Titel sagt, worum es in
der Sitzung ging, ein Pfad nennt ein Verzeichnis dieses Rechners. Wer einen
Screenshot dieser App weitergibt, gibt beides mit weiter — siehe
[SECURITY.md](SECURITY.md).

## Entwicklung

```sh
python3 -m unittest discover -s tests -q   # Tests (ohne GTK, ohne Netz)
python3 tools/make_icons.py                # Icon-Assets neu erzeugen
```

Kein Paket, kein venv, keine pip-Abhängigkeiten: System-Python mit
PyGObject/GTK3 aus den Distributionspaketen. Die Tests importieren nur die
GTK-freien Module (`data`, `actions`, `einstellungen`, `texte`) und laufen
deshalb auch auf einem nackten Python ohne PyGObject — genau das macht die
CI. Deshalb bleibt `app.py` bewusst dünn: Textformatierung gehört nach
`data.py`, der Wortlaut nach `texte.py`.

## Lizenz

MIT — siehe [LICENSE](LICENSE).

Not affiliated with Anthropic. Claude and Claude Code are products of
Anthropic; this is an independent tool.
