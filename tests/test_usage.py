"""Tests für Tokenzählung und Fünf-Stunden-Fenster."""
from __future__ import annotations

import calendar
import json
import tempfile
import time
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_sessions import data, texte  # noqa: E402

H = 3600


def utc(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts)) + ".000Z"


def assistant(ts: float, ein: int = 0, aus: int = 0, cache_neu: int = 0,
              cache_gelesen: int = 0) -> str:
    return json.dumps({
        "type": "assistant",
        "timestamp": utc(ts),
        "message": {"role": "assistant", "usage": {
            "input_tokens": ein, "output_tokens": aus,
            "cache_creation_input_tokens": cache_neu,
            "cache_read_input_tokens": cache_gelesen,
        }},
    }, separators=(",", ":"))


class EpochTest(unittest.TestCase):
    def test_utc_wird_richtig_umgerechnet(self) -> None:
        soll = calendar.timegm((2026, 7, 30, 0, 35, 1, 0, 0, 0))
        self.assertEqual(data._epoch("2026-07-30T00:35:01.353Z"), soll)

    def test_muell_ergibt_null(self) -> None:
        for s in ("", "kaputt", "2026-13", "----------T--:--:--"):
            with self.subTest(s=s):
                self.assertEqual(data._epoch(s), 0.0)


class UsageEventsTest(unittest.TestCase):
    def test_zaehlt_ein_aus_und_neuen_cache(self) -> None:
        roh = (assistant(1000, ein=3, aus=10, cache_neu=7) + "\n").encode()
        ev, verbraucht = data._usage_events(roh)
        self.assertEqual(ev, [(1000.0, 20)])
        self.assertEqual(verbraucht, len(roh))

    def test_cache_lesen_zaehlt_nicht_mit(self) -> None:
        """Sonst dominiert das Cache-Lesen alles andere um Groessenordnungen."""
        roh = (assistant(1000, aus=5, cache_gelesen=9_000_000) + "\n").encode()
        ev, _ = data._usage_events(roh)
        self.assertEqual(ev, [(1000.0, 5)])

    def test_angefangene_letzte_zeile_bleibt_liegen(self) -> None:
        ganz = assistant(1000, aus=5) + "\n"
        roh = (ganz + assistant(2000, aus=7)).encode()   # ohne \n am Ende
        ev, verbraucht = data._usage_events(roh)
        self.assertEqual(ev, [(1000.0, 5)])
        self.assertEqual(verbraucht, len(ganz.encode()))

    def test_kaputte_zeilen_fallen_weg(self) -> None:
        roh = (b'{"type":"assistant","usage": kaputt\n'
               + (assistant(1000, aus=5) + "\n").encode())
        ev, _ = data._usage_events(roh)
        self.assertEqual(ev, [(1000.0, 5)])

    def test_nutzer_und_nullzeilen_ignoriert(self) -> None:
        roh = (json.dumps({"type": "user", "message": {"usage": {}}}) + "\n"
               + assistant(1000, aus=0) + "\n").encode()
        self.assertEqual(data._usage_events(roh)[0], [])


