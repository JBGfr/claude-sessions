"""GTK3-Oberfläche: dunkle Übersicht über alle Claude-Code-Sessions."""
from __future__ import annotations

import signal
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, GLibUnix, Gtk, Pango  # noqa: E402

from . import actions, data, demo, einstellungen, texte  # noqa: E402

APP_ID = "de.jbgfr.ClaudeSessions"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
#: Takt der Aktualisierung. Jeder Durchlauf startet `claude agents` als
#: Subprozess und liest die geänderten Transkripte — bei 3 s kostete das als
#: Dauerläufer rund 9 % einer CPU, ohne dass jemand hinsieht. Sessions ändern
#: sich nicht im Sekundentakt; 6 s sind der vom Nutzer gewählte Kompromiss.
#:
#: Seit dem Einstellungsdialog ist das nur noch der **Rückfallwert**: gilt,
#: solange in `settings.json` nichts anderes steht (`refresh_seconds`).
REFRESH_SECONDS = 6

#: Takt, solange kein Fenster sichtbar ist (minimiert oder auf einem anderen
#: Arbeitsfläche). Dann wird gar nicht geladen, nur nachgesehen, ob es wieder
#: sichtbar ist.
IDLE_POLL_SECONDS = 2

#: Länge der Liste unter „Zuletzt aktiv"; ebenfalls nur der Rückfallwert
#: (`max_stored_rows` in den Einstellungen).
MAX_STORED_ROWS = 40

#: Die Ansichten der Seitenleiste: Schlüssel, **Textschlüssel**, gezeigte
#: Gruppe. `None` heißt „alle Gruppen". Reihenfolge = Reihenfolge in der
#: Leiste. Hier steht bewusst nicht die Beschriftung selbst: die wird erst
#: beim Aufbau des Fensters über `texte.t()` geholt, denn beim Import des
#: Moduls steht die Sprache noch gar nicht fest.
VIEWS = (
    ("live", "nav.live", data.GROUP_LIVE),
    ("queue", "nav.queue", data.GROUP_QUEUE),
    ("stored", "nav.stored", data.GROUP_STORED),
    ("all", "nav.all", None),
)
VIEW_GROUP = {schluessel: gruppe for schluessel, _text, gruppe in VIEWS}
VIEW_TEXT = {schluessel: text for schluessel, text, _gruppe in VIEWS}

CSS = b"""
/* Farbwerte aus der laufenden Claude-Desktop-App, Pixel fuer Pixel aus einem
   Screenshot gemessen (2026-08-18). Bewusst NICHT die Token-Werte aus
   app.asar: die sind eine Spur waermer als das, was am Bildschirm ankommt
   (#141413 statt #151515). Verglichen wird, was man sieht.
   Wer hier eine Farbe braucht, nimmt eine aus dieser Liste. */
@define-color c_canvas #151515;   /* Inhaltsflaeche */
@define-color c_side   #111111;   /* Seitenleiste und Titelleiste */
@define-color c_card   #1f1f1f;   /* erhoehte Flaeche, Karte */
@define-color c_hover  #262626;
@define-color c_active #343434;   /* aktives Element in der Seitenleiste */
@define-color c_btn    #353535;   /* Knopfflaeche - ohne Rahmen, reine Flaeche */
@define-color c_line   #dedcd1;   /* nur mit alpha() benutzt, fuer feine Kanten */
@define-color c_fg     #f0efec;   /* heller Text: Titel, Knopfbeschriftung */
@define-color c_txt    #c3c2b7;   /* Fliesstext */
@define-color c_dim    #96958d;   /* gedaempft: Zeiten, Abschnitte */
@define-color c_brand  #d97757;   /* --accent-brand */
@define-color c_ok     #65bb30;   /* --success-000 */
@define-color c_info   #74abe2;   /* --accent-000 */
@define-color c_err    #dd5353;   /* --danger-100 */
/* Fuer "wartet" gibt es in der Desktop-Palette keinen Ton; dieser ist aus dem
   warmen Grundton abgeleitet, damit er nicht wie ein Fremdkoerper wirkt. */
@define-color c_warn   #d3a04a;

* {
    /* "Anthropic Sans" liegt nur im Bundle der Desktop-App und wird hier
       NICHT mitgeliefert (Lizenz). Ist sie auf dem System installiert, wird
       sie genommen; sonst faellt es auf die Systemschrift zurueck. */
    font-family: "Anthropic Sans", Inter, "Noto Sans", Cantarell, sans-serif;
    /* Groesse in px, nicht in pt: pt haengt an der DPI-Einstellung und war
       damit je nach Bildschirm eine andere Schriftgroesse als im Vorbild. */
    font-size: 13px;
    outline: none;
}

window { background-color: @c_canvas; color: @c_txt; }

headerbar {
    background: @c_side;
    border-bottom: none;
    box-shadow: none;
    min-height: 40px;
    padding: 0 8px;
}
headerbar .hb-title { color: @c_txt; font-weight: 600; }
headerbar button.titlebutton {
    background: transparent;
    border: none;
    box-shadow: none;
    color: @c_dim;
    min-width: 26px;
    min-height: 26px;
    border-radius: 8px;
    -gtk-icon-shadow: none;
}
headerbar button.titlebutton:hover { background: @c_hover; color: @c_fg; }
headerbar button.titlebutton:active { background: @c_active; }

/* --- Seitenleiste ---------------------------------------------------- */

.side {
    background: @c_side;
    border-right: 1px solid alpha(@c_line, 0.06);
}
.side-sect {
    color: @c_dim;
    font-size: 12px;
}
button.nav {
    background: transparent;
    border: none;
    box-shadow: none;
    border-radius: 8px;
    padding: 0 10px;
    min-height: 26px;
    color: @c_txt;
    font-weight: normal;
}
button.nav image { color: @c_dim; }
button.nav.nav-on image { color: @c_txt; }
button.nav:hover { background: @c_hover; }
button.nav.nav-on { background: @c_active; color: @c_fg; }
.nav-count { color: @c_dim; font-size: 12px; }
button.nav.nav-on .nav-count { color: @c_txt; }

/* --- Inhaltsspalte ---------------------------------------------------- */

.content { background: @c_canvas; }
.chead { padding: 14px 18px 8px 18px; }
.header-title { color: @c_fg; font-weight: 600; font-size: 16px; }
.header-sub { color: @c_dim; font-size: 12px; }

list { background: transparent; }
row { background: transparent; padding: 0; }
row:hover, row:selected { background: transparent; }

.card {
    background: @c_card;
    border: 1px solid alpha(@c_line, 0.07);
    border-radius: 14px;
    padding: 10px 14px;
}
row:hover .card { background: @c_hover; border-color: alpha(@c_line, 0.12); }

.sect {
    color: @c_dim;
    font-size: 12px;
}

.title { color: @c_fg; font-weight: 600; }
.dim { color: @c_dim; font-size: 12px; }
.time { color: @c_dim; font-size: 12px; }

.dot-busy { color: @c_brand; }
.dot-idle { color: @c_ok; }
.dot-dead { color: alpha(@c_line, 0.22); }
.dot-queue { color: @c_info; }

.pill {
    border-radius: 99px;
    padding: 1px 9px;
    font-size: 11px;
}
.pill-busy { background: alpha(@c_brand, 0.16); color: @c_brand; }
.pill-idle { background: alpha(@c_ok, 0.14);    color: @c_ok; }
.pill-wd   { background: alpha(@c_info, 0.14);  color: @c_info; }
.pill-warn { background: alpha(@c_warn, 0.16);  color: @c_warn; }
.pill-err  { background: alpha(@c_err, 0.16);   color: @c_err; }

/* --- Knoepfe ---------------------------------------------------------- */

button.act {
    background: @c_btn;
    border: none;
    border-radius: 10px;
    box-shadow: none;
    color: @c_fg;
    padding: 0 14px;
    min-height: 32px;
}
button.act:hover { background: #3f3f3f; }
button.act:active { background: @c_active; }

button.hb {
    background: transparent;
    border: none;
    box-shadow: none;
    border-radius: 8px;
    color: @c_dim;
    padding: 4px 8px;
}
button.hb:hover { background: @c_hover; color: @c_fg; }
button.hb:checked { background: @c_active; color: @c_fg; }

/* --- Statuszeile und Meldungen ---------------------------------------- */

.footer { padding: 8px 12px; }
.footer-ok { color: @c_ok; font-size: 12px; }
.footer-off { color: @c_dim; font-size: 12px; }
.footer-msg { color: @c_warn; font-size: 12px; }

/* --- Begruessung -------------------------------------------------------- */

.greet-star { color: @c_brand; font-size: 22px; }
.greet {
    font-family: "Anthropic Serif", Georgia, serif;
    font-size: 26px;
    color: @c_fg;
}

/* --- Kontingentblock ----------------------------------------------------
   1:1 nach dem Nutzungs-Dialog der Desktop-App gemessen (2026-08-18):
   Track #032042, Fuellung #2a78d6, 7 px hoch, Titel #f0efec,
   Nebenzeilen #c3c2b7, "X % verwendet" rechts neben dem Balken. */

.usage {
    background: transparent;
    border-bottom: 1px solid alpha(@c_line, 0.06);
    padding: 8px 18px 18px 18px;
}
.usage-title { color: @c_fg; font-size: 13px; }
.usage-sub { color: @c_txt; font-size: 12px; }
.usage-pct { color: @c_txt; font-size: 12px; }
.usage-dim { color: @c_dim; font-size: 12px; }
progressbar { padding: 0; }
progressbar trough {
    background: #032042;
    border: none;
    border-radius: 99px;
    min-height: 7px;
}
progressbar progress {
    background: #2a78d6;
    border: none;
    border-radius: 99px;
    min-height: 7px;
}

/* --- Rollbalken ------------------------------------------------------- */

scrollbar { background: transparent; border: none; }
scrollbar slider {
    background: alpha(@c_line, 0.14);
    border: none;
    border-radius: 99px;
    min-width: 7px;
    margin: 2px;
}
scrollbar slider:hover { background: alpha(@c_line, 0.24); }

/* --- Menues und Dialoge ----------------------------------------------- */

menu, .menu {
    background: @c_card;
    border: 1px solid alpha(@c_line, 0.10);
    border-radius: 10px;
    padding: 4px;
}
menuitem { border-radius: 6px; padding: 4px 10px; color: @c_txt; }
menuitem:hover { background: @c_hover; color: @c_fg; }
messagedialog { background: @c_canvas; color: @c_txt; }

/* --- Einstellungsdialog -------------------------------------------------
   Kein einziger neuer Farbwert: Flaeche wie die Inhaltsspalte, Eingabefelder
   wie eine Karte, Knoepfe wie ueberall (.act). */

dialog, window.dialog { background: @c_canvas; color: @c_txt; }
dialog headerbar { background: @c_side; }
.einst-sect { color: @c_dim; font-size: 12px; font-weight: 600; }
.einst-hint { color: @c_dim; font-size: 12px; }

entry, spinbutton {
    background: @c_card;
    color: @c_fg;
    border: 1px solid alpha(@c_line, 0.10);
    border-radius: 8px;
    box-shadow: none;
    padding: 4px 8px;
    min-height: 28px;
}
entry:focus, spinbutton:focus { border-color: alpha(@c_line, 0.24); }
entry:disabled { color: @c_dim; }
spinbutton button {
    background: transparent;
    border: none;
    box-shadow: none;
    color: @c_dim;
}
spinbutton button:hover { color: @c_fg; }

combobox button.combo {
    background: @c_btn;
    border: none;
    border-radius: 8px;
    box-shadow: none;
    color: @c_fg;
    padding: 2px 10px;
    min-height: 28px;
}
combobox button.combo:hover { background: #3f3f3f; }

switch {
    background: @c_btn;
    border: none;
    box-shadow: none;
    border-radius: 99px;
}
switch:checked { background: @c_brand; }
switch slider {
    background: @c_fg;
    border: none;
    border-radius: 99px;
}
"""

