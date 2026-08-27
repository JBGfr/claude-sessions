# Security

This app is a local viewer. It reads a handful of files that Claude Code and
the Claude Watchdog already keep in your home directory, asks the Claude Code
CLI which sessions are running, and draws the result in a window. It also ships
three command line helpers that do open terminal windows and start services;
they have a section of their own below. Every claim here points at the line
that implements it.

## What it reads

| Data | Path | How it is opened |
|---|---|---|
| Transcripts of stored sessions | `~/.claude/projects/*/*.jsonl` — `claude_sessions/data.py:19`, globbed in `data.py:601` and `data.py:613` | `path.open("rb")`, read only, `data.py:548` |
| Running sessions | `claude agents --json --all` — `data.py:778`, binary resolved in `data.py:45`–`data.py:61` | subprocess, output captured, `data.py:777` |
| Watchdog tasks and restart count | `<watchdog dir>/state.db` — `data.py:40` | SQLite URI `file:<path>?mode=ro`, `data.py:824` |
| Watchdog daemon state | `systemctl --user is-active claude-watchdog` — `data.py:905` | subprocess, output captured |
| Plan usage | `~/.local/state/claude-sessions/usage.json` — `data.py:68` | `path.read_text(...)`, `data.py:507` |
| MCP server configuration | `~/.claude.json`, `~/.config/Claude/claude_desktop_config.json` — `data.py:76`, `data.py:77` | `path.read_bytes()`, `data.py:871` |
| Process facts of a session | `/proc/<pid>/cgroup`, `/proc/<pid>/comm`, `/proc/<pid>/stat` — `data.py:723`, `data.py:760`, `actions.py:144` | read only |

Transcripts are read incrementally: once a prefix has been parsed, the next
pass seeks past it (`data.py:548`–`data.py:551`). Nothing is copied anywhere.

## The watchdog database is opened read-only

`data.py:824` connects with the SQLite URI `file:%s?mode=ro`, so the SQLite
library itself rejects any write on that connection. The app never issues
`INSERT`, `UPDATE` or `DELETE` — the two statements it runs are the `SELECT`s
at `data.py:826` and `data.py:831`.

Every state change goes through the watchdog's own command line tool instead
(`WATCHDOG_BIN`, `data.py:42`), invoked in `actions.py:239`–`actions.py:243`.
If that directory does not exist, `watchdog_tasks()` returns an empty result
rather than raising (`data.py:820`–`data.py:821`).

## It opens no network connection

No module of the app imports a networking library. The complete import lists
are `data.py:4`–`data.py:16`, `actions.py:4`–`actions.py:12`, `app.py:4`–`app.py:16`
and `tools/statusline.py:25`–`tools/statusline.py:29`: standard library plus
`gi`. There is no `socket`, no `urllib`, no `http`, no HTTP client of any
kind, and no telemetry. Verifiable with

```sh
grep -rn "socket\|urllib\|http\|requests" claude_sessions/ tools/
```

The MCP section is the only place where a URL appears at all, and it is only
ever read out of a config file and printed into a tooltip
(`data.py:846`–`data.py:864`). `claude mcp list`, which would contact the
servers, is deliberately not used (`data.py:893`–`data.py:895`). Fields that
can carry credentials — `env`, `headersHelper` and anything else — are never
looked at: `_mcp_entry` reads `url`, `type`, `command` and `args`, nothing
else.

## It writes nothing into anybody else's data

The app writes exactly two files, both of them its own, and both only when
the user presses **Save** in the settings dialog. Everything it *reads* —
transcripts, `state.db`, the MCP configs — it never writes back.

| File | Written when | How |
|---|---|---|
| `~/.config/claude-sessions/settings.json` | Save in the settings dialog | temp file in the same directory + `fsync` + `os.replace()`, `einstellungen.py:216`–`einstellungen.py:239` |
| `~/.config/systemd/user/claude-watchdog.service.d/uebersteuerung.conf` | Save, and only if its content actually changes | same atomic write, `einstellungen.py:338`–`einstellungen.py:355` |