class TokenWindowTest(unittest.TestCase):
    def test_ohne_ereignisse_kein_fenster(self) -> None:
        w = data.token_window([], now=10_000)
        self.assertFalse(w.active)
        self.assertEqual(w.tokens, 0)

    def test_einfaches_fenster(self) -> None:
        ev = [(1000.0, 5), (1000.0 + H, 7)]
        w = data.token_window(ev, now=1000.0 + 2 * H)
        self.assertTrue(w.active)
        self.assertEqual(w.start, 1000.0)
        self.assertEqual(w.reset, 1000.0 + 5 * H)
        self.assertEqual(w.tokens, 12)
        self.assertEqual(w.msgs, 2)

    def test_kette_beginnt_nach_ablauf_neu(self) -> None:
        """Nachricht nach Ablauf eroeffnet ein Fenster — die alte zaehlt nicht."""
        ev = [(1000.0, 5), (1000.0 + 6 * H, 7), (1000.0 + 6 * H + 60, 3)]
        w = data.token_window(ev, now=1000.0 + 7 * H)
        self.assertEqual(w.start, 1000.0 + 6 * H)
        self.assertEqual(w.tokens, 10)
        self.assertEqual(w.msgs, 2)

    def test_grenze_gehoert_zum_naechsten_fenster(self) -> None:
        ev = [(1000.0, 5), (1000.0 + 5 * H, 7)]
        w = data.token_window(ev, now=1000.0 + 5 * H + 60)
        self.assertEqual(w.start, 1000.0 + 5 * H)
        self.assertEqual(w.tokens, 7)

    def test_abgelaufenes_fenster_ist_inaktiv(self) -> None:
        w = data.token_window([(1000.0, 5)], now=1000.0 + 6 * H)
        self.assertFalse(w.active)
        self.assertEqual(w.reset, 1000.0 + 5 * H)
        self.assertEqual(w.elapsed, 0.0)
        self.assertEqual(w.remaining, 0.0)

    def test_unsortierte_eingabe(self) -> None:
        ev = [(1000.0 + 2 * H, 7), (1000.0, 5)]
        w = data.token_window(ev, now=1000.0 + 3 * H)
        self.assertEqual(w.start, 1000.0)
        self.assertEqual(w.tokens, 12)


class ScannerUsageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.dir = self.root / "-home-user-Desktop"
        self.dir.mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)
        self.jetzt = time.time()

    def datei(self, name: str, zeilen: list[str]) -> Path:
        p = self.dir / (name + ".jsonl")
        p.write_text("\n".join(zeilen) + "\n")
        return p

    def test_tokens_landen_in_der_zeile(self) -> None:
        self.datei("aaa", [assistant(self.jetzt, aus=10),
                           assistant(self.jetzt, aus=5)])
        rows = data.Scanner(self.root).collect()
        self.assertEqual(rows[0]["tokens"], 15)

    def test_fortschreiben_zaehlt_nicht_doppelt(self) -> None:
        p = self.datei("aaa", [assistant(self.jetzt, aus=10)])
        sc = data.Scanner(self.root)
        self.assertEqual(sc.collect()[0]["tokens"], 10)
        with p.open("a") as fh:
            fh.write(assistant(self.jetzt, aus=4) + "\n")
        self.assertEqual(sc.collect()[0]["tokens"], 14)
        self.assertEqual(len(sc.usage_events()), 2)

    def test_geschrumpfte_datei_wird_neu_gelesen(self) -> None:
        p = self.datei("aaa", [assistant(self.jetzt, aus=10),
                               assistant(self.jetzt, aus=10)])
        sc = data.Scanner(self.root)
        self.assertEqual(sc.collect()[0]["tokens"], 20)
        p.write_text(assistant(self.jetzt, aus=3) + "\n")
        self.assertEqual(sc.collect()[0]["tokens"], 3)

    def test_ereignisse_ueber_mehrere_dateien(self) -> None:
        self.datei("aaa", [assistant(self.jetzt, aus=10)])
        self.datei("bbb", [assistant(self.jetzt, aus=4)])
        sc = data.Scanner(self.root)
        sc.collect()
        w = data.token_window(sc.usage_events(), now=self.jetzt + 60)
        self.assertEqual(w.tokens, 14)
        self.assertEqual(w.msgs, 2)

    def test_alte_ereignisse_werden_ausgeduennt(self) -> None:
        """Ausduennen darf die Gesamtsumme der Session nicht antasten."""
        alt = self.jetzt - data.USAGE_KEEP_SECONDS - 3600
        self.datei("aaa", [assistant(alt, aus=99),
                           assistant(self.jetzt, aus=7)])
        sc = data.Scanner(self.root)
        row = sc.collect()[0]
        self.assertEqual(row["tokens"], 106)
        self.assertEqual([t for _, t in sc.usage_events()], [7])


class DeutschTest(unittest.TestCase):
    """Basis für alles, was den deutschen Wortlaut prüft.

    Seit der Sprachschicht ist Englisch die Grundsprache; ohne dieses setUp
    hängen die Erwartungen an der Locale des Rechners.
    """

    def setUp(self) -> None:
        self.addCleanup(texte.set_sprache, None)
        texte.set_sprache("de")