_DOT_CLASSES = ("dot-busy", "dot-idle", "dot-dead", "dot-queue")
_PILL_CLASSES = ("pill-busy", "pill-idle", "pill-wd", "pill-warn", "pill-err")


def _swap_class(widget: Gtk.Widget, candidates: tuple, wanted: str) -> None:
    ctx = widget.get_style_context()
    for c in candidates:
        if c != wanted:
            ctx.remove_class(c)
    ctx.add_class(wanted)


class SessionRow(Gtk.ListBoxRow):
    """Eine Karte je Session; wird bei jedem Refresh in place aktualisiert."""

    def __init__(self, app: "SessionsApp", info: data.SessionInfo):
        super().__init__()
        self.app = app
        self.info = info
        self.set_activatable(False)

        pad = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        pad.set_margin_start(12)
        pad.set_margin_end(12)
        pad.set_margin_top(3)
        pad.set_margin_bottom(3)
        self.add(pad)

        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        card.get_style_context().add_class("card")
        pad.pack_start(card, True, True, 0)

        self.dot = Gtk.Label(label="●")
        self.dot.set_valign(Gtk.Align.CENTER)
        card.pack_start(self.dot, False, False, 0)

        mid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        card.pack_start(mid, True, True, 0)

        first = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mid.pack_start(first, False, False, 0)
        self.title = Gtk.Label(xalign=0)
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.title.get_style_context().add_class("title")
        first.pack_start(self.title, False, True, 0)

        self.state_pill = Gtk.Label()
        self.state_pill.get_style_context().add_class("pill")
        self.state_pill.set_no_show_all(True)
        first.pack_start(self.state_pill, False, False, 0)

        self.wd_pill = Gtk.Label()
        self.wd_pill.get_style_context().add_class("pill")
        self.wd_pill.set_no_show_all(True)
        # Ohne Ellipsize wuerde eine lange Pill den (schrumpfbaren) Titel
        # auf null druecken und die Mindestfensterbreite hochtreiben.
        self.wd_pill.set_ellipsize(Pango.EllipsizeMode.END)
        self.wd_pill.set_max_width_chars(40)
        first.pack_start(self.wd_pill, False, False, 0)

        self.sub = Gtk.Label(xalign=0)
        self.sub.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.sub.get_style_context().add_class("dim")
        mid.pack_start(self.sub, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        right.set_valign(Gtk.Align.CENTER)
        card.pack_end(right, False, False, 0)

        self.time = Gtk.Label(xalign=1)
        self.time.get_style_context().add_class("time")
        right.pack_start(self.time, False, False, 0)

        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btns.set_halign(Gtk.Align.END)
        right.pack_start(btns, False, False, 0)

        self.primary = Gtk.Button(label=texte.t("knopf.oeffnen"))
        self.primary.get_style_context().add_class("act")
        self.primary.set_no_show_all(True)
        self.primary.connect("clicked", self._on_primary)
        btns.pack_start(self.primary, False, False, 0)

        self.more = Gtk.Button(label="⋮")
        self.more.get_style_context().add_class("act")
        self.more.connect("clicked", self._on_menu)
        btns.pack_start(self.more, False, False, 0)

        self.show_all()
        self.update(info)

    # -- Anzeige ----------------------------------------------------------

    def update(self, info: data.SessionInfo) -> None:
        self.info = info
        self.title.set_text(info.title or info.id[:8])

        parts = [data.short_path(info.cwd)]
        if info.msgs:
            parts.append(texte.t("karte.nachrichten", n=info.msgs))
        if info.tokens:
            parts.append(texte.t("karte.tokens",
                                 wert=data.fmt_tokens(info.tokens)))
        if info.pid:
            parts.append(texte.t("karte.pid", pid=info.pid))
        self.sub.set_text("  ·  ".join(parts))

        self.time.set_text(data.rel_time(info.mtime))

        if info.group == data.GROUP_QUEUE:
            _swap_class(self.dot, _DOT_CLASSES, "dot-queue")
        elif not info.live:
            _swap_class(self.dot, _DOT_CLASSES, "dot-dead")
        elif info.live_status == "busy":
            _swap_class(self.dot, _DOT_CLASSES, "dot-busy")
        else:
            _swap_class(self.dot, _DOT_CLASSES, "dot-idle")

        if info.live:
            busy = info.live_status == "busy"
            self.state_pill.set_text(texte.t("pill.arbeitet" if busy
                                            else "pill.bereit"))
            _swap_class(self.state_pill, _PILL_CLASSES,
                        "pill-busy" if busy else "pill-idle")
            self.state_pill.set_visible(True)
        else:
            self.state_pill.set_visible(False)

        if info.wd_task_id:
            unbekannt = texte.t("karte.unbekannt")
            status_de = data.WD_STATUS_DE.get(info.wd_status or "",
                                              info.wd_status or unbekannt)
            mode_de = data.WD_MODE_DE.get(info.wd_mode or "",
                                          info.wd_mode or unbekannt)
            text = texte.t("karte.watchdog", modus=mode_de, status=status_de)
            if info.wd_error:
                text += texte.t("karte.watchdog_fehler", fehler=info.wd_error)
            self.wd_pill.set_text(text)
            self.wd_pill.set_tooltip_text(text)
            if info.wd_status in ("stalled", "failed"):
                pill = "pill-err"
            elif info.wd_status in ("blocked", "waiting_for_limit") or info.wd_error:
                pill = "pill-warn"
            else:
                pill = "pill-wd"
            _swap_class(self.wd_pill, _PILL_CLASSES, pill)
            self.wd_pill.set_visible(True)
        else:
            self.wd_pill.set_visible(False)

        if info.group == data.GROUP_QUEUE:
            self.primary.set_visible(False)
        elif info.live:
            # Dauer-Dienste laufen in einem dtach-Socket und haben kein
            # Fenster — dort waere "Zeigen" ein Knopf, der nie funktioniert.
            self.primary.set_label(texte.t("knopf.anhaengen" if info.service
                                           else "knopf.zeigen"))
            self.primary.set_visible(True)
        else:
            self.primary.set_label(texte.t("knopf.oeffnen"))
            self.primary.set_visible(True)

    # -- Aktionen ---------------------------------------------------------

    def _on_primary(self, _btn: Gtk.Button) -> None:
        info = self.info
        if info.live and info.service:
            self.app.im_hintergrund(
                lambda: actions.attach_session(info.service),
                lambda ok: self.app.flash(
                    texte.t("meldung.angehaengt", dienst=info.service) if ok
                    else texte.t("meldung.kein_terminal")))
        elif info.live and info.pid:
            def worker() -> None:
                ok = actions.focus_session_window(info.pid)
                if not ok:
                    GLib.idle_add(self.app.flash,
                                  texte.t("meldung.kein_fenster", pid=info.pid))
            threading.Thread(target=worker, daemon=True).start()
        else:
            self.app.im_hintergrund(
                lambda: actions.open_session(info.id),
                lambda ok: self.app.flash(
                    texte.t("meldung.oeffnet") if ok
                    else texte.t("meldung.kein_opener")))

    def _on_menu(self, btn: Gtk.Button) -> None:
        info = self.info
        menu = Gtk.Menu()

        def item(schluessel: str, cb) -> None:
            it = Gtk.MenuItem(label=texte.t(schluessel))
            it.connect("activate", lambda *_: cb())
            menu.append(it)

        def sep() -> None:
            if menu.get_children():
                menu.append(Gtk.SeparatorMenuItem())

        if info.live and not info.wd_task_id:
            item("menu.wd_beobachten",
                 lambda: self.app.run_watchdog("attach", info.id))
        if info.wd_task_id:
            if info.wd_status == "paused":
                item("menu.wd_fortsetzen",
                     lambda: self.app.run_watchdog("resume", info.wd_task_id))
            elif info.wd_status not in ("done", "failed"):
                item("menu.wd_pausieren",
                     lambda: self.app.run_watchdog("pause", info.wd_task_id))
            item("menu.wd_logs",
                 lambda: self.app.im_hintergrund(
                     lambda: actions.show_watchdog_logs(info.wd_task_id)))
            if info.wd_status == "running":
                # Die CLI verweigert rm bei laufenden Tasks ohne --force —
                # deshalb Rueckfrage und dann explizit erzwingen.
                item("menu.wd_entfernen_nachfrage",
                     lambda: self.app.confirm_wd_remove(info))
            else:
                item("menu.wd_entfernen",
                     lambda: self.app.run_watchdog("rm", info.wd_task_id))

        if info.cwd:
            sep()
            item("menu.ordner_oeffnen",
                 lambda: self.app.im_hintergrund(
                     lambda: actions.open_folder(info.cwd)))
        if not info.id.startswith("wd:"):
            item("menu.id_kopieren", lambda: self.app.copy_text(info.id))

        if info.live and info.service:
            sep()
            # Bei einem Dauer-Dienst waere SIGTERM keine Beendigung: der
            # Runner reicht 143 durch, Restart=on-failure greift, und die
            # Sitzung ist nach zehn Sekunden wieder da.
            item("menu.dienst_stoppen",
                 lambda: self.app.confirm_service_stop(info))
        elif info.live and info.pid:
            sep()
            item("menu.prozess_beenden",
                 lambda: self.app.confirm_terminate(info))

        menu.attach_to_widget(btn, None)
        # Menü nach dem Zuklappen wieder wegräumen, sonst sammeln sich an
        # jedem ⋮-Button verwaiste Menüs an.
        menu.connect("deactivate",
                     lambda m: GLib.idle_add(m.destroy))
        menu.show_all()
        menu.popup_at_widget(btn, Gdk.Gravity.SOUTH_EAST,
                             Gdk.Gravity.NORTH_EAST, None)


class EinstellungenDialog(Gtk.Dialog):
    """Einstellungen der Übersicht — Sprache, Begrüßung, Takt, Pop-ups.

    Der Dialog **liest und schreibt nichts selbst**: er liest die Werte
    einmal über `einstellungen.laden()` und gibt sie über `werte()` wieder
    heraus. Gespeichert wird in `SessionsApp`, denn dort hängt auch dran,
    was danach passiert (Watchdog, Neustart). So bleibt hier reine Anzeige.

    Grenzen und Vorgaben kommen aus `einstellungen.GRENZEN` — die
    Spinbuttons können also gar nicht erst etwas anbieten, was beim Speichern
    wieder weggeklemmt würde.
    """

    def __init__(self, app: "SessionsApp"):
        super().__init__(title=texte.t("einst.titel"),
                         transient_for=app.window, modal=True)
        self.app = app
        self.vorher = einstellungen.laden()
        self.set_default_size(460, -1)

        rahmen = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        rahmen.set_margin_top(14)
        rahmen.set_margin_bottom(8)
        rahmen.set_margin_start(18)
        rahmen.set_margin_end(18)
        self.get_content_area().pack_start(rahmen, True, True, 0)

        # -- Anzeige ------------------------------------------------------
        gitter = self._gruppe(rahmen, "einst.gruppe.anzeige")
        self.sprache = Gtk.ComboBoxText()
        for code in einstellungen.SPRACHEN:
            self.sprache.append(code, texte.t("einst.sprache.%s" % code))
        self.sprache.set_active_id(
            str(self.vorher.get("language", "auto")))
        if self.sprache.get_active_id() is None:
            self.sprache.set_active_id("auto")
        self._zeile(gitter, 0, "einst.sprache", self.sprache)

        self.begruessung = Gtk.Switch()
        self.begruessung.set_active(bool(self.vorher.get("show_greeting")))
        self._zeile(gitter, 1, "einst.begruessung", self.begruessung)

        self.name = Gtk.Entry()
        self.name.set_placeholder_text(texte.t("einst.name_platzhalter"))
        self.name.set_max_length(einstellungen.NAME_MAXLEN)
        self.name.set_width_chars(18)
        self.name.set_text(str(self.vorher.get("greet_name", "")))
        # Ein Namensfeld ohne Begrüßung wäre ein Feld ohne Wirkung.
        self.name.set_sensitive(self.begruessung.get_active())
        self.begruessung.connect(
            "notify::active",
            lambda *_: self.name.set_sensitive(self.begruessung.get_active()))
        self._zeile(gitter, 2, "einst.name", self.name)

        # -- Aktualisierung ------------------------------------------------
        gitter = self._gruppe(rahmen, "einst.gruppe.aktualisierung")
        self.takt = self._zahlenfeld("refresh_seconds")
        self._zeile(gitter, 0, "einst.takt", self.takt)
        self.zeilen = self._zahlenfeld("max_stored_rows")
        self._zeile(gitter, 1, "einst.zeilen", self.zeilen)

        # -- Pop-ups -------------------------------------------------------
        gitter = self._gruppe(rahmen, "einst.gruppe.popups")
        self.wd_notify = Gtk.Switch()
        self.wd_notify.set_active(bool(self.vorher.get("wd_notify")))
        self._zeile(gitter, 0, "einst.wd_notify", self.wd_notify)
        self.wd_max = self._zahlenfeld("wd_notify_max_per_hour")
        self._zeile(gitter, 1, "einst.wd_notify_max", self.wd_max)
        rahmen.pack_start(self._hinweis("einst.wd_hinweis"), False, False, 0)

        rahmen.pack_start(self._hinweis("einst.neustart_hinweis"),
                          False, False, 0)

        for schluessel, antwort in (
                ("einst.abbrechen", Gtk.ResponseType.CANCEL),
                ("einst.speichern", Gtk.ResponseType.OK),
                ("einst.uebernehmen", Gtk.ResponseType.APPLY)):
            knopf = self.add_button(texte.t(schluessel), antwort)
            knopf.get_style_context().add_class("act")
        self.show_all()

    # -- Bausteine --------------------------------------------------------

    @staticmethod
    def _hinweis(schluessel: str) -> Gtk.Label:
        """Gedämpfter Fließtext unter einer Gruppe."""
        label = Gtk.Label(label=texte.t(schluessel), xalign=0)
        label.get_style_context().add_class("einst-hint")
        label.set_line_wrap(True)
        label.set_max_width_chars(52)
        return label

    @staticmethod
    def _gruppe(rahmen: Gtk.Box, schluessel: str) -> Gtk.Grid:
        """Überschrift + Gitter für eine Gruppe von Einstellungen."""
        kopf = Gtk.Label(label=texte.t(schluessel), xalign=0)
        kopf.get_style_context().add_class("einst-sect")
        rahmen.pack_start(kopf, False, False, 0)
        gitter = Gtk.Grid(column_spacing=14, row_spacing=8)
        gitter.set_margin_start(4)
        rahmen.pack_start(gitter, False, False, 0)
        return gitter

    @staticmethod
    def _zeile(gitter: Gtk.Grid, zeile: int, schluessel: str,
               widget: Gtk.Widget) -> None:
        """Eine Zeile „Beschriftung links, Bedienelement rechts"."""
        label = Gtk.Label(label=texte.t(schluessel), xalign=0)
        label.set_hexpand(True)
        label.set_line_wrap(True)
        label.set_max_width_chars(34)
        gitter.attach(label, 0, zeile, 1, 1)
        widget.set_halign(Gtk.Align.END)
        widget.set_valign(Gtk.Align.CENTER)
        gitter.attach(widget, 1, zeile, 1, 1)

    def _zahlenfeld(self, schluessel: str) -> Gtk.SpinButton:
        """Spinbutton, dessen Bereich aus `einstellungen.GRENZEN` kommt."""
        unten, oben = einstellungen.GRENZEN[schluessel]
        feld = Gtk.SpinButton.new_with_range(unten, oben, 1)
        feld.set_numeric(True)
        feld.set_width_chars(5)
        feld.set_value(float(self.vorher.get(
            schluessel, einstellungen.VORGABEN[schluessel])))
        return feld

    # -- Ergebnis ---------------------------------------------------------

    def werte(self) -> dict:
        """Der Stand der Maske als Einstellungssatz.

        Muss **vor** `destroy()` aufgerufen werden — danach sind die Widgets
        weg. Geprüft und geklemmt wird beim Speichern in `einstellungen`.
        """
        return {
            "language": self.sprache.get_active_id() or "auto",
            "greet_name": self.name.get_text(),
            "show_greeting": self.begruessung.get_active(),
            "refresh_seconds": self.takt.get_value_as_int(),
            "max_stored_rows": self.zeilen.get_value_as_int(),
            "wd_notify": self.wd_notify.get_active(),
            "wd_notify_max_per_hour": self.wd_max.get_value_as_int(),
        }


class SessionsApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        #: Einstellungen **einmal** beim Start lesen. Bewusst kein
        #: Nachladen im Betrieb: eine Übersicht, die sich unter der Hand
        #: umbaut, während man auf sie sieht, ist keine Übersicht. Was der
        #: Dialog speichert, greift beim nächsten Start — und genau das
        #: steht auch im Dialog.
        self.cfg = einstellungen.laden()
        #: Sprache genau einmal auflösen; danach wechselt sie bis zum
        #: nächsten Start nicht mehr.
        texte.set_sprache(self.cfg.get("language"))
        self.refresh_seconds = int(self.cfg.get("refresh_seconds")
                                   or REFRESH_SECONDS)
        self.max_stored_rows = int(self.cfg.get("max_stored_rows")
                                   or MAX_STORED_ROWS)
        self.window: Gtk.ApplicationWindow | None = None
        self.scanner = data.Scanner()
        self.rows: dict[str, SessionRow] = {}
        self.snap = data.Snapshot()
        self.hidden_stored = 0
        self._loading = False
        self._got_snapshot = False
        self._msg_token = 0
        #: Quellen-ID des laufenden Timers (0 = keiner geplant).
        self._timer = 0
        self._iconified = False
        #: Gewählte Ansicht der Seitenleiste (Schlüssel aus VIEWS).
        self._view = "live"

    # -- Aufbau -----------------------------------------------------------

    def do_activate(self) -> None:
        if self.window:
            self.window.present()
            return
        self._load_css()
        self._build_window()
        self.window.show_all()
        self._tick()
        self._schedule(self.refresh_seconds)

    def _load_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", True)
            # Die Desktop-App glättet Text in Graustufen
            # (`-webkit-font-smoothing: antialiased`), GTK nimmt hier von Haus
            # aus Subpixel-Glättung. Das ist der auffälligste Unterschied im
            # direkten Vergleich: derselbe Text zerfiel gemessen in farbige
            # Säume (#6ea193, #84c3de) statt sauber #c3c2b7 zu bleiben.
            # Gilt nur für diesen Prozess, nicht für den Rest des Desktops.
            settings.set_property("gtk-xft-rgba", "none")
            settings.set_property("gtk-xft-antialias", 1)
            settings.set_property("gtk-xft-hintstyle", "hintslight")

    def _build_window(self) -> None:
        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_default_size(1040, 680)
        self.window.set_title("Claude Sessions")

        icon = ASSETS / "icon-256.png"
        if icon.exists():
            try:
                self.window.set_icon(GdkPixbuf.Pixbuf.new_from_file(str(icon)))
            except GLib.Error:
                pass

        self.window.set_titlebar(self._build_header())
        # Nach dem Titlebar-Tausch erneut setzen, sonst meldet das Fenster
        # dem WM den prgname als Titel.
        self.window.set_title("Claude Sessions")

        # Zwei Spalten wie in der Claude-Desktop-App: schmale Seitenleiste
        # links, ruhige Inhaltsfläche rechts.
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.window.add(outer)
        outer.pack_start(self._build_sidebar(), False, False, 0)
        outer.pack_start(self._build_content(), True, True, 0)

        # GLibUnix statt GLib.unix_signal_add: letzteres ist deprecated und
        # schrieb bei jedem Dienststart eine Warnung ins Journal.
        self.window.connect("window-state-event", self._on_window_state)

        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT,
                            lambda *_: self.quit())

    def _build_header(self) -> Gtk.HeaderBar:
        """Titelleiste: nur Name und Aktualisieren — der Rest steht links."""
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)

        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        banner = ASSETS / "banner.png"
        if banner.exists():
            try:
                title_box.pack_start(
                    Gtk.Image.new_from_pixbuf(
                        GdkPixbuf.Pixbuf.new_from_file(str(banner))),
                    False, False, 0)
            except GLib.Error:
                pass
        titel = Gtk.Label(label="Claude Sessions")
        titel.get_style_context().add_class("hb-title")
        title_box.pack_start(titel, False, False, 0)
        # Links verankert wie im Vorbild - dort sitzt nichts in der
        # Fenstermitte. Ohne leeren custom_title malt die HeaderBar den
        # Fenstertitel trotzdem zentriert, und das Deko-Layout haengt sonst
        # je nach Theme noch ein Fenster-Icon ganz links daneben.
        header.set_decoration_layout(":minimize,maximize,close")
        header.set_custom_title(Gtk.Box())
        header.pack_start(title_box)

        # `pack_end` fuellt von rechts nach links: der zuerst gepackte
        # Knopf sitzt am weitesten rechts. Das Zahnrad kommt also vor dem
        # Aktualisieren-Knopf ins Paket, damit es rechts neben ihm steht.
        zahnrad = Gtk.Button.new_from_icon_name("emblem-system-symbolic",
                                                Gtk.IconSize.BUTTON)
        zahnrad.get_style_context().add_class("hb")
        zahnrad.set_tooltip_text(texte.t("knopf.einstellungen_tooltip"))
        zahnrad.connect("clicked", self._on_einstellungen)
        header.pack_end(zahnrad)

        refresh = Gtk.Button.new_from_icon_name("view-refresh-symbolic",
                                                Gtk.IconSize.BUTTON)
        refresh.get_style_context().add_class("hb")
        refresh.set_tooltip_text(texte.t("knopf.aktualisieren_tooltip"))
        refresh.connect("clicked", lambda *_: self._tick())
        header.pack_end(refresh)
        return header

    @staticmethod
    def _sect_label(schluessel: str) -> Gtk.Label:
        """Abschnittsüberschrift der Seitenleiste (Textschlüssel)."""
        label = Gtk.Label(label=texte.t(schluessel), xalign=0)
        label.get_style_context().add_class("side-sect")
        label.set_margin_top(6)
        label.set_margin_bottom(4)
        label.set_margin_start(10)
        return label

    def _build_sidebar(self) -> Gtk.Widget:
        """Seitenleiste: oben die Ansichten, unten der Watchdog.

        Die Ansichten ersetzen den früheren Schalter „Nur laufende" in der
        Kopfzeile — statt an/aus gibt es jetzt eine Auswahl je Gruppe, und
        die Zahl daneben sagt, was einen dort erwartet.
        """
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        side.get_style_context().add_class("side")
        side.set_size_request(260, -1)

        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        nav.set_margin_start(8)
        nav.set_margin_end(8)
        nav.set_margin_top(10)
        side.pack_start(nav, False, False, 0)
        nav.pack_start(self._sect_label("nav.abschnitt.sitzungen"),
                       False, False, 0)

        self.nav_buttons: dict[str, Gtk.Button] = {}
        self.nav_counts: dict[str, Gtk.Label] = {}
        symbole = {"live": "media-playback-start-symbolic",
                   "queue": "security-high-symbolic",
                   "stored": "document-open-recent-symbolic",
                   "all": "view-grid-symbolic"}
        for schluessel, textschluessel, _gruppe in VIEWS:
            btn = Gtk.Button()
            btn.get_style_context().add_class("nav")
            zeile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            bild = Gtk.Image.new_from_icon_name(symbole[schluessel],
                                                Gtk.IconSize.MENU)
            zeile.pack_start(bild, False, False, 0)
            name = Gtk.Label(label=texte.t(textschluessel), xalign=0)
            name.set_ellipsize(Pango.EllipsizeMode.END)
            zeile.pack_start(name, True, True, 0)
            zahl = Gtk.Label(label="", xalign=1)
            zahl.get_style_context().add_class("nav-count")
            zeile.pack_end(zahl, False, False, 0)
            btn.add(zeile)
            btn.connect("clicked", self._on_nav, schluessel)
            nav.pack_start(btn, False, False, 0)
            self.nav_buttons[schluessel] = btn
            self.nav_counts[schluessel] = zahl
        self.nav_buttons[self._view].get_style_context().add_class("nav-on")

        wd = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        wd.set_margin_start(8)
        wd.set_margin_end(8)
        wd.set_margin_bottom(12)
        side.pack_end(wd, False, False, 0)
        wd.pack_start(self._sect_label("nav.abschnitt.watchdog"),
                      False, False, 0)

        self.f_status = Gtk.Label(xalign=0)
        self.f_status.get_style_context().add_class("footer-off")
        self.f_status.set_ellipsize(Pango.EllipsizeMode.END)
        self.f_status.set_margin_start(10)
        wd.pack_start(self.f_status, False, False, 0)

        self.f_mcp = Gtk.Label(xalign=0)
        self.f_mcp.get_style_context().add_class("footer-off")
        self.f_mcp.set_ellipsize(Pango.EllipsizeMode.END)
        self.f_mcp.set_margin_start(10)
        wd.pack_start(self.f_mcp, False, False, 0)

        knoepfe = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        knoepfe.set_margin_top(2)
        wd.pack_start(knoepfe, False, False, 0)

        live = Gtk.Button(label=texte.t("knopf.live_log"))
        live.get_style_context().add_class("act")
        live.set_tooltip_text(texte.t("knopf.live_log_tooltip"))
        live.connect("clicked", self._on_live_log)
        knoepfe.pack_start(live, True, True, 0)

        # Erst nach dem ersten Snapshot scharf schalten: vorher ist der
        # Daemon-Zustand unbekannt und Label/Aktion könnten sich
        # widersprechen (target = not daemon_active).
        self.f_daemon_btn = Gtk.Button(
            label=texte.t("knopf.daemon_unbekannt"))
        self.f_daemon_btn.get_style_context().add_class("act")
        self.f_daemon_btn.set_sensitive(False)
        self.f_daemon_btn.connect("clicked", self._on_daemon_toggle)
        knoepfe.pack_start(self.f_daemon_btn, True, True, 0)
        return side

    def _build_content(self) -> Gtk.Widget:
        """Rechte Spalte: Überschrift der Ansicht, Kontingent, Liste."""
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.get_style_context().add_class("content")

        kopf = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        kopf.get_style_context().add_class("chead")
        # Begrüßung wie im Vorbild; welche Ansicht offen ist, sagen die
        # Seitenleiste und die Abschnittsüberschrift der Liste. Wer sie
        # abschaltet (`show_greeting`), bekommt die Zeile gar nicht erst
        # gepackt — ein leeres, aber vorhandenes Label würde weiter Platz
        # beanspruchen.
        self.greet: Gtk.Label | None = None
        if self.cfg.get("show_greeting", True):
            gruss_zeile = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=10)
            stern = Gtk.DrawingArea()
            stern.set_size_request(30, 30)
            stern.set_valign(Gtk.Align.CENTER)
            stern.connect("draw", self._male_sonnenrad)
            gruss_zeile.pack_start(stern, False, False, 0)
            self.greet = Gtk.Label(
                label=data.gruss(time.localtime().tm_hour, data.gruss_name()),
                xalign=0)
            self.greet.get_style_context().add_class("greet")
            gruss_zeile.pack_start(self.greet, False, False, 0)
            kopf.pack_start(gruss_zeile, False, False, 0)
        self.h_sub = Gtk.Label(label=texte.t("kopf.laedt"), xalign=0)
        self.h_sub.get_style_context().add_class("header-sub")
        self.h_sub.set_ellipsize(Pango.EllipsizeMode.END)
        kopf.pack_start(self.h_sub, False, False, 0)
        content.pack_start(kopf, False, False, 0)

        content.pack_start(self._build_usage(), False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        content.pack_start(scroll, True, True, 0)

        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.set_sort_func(self._sort_func)
        self.listbox.set_filter_func(self._filter_func)
        self.listbox.set_header_func(self._header_func)
        self.placeholder = Gtk.Label(label=texte.t("platzhalter.laedt"))
        self.placeholder.get_style_context().add_class("dim")
        self.placeholder.set_margin_top(40)
        self.placeholder.show()
        self.listbox.set_placeholder(self.placeholder)
        scroll.add(self.listbox)

        meldung = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        meldung.get_style_context().add_class("footer")
        content.pack_end(meldung, False, False, 0)
        self.f_msg = Gtk.Label(xalign=0)
        self.f_msg.get_style_context().add_class("footer-msg")
        self.f_msg.set_ellipsize(Pango.EllipsizeMode.START)
        meldung.pack_start(self.f_msg, True, True, 0)
        return content

    def _on_nav(self, _btn: Gtk.Button, schluessel: str) -> None:
        if schluessel == self._view:
            return
        self.nav_buttons[self._view].get_style_context().remove_class("nav-on")
        self._view = schluessel
        self.nav_buttons[schluessel].get_style_context().add_class("nav-on")
        self.listbox.invalidate_filter()
        self.listbox.invalidate_headers()
        self._update_placeholder()

    def _update_nav(self, snap: data.Snapshot) -> None:
        """Zahlen neben den Ansichten nachziehen."""
        zahlen = {
            "live": snap.n_live,
            "queue": snap.n_queue,
            "stored": snap.n_stored,
            "all": snap.n_live + snap.n_queue + snap.n_stored,
        }
        for schluessel, label in self.nav_counts.items():
            label.set_text(str(zahlen.get(schluessel, 0)))

        # -- ListBox-Hilfen ---------------------------------------------------

    @staticmethod
    def _sort_func(r1: SessionRow, r2: SessionRow) -> int:
        a, b = r1.info.sort_key, r2.info.sort_key
        return -1 if a < b else (1 if a > b else 0)

    # -- Nutzungsfenster ---------------------------------------------------

    def _build_usage(self) -> Gtk.Widget:
        """Kontingentblock, 1:1 nach dem Nutzungs-Dialog der Desktop-App.

        Zwei Zeilen wie im Vorbild: „Aktuelle Sitzung" (Fünf-Stunden-Fenster)
        und „Wöchentliche Limits", jeweils Titel + Zurücksetzung links, Balken
        in der Mitte, „X % verwendet" rechts. Die Prozentzahlen kommen
        ausschließlich aus `rate_limits` (dieselbe Quelle wie `/usage`) — die
        lokal summierten Tokens stehen nur als gedämpfte Randnotiz darunter,
        sie sind nachprüfbar, aber sie sind *nicht* das Kontingent.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.get_style_context().add_class("usage")
        # Beim Draufzeigen soll ablesbar sein, woher jede Zahl stammt — die
        # Frage kam zu Recht auf, als hier noch geschaetzte Werte standen.
        self.u_box = box
        box.set_has_tooltip(True)

        def zeile(titel: str):
            reihe = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
            links = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            links.set_size_request(190, -1)
            kopf = Gtk.Label(label=titel, xalign=0)
            kopf.get_style_context().add_class("usage-title")
            links.pack_start(kopf, False, False, 0)
            sub = Gtk.Label(label="", xalign=0)
            sub.get_style_context().add_class("usage-sub")
            links.pack_start(sub, False, False, 0)
            reihe.pack_start(links, False, False, 0)
            balken = Gtk.ProgressBar()
            balken.set_valign(Gtk.Align.CENTER)
            reihe.pack_start(balken, True, True, 0)
            pct = Gtk.Label(label="", xalign=0)
            pct.get_style_context().add_class("usage-pct")
            # Feste Breite, damit der Balken nicht springt, wenn aus 9 % ein
            # 10 % wird.
            pct.set_width_chars(14)
            reihe.pack_end(pct, False, False, 0)
            box.pack_start(reihe, False, False, 0)
            return sub, balken, pct

        self.u_reset, self.u_bar, self.u_pct = zeile(
            texte.t("nutzung.sitzung"))
        self.w_reset, self.w_bar, self.w_pct = zeile(
            texte.t("nutzung.woche"))

        self.u_sum = Gtk.Label(label="", xalign=0.0)
        self.u_sum.get_style_context().add_class("usage-dim")
        box.pack_start(self.u_sum, False, False, 0)
        return box

    @staticmethod
    def _male_sonnenrad(flaeche: Gtk.DrawingArea, ctx) -> bool:
        """Zwölfstrahliges Sonnenrad zur Begrüßung, in Akzentfarbe gezeichnet.

        Ein Textzeichen (✳) war zu dünn und zu symmetrisch — das Vorbild hat
        kräftige, ungleich lange Strahlen. Selbst gezeichnet statt als Asset
        aus der Desktop-App kopiert; die Längenfolge gibt die unregelmäßige
        Anmutung, ohne eine Datei von Anthropic mitzunehmen.
        """
        import math
        breite = flaeche.get_allocated_width()
        hoehe = flaeche.get_allocated_height()
        mx, my = breite / 2.0, hoehe / 2.0
        aussen = min(mx, my) - 1.0
        laengen = (1.0, 0.72, 0.9, 0.74, 0.97, 0.7,
                   1.0, 0.73, 0.92, 0.7, 0.95, 0.75)
        ctx.set_source_rgb(0xd9 / 255.0, 0x77 / 255.0, 0x57 / 255.0)
        ctx.set_line_width(3.4)
        ctx.set_line_cap(1)  # rund
        for i, anteil in enumerate(laengen):
            winkel = i * math.pi / 6.0 - math.pi / 2.0
            ctx.move_to(mx + math.cos(winkel) * aussen * 0.18,
                        my + math.sin(winkel) * aussen * 0.18)
            ctx.line_to(mx + math.cos(winkel) * aussen * anteil,
                        my + math.sin(winkel) * aussen * anteil)
            ctx.stroke()
        return False

    @staticmethod
    def _wochentag(zeitpunkt: float) -> str:
        """„Mo., 02:00" — aus der Sprachtabelle, nicht aus der Locale.

        Die Prozess-Locale steht hier oft auf `C` (Dienststart ohne
        Anmeldeumgebung); `%a` lieferte dann „Mon" mitten im deutschen Text.
        Die Kürzel stehen deshalb in `texte` unter `wochentag.0…6`.
        """
        tm = time.localtime(zeitpunkt)
        return texte.t("wochentag.zeit",
                       tag=texte.t("wochentag.%d" % tm.tm_wday),
                       uhrzeit=time.strftime("%H:%M", tm))

    def _update_usage(self, snap: data.Snapshot) -> None:
        p, w = snap.plan, snap.window
        self.u_box.set_tooltip_text(data.usage_tooltip(p, w))

        # Zeile 1: Fuenf-Stunden-Fenster
        if p.five_pct is None or p.expired:
            self.u_bar.set_fraction(0.0)
            self.u_pct.set_text(texte.t("nutzung.leer"))
            if p.expired:
                # Der gespeicherte Prozentsatz beschreibt ein Fenster, das es
                # nicht mehr gibt. Der neue Stand kommt erst mit der naechsten
                # Sitzung — bis dahin lieber nichts behaupten.
                self.u_reset.set_text(texte.t(
                    "nutzung.zurueckgesetzt",
                    zeit=time.strftime("%H:%M", time.localtime(p.five_reset))))
            else:
                self.u_reset.set_text(texte.t("nutzung.keine_werte"))
        else:
            self.u_bar.set_fraction(min(1.0, max(0.0, p.five_pct / 100.0)))
            self.u_pct.set_text(texte.t("nutzung.prozent",
                                        pct=round(p.five_pct)))
            if p.five_reset:
                self.u_reset.set_text(texte.t(
                    "nutzung.reset_in",
                    spanne=data.fmt_span(p.five_reset - time.time())))
            else:
                self.u_reset.set_text(texte.t("nutzung.fenster"))

        # Zeile 2: Wochenfenster
        if p.week_pct is None:
            self.w_bar.set_fraction(0.0)
            self.w_pct.set_text(texte.t("nutzung.leer"))
            self.w_reset.set_text(texte.t("nutzung.keine_werte"))
        else:
            self.w_bar.set_fraction(min(1.0, max(0.0, p.week_pct / 100.0)))
            self.w_pct.set_text(texte.t("nutzung.prozent",
                                        pct=round(p.week_pct)))
            if p.week_reset:
                self.w_reset.set_text(texte.t(
                    "nutzung.reset_am",
                    zeitpunkt=self._wochentag(p.week_reset)))
            else:
                self.w_reset.set_text("")

        # Randnotiz: lokal nachgezaehlte Tokens und Alter der Werte
        teile = []
        if w.tokens:
            teile.append(texte.t("nutzung.tokens_lokal",
                                 wert=data.fmt_tokens(w.tokens)))
        if p.stale:
            teile.append(texte.t("nutzung.stand",
                                 rel=data.rel_time(p.written_at)))
        self.u_sum.set_text("  ·  ".join(teile))
        self.u_sum.set_visible(bool(teile))

    def _filter_func(self, row: SessionRow) -> bool:
        gruppe = VIEW_GROUP[self._view]
        return gruppe is None or row.info.group == gruppe

    def _update_placeholder(self) -> None:
        """Platzhaltertext passend zum tatsaechlichen Zustand waehlen."""
        if not self._got_snapshot:
            return
        if self._view == "live" and self.snap.n_live == 0:
            self.placeholder.set_text(texte.t("platzhalter.keine_laufenden"))
        elif self._view == "queue" and self.snap.n_queue == 0:
            self.placeholder.set_text(
                texte.t("platzhalter.warteschlange_leer"))
        else:
            self.placeholder.set_text(texte.t("platzhalter.keine"))

    def _header_func(self, row: SessionRow, before: SessionRow | None) -> None:
        if before is not None and before.info.group == row.info.group:
            row.set_header(None)
            return
        g = row.info.group
        text = data.GROUP_LABELS[g]
        if g == data.GROUP_LIVE:
            text = texte.t("liste.kopf", label=text, n=self.snap.n_live)
        elif g == data.GROUP_STORED:
            shown = self.snap.n_stored - self.hidden_stored
            if self.hidden_stored > 0:
                text = texte.t("liste.kopf_teilmenge", label=text,
                               gezeigt=shown, gesamt=self.snap.n_stored)
            else:
                text = texte.t("liste.kopf", label=text, n=self.snap.n_stored)
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class("sect")
        label.set_margin_start(16)
        label.set_margin_top(14)
        label.set_margin_bottom(4)
        label.show()
        row.set_header(label)

    # -- Datenfluss -------------------------------------------------------

    def _visible(self) -> bool:
        """Sieht gerade jemand auf das Fenster?

        Minimiert oder auf einer anderen Arbeitsfläche ist es nicht gemappt —
        dann kostet Aktualisieren nur Rechenzeit für niemanden.
        """
        return bool(self.window and self.window.get_mapped()
                    and not self._iconified)

    def _schedule(self, seconds: int) -> None:
        """Nächsten Durchlauf planen und einen alten Timer verwerfen."""
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add_seconds(seconds, self._tick)

    def _tick(self) -> bool:
        self._timer = 0
        if not self._visible():
            # Nicht laden, nur bald wieder nachsehen. Wird das Fenster
            # sichtbar, aktualisiert der State-Handler ohnehin sofort.
            self._schedule(IDLE_POLL_SECONDS)
            return False
        if not self._loading:
            self._loading = True
            threading.Thread(target=self._load, daemon=True).start()
        self._schedule(self.refresh_seconds)
        return False

    def _on_window_state(self, _w: Gtk.Widget, event) -> bool:
        war_versteckt = self._iconified
        self._iconified = bool(event.new_window_state
                               & Gdk.WindowState.ICONIFIED)
        if war_versteckt and not self._iconified:
            # Gerade wieder aufgetaucht: sofort frische Zahlen zeigen,
            # statt den Nutzer auf den nächsten Takt warten zu lassen.
            self._tick()
        return False

    def _load(self) -> None:
        try:
            # Demo-Modus: erfundene Sitzungen statt der echten. Nur so
            # entsteht ein Screenshot fürs README, ohne fremde Titel und
            # Projektpfade zu veröffentlichen (siehe demo.py).
            snap = demo.snapshot() if demo.aktiv() else data.snapshot(self.scanner)
        except Exception as exc:  # Anzeige statt stummem Thread-Tod
            GLib.idle_add(self._apply_error, "%s: %s" % (type(exc).__name__, exc))
            return
        GLib.idle_add(self._apply, snap)

    def _apply_error(self, text: str) -> bool:
        self._loading = False
        if not self._got_snapshot:
            self.placeholder.set_text(texte.t("platzhalter.fehler"))
        self.flash(texte.t("meldung.refresh_fehler", fehler=text))
        return False

    def _apply(self, snap: data.Snapshot) -> bool:
        self._loading = False
        self._got_snapshot = True
        self.snap = snap
        self._update_usage(snap)
        # Die Begrüßung folgt der Tageszeit — wer das Fenster über Nacht offen
        # lässt, soll morgens nicht mehr „Guten Abend" lesen. Ist sie
        # abgeschaltet, gibt es das Label gar nicht.
        if self.greet is not None:
            self.greet.set_text(data.gruss(time.localtime().tm_hour,
                                           data.gruss_name()))

        display = [i for i in snap.sessions if i.group != data.GROUP_STORED]
        stored = [i for i in snap.sessions if i.group == data.GROUP_STORED]
        display += stored[:self.max_stored_rows]
        self.hidden_stored = max(0, len(stored) - self.max_stored_rows)

        wanted = {}
        for info in display:
            wanted[info.id] = info
        for key in list(self.rows):
            if key not in wanted:
                row = self.rows.pop(key)
                self.listbox.remove(row)
        for key, info in wanted.items():
            row = self.rows.get(key)
            if row is None:
                row = SessionRow(self, info)
                self.rows[key] = row
                self.listbox.add(row)
            else:
                row.update(info)
        self.listbox.invalidate_sort()
        self.listbox.invalidate_filter()
        self.listbox.invalidate_headers()
        self._update_placeholder()

        bits = []
        if snap.n_busy:
            bits.append(texte.t("kopf.arbeiten", n=snap.n_busy))
        idle = snap.n_live - snap.n_busy
        if idle > 0:
            bits.append(texte.t("kopf.bereit", n=idle))
        if not snap.agents_ok:
            bits.append(texte.t("kopf.kein_livestatus"))
        bits.append(texte.t("kopf.gespeichert", n=snap.n_stored))
        self.h_sub.set_text("  ·  ".join(bits))
        self._update_nav(snap)

        if snap.daemon_active:
            extra = (texte.t("fuss.neustarts", n=snap.wd_restarts)
                     if snap.wd_restarts else "")
            self.f_status.set_text(texte.t("fuss.daemon_aktiv") + extra)
            _swap_class(self.f_status, ("footer-ok", "footer-off"), "footer-ok")
            self.f_daemon_btn.set_label(texte.t("knopf.daemon_stoppen"))
        else:
            self.f_status.set_text(texte.t("fuss.daemon_inaktiv"))
            _swap_class(self.f_status, ("footer-ok", "footer-off"), "footer-off")
            self.f_daemon_btn.set_label(texte.t("knopf.daemon_starten"))
        if not snap.wd_ok:
            self.f_status.set_text(self.f_status.get_text()
                                   + texte.t("fuss.db_unlesbar"))
        self._apply_mcp(snap)
        self.f_daemon_btn.set_sensitive(True)
        return False

    def _apply_mcp(self, snap: data.Snapshot) -> None:
        """Footer-Pille für die konfigurierten MCP-Server."""
        if not snap.mcp_ok:
            self.f_mcp.set_text(texte.t("fuss.mcp_unlesbar"))
            self.f_mcp.set_tooltip_text(None)
            _swap_class(self.f_mcp, ("footer-ok", "footer-off"), "footer-off")
            return
        if not snap.mcp:
            self.f_mcp.set_text(texte.t("fuss.mcp_keine"))
            self.f_mcp.set_tooltip_text(None)
            _swap_class(self.f_mcp, ("footer-ok", "footer-off"), "footer-off")
            return

        by_client: dict[str, list[data.McpServer]] = {}
        for s in snap.mcp:
            by_client.setdefault(s.client, []).append(s)
        self.f_mcp.set_text(texte.t(
            "fuss.mcp", n=len(snap.mcp),
            namen=", ".join(s.name for s in snap.mcp)))
        _swap_class(self.f_mcp, ("footer-ok", "footer-off"), "footer-ok")

        lines = []
        for client, servers in by_client.items():
            lines.append(client)
            for s in servers:
                detail = s.detail if len(s.detail) <= 70 else s.detail[:69] + "…"
                lines.append("   %s  [%s]  %s" % (s.name, s.transport, detail))
        lines.append("")
        lines.append(texte.t("fuss.mcp_hinweis"))
        self.f_mcp.set_tooltip_text("\n".join(lines))

    # -- Aktionen / Rückmeldungen -----------------------------------------

    def flash(self, text: str) -> bool:
        self._msg_token += 1
        token = self._msg_token
        self.f_msg.set_text(text)

        def clear() -> bool:
            if token == self._msg_token:
                self.f_msg.set_text("")
            return False

        GLib.timeout_add_seconds(8, clear)
        return False

    def im_hintergrund(self, arbeit, fertig=None) -> None:
        """Blockierenden Aufruf aus dem Mainthread heraushalten.

        Jeder dieser Aufrufe startet Subprozesse mit Zeitgrenzen bis 30 s —
        im Mainthread friert das Fenster genau so lange ein (vom Prüfer am
        2026-08-18 an sieben Stellen nachgewiesen). `arbeit()` läuft im
        Thread, `fertig(ergebnis)` wieder im Mainthread.
        """
        def worker() -> None:
            try:
                ergebnis = arbeit()
            except Exception:
                # Threadgrenze: ein Fehler hier darf das Fenster nicht
                # mitreißen. Sichtbar wird er über die Rückmeldung, die dann
                # den Fehlerfall meldet.
                ergebnis = None
            if fertig is not None:
                GLib.idle_add(fertig, ergebnis)
        threading.Thread(target=worker, daemon=True).start()

    def run_watchdog(self, *args: str) -> None:
        def worker() -> None:
            ok, msg = actions.watchdog(*args)
            GLib.idle_add(self.flash, msg or texte.t("meldung.ok" if ok
                                                     else "meldung.fehler"))
            GLib.idle_add(self._quick_refresh)
        threading.Thread(target=worker, daemon=True).start()

    def _quick_refresh(self) -> bool:
        # Nach einer Aktion kurz warten, damit der Watchdog seine Datenbank
        # geschrieben hat. _tick() laeuft einmal und plant den regulaeren
        # Takt selbst neu.
        GLib.timeout_add(500, self._tick)
        return False

    def copy_text(self, text: str) -> None:
        clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clip.set_text(text, -1)
        clip.store()
        self.flash(texte.t("meldung.kopiert", text=text))

    def confirm_terminate(self, info: data.SessionInfo) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self.window, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=texte.t("dialog.beenden_titel"))
        dlg.format_secondary_text(texte.t(
            "dialog.beenden_text",
            titel=info.title or info.id[:8], pid=info.pid))
        answer = dlg.run()
        dlg.destroy()
        if answer == Gtk.ResponseType.YES:
            if actions.terminate(info.pid):
                self.flash(texte.t("meldung.sigterm", pid=info.pid))
            else:
                self.flash(texte.t("meldung.kein_prozess", pid=info.pid))
            self._quick_refresh()

    def confirm_service_stop(self, info: data.SessionInfo) -> None:
        """Dauer-Dienst beenden — mit deutlichem Hinweis auf den Autostart."""
        dlg = Gtk.MessageDialog(
            transient_for=self.window, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=texte.t("dialog.dienst_titel", dienst=info.service))
        dlg.format_secondary_text(texte.t("dialog.dienst_text",
                                          dienst=info.service))
        answer = dlg.run()
        dlg.destroy()
        if answer == Gtk.ResponseType.YES:
            def fertig(ergebnis) -> None:
                ok, meldung = ergebnis if ergebnis else (False, "")
                self.flash(meldung or texte.t(
                    "meldung.dienst_gestoppt" if ok
                    else "meldung.stoppen_fehlgeschlagen",
                    dienst=info.service))
                self._quick_refresh()
            self.im_hintergrund(lambda: actions.stop_service(info.service),
                                fertig)

    def confirm_wd_remove(self, info: data.SessionInfo) -> None:
        dlg = Gtk.MessageDialog(
            transient_for=self.window, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=texte.t("dialog.wd_entfernen_titel"))
        dlg.format_secondary_text(texte.t("dialog.wd_entfernen_text"))
        answer = dlg.run()
        dlg.destroy()
        if answer == Gtk.ResponseType.YES:
            self.run_watchdog("rm", info.wd_task_id, "--force")

    def _on_live_log(self, _btn: Gtk.Button) -> None:
        self.im_hintergrund(
            actions.show_live_log,
            lambda ok: self.flash(texte.t("meldung.live_log") if ok
                                  else texte.t("meldung.kein_qterminal")))

    def _on_daemon_toggle(self, _btn: Gtk.Button) -> None:
        target = not self.snap.daemon_active

        def worker() -> None:
            ok, msg = actions.set_daemon(target)
            GLib.idle_add(self.flash, msg)
            GLib.idle_add(self._quick_refresh)
        threading.Thread(target=worker, daemon=True).start()

    # -- Einstellungen -----------------------------------------------------

    def _on_einstellungen(self, _btn: Gtk.Button) -> None:
        dlg = EinstellungenDialog(self)
        antwort = dlg.run()
        werte = dlg.werte()          # noch vor dem Zerstören auslesen
        dlg.destroy()
        if antwort not in (Gtk.ResponseType.OK, Gtk.ResponseType.APPLY):
            return
        self._einstellungen_speichern(
            werte, neu_starten=(antwort == Gtk.ResponseType.APPLY))

    def _einstellungen_speichern(self, werte: dict,
                                 neu_starten: bool) -> None:
        """Speichern, an den Watchdog weiterreichen, notfalls neu starten.

        Das laufende Fenster behält bewusst die Werte, mit denen es gestartet
        ist (Sprache, Takt, Zeilenzahl) — deshalb steht im Dialog, was erst
        nach einem Neustart greift, und daneben der Knopf, der ihn auslöst.
        """
        try:
            sauber = einstellungen.speichern(werte)
        except OSError:
            self.flash(texte.t("einst.nicht_gespeichert"))
            return
        self.flash(texte.t("einst.gespeichert"))
        self._watchdog_uebernehmen(
            sauber, danach=self._neu_starten if neu_starten else None)

    def _watchdog_uebernehmen(self, werte: dict, danach=None) -> None:
        """Die Pop-up-Werte an den Watchdog weitergeben (Drop-in + Neustart).

        `danach` läuft, sobald dieser Teil erledigt ist — auch dann, wenn es
        nichts zu tun gab. So kommt der Neustart der App erst, nachdem der
        Watchdog seine neue Umgebung hat, ohne dass irgendwo gewartet wird.
        """
        def fertig() -> bool:
            if danach is not None:
                danach()
            return False

        # Kein Watchdog installiert: die Übersicht läuft auch ohne ihn, und
        # ein Drop-in für eine Unit, die es nicht gibt, wäre ein Zettel an
        # eine leere Wand. Still übergehen, gespeichert ist trotzdem.
        if not einstellungen.wd_unit_vorhanden():
            fertig()
            return
        try:
            geaendert = einstellungen.dropin_schreiben(werte)
        except OSError as exc:
            self.flash(texte.t("einst.wd_fehler",
                               fehler=exc.strerror or str(exc)))
            fertig()
            return
        if not geaendert:
            # Nichts am Watchdog geändert — dann auch keinen laufenden
            # Daemon anfassen.
            fertig()
            return

        def worker() -> None:
            ok, fehler = actions.reload_watchdog()
            GLib.idle_add(self.flash,
                          texte.t("einst.wd_neugestartet") if ok
                          else texte.t("einst.wd_fehler", fehler=fehler))
            GLib.idle_add(fertig)
        threading.Thread(target=worker, daemon=True).start()

    def _neu_starten(self) -> bool:
        """Die App über ihre Unit neu starten — abgelöst, ohne Warten."""
        self.im_hintergrund(
            actions.restart_app,
            lambda ok: self.flash(texte.t("einst.neustart_laeuft") if ok
                                  else texte.t("einst.neustart_fehlgeschlagen")))
        return False


def main() -> int:
    GLib.set_prgname("claude-sessions")
    Gdk.set_program_class("claude-sessions")
    Gtk.Window.set_default_icon_name("claude-sessions")
    app = SessionsApp()
    return app.run(None)


if __name__ == "__main__":
    raise SystemExit(main())
