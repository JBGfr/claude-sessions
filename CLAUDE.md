# Claude Sessions — Projektanweisungen

Kleine GTK3-Übersicht über Claude-Code-Sessions. Was die App tut, steht im
`README.md` (englisch, für Fremde) und in `README.de.md` (deutsch) — hier
steht, wie in diesem Repo gearbeitet wird. Was die App liest und was sie
nicht anfasst, steht mit Datei:Zeile-Belegen in `SECURITY.md`; wer an
`data.py`, `actions.py` oder den Helfern in `bin/` etwas verschiebt, zieht die
Zeilennummern dort nach. Verhaltensänderungen gehören in **beide** READMEs.

## Tech-Stack

| | |
|---|---|
| Sprache | Python, System-`/usr/bin/python3` (3.13) |
| GUI | PyGObject + **GTK 3** (GTK 4 ist auf der Kiste nicht verfügbar) |
| Abhängigkeiten | stdlib + `gi`/`cairo` aus den Kali-Paketen — **kein pip, kein venv** |
| Tests | `unittest`, ohne GTK, ohne Netz, ohne echte Subprozesse |
| Packaging | keins — `bin/claude-sessions` ist ein `PYTHONPATH`-Wrapper |
| Einstellungen | `~/.config/claude-sessions/settings.json` (`$XDG_CONFIG_HOME`, `CS_SETTINGS_PATH`), Pop-ups zusätzlich als systemd-Drop-in `~/.config/systemd/user/claude-watchdog.service.d/uebersteuerung.conf` (`CS_WD_DROPIN_PATH`) |
| Datenquellen | `claude agents --json` (live), Transkripte unter `~/.claude/projects` (Titel, Tokens), `state.db` des Watchdogs (nur lesend, Ort per `CS_WATCHDOG_DIR`), `~/.local/state/claude-sessions/usage.json` (Kontingent) |

`tools/statusline.py` gehört zwar zu diesem Repo, läuft aber **außerhalb** der
App: Claude Code ruft es als `statusLine`-Kommando auf und reicht ihm
`rate_limits` herein. Es muss deshalb schnell (gemessen 22 ms), abhängigkeitsfrei
und absolut fehlertolerant bleiben — eine Statusleiste darf niemals eine Sitzung
stören. Kein Subprozess darin, auch kein `git`.

## Regeln

- **Anders als im Watchdog-Repo:** echte Umlaute sind überall erlaubt (auch in
  `.py`) — eine GUI braucht „Öffnen", nicht „Oeffnen". Kommentare, Docstrings
  und Commit-Nachrichten sind Deutsch.
- **Nutzersichtbare Texte stehen nur in `claude_sessions/texte.py` und kommen
  über `texte.t("schluessel")` ins Fenster — englisch zuerst.** `TEXTE` ist die
  Grundsprache (Englisch), `UEBERSETZUNGEN["de"]` die deutsche Tabelle daneben;
  ein neuer Text wird in **beiden** angelegt, sonst wird `tests/test_texte.py`
  rot (es prüft beide Richtungen, gleiche Platzhalter, keine leeren Texte).
  Platzhalter sind benannt (`{n}`, `{pct}`) und im `str.format`-Stil, nie `%s`.
  In `app.py` gehört damit **keine** Zeichenkette mehr, die jemand liest —
  einzige Ausnahme ist der Produktname „Claude Sessions". Wörter, die aus
  `data.py` kommen (Gruppen, Watchdog-Status), stehen dort in
  `_Sprachtabelle`-Tabellen und übersetzen sich beim Zugriff.
- Die Sprache wird **einmal beim Start** aufgelöst (`SessionsApp.__init__`).
  Ein Wechsel im Einstellungsdialog greift erst nach einem Neustart; das steht
  so im Dialog und ist gewollt — eine Oberfläche, die sich unter der Hand
  umbaut, während man auf sie sieht, ist keine Übersicht.
- GTK-Widgets werden **nur im Mainthread** angefasst; alles aus
  Hintergrund-Threads läuft über `GLib.idle_add`. Der Refresh-Thread ist der
  einzige Ort, an dem Subprozesse/Dateisystem-Scans laufen dürfen.
- Die Watchdog-Datenbank (`state.db`) wird ausschließlich **lesend** geöffnet
  (`mode=ro`); schreibende Watchdog-Aktionen gehen immer über dessen CLI
  `<CS_WATCHDOG_DIR>/bin/claude-watchdog` (Vorgabe `~/.claude-watchdog`; die
  Umgebungsvariable verschiebt Datenbank **und** CLI, `data.py:36`).