The drop-in is the only file the app puts into somebody else's directory,
and it is deliberately narrow: a file of its own name next to the watchdog
unit (never the unit itself, which is a symlink into the watchdog repo), with
two `Environment=` lines and nothing else (`einstellungen.py:322`–
`einstellungen.py:335`). If the watchdog unit does not exist, the step is
skipped in silence (`einstellungen.py:307`–`einstellungen.py:319`,
`app.py:1521`–`app.py:1523`). Both paths can be moved for tests:
`CS_SETTINGS_PATH` and `CS_WD_DROPIN_PATH`.

Neither write is in place — a temporary file is renamed over the target, so
an interrupted save leaves either the old or the new file, never half of one.
Both are covered by tests that go red if that ever changes
(`tests/test_einstellungen.py`, `tests/test_dropin.py`).

Nothing else in the package writes anything. Both files go through the same
single write path, `_atomar_schreiben`, and the grep below finds no other:

```sh
grep -rn "write_text\|write_bytes\|open(.*[\"']w\|os.replace" claude_sessions/
```

The other writer in this repository is the status line script, and it writes
exactly one file of its own under `~/.local/state/claude-sessions/usage.json`
(`tools/statusline.py:31`, written atomically in
`tools/statusline.py:60`–`tools/statusline.py:78`). It touches neither the
transcripts nor `state.db`, starts no subprocess, and swallows every error so
that it can never disturb the session that calls it.

## Windows, terminals and signals happen on click only

Everything that starts a process is wired to a widget the user has to
activate:

- the row's primary button and its `⋮` menu — `app.py:404`, `app.py:410`,
  `app.py:512`;
- the footer buttons for the live log and the watchdog daemon —
  `app.py:937`, `app.py:947`, handled in `app.py:1462` and `app.py:1468`;
- the gear button in the header bar — `app.py:844`, handled in
  `app.py:1479`; the two systemd commands it can trigger (`try-restart` of
  the watchdog, `restart` of the app itself) run only after that dialog was
  confirmed (`actions.py:294`, `actions.py:323`).

From there the actions are `open_session` (`actions.py:120`),
`attach_session` (`actions.py:126`), `open_folder` (`actions.py:233`),
`show_watchdog_logs` (`actions.py:251`) and `show_live_log`
(`actions.py:261`), all of which go through `_spawn_detached`
(`actions.py:60`) and end up in a transient systemd unit with memory limits
(`actions.py:53`–`actions.py:57`).

The only automatic subprocesses are the three read-only queries listed above
(`data.py:778`, `data.py:905`, plus the `/proc` reads), and they run only
while a window is actually visible: the refresh timer skips the load entirely
when the window is closed, minimised or unmapped (`app.py:1228`,
`app.py:1245`–`app.py:1249`).

Destructive actions ask first. Terminating a session opens a confirmation
dialog (`app.py:1414`), and `actions.terminate` re-checks that the PID still
belongs to a `claude` process before it sends `SIGTERM` — never `SIGKILL` —
because the PID may have been recycled while the dialog was open
(`actions.py:203`–`actions.py:209`). Stopping a session service
(`app.py:1432`) and removing a running watchdog task (`app.py:1450`) are
confirmed the same way.

## The helper commands start things — but only when called

The three tools in `bin/` do more than the window does: they open terminal
windows and start systemd user services. None of that happens by itself.
`claude-session-open` opens exactly one window per call, through `systemd-run
--user` (`bin/claude-session-open:249`–`bin/claude-session-open:258`) or, where
there is no systemd, directly
(`bin/claude-session-open:271`–`bin/claude-session-open:275`), and it does
nothing unless it is run as a script
(`bin/claude-session-open:319`–`bin/claude-session-open:320`). In
`claude-sessionctl` only `new`, `start`, `stop`, `restart` and `rm` change
anything — `status`, `attach`, `log`, `list` and `pid` only read (dispatch:
`bin/claude-sessionctl:297`–`bin/claude-sessionctl:311`). A service is enabled
only inside `start` and `restart` (`bin/claude-sessionctl:136`,
`bin/claude-sessionctl:161`), that is, for a session you asked for;
`tools/install-desktop.sh` places the unit template as a symlink and enables
nothing (`tools/install-desktop.sh:277`). `claude-session-runner` is not a
user-facing command at all: it is the `ExecStart=` of that template
(`systemd/claude-session@.service:18`) and exits without doing anything when it
is called without an instance name
(`bin/claude-session-runner:18`–`bin/claude-session-runner:24`).

