"""``brain tui``: the cockpit: sessions and their steps, the owner's queue, alerts, milestones, frontier, audit, stacks
and index, digest; read-only, zero token.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import cockpit, detail, shutdown
from ._common import _scope

ORDER = 140   # its place in brain --help's list of commands (brain.commands)
USAGE_ORDER = 540   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain tui [--project P | --all | --scope REF] [--refresh 2s] [--probe 5m] [--hours 24] [--plain]
            [--sort PANEL:KEY]... [--filter PANEL:FIELD=VALUE]... [--search TEXT] [--tab NAME] [--tz local|utc]
            [--reset]
            [--once [--quick]] [--json]
                 the cockpit, read-only and at zero token: sessions (project, task, step n/m of its plan, state,
                 model, effort, context and tokens), {owner}'s queue, alerts, milestones, the frontier by priority,
                 audit debt, stacks and code index, the digest; the panels re-read when their files change (checked
                 every --refresh, default 2 s; + and - change it), the probes (alerts, audit, health, digest, denied
                 calls) every --probe and on the r key; the Textual app with the tui extra (pip install brain[tui]),
                 else (--plain) the same text redrawn in place; --once prints it once (--quick: no probe), --json its
                 data (unfiltered). One tab per question, each on its key: 0 overview (its views, v: one card per tab,
                 which Enter or a click opens already filtered, the grid, the digest), 1 {owner}'s queue, 2 sessions,
                 3 frontier, 4 milestones, 8 health (alerts, audit, stacks and index, exec times), the comma settings
                 (its pages: Cockpit, the screen's own settings in tui.json, edited there with Enter: theme,
                 timezone, language, refresh and probe intervals, each panel's free title; Identity, Brain,
                 Permissions, each brain setting with its file and the command that changes it, never edited there;
                 Modules, each module of the catalogue with its state, cost and needs, turned on or off by
                 brain mod's plan then its apply on y;
                 Setup, the setup wizards: a choice, the plan run, then the apply on y, each command logged as
                 {owner}'s), then a plugged project's tabs and panels, as its plugin declares them (COCKPIT,
                 brain.plugin_panels: a tab by its name, no number, before the settings; its tables sorted, filtered,
                 searched and saved as the others, read at the first read and at each probe), ctrl+pageup and
                 ctrl+pagedown the previous and next, Escape back to the overview;
                 Escape first clears the search and closes a full view; the bar shows the queue's band now, the
                 sessions asking and the open alerts, and is reduced to its
                 numbers under 120 columns or 30 rows, where the cards take one column and the grid is not offered;
                 --tab NAME starts there, and with --once or --plain prints that tab's panels alone (the overview:
                 its cards; the settings: its pages). The project selector (p: global or one
                 project), the sessions', queue's and frontier's filters and sorts (f, s, o), a table's columns (C:
                 shown or hidden, their order, the longest a title may be; the sessions also offer Cost, App id, Id and
                 Branch), the palette (ctrl+p: every tab, view, project, sort, filter and table's columns, and reset
                 the views), the search (/), a panel's
                 help (i), a full view where a tab shows several panels (m, Escape back), the pause (space) and ? for
                 every key; a refresh keeps the scroll and the cursor; an empty
                 table says why (a filter, nothing in the scope, a project not on this machine), a panel not probed
                 yet its countdown then its progress, a failed read keeps the last content and its time (--all
                 without a registry: this folder's project); the
                 interactive views remember the scope, views, last tab, columns, theme and timezone (--tz, t; default local) in
                 $BRAIN_HOME/tui.json (--reset forgets them; --project, --all, --sort, --filter, --tab and --tz win;
                 a newer brain's tui.json is shown, never written); one interactive cockpit per machine (a second
                 is refused, exit 1; --once, --json and --detail read beside it).
                 Enter: the row's detail (a DDR's options, an item's spec, ADRs and PR, a session's plan): from 140
                 columns, on a tab of one list, it sits right of the list and follows the cursor (Enter gives it the
                 focus, Escape gives it back; a, d and A work from the list too), else it opens over the panels; in it, o
                 opens a link in the editor or the browser, a answers a decision, d marks an action or a permission
                 done, A applies an action's command, each run as {owner}'s after a confirmation of the exact brain
                 command and logged in $BRAIN_HOME/ledger/cockpit-<month>.jsonl (refused in a Claude Code session).
                 The title bar: the installed version, « pin v0.2.3: -Apply » when it lags config.json engine.pin and
                 the brain declares its installer (engine.installer), « 0.2.4 available » for a newer tag; u then
                 shows that installer's plan (else brain update's) and, on y, the cockpit exits and a new window
                 installs (-Apply, or brain update --yes) and relaunches brain tui with the same arguments
  brain tui --detail ID [--quick] [--json]   one row's detail printed: a DDR, an item, a milestone, a session (the
                 start of its id), an alert's key; its links and its actions with their exact commands
"""


