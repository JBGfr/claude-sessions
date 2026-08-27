#!/bin/sh
# Desktop-Integration: hicolor-Icons, Launcher im Menue und auf dem Desktop
# (mit XFCE-Trust-Attributen), Startprogramm und Helfer in ~/.local/bin sowie
# die systemd-Units als Symlink. Idempotent, alles im Benutzerverzeichnis,
# kein sudo.
#
# Das Skript arbeitet rein additiv:
#   * es loescht nichts,
#   * es ruft kein 'enable' auf und startet nichts,
#   * bestehende Dateien werden nur ersetzt, wenn es das vorher meldet.
#
# Der Repo-Pfad kommt aus dem Ort DIESER Datei — das Projekt darf also liegen,
# wo der Nutzer es haben will; ~/Projekte wird nirgends vorausgesetzt.
set -eu

# --- Repo-Pfad aus dem eigenen Ort -----------------------------------------
self="$0"
case "$self" in
    */*) : ;;
    *) self="$(command -v -- "$self" 2>/dev/null || printf '%s' "$self")" ;;
esac
verzeichnis="$(dirname -- "$self")"
name="$(basename -- "$self")"
schritt=0
while [ -L "$verzeichnis/$name" ] && [ "$schritt" -lt 40 ]; do
    schritt=$((schritt + 1))
    ziel="$(readlink -- "$verzeichnis/$name")"
    case "$ziel" in
        /*) verzeichnis="$(dirname -- "$ziel")" ;;
        *) verzeichnis="$(cd -- "$verzeichnis" && cd -- "$(dirname -- "$ziel")" && pwd)" ;;
    esac
    name="$(basename -- "$ziel")"
done
REPO="$(cd -- "$verzeichnis/.." && pwd)"

# Zielorte nach XDG: die Umgebung schlaegt die Vorgabe. Wer $XDG_DATA_HOME
# oder $XDG_CONFIG_HOME umgesetzt hat, sucht Icons, Menue-Eintrag und Unit
# genau dort — ein Eintrag unter $HOME/.local/share waere dann fuer Desktop
# und systemd unsichtbar. Relative Werte ignoriert die Spezifikation
# ausdruecklich, deshalb die Pruefung auf den fuehrenden Schraegstrich.
DATEN="${XDG_DATA_HOME:-}"
case "$DATEN" in /*) ;; *) DATEN="$HOME/.local/share" ;; esac
KONFIG="${XDG_CONFIG_HOME:-}"
case "$KONFIG" in /*) ;; *) KONFIG="$HOME/.config" ;; esac

ICONS="$DATEN/icons/hicolor"
APPS="$DATEN/applications"
# ~/.local/bin ist kein XDG-Ort; es gibt keine Variable dafuer.
BIN="$HOME/.local/bin"
UNITS="$KONFIG/systemd/user"
DESKTOP_FILE="claude-sessions.desktop"
UNIT_FILE="claude-sessions-app.service"
# Vorlage fuer die Dauer-Sitzungen: claude-session@<name>.service. Sie wird nur
# hingelegt, nie gestartet und nie enabled - das macht 'claude-sessionctl new'.
SESSION_UNIT_FILE="claude-session@.service"

# Meldet, dass eine vorhandene Datei gleich ersetzt wird. Ohne diesen Hinweis
# ueberschreibt das Skript nichts stillschweigend.
#
# Gemeldet wird nur, was sich wirklich aendert: $2 ist die neue Fassung
# (Datei). Ohne diesen Vergleich meldete jeder zweite Lauf eine "Ersetzung",
# bei der kein einziges Byte anders wurde — eine Meldung, die man nach dem
# dritten Mal nicht mehr liest.
melde_ersatz() {
    [ -e "$1" ] || [ -L "$1" ] || return 0
    if [ -n "${2:-}" ] && [ -f "$1" ] && [ ! -L "$1" ] &&
       command -v cmp > /dev/null 2>&1 && cmp -s -- "$2" "$1"; then
        return 0
    fi
    printf '  ersetzt vorhandene Datei: %s\n' "$1"
}

# Schreibt den Text $2 nach $1 und meldet vorher, falls dabei ein ANDERER
# Inhalt verschwindet. Ohne 'cmp' wird im Zweifel gemeldet.
schreibe_datei() {
    # Ein Symlink am Ziel wird NICHT verfolgt. `> "$1"` schreibt sonst durch
    # ihn hindurch in eine fremde Datei — auf der Kiste des Autors zeigt der
    # Menueintrag in ein anderes Projekt, das dabei stillschweigend
    # umgeschrieben wuerde. Nachgestellt am 2026-08-20: die Zieldatei war
    # danach der Desktop-Eintrag, ohne eine einzige Meldung.
    if [ -L "$1" ]; then
        ziel=$(readlink -- "$1" 2>/dev/null || printf '?')
        printf '  VERWEIS   %s -> %s (nicht angefasst)\n' "$1" "$ziel"
        printf '            kommt der Eintrag von dort, ist alles gut;\n'
        printf '            sonst den Verweis entfernen und erneut laufen lassen\n'
        return 0
    fi
    if [ -e "$1" ]; then
        if command -v cmp > /dev/null 2>&1 &&
           printf '%s\n' "$2" | cmp -s - "$1"; then
            :
        else
            printf '  ersetzt vorhandene Datei: %s\n' "$1"
        fi
    fi
    printf '%s\n' "$2" > "$1"
}

# Symlink anlegen und die Ersetzung melden, falls dort schon etwas anderes
# liegt. Zeigt der Symlink bereits richtig, bleibt es still (Idempotenz).
setze_symlink() {
    quelle="$1"
    link="$2"
    if [ "$(readlink -- "$link" 2>/dev/null || printf '')" != "$quelle" ]; then
        melde_ersatz "$link"
    fi
    ln -sfn "$quelle" "$link"
}

# Symlink anlegen, aber NICHTS umbiegen, was schon woanders hin zeigt.
#
# Anders als setze_symlink: die Helfer koennen aus einer aelteren, eigenen oder
# fremden Installation stammen - auf der Kiste des Autors zeigen genau diese
# drei Namen in ein anderes Projekt, aus dem heraus drei Dienste laufen. Ein
# 'ln -sfn' darueber haette sie im laufenden Betrieb auf diese Arbeitskopie
# umgehaengt. Gemeldet wird das, entschieden wird es vom Menschen.
setze_symlink_geschuetzt() {
    quelle="$1"
    link="$2"
    if [ -L "$link" ]; then
        ziel="$(readlink -- "$link" 2>/dev/null || printf '?')"
        [ "$ziel" = "$quelle" ] && return 0
        # Ein anderer Pfad kann dieselbe Datei sein (etwa wenn das Repo selbst
        # ueber einen Symlink erreicht wird). Dann ist nichts zu melden.
        if command -v readlink > /dev/null 2>&1; then
            a="$(readlink -f -- "$link" 2>/dev/null || printf 'a')"
            b="$(readlink -f -- "$quelle" 2>/dev/null || printf 'b')"
            [ "$a" = "$b" ] && return 0
        fi
        printf '  VERWEIS   %s -> %s (nicht angefasst)\n' "$link" "$ziel"
        printf '            kommt die Datei von dort, ist alles gut;\n'
        printf '            sonst den Verweis entfernen und erneut laufen lassen\n'
        return 0
    fi
    if [ -e "$link" ]; then
        printf '  DATEI     %s (nicht angefasst)\n' "$link"
        printf '            hier liegt eine echte Datei im Weg - selbst\n'
        printf '            entfernen, dann erneut laufen lassen\n'
        return 0
    fi
    ln -s "$quelle" "$link"
}

echo "Projektverzeichnis: $REPO"
echo

# --- Icons -----------------------------------------------------------------
icons_da=0
for s in 48 64 128 256; do
    quelle="$REPO/assets/icon-$s.png"
    ziel="$ICONS/${s}x${s}/apps/claude-sessions.png"
    if [ ! -f "$quelle" ]; then
        printf 'Icon fehlt, uebersprungen: %s (erst "python3 tools/make_icons.py")\n' "$quelle"
        continue
    fi
    mkdir -p "$ICONS/${s}x${s}/apps"
    melde_ersatz "$ziel" "$quelle"
    cp "$quelle" "$ziel"
    icons_da=1
done

# Fruehere Fassungen legten hier zusaetzlich ein SVG ab. Das Master ist jetzt
# ein PNG; ein liegengebliebenes SVG gewinnt bei grossen Groessen und zeigt
# weiter das alte Motiv. Entfernt wird es hier NICHT — nur gemeldet.
alt_svg="$ICONS/scalable/apps/claude-sessions.svg"
if [ -e "$alt_svg" ]; then
    echo "Hinweis: aus einer aelteren Fassung liegt noch $alt_svg."
    echo "         Es verdraengt das PNG bei grossen Groessen — bei Bedarf selbst loeschen."
fi

if [ "$icons_da" = 1 ] && command -v gtk-update-icon-cache > /dev/null 2>&1; then
    gtk-update-icon-cache -f "$ICONS" > /dev/null 2>&1 || true
fi

# --- Startprogramm ---------------------------------------------------------
# Symlink statt Kopie: die Unit und der Launcher zeigen auf einen festen,
# maschinenneutralen Pfad, der Wrapper loest ihn auf und findet so das Repo.
mkdir -p "$BIN"
if [ ! -x "$REPO/bin/claude-sessions" ]; then
    echo "Hinweis: $REPO/bin/claude-sessions ist nicht ausfuehrbar —"
    echo "         'chmod +x bin/claude-sessions' nachholen, sonst startet nichts."
fi
setze_symlink "$REPO/bin/claude-sessions" "$BIN/claude-sessions"

# --- Helfer ----------------------------------------------------------------
# Ohne diese drei Namen im PATH bleiben "Oeffnen" und "Anhaengen" in der
# Uebersicht wirkungslos, und die Unit-Vorlage findet ihren Runner nicht.
# Vorhandene Verweise auf etwas anderes werden nur gemeldet (siehe
# setze_symlink_geschuetzt).
# Die Namen stehen fest und deshalb woertlich hier: die Unit-Vorlage ruft
# %h/.local/bin/claude-session-runner auf, und actions.py ruft
# claude-session-open bzw. claude-sessionctl ueber den PATH. Woertlich auch
# deshalb, weil eine Variable in einer Liste nur dort zerfaellt, wo die Shell
# Wortsplitting macht - unter zsh waere daraus ein einziger, sinnloser Name.
for helfer in claude-session-open claude-sessionctl claude-session-runner; do
    if [ ! -x "$REPO/bin/$helfer" ]; then
        printf 'Hinweis: %s ist nicht ausfuehrbar -\n' "$REPO/bin/$helfer"
        printf "         'chmod +x bin/%s' nachholen.\n" "$helfer"
    fi
    setze_symlink_geschuetzt "$REPO/bin/$helfer" "$BIN/$helfer"
done

# --- Launcher --------------------------------------------------------------
mkdir -p "$APPS"

# Nutzersichtbare Woerter stehen nur in claude_sessions/texte.py (Projektregel)
# — auch die des Menue-Eintrags. Der Desktop-Eintrag hat dafuer eigene
# Sprachschluessel: der Grundtext ist Englisch, "[de]" die Uebersetzung.
# Laesst sich das nicht abfragen (kein python3), bleibt der Eintrag beim
# blossen Namen, statt hier eine zweite Textquelle aufzumachen.
sprachzeilen="$(PYTHONPATH="$REPO" "${PYTHON3:-$(command -v python3 || echo /usr/bin/python3)}" -c '
import sys
from claude_sessions import texte
for schluessel, feld in (("desktop.gattung", "GenericName"),
                         ("desktop.zweck", "Comment")):
    en = texte.text(schluessel, "en")
    de = texte.text(schluessel, "de")
    if schluessel in (en, de):
        sys.exit(1)
    print(feld + "=" + en)
    print(feld + "[de]=" + de)
' 2>/dev/null || printf '')"
if [ -z "$sprachzeilen" ]; then
    echo "Hinweis: die Beschriftung des Menue-Eintrags liess sich nicht aus"
    echo "         claude_sessions/texte.py holen — der Eintrag traegt nur"
    echo "         den Namen 'Claude Sessions'."
fi

# Der Wert von Exec= wird beim Start wie eine Shell-Zeile zerlegt. Ein
# Leerzeichen im Heimatpfad zerrisse ihn sonst in mehrere Argumente — und das
# faellt nicht etwa erst beim Start auf: GIO nimmt den Eintrag dann gar nicht
# an. Nachgemessen mit einem Heimatverzeichnis, dessen Name ein Leerzeichen
# enthaelt: Gio.DesktopAppInfo.new_from_filename() lieferte NULL, der
# Menuepunkt existierte fuer den Desktop also nicht. Der Pfad kommt deshalb in
# doppelte Anfuehrungszeichen; innerhalb davon schuetzt die Spezifikation vier
# Zeichen per Backslash: Anfuehrungszeichen, Backslash, Dollar und Gravis.
if command -v sed > /dev/null 2>&1; then
    exec_pfad="$(printf '%s' "$BIN/claude-sessions" | sed 's/[\\"`$]/\\&/g')"
else
    # Ohne 'sed' lieber den blanken Pfad als eine leere Exec-Zeile. Das
    # traegt fuer jeden Heimatpfad ohne diese vier Zeichen.
    exec_pfad="$BIN/claude-sessions"
fi

eintrag="[Desktop Entry]
Type=Application
Version=1.0
Name=Claude Sessions"
[ -z "$sprachzeilen" ] || eintrag="$eintrag
$sprachzeilen"
eintrag="$eintrag
Exec=\"$exec_pfad\" --service
Icon=claude-sessions
Terminal=false
Categories=Development;Utility;
Keywords=claude;session;watchdog;
StartupNotify=true
StartupWMClass=claude-sessions"

schreibe_datei "$APPS/$DESKTOP_FILE" "$eintrag"
if command -v update-desktop-database > /dev/null 2>&1; then
    update-desktop-database "$APPS" > /dev/null 2>&1 || true
fi

# --- Unit fuer den Start ueber das Icon ------------------------------------
# KEIN Autostart und kein 'enable': die Uebersicht geht nur auf, wenn sie
# ausdruecklich aufgerufen wird. Die Unit sorgt nur fuer sauberes Logging und
# eine eigene cgroup, wenn der Start ueber das Icon laeuft.
# Symlink statt Kopie: so kann die installierte Unit nicht von der im Repo
# abweichen. Eine Aenderung wirkt nach 'systemctl --user daemon-reload'.
# 'enable' scheitert weiterhin an der fehlenden [Install]-Sektion.
mkdir -p "$UNITS"
setze_symlink "$REPO/systemd/$UNIT_FILE" "$UNITS/$UNIT_FILE"
# Die Vorlage der Dauer-Sitzungen kommt daneben. Auch sie wird NICHT gestartet
# und NICHT enabled: eine Vorlage laesst sich ohne Instanznamen ohnehin nicht
# starten, und die Instanzen legt 'claude-sessionctl new <name>' an.
setze_symlink_geschuetzt "$REPO/systemd/$SESSION_UNIT_FILE" "$UNITS/$SESSION_UNIT_FILE"
if command -v systemctl > /dev/null 2>&1; then
    systemctl --user daemon-reload > /dev/null 2>&1 || true
fi

# Frueher lag hier ein Autostart-Eintrag. Er wird nicht mehr entfernt, sondern
# nur gemeldet — dieses Skript loescht nichts.
alt_autostart="$KONFIG/autostart/claude-sessions-app.desktop"
if [ -e "$alt_autostart" ]; then
    echo "Hinweis: $alt_autostart stammt aus einer aelteren Fassung."
    echo "         Die App soll NICHT von selbst aufgehen — Eintrag bitte selbst loeschen."
fi

# --- Desktop-Verknuepfung mit XFCE-Trust -----------------------------------
# Fehlertolerant: ohne Desktop-Ordner, ohne 'gio' oder ohne 'sha256sum' faellt
# nur dieser Schritt aus, die Installation gilt trotzdem als gelungen.
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || printf '')"
[ -n "$DESKTOP_DIR" ] || DESKTOP_DIR="$HOME/Desktop"
if [ -d "$DESKTOP_DIR" ] && [ "$DESKTOP_DIR" != "$HOME" ]; then
    ziel="$DESKTOP_DIR/$DESKTOP_FILE"
    schreibe_datei "$ziel" "$eintrag"
    chmod +x "$ziel"
    # XFCE startet .desktop-Dateien auf dem Schreibtisch nur, wenn sie als
    # vertrauenswuerdig markiert sind; die Pruefsumme bindet die Markierung an
    # genau diesen Inhalt. Auf anderen Oberflaechen ist der Schritt wirkungslos.
    # Der Erfolg wird geprueft, nicht angenommen: 'gio set' kann vorhanden sein
    # und trotzdem scheitern — ohne Sitzungsbus (gvfs-Metadatendienst) meldet
    # es "Setting attribute metadata::trusted not supported" und endet mit 1.
    # Ohne die Pruefung bliebe das Icon stumm unmarkiert.
    vertraut=0
    if command -v gio > /dev/null 2>&1 && command -v sha256sum > /dev/null 2>&1; then
        pruefsumme="$(sha256sum "$ziel" 2>/dev/null | cut -d' ' -f1 || printf '')"
        vertraut=1
        gio set "$ziel" metadata::xfce-exe-checksum "$pruefsumme" > /dev/null 2>&1 ||
            vertraut=0
        gio set "$ziel" metadata::trusted true > /dev/null 2>&1 || vertraut=0
    fi
    if [ "$vertraut" = 0 ]; then
        echo "Hinweis: das Desktop-Icon liess sich nicht als vertrauenswuerdig"
        echo "         markieren ('gio'/'sha256sum' fehlen, oder die Metadaten"
        echo "         werden hier nicht unterstuetzt). Unter XFCE einmal im"
        echo "         Kontextmenue 'Starter ausfuehren' bestaetigen."
    fi
else
    ziel=""
    echo "Hinweis: kein Desktop-Ordner gefunden — Desktop-Icon uebersprungen."
    echo "         Der Menue-Eintrag ist trotzdem da."
fi

# --- Zusammenfassung -------------------------------------------------------
echo
echo "Installiert:"
if [ "$icons_da" = 1 ]; then
    echo "  Icons        $ICONS/*/apps/claude-sessions.png"
