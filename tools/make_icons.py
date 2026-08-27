"""Erzeugt alle Icon-Groessen aus dem Master-Icon.

Quelle ist `assets/app-icon-master.png` — das fertige App-Icon (cremefarbenes
Maskottchen auf Terrakotta, abgerundete Kachel). Frueher wurde das Icon hier
aus einer Pixelmatrix gezeichnet; diese Fassung skaliert nur noch, damit es
genau eine Wahrheit gibt. Die alte Zeichenroutine steht in der Git-Historie.

Skaliert wird proportional mit Lanczos und ohne Verzerrung: das Master ist
quadratisch, die Zielgroessen sind es auch.

Aufruf:  python3 tools/make_icons.py
Schreibt nach assets/: icon-{48,64,128,256}.png und banner.png
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets"
MASTER = ASSETS / "app-icon-master.png"

#: Groessen fuer den hicolor-Icon-Baum.
SIZES = (48, 64, 128, 256)

#: Hoehe des kleinen Icons in der Kopfzeile der App.
BANNER_HEIGHT = 26


def scale(target: pathlib.Path, size: int) -> None:
    subprocess.run(
        ["convert", str(MASTER), "-filter", "Lanczos",
         "-resize", "%dx%d" % (size, size),
         "-strip", str(target)],
        check=True,
    )
    print("%-22s %dx%d" % (target.name, size, size))


def main() -> int:
    if not MASTER.exists():
        print("Master-Icon fehlt: %s" % MASTER, file=sys.stderr)
        return 1
    if not shutil.which("convert"):
        print("ImageMagick ('convert') nicht gefunden", file=sys.stderr)
        return 1

    for size in SIZES:
        scale(ASSETS / ("icon-%d.png" % size), size)
    scale(ASSETS / "banner.png", BANNER_HEIGHT)

    # Die alte SVG-Fassung zeigte noch das gezeichnete Maskottchen auf
    # dunklem Grund. Bliebe sie liegen, hoelte der Icon-Cache bei grossen
    # Groessen weiter das alte Motiv.
    veraltet = ASSETS / "claude-sessions.svg"
    if veraltet.exists():
        veraltet.unlink()
        print("%-22s entfernt (ersetzt durch das Master-PNG)" % veraltet.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
