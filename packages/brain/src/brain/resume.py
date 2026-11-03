"""The resume pack: ``brain resume [--project p | --all] [--budget N] [--write]`` (wi-brain-resume-pack, spec
2026-11-02 learned harness §3.16 and §4.9; Q7: on demand, plus one line at session start, and sub-session
briefs include it).

A short snapshot of a project's present state, built at zero token from its graph store, its records, its journal
and git, so that a session resuming the project does not rebuild it with tens of tool calls. It is deterministic (the
same inputs give the same bytes) and ordered from the most stable to the most volatile, so that a provider's prompt
cache, an exact prefix, keeps the longest prefix between two sessions started minutes apart:

  1. the project, its rules and the commands that hold the details;
  2. the milestones: pending ones with their progress, reached ones by id;
  3. the work: doing, then the startable P0/P1 items (the frontier), then the waiting P0/P1 items;
  4. the decisions: the queue's DDRs pending and answered, the items' open questions (``props.open``);
  5. git: the open PRs (gh, skipped with --offline or when it fails), the worktrees' branches;
  6. the journal: the last bullets of its last entry;
  7. the hand-over notes that name an open item (the desktop app's session-group notes folders,
     ``<BRAIN_HOME>/handover``, or ``$BRAIN_NOTES``);
  8. last, what changes every minute: the date and HEAD, the stacks, the session.

No date, age or counter of time comes before the last section. The pack points to the commands (``brain decision
pending``, ``research_graph work-frontier``, the kanban) instead of copying them, and copies neither the rules nor
the memory (both are injected) nor the history (``brain digest``: the journal section names the latest one written).
With a budget (tokens estimated at four characters each), lines are dropped from the volatile end, the hand-over
notes first, and one line says how many; the header and the last section stay. ``--write`` keeps the pack in
``<BRAIN_HOME>/resume/<project>.md``, outside the repo since it changes with every PR and journal line; the
SessionStart hook (``hooks/resume.sh``) says in one line whether it exists and how old it is, never what it holds.

Its readers (the store, the DDRs, the journal's entries, gh's JSON) and its budget cut serve ``brain digest`` too.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import actions, config, decisions, graph, midsession, milestones, paths, projects, records

BUDGET = 3000  # tokens; 0: no limit
CHARS_PER_TOKEN = 4
WIDTH = 118
JOURNAL_BULLETS = 4
NOTES_MAX = 8
PACK_DIR = "resume"
# research_graph's LayeredGraph: a todo item whose depends_on / gated_by targets all have one of these
# statuses is on the frontier.
SATISFIED = frozenset({"done", "reached", "validated", "active", "live"})
WORK_OPEN = ("todo", "doing", "blocked")
PRIORITIES = ("P0", "P1")
_ID_RE = re.compile(r"\b(?:wi|ms)-[a-z0-9][a-z0-9-]*[a-z0-9]")


@dataclass
class Section:
    title: str
    lines: list[str] = field(default_factory=list)
    keep: bool = False  # never dropped by the budget: the header and the last section


# --- the project and its store ---

def project_for(root: Path) -> projects.Project:
    """The registered project at ``root``; a worktree of a registered project's checkout gets that project's name and
    layout at the worktree."""
    p = projects.for_root(root)
    if p.registered:
        return p
    main = paths.main_checkout(root)
    if main and main.resolve() != root.resolve():
        m = projects.for_root(main)
        if m.registered:
            return projects.get(m.name, root)
    return p


def _load_list(path: Path) -> list:
    """A YAML list, read with libyaml's loader when PyYAML has it (a large store: 2.5 s in pure Python)."""
    if not path.is_file():
        return []
    data = graph.load_yaml_file(path)
    return data if isinstance(data, list) else []


def _nodes(store: Path) -> dict[str, dict]:
    return {str(n["id"]): n for f in sorted((store / "nodes").glob("*.yaml")) for n in _load_list(f)
            if isinstance(n, dict) and n.get("id")}


def _edges(store: Path) -> list[dict]:
    files = [store / "edges.yaml", *sorted((store / "edges").glob("*.yaml"))]
    return [e for f in files for e in _load_list(f) if isinstance(e, dict) and e.get("from")]


