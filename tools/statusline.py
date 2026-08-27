#!/usr/bin/env python3
"""Statusleiste für Claude Code — und Quelle der echten Limitwerte.

Claude Code ruft dieses Skript bei jeder Aktualisierung auf und reicht die
Sitzungsdaten als JSON über stdin herein. Darin stehen unter `rate_limits`
genau die Zahlen, die `/usage` anzeigt: Auslastung und Zurücksetzung des
Fünf-Stunden- und des Sieben-Tage-Fensters.

Zwei Aufgaben:

1. Die Werte nach ``~/.local/state/claude-sessions/usage.json`` schreiben.
   Die Übersicht liest sie von dort. Vorher hat sie den Verbrauch aus den
   Transkripten *rekonstruiert* — das konnte prinzipiell nicht stimmen, weil
   Desktop-App, Browser und andere Geräte dasselbe Kontingent belasten, ohne
   hier eine Zeile zu hinterlassen (gemessen: 12 Minuten Fensterversatz).
2. Eine Zeile ausgeben, die Claude Code unten anzeigt.

Laut Doku kostet das keine Tokens — es läuft rein lokal. Deshalb muss es
aber auch schnell sein: Claude Code bricht einen noch laufenden Aufruf ab,
wenn schon die nächste Aktualisierung ansteht. Kein Subprozess, kein `git`,
keine Netzwerkzugriffe; der Zweig kommt direkt aus `.git/HEAD`.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

STATE = Path.home() / ".local/state/claude-sessions/usage.json"

#: Nicht bei jeder Aktualisierung schreiben — nur wenn sich etwas geändert hat
#: oder die Datei alt ist. Spart Schreibzugriffe bei schnellen Neuzeichnungen.
MIN_WRITE_INTERVAL = 15


def git_branch(cwd: str) -> str:
    """Aktueller Zweig, ohne `git` aufzurufen."""
    p = Path(cwd or ".")
    for verzeichnis in [p, *p.parents][:6]:
        head = verzeichnis / ".git" / "HEAD"
        try:
            text = head.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text.startswith("ref: refs/heads/"):
            return text[len("ref: refs/heads/"):]
        return text[:7]          # losgelöster HEAD: verkürzter Commit
    return ""


def kurz_pfad(cwd: str) -> str:
    home = str(Path.home())
    if cwd == home:
        return "~"
    return "~" + cwd[len(home):] if cwd.startswith(home + "/") else (cwd or "?")


def merken(limits: dict, model: str) -> None:
    """Limitwerte wegschreiben — atomar, damit die App nie halbe Dateien sieht."""
    if not limits:
        return
    neu = {"written_at": time.time(), "model": model, "rate_limits": limits}
    try:
        alt = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        alt = None
    if (alt and alt.get("rate_limits") == limits
            and time.time() - float(alt.get("written_at") or 0) < MIN_WRITE_INTERVAL):
        return
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE.with_suffix(".tmp.%d" % os.getpid())
        tmp.write_text(json.dumps(neu, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE)
    except OSError:
        pass


def prozent(wert) -> str:
    try:
        return "%d %%" % round(float(wert))
    except (TypeError, ValueError):
        return "—"


def uhrzeit(epoch) -> str:
    try:
        return time.strftime("%H:%M", time.localtime(float(epoch)))
    except (TypeError, ValueError, OSError):
        return "—"


def main() -> int:
    try:
        d = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0
    if not isinstance(d, dict):
        return 0

    model = str((d.get("model") or {}).get("display_name") or "")
    cwd = str((d.get("workspace") or {}).get("current_dir")
              or d.get("cwd") or "")
    limits = d.get("rate_limits")
    limits = limits if isinstance(limits, dict) else {}
    merken(limits, model)

    kopf = [t for t in (model, kurz_pfad(cwd), git_branch(cwd)) if t]

    unten = []
    fuenf = limits.get("five_hour") or {}
    if fuenf:
        unten.append("Limit %s" % prozent(fuenf.get("used_percentage")))
        unten.append("Reset %s" % uhrzeit(fuenf.get("resets_at")))
    woche = limits.get("seven_day") or {}
    if woche:
        unten.append("Woche %s" % prozent(woche.get("used_percentage")))
    ctx = (d.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        unten.append("Kontext %s" % prozent(ctx))

    print("  ·  ".join(kopf))
    if unten:
        print("  ·  ".join(unten))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Eine Statusleiste darf niemals eine Sitzung stoeren.
        sys.exit(0)