def cmd_tui(args, root: Path) -> int:
    """The cockpit (brain.cockpit): the Textual app with the tui extra, else its text redrawn in place; --once or
    --json: one read. The interactive views start from the scope, the views, the tab and the columns they last showed
    (<BRAIN_HOME>/tui.json; --project or --all, --sort, --filter and --tab win, --reset forgets them) and remember
    them."""
    notes = cockpit.plug_registry(root)   # the plugged projects' panels and tabs, before their views are read
    if args.tab and args.tab not in cockpit.built_tabs():
        raise SystemExit(f"brain tui: --tab {args.tab}: one of {', '.join(cockpit.built_tabs())}")
    try:
        flags = cockpit.parse_view(args.sort, args.filter)
    except ValueError as exc:
        raise SystemExit(f"brain tui: {exc}") from None
    interactive = not (args.once or args.json or args.detail)
    if not interactive:   # the cockpit notifies them; a one-shot read says them on stderr
        for text in notes:
            print(f"brain tui: plugin: {text}", file=sys.stderr)
    saved = cockpit.load_state() if interactive and not args.reset else {}
    views = {n: {**(saved.get("panels") or {}).get(n, {}), **flags.get(n, {})} for n in cockpit.SORTS}
    settings = {"tz": "local", **(saved.get("settings") or {}), **({"tz": args.tz} if args.tz else {})}
    # --refresh and --probe win for one launch; else the Settings tab's (tui.json), else the defaults
    args.refresh = args.refresh or settings.get("refresh") or cockpit.REFRESH_S
    args.probe = args.probe or settings.get("probe") or cockpit.PROBE_S
    projs = _projects(args, root)
    cp = cockpit.Cockpit(projs, every=args.all, root=root, hours=args.hours)   # --scope: its projects, no more
    if not (args.all or args.scope or getattr(args, "project", None)) and saved.get("scope") in (cockpit.ALL,
                                                                                                *cp.choices):
        cp.select(saved["scope"])  # the last scope shown, when it is still registered
    if args.detail:  # the files first; the probes only when the row is not found in them (an alert, a denial)
        cp.refresh(probe=False)
        d = detail.lookup(cp, args.detail)
        if d is None and not args.quick:
            cp.refresh(probe=True)
            d = detail.lookup(cp, args.detail)
        if d is None:
            print(f"brain tui: {args.detail}: no row, DDR, item or milestone of that id in {cp.scope}",
                  file=sys.stderr)
            _failed_reads(cp.snapshot())
            return 1
        print(detail.as_json(d) if args.json else "\n".join(detail.lines(d)))
        return 0
    if not interactive:
        cp.refresh(probe=not args.quick and args.tab != "settings")   # the settings read no probe
        snap = cp.snapshot()
        print(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True) if args.json
              else "\n".join(cockpit.render(snap, views=views, search=args.search, tz=args.tz, tab=args.tab,
                                                 root=root)))
        return 1 if _failed_reads(snap) else 0
    try:   # one interactive cockpit per machine (brain.shutdown); --once, --json and --detail read beside it
        with shutdown.single_instance("cockpit", "brain tui"):
            return _interactive(args, cp, saved, views, settings)
    except shutdown.Busy as exc:
        print(f"brain tui: {exc}; brain tui --once reads beside it", file=sys.stderr)
        return 1


def _interactive(args, cp, saved: dict, views: dict, settings: dict) -> int:
    tab, tabs, columns = args.tab or saved.get("tab"), saved.get("tabs") or {}, saved.get("columns") or {}
    kept = (saved.get("scope") or cp.scope) if args.scope else cp.scope   # --scope keeps the one remembered
    if not cockpit.save_state({"scope": kept, "panels": views, "settings": settings, "tab": tab, "tabs": tabs,
                               "columns": columns}):
        why = cockpit.state_refusal()   # a newer brain's tui.json: shown, never written (before the screen draws)
        if why:
            print(f"brain tui: {why}; the views are not remembered", file=sys.stderr)
    if not args.plain:
        try:
            from .. import tui
        except ModuleNotFoundError as exc:
            if (exc.name or "").split(".")[0] not in ("textual", "rich"):
                raise
            print("brain tui: the Textual app needs the tui extra (pip install -e <brain checkout>[tui] in brain's "
                  "venv); the text view meanwhile (Ctrl-C quits)", file=sys.stderr)
        else:
            return tui.run(cp, refresh=args.refresh, probe=args.probe, views=views, search=args.search,
                           settings=settings, tab=tab, tabs=tabs, columns=columns)
    return cockpit.watch(cp, args.refresh, args.probe, views=views, search=args.search, tz=settings["tz"], tab=args.tab)