def _priority(node: dict) -> str:
    return str((node.get("props") or {}).get("priority") or "").strip()


def _sort_key(node: dict) -> tuple:
    p = _priority(node)
    return (p if p in PRIORITIES else "P9", node["id"])


def _row(prefix: str, text: str, width: int = WIDTH) -> str:
    """``prefix: text``, the text cut so the line fits the width (ids are never cut)."""
    room = max(width - len(prefix) - 2, 24)
    return f"{prefix}: {decisions._short(text, room)}" if text else prefix


@dataclass
class Store:
    nodes: dict[str, dict]
    edges: list[dict]

    @classmethod
    def load(cls, store: Path) -> "Store":
        return cls(_nodes(store), _edges(store))

    def status(self, nid: str) -> str:
        return str((self.nodes.get(nid) or {}).get("status") or "")

    def of_type(self, node_type: str) -> list[dict]:
        return sorted((n for n in self.nodes.values() if n.get("type") == node_type), key=lambda n: n["id"])

    def blockers(self, nid: str) -> list[str]:
        return sorted(e["to"] for e in self.edges if e["from"] == nid and e.get("type") in ("depends_on", "gated_by")
                      and self.status(e["to"]) not in SATISFIED)

    def milestone_items(self, mid: str) -> list[str]:
        """The work items part of a milestone, through its sub-milestones."""
        out, seen, stack = set(), {mid}, [mid]
        while stack:
            cur = stack.pop()
            for e in self.edges:
                if e.get("type") == "part_of" and e["to"] == cur and e["from"] not in seen:
                    seen.add(e["from"])
                    stack.append(e["from"])
                    if (self.nodes.get(e["from"]) or {}).get("type") == "WorkItem":
                        out.add(e["from"])
        return sorted(out)

    def open_items(self) -> set[str]:
        return {n["id"] for n in self.of_type("WorkItem") if n.get("status") in WORK_OPEN}


# --- the sections, stable to volatile ---

def _header(project: projects.Project, repo: str) -> Section:
    s = Section(f"Resume pack — {project.name} ({repo})", keep=True)
    rules = [f for f in ("CLAUDE.md", "AGENTS.md", ".claude/CLAUDE.md") if (project.root / f).is_file()]
    s.lines.append("Generated by `brain resume` from the graph, the records, the journal and git (zero token). The "
                   "global rules and the memory are injected already; the history: `brain digest` (the past week).")
    s.lines.append(f"Rules: {config.claude(config.load())['plugin']} rules/global.md (every project)"
                   + (f"; this project: {', '.join(rules)}" if rules else "") + ".")
    views = [v for v in ("notes/kanban_graph.md", "notes/roadmap_graph.md", "notes/decision_queue.md")
             if (project.root / v).is_file()]
    s.lines.append("Details: `brain decision pending`, `research_graph work-frontier | blocked | milestone <id>`"
                   + (f", {', '.join(views)}" if views else "") + "; everything: `brain resume --budget 0`.")
    return s


def _milestones(st: Store) -> Section:
    ms = [m for m in st.of_type("Milestone") if m.get("status") != "dropped"]
    pending = [m for m in ms if m.get("status") != "reached"]
    reached = [m for m in ms if m.get("status") == "reached"]
    s = Section(f"Milestones ({len(pending)} pending, {len(reached)} reached)")
    for m in pending:
        items = st.milestone_items(m["id"])
        live = [i for i in items if st.status(i) != "dropped"]
        done = sum(1 for i in live if st.status(i) == "done")
        s.lines.append(_row(f"- {m['id']} {done}/{len(live)} done", m.get("title", "")))
    if reached:
        s.lines.append(_row("Reached", ", ".join(m["id"] for m in reached), WIDTH * 4))
    ix = milestones.Index(st.nodes, st.edges)
    orphans = ix.orphans()
    if ms and orphans:
        proposed = sum(1 for o in orphans if (st.nodes[o].get("props") or {}).get(milestones.PROPOSED))
        s.lines.append(f"Outside every milestone: {len(orphans)} open item(s), {proposed} with a proposal waiting on "
                       f"{config.name_of()} (`brain milestone suggest`).")
    if not ms:
        s.lines.append("No milestone in the store.")
    return s