fi
echo "  Startbefehl  $BIN/claude-sessions -> $REPO/bin/claude-sessions"
# Nur melden, was wirklich auf dieses Repo zeigt. Ein VERWEIS auf ein anderes
# Ziel wurde oben in Ruhe gelassen - die Zusammenfassung darf dann nicht so
# tun, als seien die Helfer dieses Repos aktiv (Pruefer 2026-08-21).
helfer_da=""; helfer_fremd=""
for h in claude-session-open claude-sessionctl claude-session-runner; do
    if [ "$(readlink -f -- "$BIN/$h" 2>/dev/null)" = "$(readlink -f -- "$REPO/bin/$h" 2>/dev/null)" ]; then
        helfer_da="$helfer_da $h"
    else
        helfer_fremd="$helfer_fremd $h"
    fi
done
[ -n "$helfer_da" ]    && echo "  Helfer      $helfer_da in $BIN"
[ -n "$helfer_fremd" ] && echo "  NICHT aktiv $helfer_fremd — $BIN zeigt woandershin (s. VERWEIS oben)"
echo "  Menue        $APPS/$DESKTOP_FILE"
if [ -n "$ziel" ]; then
    echo "  Desktop-Icon $ziel"
fi
echo "  Dienst-Unit  $UNITS/$UNIT_FILE — Start nur auf Anweisung"
if [ "$(readlink -f -- "$UNITS/$SESSION_UNIT_FILE" 2>/dev/null)" = "$(readlink -f -- "$REPO/systemd/$SESSION_UNIT_FILE" 2>/dev/null)" ]; then
    echo "  Vorlage      $UNITS/$SESSION_UNIT_FILE — nicht gestartet, nicht enabled"