def _projects(args, root: Path) -> list:
    """The scope's projects; --all without a registry: this folder's project, which stderr says (args.all goes off)."""
    try:
        return _scope(args, root)
    except SystemExit as exc:
        if not args.all or getattr(args, "project", None):
            raise
        print(f"{exc}; brain tui shows this folder's project", file=sys.stderr)
        args.all = False
        return _scope(args, root)


def _failed_reads(snap: dict) -> bool:
    """A one-shot read (--once, --json, --detail) that failed: each error on stderr, once per error; True if any."""
    by_error: dict[str, list[str]] = {}
    for name, e in (snap.get("errors") or {}).items():
        by_error.setdefault(e["error"], []).append(name)
    for error, names in by_error.items():
        print(f"brain tui: reading {', '.join(names)} failed: {error}", file=sys.stderr)
    return bool(by_error)


def _duration(text: str) -> float:
    """argparse type: 500ms, 2s, 5m, 1h or seconds, at least 0.25 s."""
    try:
        s = cockpit.duration(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None
    if s < 0.25:
        raise argparse.ArgumentTypeError(f"{text!r}: 250ms at least")
    return s


def register(sub, ctx) -> None:
    who = ctx.who
    tu = sub.add_parser("tui", help=f"the cockpit: sessions and their steps, {who}'s queue, alerts, milestones, "
                                    "frontier, audit, stacks and index, digest; read-only, zero token")
    tu.add_argument("--all", action="store_true", help="every registered project, and every session")
    tu.add_argument("--scope", help="the projects of a node's subtree in the scope tree (brain scopes): an "
                    "id, a path of ids, global (= --all), . or ..")
    tu.add_argument("--refresh", type=_duration, metavar="DURATION",
                    help="how often the panels' files are checked, re-read when changed: 500ms, 1s, 2s, 5s... "
                         "(for this launch; default: the Settings tab's, else 2s)")
    tu.add_argument("--probe", type=_duration, metavar="DURATION",
                    help="how often alerts, audit, stacks and index, digest and the denied calls are read again "
                         "(for this launch; default: the Settings tab's, else 5m; the r key: now)")
    tu.add_argument("--hours", type=float, default=cockpit.HOURS,
                    help=f"the sessions whose transcript was written in the last N hours (default {cockpit.HOURS:g})")
    tu.add_argument("--plain", action="store_true", help="the text view redrawn in place, even with the tui extra")
    tu.add_argument("--sort", action="append", default=[], metavar="PANEL:KEY",
                    help="a panel's sort, -KEY reversed: "
                         + ", ".join(f"{n}:{'|'.join(keys)}" for n, keys in cockpit.SORTS.items())
                         + " (the first: the default; repeatable)")
    tu.add_argument("--filter", action="append", default=[], metavar="PANEL:FIELD=VALUE",
                    help="a panel's filter: sessions:state=open|all|asking|running|stale|idle|ended, "
                         "queue:kind=all|decision|action|permission, frontier:priority=all|P0-P1|P0-P2|none, "
                         "frontier:milestone=all|none|<id> (repeatable)")
    tu.add_argument("--search", default="", metavar="TEXT",
                    help="the rows holding every word of TEXT (ids, titles, projects; case ignored)")
    tu.add_argument("--tab", metavar="NAME",
                    help="start on that tab: " + ", ".join(cockpit.built_tabs()) + ", or a plugged project's tab "
                         "(default: the last one shown, else the overview); with --once or --plain, print its panels "
                         "alone (the overview: its cards)")
    tu.add_argument("--tz", choices=cockpit.TZS,
                    help="the times shown: this machine's timezone (local, the interactive default) or UTC; --once "
                         "and --json keep the recorded UTC times unless it is given")
    tu.add_argument("--reset", action="store_true",
                    help="start from the defaults: forget the scope, views, tab and columns remembered in "
                         "<BRAIN_HOME>/tui.json")
    tu.add_argument("--detail", metavar="ID",
                    help="print a row's detail and exit, as Enter shows it: a DDR (its options, its answer), an item "
                         "(props, spec sections, ADRs, PR, code), a milestone, a session (its plan; the start of its "
                         "id), an alert's key; its links and its actions with their exact commands (--json: the data)")
    tu.add_argument("--once", action="store_true", help="print the text view once and exit")
    tu.add_argument("--quick", action="store_true", help="with --once or --json: the files only, no probe")
    tu.add_argument("--json", action="store_true", help="the panels' data, once")


run = cmd_tui