class FormatTest(DeutschTest):
    def test_tokens(self) -> None:
        self.assertEqual(data.fmt_tokens(0), "0")
        self.assertEqual(data.fmt_tokens(999), "999")
        self.assertEqual(data.fmt_tokens(1500), "2 Tsd")
        self.assertEqual(data.fmt_tokens(812_000), "812 Tsd")
        self.assertEqual(data.fmt_tokens(4_904_699), "4,90 Mio")

    def test_spanne(self) -> None:
        self.assertEqual(data.fmt_span(0), "0 min")
        self.assertEqual(data.fmt_span(-5), "0 min")
        self.assertEqual(data.fmt_span(47 * 60), "47 min")
        self.assertEqual(data.fmt_span(2 * H + 3 * 60), "2 h 03 min")


if __name__ == "__main__":
    unittest.main()


class PlanUsageTest(unittest.TestCase):
    """Die echten Limitwerte aus tools/statusline.py."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "usage.json"
        self.addCleanup(self.tmp.cleanup)

    def schreib(self, obj) -> Path:
        self.p.write_text(json.dumps(obj))
        return self.p

    def test_fehlende_datei_meldet_nichts(self) -> None:
        u = data.plan_usage(self.p)
        self.assertFalse(u.ok)
        self.assertIsNone(u.five_pct)

    def test_kaputte_datei_meldet_nichts(self) -> None:
        self.p.write_text("{kein json")
        self.assertFalse(data.plan_usage(self.p).ok)

    def test_werte_werden_gelesen(self) -> None:
        self.schreib({"written_at": 1000.0, "rate_limits": {
            "five_hour": {"used_percentage": 27.0, "resets_at": 2000.0},
            "seven_day": {"used_percentage": 22.5, "resets_at": 9000.0}}})
        u = data.plan_usage(self.p)
        self.assertTrue(u.ok)
        self.assertEqual(u.five_pct, 27.0)
        self.assertEqual(u.five_reset, 2000.0)
        self.assertEqual(u.week_pct, 22.5)
        self.assertEqual(u.written_at, 1000.0)

    def test_einzelnes_fenster_darf_fehlen(self) -> None:
        """Laut Doku kann jedes Fenster unabhaengig fehlen."""
        self.schreib({"rate_limits": {
            "five_hour": {"used_percentage": 5.0, "resets_at": 1.0}}})
        u = data.plan_usage(self.p)
        self.assertEqual(u.five_pct, 5.0)
        self.assertIsNone(u.week_pct)
        self.assertTrue(u.ok)

    def test_ohne_rate_limits_nicht_ok(self) -> None:
        """Ohne Abo liefert Claude Code den Block gar nicht."""
        self.schreib({"written_at": 1.0, "model": "Fable 5"})
        self.assertFalse(data.plan_usage(self.p).ok)

    def test_muellwerte_kippen_nicht_um(self) -> None:
        self.schreib({"rate_limits": {
            "five_hour": {"used_percentage": "viel", "resets_at": "bald"}}})
        u = data.plan_usage(self.p)
        self.assertIsNone(u.five_pct)
        self.assertEqual(u.five_reset, 0.0)

    def test_alter_wird_erkannt(self) -> None:
        self.schreib({"written_at": time.time() - data.PLAN_USAGE_STALE - 10,
                      "rate_limits": {"five_hour": {"used_percentage": 3.0}}})
        self.assertTrue(data.plan_usage(self.p).stale)
        self.schreib({"written_at": time.time(),
                      "rate_limits": {"five_hour": {"used_percentage": 3.0}}})
        self.assertFalse(data.plan_usage(self.p).stale)

    def test_ueberholter_wert_wird_erkannt(self) -> None:
        """Nach dem Reset beschreibt der Wert ein Fenster, das es nicht gibt."""
        self.schreib({"written_at": time.time() - 60, "rate_limits": {
            "five_hour": {"used_percentage": 30.0,
                          "resets_at": time.time() - 1}}})
        self.assertTrue(data.plan_usage(self.p).expired)

    def test_laufendes_fenster_ist_nicht_ueberholt(self) -> None:
        self.schreib({"written_at": time.time(), "rate_limits": {
            "five_hour": {"used_percentage": 30.0,
                          "resets_at": time.time() + 600}}})
        self.assertFalse(data.plan_usage(self.p).expired)

    def test_ohne_reset_zeit_nicht_ueberholt(self) -> None:
        """Fehlt resets_at, ist 'ueberholt' nicht entscheidbar — also nein."""
        self.schreib({"rate_limits": {"five_hour": {"used_percentage": 30.0}}})
        u = data.plan_usage(self.p)
        self.assertFalse(u.expired)
        self.assertEqual(u.five_pct, 30.0)


class TooltipTest(DeutschTest):
    """Der Tooltip muss die Herkunft jeder Zahl nennen."""

    def test_nennt_die_quelle_der_prozente(self) -> None:
        p = data.PlanUsage(five_pct=30.0, five_reset=time.time() + 600,
                           written_at=time.time())
        t = data.usage_tooltip(p, data.TokenWindow())
        self.assertIn("rate_limits", t)
        self.assertIn("/usage", t)

    def test_sagt_dass_tokens_nicht_das_kontingent_sind(self) -> None:
        w = data.TokenWindow(start=1.0, reset=2.0, tokens=5000, msgs=3,
                             active=True)
        t = data.usage_tooltip(data.PlanUsage(), w)
        self.assertIn("NICHT das Kontingent", t)
        self.assertIn("Cache-Lesen", t)

    def test_ohne_werte_erklaert_er_warum(self) -> None:
        t = data.usage_tooltip(data.PlanUsage(), data.TokenWindow())
        self.assertIn("Noch keine Limitwerte", t)
        self.assertIn("Pro/Max", t)

    def test_ueberholtes_fenster_wird_erwaehnt(self) -> None:
        p = data.PlanUsage(five_pct=30.0, five_reset=time.time() - 1,
                           written_at=time.time() - 60)
        self.assertIn("überholt", data.usage_tooltip(p, data.TokenWindow()))


class SubagentTest(unittest.TestCase):
    """Sub-Agenten zaehlen zur aufrufenden Session, bekommen aber keine Zeile."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.proj = self.root / "-home-user-Desktop"
        self.proj.mkdir(parents=True)
        self.addCleanup(self.tmp.cleanup)
        self.jetzt = time.time()
        self.sid = "11111111-2222-3333-4444-555555555555"
        (self.proj / (self.sid + ".jsonl")).write_text(
            assistant(self.jetzt, aus=100) + "\n")

    def agent(self, unterpfad: str, aus: int) -> None:
        p = self.proj / self.sid / "subagents" / unterpfad
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(assistant(self.jetzt, aus=aus) + "\n")

    def test_tokens_werden_der_session_zugerechnet(self) -> None:
        self.agent("agent-abc.jsonl", 40)
        rows = data.Scanner(self.root).collect()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.sid)
        self.assertEqual(rows[0]["tokens"], 140)

    def test_workflow_agenten_liegen_tiefer_und_zaehlen_trotzdem(self) -> None:
        self.agent("agent-abc.jsonl", 40)
        self.agent("workflows/wf_123/agent-def.jsonl", 7)
        rows = data.Scanner(self.root).collect()
        self.assertEqual(rows[0]["tokens"], 147)

    def test_agenten_bekommen_keine_eigene_zeile(self) -> None:
        self.agent("agent-abc.jsonl", 40)
        self.agent("workflows/wf_123/agent-def.jsonl", 7)
        rows = data.Scanner(self.root).collect()
        self.assertEqual([r["id"] for r in rows], [self.sid])

    def test_agenten_ereignisse_zaehlen_im_fenster(self) -> None:
        self.agent("agent-abc.jsonl", 40)
        sc = data.Scanner(self.root)
        sc.collect()
        w = data.token_window(sc.usage_events(), now=self.jetzt + 60)
        self.assertEqual(w.tokens, 140)
        self.assertEqual(w.msgs, 2)

    def test_agent_ohne_passende_session_stuerzt_nicht_ab(self) -> None:
        """Verwaiste Agenten-Ordner duerfen den Scan nicht kippen."""
        p = self.proj / "verwaist" / "subagents" / "agent-x.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(assistant(self.jetzt, aus=9) + "\n")
        rows = data.Scanner(self.root).collect()
        self.assertEqual(rows[0]["tokens"], 100)