def _work(st: Store) -> Section:
    items = st.of_type("WorkItem")
    doing = sorted((n for n in items if n.get("status") == "doing"), key=_sort_key)
    top = [n for n in items if n.get("status") in ("todo", "blocked") and _priority(n) in PRIORITIES]
    startable = sorted((n for n in top if n.get("status") == "todo" and not st.blockers(n["id"])), key=_sort_key)
    ids = {n["id"] for n in startable}
    waiting = sorted((n for n in top if n["id"] not in ids), key=_sort_key)
    frontier = sum(1 for n in items if n.get("status") == "todo" and not st.blockers(n["id"]))
    s = Section("Work: doing, then the startable P0/P1 items, then the waiting ones")
    s.lines.append(f"Doing ({len(doing)}):" if doing else "Doing: none.")
    s.lines += [_row(f"- {n['id']} [{_priority(n) or '-'}]", n.get("title", "")) for n in doing]
    s.lines.append(f"Startable P0/P1 ({len(startable)} of the {frontier} on the frontier):")
    s.lines += [_row(f"- {n['id']} [{_priority(n)}]", n.get("title", "")) for n in startable]
    if waiting:
        s.lines.append(f"Waiting P0/P1 ({len(waiting)}):")
    for n in waiting:
        why = st.blockers(n["id"]) + (["blocked"] if n.get("status") == "blocked" else [])
        s.lines.append(_row(f"- {n['id']} [{_priority(n)}] after {', '.join(why)}", n.get("title", "")))
    return s


def record_files(root: Path, kind: str) -> list[dict]:
    """The DDRs (kind ddr) or SRs (kind sr) of a repo, by file name; records.load would also parse every AR."""
    files = sorted((root / records.RECORDS_DIR / kind).glob("*.yaml" if kind == "ddr" else "*/*.yaml"))
    recs = [graph.load_yaml_file(f) for f in files]
    return [r for r in recs if isinstance(r, dict) and r.get("id")]


def _decisions(project: projects.Project, st: Store) -> Section:
    ddrs = record_files(project.root, "ddr")
    pend = sorted((d for d in ddrs if d.get("status") == "pending"),
                  key=lambda d: (not d.get("blocking"), decisions._day(d.get("asked")), d["id"]))
    answered = sorted((d for d in ddrs if d.get("status") == "answered"), key=lambda d: d["id"])
    opens = [n for n in st.of_type("WorkItem") if n.get("status") in WORK_OPEN and (n.get("props") or {}).get("open")]
    s = Section("Decisions (the full list with the spec questions: `brain decision pending`)")
    if pend:
        s.lines.append(f"Waiting on {config.name_of()} ({len(pend)}):")
    for d in pend:
        rec = (d.get("recommendation") or {}).get("option") or "?"
        head = f"- {d['id']}{' [blocking]' if d.get('blocking') else ''} asked {decisions._day(d.get('asked'))}"
        s.lines.append(_row(head, f"{d.get('title', '')} -> recommended: {rec}"))
    if answered:
        s.lines.append(f"Answered, to integrate ({len(answered)}; `brain decision ack <id> --applied <where>`):")
    s.lines += [_row(f"- {d['id']}", f"{decisions._answer_text(d)} ({d.get('title', '')})") for d in answered]
    if opens:
        s.lines.append(f"Open questions on items, props.open ({len(opens)}):")
    s.lines += [_row(f"- {n['id']}", str(n["props"]["open"])) for n in opens]
    if not (pend or answered or opens):
        s.lines.append("Nothing in the queue and no open question on an item.")
    return s