- **Farben kommen aus der Palette, nicht aus dem Kopf.** Die Werte stammen
  aus der Claude-Desktop-App (`.darkTheme` in deren `app.asar`) und stehen als
  `@define-color`-Block am Kopf von `claude_sessions/app.py` (dort ab `CSS =`,
  Zeile 43). Wer eine Farbe braucht, nimmt eine von dort — keine neue erfinden,
  keine mischen. Einzige Ausnahme ist bereits vermerkt: für „wartet" gibt es in
  der Desktop-Palette keinen Ton.
- Einzige Icon-Quelle ist `assets/app-icon-master.png`; `make_icons.py` skaliert
  nur daraus und zeichnet nichts selbst. Nach einem Tausch des Masters
  `make_icons.py` laufen lassen und `tools/install-desktop.sh` erneut ausführen.
- Die Übersicht geht **nur auf Anweisung** auf (Icon, Menü, `systemctl start`).
  Deshalb hat `systemd/claude-sessions-app.service` kein `[Install]`, kein
  `Restart` und keinen Autostart-Eintrag. Nicht „der Bequemlichkeit halber"
  nachrüsten — ein Fenster, das von selbst aufgeht, ist ausdrücklich nicht
  gewollt. (Ein Autostart über systemd ginge hier ohnehin nicht: XFCE
  aktiviert `graphical-session.target` nicht, und `default.target` ist wegen
  `Linger=yes` schon vor dem X-Server erreicht.)
- Fenster, die die App öffnet (Terminal, Ordner, Logs), laufen **immer** über
  `actions._spawn_detached` und damit in einer eigenen transienten Unit.
  `subprocess.Popen(..., start_new_session=True)` reicht nicht: das löst nur
  von der Prozessgruppe, nicht von der cgroup — die geöffneten Sessions hingen
  sonst am Dienst und stürben beim Abmelden mit.
- **Kontingentwerte kommen ausschließlich aus `data.plan_usage()`**, also aus
  der Datei, die `tools/statusline.py` schreibt. Sie **nie** aus den
  Transkripten rekonstruieren: Claude Desktop, claude.ai im Browser und andere
  Geräte belasten dasselbe Konto, ohne hier eine Zeile zu hinterlassen. Genau
  dieser Versuch lag am 2026-07-30 beim Reset-Zeitpunkt 13 Minuten daneben und
  wurde vom Nutzer sofort als falsch erkannt. Liegen keine Werte vor, zeigt die
  Kopfzeile das offen an — lieber keine Zahl als eine erfundene. Aus den
  Transkripten stammen nur die Tokensummen je Session, und die sind
  ausdrücklich als „lokal" gekennzeichnet.
- Ausnahmen eng fangen (`OSError`, `ValueError`, `sqlite3.Error`, …);
  `except Exception` nur an der Thread-Grenze in `app._load`.
- **Nach Änderungen an `.py` den Dienst neu starten** — Python liest die Module
  beim Start ein, ein offenes Fenster arbeitet sonst weiter mit der alten
  Fassung. Bei einer Gegenprobe unbedingt Prozess-Startzeit gegen den
  Dateistand prüfen, sonst misst man den alten Stand (genau das ist am
  2026-07-30 zweimal passiert).

## Helfer

Neben der Oberfläche liegen drei eigenständige Kommandozeilenwerkzeuge im Repo.
Sie stammen aus einem privaten Repo und sind mit der Veröffentlichung hierher
übernommen worden — **diese Fassung ist ab jetzt die maßgebliche.** Wer etwas
an ihnen ändert, ändert es hier; die alte Ablage wird nicht mehr gepflegt, und
es wird nichts dorthin zurückgeschrieben.