None of the three opens a network connection. The grep below has exactly one
hit worth naming: `bin/claude-session-open:30` imports `urllib.parse` — the
string parser for the `claude-session://` URI. `urlparse` and `unquote` contact
nothing. The "sockets" in the other two files are the local `dtach` Unix socket
under `$XDG_RUNTIME_DIR`.

```sh
grep -rn "socket\|urllib\|http\|requests\|curl\|wget" bin/ systemd/
```

What they write:

| Tool | What | Where |
|---|---|---|
| `claude-session-open` | one appended log line per call, and nothing else | `~/.local/state/claude-sessions/events.log` — path in `bin/claude-session-open:45`–`bin/claude-session-open:61`, written in `bin/claude-session-open:92`–`bin/claude-session-open:100` |
| `claude-sessionctl` | the project file (`bin/claude-sessionctl:102`, removed again in `bin/claude-sessionctl:184`) and the shared event log (`bin/claude-sessionctl:80`–`bin/claude-sessionctl:83`); both directories are created only by `new`, `start`, `restart` and `rm` (`ensure_dirs`, `bin/claude-sessionctl:36`); `--help`, `list`, `status`, `log` and `attach` write nothing | `~/.config/claude-sessions/`, `~/.local/state/claude-sessions/` |
| `claude-session-runner` | project log and event log (`bin/claude-session-runner:40`, `bin/claude-session-runner:44`), the dtach socket (`bin/claude-session-runner:155`), and one temporary file carrying the real exit code, removed by its own `trap` (`bin/claude-session-runner:152`–`bin/claude-session-runner:153`) | `~/.local/state/claude-sessions/`, `$XDG_RUNTIME_DIR`, `$TMPDIR` |

Two writes reach past those two directories, and both are deliberate.
`claude-sessionctl rm` deletes the dtach socket of that project
(`bin/claude-sessionctl:183`), but only for a name that has a config file here
(`bin/claude-sessionctl:176`–`bin/claude-sessionctl:177`): other programs keep
sockets in `$XDG_RUNTIME_DIR` as well, and without that guard a typo would have
disabled one of them while reporting success for a project that never existed.
And `enable`/`disable` (`bin/claude-sessionctl:136`, `:145`, `:161`, `:179`)
have systemd add or remove its own symlink under
`~/.config/systemd/user/default.target.wants/`. Neither tool ever writes a unit
file.

## What it shows

The window displays the **titles** and the **project paths** of your Claude
Code sessions, side by side with the directories they ran in
(`data.py:238`–`data.py:285` extracts title and `cwd` from the transcript).
A session title says what the session was about. A path names a directory on
your machine and usually a user name with it.

That means: anyone who shares a screenshot of this app shares that list.
Titles of client work, names of unreleased projects, the layout of a home
directory — all of it is legible in a single picture. This repository
therefore contains no screenshots, and none should be added; the same goes for
bug reports and pull requests. When you need to show the interface, blank the
title and path columns first.

The app itself sends nothing anywhere, so this is the one real exposure it
has, and it is entirely under your control.

## Reporting a problem

Open an issue at
<https://github.com/JBGfr/claude-sessions/issues> and describe what an
attacker could reach and how you got there. Please strip session titles,
paths, user names and any transcript content from the report first — a
redacted report is more useful here than a complete one.

There is no bug bounty, and there are no security releases: this is a local
desktop tool maintained in someone's spare time. Fixes land on `main` like
everything else.
