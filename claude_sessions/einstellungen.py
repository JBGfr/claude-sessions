"""Einstellungen der Übersicht — eine kleine JSON-Datei, tolerant gelesen.

Die Datei liegt in `~/.config/claude-sessions/settings.json` (bzw. unter
`$XDG_CONFIG_HOME`, wenn gesetzt) und lässt sich mit `CS_SETTINGS_PATH`
komplett woandershin verlegen — genau das nutzen die Tests, damit sie nie die
echte Datei des Nutzers anfassen.

Zwei Grundsätze, beide aus Schaden gelernt:

* **Lesen darf nie scheitern.** Fehlt die Datei, ist sie kaputt oder stehen
  fremde Schlüssel darin, liefert `laden()` trotzdem einen vollständigen,
  gültigen Satz Werte. Eine Übersicht, die wegen einer verunglückten
  Konfigurationsdatei gar nicht erst aufgeht, ist schlimmer als eine, die mit
  den Vorgaben startet.
* **Schreiben ist atomar.** Erst eine Tempdatei *im selben Verzeichnis*, dann
  `os.replace()`. Ein Abbruch mittendrin lässt damit entweder den alten oder
  den neuen Stand zurück, nie eine halbe Datei.

Zwei Werte gehören nicht der Übersicht, sondern dem **Watchdog**
(`wd_notify`, `wd_notify_max_per_hour`). Die App reicht sie über ein
systemd-Drop-in an dessen Unit weiter — der Weg dorthin steht am Ende dieses
Moduls (`dropin_pfad()`, `dropin_schreiben()`), damit auch er ohne Anzeige
prüfbar ist.

GTK kommt hier nicht vor: das Modul ist reine stdlib und damit ohne Anzeige
testbar (Projektregel).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

#: Erlaubte Werte für `language`. "auto" heißt: nach `$LC_ALL`/`$LANG` gehen.
SPRACHEN = ("auto", "en", "de")

#: Alle bekannten Schlüssel mit ihren Vorgaben. Was hier nicht steht, gibt es
#: nicht — fremde Schlüssel aus der Datei werden beim Laden verworfen.
VORGABEN: dict[str, Any] = {
    "language": "auto",
    "greet_name": "",
    "show_greeting": True,
    "refresh_seconds": 6,
    "max_stored_rows": 40,
    "wd_notify": True,
    #: 0 = unbegrenzt.
    "wd_notify_max_per_hour": 0,
}

#: Zahlenwerte werden geklemmt, nicht abgelehnt: ein zu kleiner Takt macht die
#: Übersicht zum Dauerläufer, ein zu großer zur Standbildanzeige.
GRENZEN: dict[str, tuple[int, int]] = {
    "refresh_seconds": (2, 60),
    "max_stored_rows": (5, 500),
    "wd_notify_max_per_hour": (0, 100),
}

#: Ein Name in der Begrüßung, nicht ein Aufsatz — länger wird abgeschnitten.
NAME_MAXLEN = 40

#: Die Watchdog-Unit, an die die Pop-up-Einstellungen gehen.
WD_UNIT = "claude-watchdog.service"

#: Name des Drop-ins in `<unit>.service.d/`. Ein eigener Name neben den
#: mitgelieferten Drop-ins des Watchdogs: die App überschreibt nur ihre
#: eigene Datei und fasst fremde nie an.
DROPIN_DATEI = "uebersteuerung.conf"

#: Kopfzeilen des Drop-ins — wer die Datei später von Hand findet, soll
#: sofort sehen, wer sie geschrieben hat und dass sie überschrieben wird.
DROPIN_KOPF = (
    "# Von der Claude-Sessions-Übersicht geschrieben "
    "(Einstellungen → Pop-ups).\n"
    "# Änderungen von Hand gehen beim nächsten Speichern verloren.\n"
)


# --------------------------------------------------------------------------
# Ort der Datei
# --------------------------------------------------------------------------

def pfad() -> Path:
    """Wo die Einstellungen liegen.

    Reihenfolge: `CS_SETTINGS_PATH` (ganze Datei, für Tests) →
    `$XDG_CONFIG_HOME/claude-sessions/settings.json` → `~/.config/…`.
    Gelesen bei jedem Aufruf, damit ein Test die Umgebung setzen kann, ohne
    das Modul neu laden zu müssen.
    """
    roh = os.environ.get("CS_SETTINGS_PATH", "").strip()
    if roh:
        return Path(roh).expanduser()
    basis = os.environ.get("XDG_CONFIG_HOME", "").strip()
    wurzel = Path(basis).expanduser() if basis else Path.home() / ".config"
    return wurzel / "claude-sessions" / "settings.json"


# --------------------------------------------------------------------------
# Wertepruefung
# --------------------------------------------------------------------------

def _als_bool(wert: Any, vorgabe: bool) -> bool:
    """Wahrheitswert aus JSON — auch aus „true"/„1", sonst die Vorgabe."""
    if isinstance(wert, bool):
        return wert
    if isinstance(wert, (int, float)) and not isinstance(wert, bool):
        return bool(wert)
    if isinstance(wert, str):
        t = wert.strip().lower()
        if t in ("true", "ja", "yes", "1", "an", "on"):
            return True
        if t in ("false", "nein", "no", "0", "aus", "off"):
            return False
    return vorgabe


def _als_zahl(wert: Any, vorgabe: int, grenzen: tuple[int, int]) -> int:
    """Ganze Zahl im erlaubten Bereich; Unsinn fällt auf die Vorgabe zurück.

    `True`/`False` gelten hier ausdrücklich **nicht** als Zahl (in Python ist
    `bool` eine `int`-Unterklasse — `True` würde sonst still zu 1 werden und
    als „Takt: 1 Sekunde" durchgehen).
    """
    unten, oben = grenzen
    if isinstance(wert, bool):
        return vorgabe
    if isinstance(wert, str):
        try:
            wert = float(wert.strip())
        except ValueError:
            return vorgabe
    if not isinstance(wert, (int, float)):
        return vorgabe
    try:
        zahl = int(round(float(wert)))
    except (OverflowError, ValueError):
        return vorgabe
    return max(unten, min(oben, zahl))


def _als_name(wert: Any) -> str:
    """Ein einzeiliger, gekürzter Name — er landet in der Begrüßung."""
    if not isinstance(wert, str):
        return ""
    sauber = "".join(z for z in wert if z.isprintable()).strip()
    return sauber[:NAME_MAXLEN]


def pruefen(roh: Mapping[str, Any] | None) -> dict[str, Any]:
    """Beliebige Eingabe auf einen vollständigen, gültigen Satz Werte bringen.

    Fehlende Schlüssel bekommen die Vorgabe, fremde fliegen raus, Zahlen
    werden geklemmt, alles Unpassende fällt auf die Vorgabe zurück.
    """
    quelle: Mapping[str, Any] = roh if isinstance(roh, Mapping) else {}
    werte = dict(VORGABEN)

    sprache = quelle.get("language", VORGABEN["language"])
    if isinstance(sprache, str) and sprache.strip().lower() in SPRACHEN:
        werte["language"] = sprache.strip().lower()

    werte["greet_name"] = _als_name(quelle.get("greet_name", ""))
    werte["show_greeting"] = _als_bool(quelle.get("show_greeting"),
                                       VORGABEN["show_greeting"])
    werte["wd_notify"] = _als_bool(quelle.get("wd_notify"),
                                   VORGABEN["wd_notify"])
    for schluessel, grenzen in GRENZEN.items():
        werte[schluessel] = _als_zahl(quelle.get(schluessel),
                                      VORGABEN[schluessel], grenzen)
    return werte


# --------------------------------------------------------------------------
# Lesen und Schreiben
# --------------------------------------------------------------------------

def laden(path: Path | None = None) -> dict[str, Any]:
    """Die Einstellungen lesen — ohne je zu scheitern.

    Fehlende Datei, kaputtes JSON, eine Liste statt eines Objekts, ein
    Verzeichnis an der Stelle der Datei: alles endet in den Vorgaben.
    """
    ziel = pfad() if path is None else path
    try:
        text = ziel.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return dict(VORGABEN)
    try:
        roh = json.loads(text)
    except (ValueError, RecursionError):
        return dict(VORGABEN)
    return pruefen(roh if isinstance(roh, dict) else None)


def speichern(werte: Mapping[str, Any] | None,
              path: Path | None = None) -> dict[str, Any]:
    """Einen kompletten Satz Werte atomar ablegen und normalisiert liefern.

    `werte` darf lückenhaft sein — was fehlt, bekommt die Vorgabe. Wer nur
    einzelne Werte ändern will, nimmt `aktualisieren()`.

    Geschrieben wird in eine Tempdatei **im Zielverzeichnis** (nur dann ist
    `os.replace()` atomar, weil beides auf demselben Dateisystem liegt);
    danach wird umbenannt. Die laufende Datei wird nie in place überschrieben.
    """
    ziel = pfad() if path is None else path
    sauber = pruefen(werte)
    text = json.dumps(sauber, ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"
    _atomar_schreiben(ziel, text)
    return sauber


def _atomar_schreiben(ziel: Path, text: str) -> None:
    """Text so ablegen, dass nie eine halbe Datei zurückbleibt.

    Erst eine Tempdatei **im Zielverzeichnis** (nur dann liegen beide auf
    demselben Dateisystem und `os.replace()` ist atomar), dann `fsync`, dann
    umbenennen. Die Zieldatei wird dabei nie in place beschrieben: ihr Inode
    wird ersetzt — ein Leser, der sie gerade offen hat, liest den alten Stand
    zu Ende, statt Bruchstücke zu sehen.
    """
    ziel.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(ziel.parent),
                               prefix=ziel.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ziel)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def aktualisieren(path: Path | None = None, **teilwerte: Any) -> dict[str, Any]:
    """Einzelne Werte ändern, den Rest so lassen, wie er in der Datei steht."""
    werte = laden(path)
    werte.update(teilwerte)
    return speichern(werte, path)


# --------------------------------------------------------------------------
# Abgeleitete Werte
# --------------------------------------------------------------------------

def greet_name(path: Path | None = None) -> str:
    """Name für die Begrüßung — Fallback-Kette, dokumentiert und getestet.

    1. `greet_name` aus der Einstellungsdatei (was der Nutzer im Dialog
       eingetragen hat, gewinnt),
    2. sonst die Umgebungsvariable `CS_GREET_NAME` (der bisherige Weg, z. B.
       über ein systemd-Drop-in gesetzt — bleibt gültig, damit bestehende
       Installationen nichts verlieren),
    3. sonst leer; dann grüßt die App ohne Namen.

    Der Name steht bewusst in keiner Datei dieses Repos.
    """
    aus_datei = _als_name(laden(path).get("greet_name"))
    if aus_datei:
        return aus_datei
    return _als_name(os.environ.get("CS_GREET_NAME"))


def sprache(path: Path | None = None) -> str:
    """Eingestellte Sprache („auto", „en" oder „de")."""
    return str(laden(path).get("language") or VORGABEN["language"])


# --------------------------------------------------------------------------
# Weitergabe an den Watchdog (systemd-Drop-in)
# --------------------------------------------------------------------------
#
# Die beiden Pop-up-Werte wirken nicht in dieser App, sondern im Daemon des
# Watchdogs: dort heißen sie `CW_NOTIFY` und `CW_NOTIFY_MAX_PER_HOUR` und
# werden beim Start aus der Umgebung gelesen. Der einzige Weg, einer
# systemd-Unit dauerhaft eine Umgebungsvariable mitzugeben, ist ein Drop-in —
# deshalb schreibt die Übersicht eine eigene kleine `.conf` daneben, statt in
# die (per Symlink aus dem Watchdog-Repo stammende) Unit zu schreiben.

def dropin_pfad() -> Path:
    """Ort des Drop-ins für die Watchdog-Unit.

    Reihenfolge wie bei `pfad()`: `CS_WD_DROPIN_PATH` (ganze Datei, für
    Tests) → `$XDG_CONFIG_HOME/systemd/user/…` → `~/.config/systemd/user/…`.
    """
    roh = os.environ.get("CS_WD_DROPIN_PATH", "").strip()
    if roh:
        return Path(roh).expanduser()
    basis = os.environ.get("XDG_CONFIG_HOME", "").strip()
    wurzel = Path(basis).expanduser() if basis else Path.home() / ".config"
    return wurzel / "systemd" / "user" / (WD_UNIT + ".d") / DROPIN_DATEI


def wd_unit_pfad(path: Path | None = None) -> Path:
    """Die Unit, zu der das Drop-in gehört: Nachbar des `.d`-Ordners."""
    ziel = dropin_pfad() if path is None else path
    return ziel.parent.parent / WD_UNIT


def wd_unit_vorhanden(path: Path | None = None) -> bool:
    """Gibt es die Watchdog-Unit überhaupt?

    Ohne sie wäre das Drop-in ein Zettel für einen Dienst, den es nicht gibt
    (und `daemon-reload` würde ihn auch nicht herbeizaubern). Der
    Einstellungsdialog überspringt den Watchdog-Teil dann still — die
    Übersicht selbst funktioniert auch ohne Watchdog.

    Ein *toter* Symlink zählt als vorhanden: er ist ein Hinweis auf eine
    Installation, die gerade woanders liegt, nicht auf deren Abwesenheit.
    """
    unit = wd_unit_pfad(path)
    return unit.exists() or unit.is_symlink()


def dropin_inhalt(werte: Mapping[str, Any] | None) -> str:
    """Der vollständige Text des Drop-ins zu einem Satz Einstellungen.

    `CW_NOTIFY` liest der Watchdog als „alles außer 0/false/no ist an"; hier
    wird bewusst die knappste eindeutige Form geschrieben (`1`/`0`).
    """
    sauber = pruefen(werte)
    return (
        DROPIN_KOPF
        + "[Service]\n"
        + "Environment=CW_NOTIFY=%d\n" % (1 if sauber["wd_notify"] else 0)
        + "Environment=CW_NOTIFY_MAX_PER_HOUR=%d\n"
          % sauber["wd_notify_max_per_hour"]
    )


def dropin_schreiben(werte: Mapping[str, Any] | None,
                     path: Path | None = None) -> bool:
    """Drop-in schreiben, wenn es sich ändert; `True` = geschrieben.

    Der Vergleich vorher ist kein Geiz, sondern der Unterschied zwischen
    „Einstellungen gespeichert" und „Watchdog neu gestartet": nur wer die
    Datei wirklich anfasst, muss den Daemon anfassen. Wer im Dialog nur die
    Sprache ändert, soll keinen laufenden Watchdog unterbrechen.
    """
    ziel = dropin_pfad() if path is None else path
    text = dropin_inhalt(werte)
    try:
        if ziel.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass  # fehlt, unlesbar oder kaputt: neu schreiben
    _atomar_schreiben(ziel, text)
    return True