| Datei | Aufgabe |
|---|---|
| `bin/claude-session-open` | öffnet eine gespeicherte Session per `claude --resume` in einem neuen Terminalfenster. Rückfallkette `qterminal` → `x-terminal-emulator` → `xfce4-terminal` → `konsole` → `xterm`; findet sich keines, endet es mit einer Meldung, die alle gesuchten Namen nennt. Hängt an „Öffnen" (`actions.open_session`) und am URI-Schema `claude-session://`. |
| `bin/claude-sessionctl` | legt Dauer-Sitzungen an, startet/stoppt sie, hängt an sie an. Projektdatei `~/.config/claude-sessions/<name>.conf`. Hängt an „Anhängen" (`actions.attach_session`) und am Beenden eines Dauer-Dienstes (`actions.stop_service`, das die erste Ausgabezeile im Dialog zeigt — deshalb Farben nur am Terminal). |
| `bin/claude-session-runner` | startet **eine** Sitzung unter `dtach`; wird nur vom Dienst aufgerufen, nie von Hand. |
| `systemd/claude-session@.service` | die Vorlage dazu. `tools/install-desktop.sh` legt sie als Symlink nach `~/.config/systemd/user`, startet sie aber nicht und `enable`t sie nicht — die Instanzen legt `claude-sessionctl new` an. |

Ihre Ausgaben sind **Englisch**, wie die Grundsprache des Repos; Kommentare und
Docstrings bleiben Deutsch. Sie gehören ausdrücklich **nicht** nach
`claude_sessions/texte.py`: Die Tabelle dort gehört der GTK-Oberfläche, und die
Helfer laufen auch ohne sie. Nichts Maschinenspezifisches hinein — kein fester
Heimatpfad, keine Annahme über den Ablageort des Repos.

**Zwei Entscheidungen darin sind teuer erkauft. Sie sehen aus wie Altlast und
sind keine:**

- **`dtach -N` statt `-n`** (Kopfkommentar in `bin/claude-session-runner`). `-n`
  kehrt sofort zurück; unter `Type=simple` gilt der Dienst damit als beendet,
  und die Neustartregel startete in einer Endlosschleife immer neue
  Claude-Prozesse — auf Tokenkosten. Zum selben Punkt gehört der Umweg über die
  Statusdatei: `dtach -N` endet **immer** mit 1, ein sauberes `/exit` sähe sonst
  wie ein Absturz aus.
- **`Restart=on-failure` statt `always`** (`systemd/claude-session@.service`).
  Ein sauberes Ende ist kein Absturz; `always` startete sofort eine neue Sitzung
  mit `--continue` und läse den kompletten Verlauf noch einmal ein. Daneben
  hängen `RestartPreventExitStatus=77 78 127` (Bedien-, Rechte- und
  Programmfehler heilt kein Neustart), `StartLimitBurst` gegen die Schleife und
  `KillMode=control-group` statt `mixed` — bei `mixed` bekommt nur der Runner
  ein SIGTERM, Claude nie eines (nachgemessen: 1,3 ms bis zum SIGKILL).

Die vollständigen Begründungen samt Messwerten stehen in den Dateien selbst.
Wer eine dieser Stellen ändert, streicht die Begründung mit oder schreibt die
neue Messung daneben — eine Änderung ohne Gegenmessung ist hier schon einmal
teuer geworden.

## Die Helfer gehören hierher

`bin/claude-session-open`, `bin/claude-sessionctl`, `bin/claude-session-runner` und
`systemd/claude-session@.service` sind seit dem 2026-08-27 die **maßgebliche** Fassung. Das
private `zsh-menu` hält nur noch relative Verweise hierher; `~/.local/bin` löst über diese
Kette auf. Änderungen also hier machen — eine zweite Kopie drüben würde auseinanderlaufen,
und die produktiven `claude-session@`-Dienste dieser Maschine hängen an genau diesen Dateien.

Zwei Entscheidungen darin sind teuer erkauft und bleiben: `dtach -N` (nicht `-n`, sonst hält
systemd den Dienst für beendet und startet in einer Schleife neu) und `Restart=on-failure`.
Der Transkript-Pfad kodiert **jedes** Nicht-Alphanumerische zu `-`, nicht nur `/` — sonst
bekommt jeder Projektpfad mit Punkt nie ein `--continue`.

## Screenshots: nur aus dem Demo-Modus

Die Übersicht zeigt Titel und Projektpfade echter Sitzungen. Ein Screenshot davon
veröffentlicht genau diese Titel — deshalb entsteht jedes Bild fürs README aus
`claude_sessions/demo.py`:

```sh
CS_DEMO=1 bin/claude-sessions
```