def gh_json(root: Path, args: list[str], timeout: float = 15.0) -> tuple[list | None, str]:
    """gh's --json output for the repo at ``root``, or None and why (no gh, offline, not a GitHub repo)."""
    exe = shutil.which("gh")
    if not exe:
        return None, "gh not found"
    try:
        out = subprocess.run([exe, *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"gh: {type(exc).__name__}"
    if out.returncode:
        err = (out.stderr or "").strip().splitlines()
        return None, "gh: " + decisions._short(err[-1] if err else f"exit {out.returncode}", 80)
    try:
        data = json.loads(out.stdout or "[]")
    except ValueError:
        return None, "gh: no JSON in its output"
    return (data, "") if isinstance(data, list) else (None, "gh: not a JSON list")


def open_prs(root: Path, timeout: float = 15.0) -> tuple[list[dict] | None, str]:
    """The repo's open PRs by number, or None and why."""
    prs, why = gh_json(root, ["pr", "list", "--state", "open", "--limit", "50", "--json",
                              "number,title,headRefName,isDraft"], timeout)
    return (None, why) if prs is None else (sorted(prs, key=lambda p: p.get("number", 0)), "")


def worktree_branches(root: Path) -> list[str]:
    """The branches checked out in the repo's linked worktrees (the main checkout's is left out)."""
    blocks = actions.git(root, "worktree", "list", "--porcelain").replace("\r\n", "\n").split("\n\n")
    return sorted({ln[len("branch refs/heads/"):] for b in blocks[1:] for ln in b.splitlines()
                   if ln.startswith("branch refs/heads/")})


def _git(project: projects.Project, offline: bool) -> Section:
    s = Section("Git: open PRs and worktree branches")
    prs, why = (None, "--offline") if offline else open_prs(project.root)
    if prs is None:
        s.lines.append(f"Open PRs: not read ({why}).")
    else:
        s.lines.append(f"Open PRs ({len(prs)}):" if prs else "Open PRs: none.")
        s.lines += [_row(f"- #{p.get('number')} {p.get('headRefName', '')}{' [draft]' if p.get('isDraft') else ''}",
                         p.get("title", "")) for p in prs]
    branches = worktree_branches(project.root)
    if branches:
        s.lines.append(_row(f"Worktree branches ({len(branches)})", ", ".join(branches), WIDTH * 8))
    return s


def journal_entries(path: Path | None) -> list[tuple[str, list[list[str]]]]:
    """The journal's ``## `` entries in file order: (heading, its bullets, each with its continuation lines)."""
    if not path or not path.is_file():
        return []
    out: list[tuple[str, list[list[str]]]] = []
    for ln in path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n"):
        if ln.startswith("## "):
            out.append((ln[3:].strip(), []))
        elif not out or not ln.strip():
            continue
        elif ln.startswith(("- ", "* ")) or not ln[:1].isspace() or not out[-1][1]:
            out[-1][1].append([ln.rstrip()])
        else:
            out[-1][1][-1].append(ln.rstrip())
    return out


def last_entry(path: Path | None, bullets: int = JOURNAL_BULLETS) -> tuple[str, list[list[str]], int]:
    """The heading of the journal's last entry, its last bullets (each with its continuation lines), and how many
    bullets the entry has."""
    entries = journal_entries(path)
    if not entries:
        return "", [], 0
    head, groups = entries[-1]
    return head, groups[-bullets:], len(groups)


def relative(project: projects.Project, path: Path | None) -> str:
    return path.relative_to(project.root).as_posix() if path and path.is_relative_to(project.root) else str(path)


def _journal(project: projects.Project) -> Section:
    from . import digest  # digest imports this module
    head, kept, n = last_entry(project.journal)
    s = Section(f"Journal ({relative(project, project.journal)}): the last entry's last bullets")
    latest = digest.latest(project.name)
    if latest:
        s.lines.append(f"History: the latest digest is {_display(latest)}; `brain digest --since <day>` for another "
                       "window.")
    if not head:
        s.lines.append("No entry.")
        return s
    s.lines.append(f"Last entry: {head}" + (f" (its last {len(kept)} of {n} bullets)" if n > len(kept) else ""))
    s.lines += [ln for g in kept for ln in g]
    return s


def notes_dirs(extra: list[str] | None = None) -> list[Path]:
    """Where hand-over notes are looked for: --notes, then ``$BRAIN_NOTES`` (os.pathsep-separated) when set, else
    ``<BRAIN_HOME>/handover`` and the desktop app's session-group notes folders
    (``%LOCALAPPDATA%/Claude-Data/*/side-session-notes/*``)."""
    env = os.environ.get("BRAIN_NOTES")
    if env is not None:
        dirs = [Path(p).expanduser() for p in env.split(os.pathsep) if p]
    else:
        dirs = [paths.brain_home() / "handover"]
        app = os.environ.get("LOCALAPPDATA")
        if app:
            dirs += sorted(Path(app).glob("Claude-Data/*/side-session-notes/*"))
    return [d for d in [*(Path(x).expanduser() for x in extra or []), *dirs] if d.is_dir()]


def _display(path: Path) -> str:
    try:
        return "~/" + path.resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def handover_notes(dirs: list[Path], open_ids: set[str]) -> list[tuple[float, Path, str, list[str]]]:
    """The markdown notes that name an open item of the project (the others are done with or belong to another
    project), newest first: (mtime, path, title, the open ids it names)."""
    out = []
    for d in dirs:
        for f in sorted(d.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                mtime = f.stat().st_mtime
            except OSError:
                continue
            ids = sorted(set(_ID_RE.findall(text)) & open_ids)
            if ids:
                title = next((ln.lstrip("#").strip() for ln in text.splitlines() if ln.startswith("#")), f.stem)
                out.append((mtime, f, title, ids))
    return sorted(out, key=lambda r: (-r[0], r[1].as_posix()))


def _handover(st: Store, dirs: list[Path]) -> Section:
    notes = handover_notes(dirs, st.open_items())
    s = Section("Hand-over notes that name an open item (newest first)")
    for mtime, f, title, ids in notes[:NOTES_MAX]:
        day = datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%d")
        s.lines.append(_row(f"- {_display(f)} ({day})", f"{title} [{', '.join(ids)}]", WIDTH * 2))
    if len(notes) > NOTES_MAX:
        s.lines.append(f"... and {len(notes) - NOTES_MAX} older one(s).")
    if not notes:
        s.lines.append("None" + (f" in {len(dirs)} folder(s)." if dirs else ": no notes folder found."))
    return s


def _stacks_line(project: projects.Project, health: bool) -> str:
    try:
        from . import stacks
        mine = [s for s in stacks.load(project.root).values() if s.project == project.name]
    except Exception as exc:  # noqa: BLE001 - the registry is optional here
        return f"Stacks: not read ({type(exc).__name__})."
    if not mine:
        return "Stacks: none declared."
    rows = []
    for s in mine:
        state = ""
        if health:
            why = stacks.check(s, stacks.HOOK_URL_TIMEOUT, stacks.HOOK_CMD_TIMEOUT)
            state = f" {'DOWN' if why else 'OK'}"
        rows.append(f"{s.name}{state}{'' if s.watch else ' (on demand)'}")
    return f"Stacks: {', '.join(rows)}; `brain health {' '.join(s.name for s in mine)}`" + \
        ("" if health else " checks them") + "."


def _now(project: projects.Project, now: datetime, health: bool) -> Section:
    s = Section("Now", keep=True)
    head = actions.git(project.root, "rev-parse", "--short", "HEAD")
    branch = actions.git(project.root, "rev-parse", "--abbrev-ref", "HEAD")
    s.lines.append(f"Generated {now.strftime('%Y-%m-%d %H:%M')} UTC"
                   + (f" at {head} on {branch}" if head else " (not a git checkout)") + ".")
    s.lines.append(_stacks_line(project, health))
    session = os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")
    if session:
        s.lines.append(f"Session: {session}.")
    return s


# --- assembly ---

def tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def render(sections: list[Section]) -> str:
    return "\n\n".join("\n".join([f"## {s.title}" if i else f"# {s.title}", *s.lines])
                       for i, s in enumerate(sections) if s.lines or s.keep) + "\n"


def fit(sections: list[Section], budget: int, end: str = "the volatile end", command: str = "brain resume") \
        -> list[Section]:
    """Drop lines from the end (the last section that may lose lines first) until the text fits the budget; a
    section left without lines goes, and a line before the last section says what was dropped."""
    if budget <= 0 or tokens(render(sections)) <= budget:
        return sections
    out = [Section(s.title, list(s.lines), s.keep) for s in sections]
    dropped = 0
    note = Section("Cut", ["(placeholder)"])
    out.insert(len(out) - 1, note)
    while tokens(render(out)) > budget:
        victim = next((s for s in reversed(out) if not s.keep and s is not note and s.lines), None)
        if victim is None:
            break
        victim.lines.pop()
        dropped += 1
        while victim.lines and victim.lines[-1].endswith(":"):  # a sub-heading whose rows are gone
            victim.lines.pop()
            dropped += 1
        note.lines = [f"{dropped} line(s) dropped from {end} to fit --budget {budget} (~{CHARS_PER_TOKEN} "
                      f"characters per token); `{command} --budget 0` prints them all."]
    return [s for s in out if s.lines or s.keep]


def graph_store(project: projects.Project) -> Path | None:
    """The project's first store with a schema."""
    return next((s for s in project.stores if (s / "schema.yaml").is_file()), None)


def build(project: projects.Project, *, budget: int = BUDGET, offline: bool = False, health: bool = False,
          notes: list[str] | None = None, now: datetime | None = None) -> str:
    store = graph_store(project)
    st = Store.load(store) if store else Store({}, [])
    main = paths.main_checkout(project.root)
    repo = (main or project.root).name
    sections = [_header(project, repo)]
    if store:
        sections += [_milestones(st), _work(st)]
    sections += [_decisions(project, st), _git(project, offline), _journal(project),
                 _handover(st, notes_dirs(notes)), _now(project, now or datetime.now(timezone.utc), health)]
    return render(fit(sections, budget))


def pack_path(name: str) -> Path:
    return paths.brain_home() / PACK_DIR / f"{name}.md"


def write(name: str, text: str) -> Path:
    f = pack_path(name)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8", newline="\n")
    return f


# --- the SessionStart line ---

def age(seconds: float) -> str:
    if seconds < 60:
        return "less than a minute"
    for unit, n in (("day", 86400), ("h", 3600), ("min", 60)):
        if seconds >= n:
            v = int(seconds // n)
            return f"{v} {unit}{'s' if unit == 'day' and v > 1 else ''}"
    return ""  # pragma: no cover


def announce(cwd: str | Path, now: float | None = None) -> str:
    """One line for the session's project (the nearest folder above ``cwd`` with notes/graph/schema.yaml): whether its
    pack is written and how old it is; '' outside a project."""
    here = Path(cwd).resolve()
    root = next((d for d in (here, *here.parents) if (d / "notes" / "graph" / "schema.yaml").is_file()), None)
    if root is None:
        return ""
    name = project_for(root).name
    f = pack_path(name)
    what = ("`brain resume` prints the present state (milestones, frontier, decisions, PRs, journal, hand-over "
            "notes): read it to resume work, and put it in sub-session briefs.")
    if not f.is_file():
        return f"Resume pack of {name}: none written. {what}"
    when = age((now if now is not None else time.time()) - f.stat().st_mtime)
    return (f"Resume pack of {name}: written {when} ago ({_display(f)}, ~{tokens(f.read_text(encoding='utf-8'))} "
            f"tokens). {what}")


def hook_main(argv: list[str], stdin=None) -> int:
    """SessionStart hook: the line as additionalContext. Never fails: an error goes to <BRAIN_HOME>/ledger/errors.log
    and the session goes on."""
    try:
        data = midsession.read_payload(stdin)   # UTF-8 bytes, whatever the console's codepage
        text = announce(data.get("cwd") or ".")
        if text:
            event = argv[0] if argv else "SessionStart"
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
                             ensure_ascii=True))
    except BaseException as exc:  # noqa: BLE001 - a hook never breaks a session start, SystemExit included
        from .capture import _log_error
        _log_error("resume-announce", exc)
    return 0