else
    echo "  NICHT aktiv  $UNITS/$SESSION_UNIT_FILE zeigt woandershin (s. VERWEIS oben)"
fi
echo
echo "Jetzt starten:  systemctl --user start claude-sessions-app"

case ":${PATH:-}:" in
    *":$BIN:"*) ;;
    *)
        echo
        echo "Hinweis: $BIN liegt nicht in PATH. Menue-Eintrag, Desktop-Icon und"
        echo "         Dienst arbeiten trotzdem (sie nutzen den vollen Pfad);"
        echo "         fuer den Aufruf 'claude-sessions' im Terminal PATH ergaenzen."
        ;;
esac

# Die Dauer-Sitzungen haengen an dtach. Fehlt es, laesst sich der Dienst zwar
# anlegen, aber nicht starten - der Hinweis gehoert deshalb hierher und nicht
# erst ins Journal.
if ! command -v dtach > /dev/null 2>&1; then
    echo
    echo "Hinweis: 'dtach' fehlt. Die Uebersicht laeuft trotzdem; die Dauer-"
    echo "         Sitzungen (claude-sessionctl) brauchen es aber - unter"
    echo "         Debian/Ubuntu: apt install dtach."
fi

# Die Kontingent-Anzeige braucht das Statusleisten-Skript. Bewusst nur ein
# Hinweis: der Eintrag steht in ~/.claude/settings.json und gilt fuer JEDE
# Claude-Code-Sitzung — das aendert dieses Skript nicht ungefragt.
if ! grep -q "statusLine" "$HOME/.claude/settings.json" 2>/dev/null; then
    echo
    echo "Hinweis: fuer die Kontingent-Anzeige (Limit, Reset, Woche) fehlt noch"
    echo "         der statusLine-Eintrag in ~/.claude/settings.json — siehe"
    echo "         Abschnitt 'Kontingent-Anzeige' im README."
fi