Der Modus ersetzt in `app._load()` den echten Schnappschuss durch erfundene Sitzungen
(`~/code/shop-api` statt echter Pfade, UUIDs nach derselben Regel, die `tools/leak-check.py`
als „erfunden" durchgehen lässt). `tests/test_demo.py` sichert ab, dass die Zähler zur Liste
passen, keine `/home/`-Pfade auftauchen und zwei Läufe dasselbe Bild ergeben.

**Nie einen Screenshot aus der laufenden Übersicht ins Repo legen** — auch nicht „kurz zum
Zeigen". Für ein neues Bild: Demo-Modus starten, Fenster aufnehmen, nach `assets/screenshot.png`.

## Build & Test

```sh
python3 -m unittest discover -s tests -q
python3 tools/make_icons.py
tools/install-desktop.sh
python3 tools/leak-check.py --selbsttest   # Gegenprobe der Leck-Pruefung
```

Stand 2026-08-21: **251 Tests, OK** — gemessen mit
`python3 -m unittest discover -s tests -q`. Die Zahl wächst; nicht aus dem
Gedächtnis zitieren, sondern den Befehl laufen lassen.

## Git

- **Kein direkter Push auf `main`.** Seit dem 2026-07-30 blockiert
  `.git/hooks/pre-push` das (Schutzschicht der CEO-Flotte, gilt auch für
  Branch-Löschungen). Weg: `git switch -c feature/ceo-<thema>`, danach
  `git branch -f main origin/main`, pushen und `gh pr create --base main`.
  `gh pr merge` steht in der `deny`-Liste von `.claude/settings.json`.
- **Feature-Branches sofort nach dem Merge auflösen.** Die ausgelieferten
  Programme sind Symlinks in diese Arbeitskopie (`~/.local/bin/…`, die
  systemd-Unit); solange ein Branch ausgecheckt ist, **läuft sein Stand
  produktiv**, und ein `git switch main` nimmt ihn ohne Vorwarnung wieder weg.
- Betreff deutsch und ohne Präfixe.
- Remote: **`JBGfr/claude-sessions`**. Die Arbeitskopie mit ihrer History
  bleibt privat; veröffentlicht wird nur der gespiegelte Stand, siehe
  „Veröffentlichung".
- Nicht einchecken: `__pycache__/`, Screenshots, Capture-Rohdaten.

## Veröffentlichung

Das Repo wird öffentlich **gespiegelt**, nicht umgestellt: `tools/publish.sh`
baut aus dem gewünschten Stand einen Baum ohne die privaten Dateien und setzt
ihn als Commit auf den Zweig `public`. Der erste dieser Commits hat keinen
Elternteil (Orphan), spätere Läufe hängen sich an ihren Vorgänger, damit
Fremde pullen statt neu klonen können. Die echte History bleibt privat und
wird **nie** gepusht — in ihr stehen Session-IDs, Transkriptpfade und private
Absenderadressen, und die lassen sich nachträglich nicht zuverlässig
entfernen: GitHub liefert gelöschte Objekte weiter per SHA aus.

Nie ins Repo — auch nicht in Kommentare, Docstrings, Tests oder
Commit-Nachrichten:

- **echte Session-IDs** (UUIDs und die kurzen 8-Hex-Präfixe) und **echte
  Sitzungstitel**; erfundene UUIDs bestehen je Gruppe aus einem einzigen
  wiederholten Zeichen (`11111111-2222-3333-4444-555555555555`),
- **`/home/<benutzer>`-Pfade**; in Beispielen `~` oder `/home/user`,
- **Screenshots mit echten Sitzungen** — die Übersicht zeigt Titel und Pfade,
  ein Bild davon ist ein Leck. Auch in Issues und PRs nicht,
- **Klarnamen und private Adressen**; `user.email` muss die
  noreply-Adresse sein, sonst bricht `publish.sh` gleich am Anfang ab,
- IP- und MAC-Adressen, Tokens/Schlüssel, `state.db`, `*.jsonl`, `.claude/`
  und die Vault-Notiz `projekt-claude-sessions.md`.

Geprüft wird das vor **jeder** Veröffentlichung von `tools/leak-check.py`: es
läuft über den Git-Baum (nicht den Arbeitsbaum) und über die Absenderadressen
des Logs, und `publish.sh` bricht bei Befunden ab, bevor irgendetwas
hinausgeht. Gepusht wird ohnehin von Hand.

Die Prüfung selbst muss rot werden können: `python3 tools/leak-check.py
--selbsttest` legt eine Attrappe an, in der jede Regel anschlagen **muss**,
und eine saubere Datei, bei der keine anschlagen darf. Wer eine Regel
ergänzt, ergänzt die Attrappe mit.
