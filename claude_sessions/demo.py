"""Erfundene Sitzungen für Screenshots — echte Daten bleiben draußen.

Die Übersicht zeigt Titel und Projektpfade echter Sitzungen an. Ein Screenshot
davon veröffentlicht genau diese Titel, deshalb entsteht das Bild in der
README aus diesem Modul statt aus dem, was gerade läuft:

    CS_DEMO=1 bin/claude-sessions

Die Zeitpunkte sind relativ zum Aufruf, damit die Zeitangaben ("gerade",
"vor 12 Min") stimmen; alles andere ist fest, damit zwei Läufe dasselbe Bild
ergeben.
"""
from __future__ import annotations

import os
import time

from . import data


def aktiv() -> bool:
    """Ist der Demo-Modus eingeschaltet?"""
    return os.environ.get("CS_DEMO", "").strip() not in ("", "0", "false", "no")


def snapshot() -> data.Snapshot:
    """Ein vollständiger Schnappschuss aus erfundenen Sitzungen."""
    jetzt = time.time()

    def sitzung(id_: str, titel: str, cwd: str, msgs: int, tokens: int,
                alter: float, **rest) -> data.SessionInfo:
        return data.SessionInfo(id=id_, title=titel, cwd=cwd, msgs=msgs,
                                tokens=tokens, mtime=jetzt - alter, **rest)

    sitzungen = [
        sitzung("11111111-2222-3333-4444-555555555555",
                "Refactor the payment webhook", "~/code/shop-api",
                msgs=214, tokens=1_840_000, alter=20,
                group=data.GROUP_LIVE, live=True, live_status="busy", pid=4711,
                wd_task_id="a1b2c3d4", wd_mode="observed", wd_status="running"),
        sitzung("66666666-7777-8888-9999-000000000000",
                "Port the CLI to argparse", "~/code/toolbelt",
                msgs=88, tokens=520_000, alter=95,
                group=data.GROUP_LIVE, live=True, live_status="idle", pid=4820),
        sitzung("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "Nightly build babysitter", "~/code/infra",
                msgs=1302, tokens=12_400_000, alter=240,
                group=data.GROUP_LIVE, live=True, live_status="idle",
                pid=4102, service="nightly",
                wd_task_id="e5f6a7b8", wd_mode="observed", wd_status="running"),
        sitzung("22222222-3333-4444-5555-666666666666",
                "Write the migration guide", "~/code/docs",
                msgs=41, tokens=210_000, alter=60 * 47,
                wd_task_id="c9d0e1f2", wd_mode="managed",
                wd_status="waiting_for_limit"),
        sitzung("33333333-4444-5555-6666-777777777777",
                "Flaky test in the queue worker", "~/code/shop-api",
                msgs=176, tokens=930_000, alter=60 * 96),
        sitzung("44444444-5555-6666-7777-888888888888",
                "Set up the staging box", "~/code/infra",
                msgs=59, tokens=300_000, alter=3600 * 5),
    ]

    fenster = data.TokenWindow(start=jetzt - 3600 * 1.5,
                               reset=jetzt + 3600 * 3.5,
                               tokens=4_930_000, msgs=880)
    plan = data.PlanUsage(five_pct=27.0, five_reset=jetzt + 3600 * 3.5,
                          week_pct=41.0, week_reset=jetzt + 3600 * 52,
                          written_at=jetzt - 30)
    return data.Snapshot(
        sessions=sitzungen,
        n_live=3, n_busy=1, n_stored=3, n_queue=0,
        agents_ok=True, wd_ok=True, daemon_active=True, wd_restarts=0,
        mcp=[data.McpServer(name="github", client="Claude Code"),
             data.McpServer(name="playwright", client="Claude Code")],
        mcp_ok=True, taken_at=jetzt, window=fenster, plan=plan)
