"""The cockpit's detail pane and its actions (wi-brain-tui-detail, wi-brain-tui-actions; spec 2026-11-02 cockpit-ux
§4.6, §4.7 and §4.14; UX-3, UX-4 and UX-9). The standard library and brain only: the Textual app
(``brain.tui``) draws what this module returns, and ``brain tui --detail ID`` prints it.

``of(name, row, cp)`` is a row's detail, read at zero token from files already there, as sections of lines:

  queue       a DDR's question, context, options with their consequences, the recommendation and its reason, what
              waits on it; an action's or a permission's ask; an item prop's text; a denied call's occurrences; the
              items and milestones it unblocks; how to answer it;
  frontier    an item (``item``): its full title, status and props, its spec sections (documented_in, specified_by),
              its ADRs (decided_by), its PR, its code and tests, what it waits on and what waits on it;
  milestones  a milestone's trigger and its items by status;
  sessions    a session's plan step by step, folder, branch, model, context and budget, cost, transcript;
  alerts      an alert's level, source, subject, since and full message, and the command for more.

Each detail has ``links``: a file at a line (a spec section, an ADR, a DDR, a folder) that ``open_link`` opens in
the editor ($EDITOR, else VS Code's ``code -g``, else the system's opener), a pull request it opens in the browser, or
another item's detail. Opening is a side effect on the desktop only: nothing is written.

And ``actions``, each one or two ``brain`` commands the owner runs from the TUI after a confirmation that shows them
exactly (UX-9: "Lancer après confirmation"):

  answer  a pending decision: ``brain decision answer ID CHOICE... --via tui --by <owner>`` (``--other``, ``--notes``);
  done    an action or a permission DDR, or a denied call: ``brain queue done ID``;
  apply   an action whose text holds the exact command the owner alone runs (in backquotes, or the whole text: ``brain
          ...`` or ``install.ps1 ...``; or install.ps1 named with its parameters, an apply first): that command,
          then ``brain queue done ID`` for a DDR. ``install.ps1 -Apply`` first runs its plan (install.ps1 without
          -Apply, its own dry run), whose output the confirmation shows before Run. The brain's own installer
          (config.json ``engine.installer``, whatever its name) runs the same way from the brain's root, and an
          engine install (``handover``) is run by a window once the cockpit has exited (brain.handover).

``run`` executes them in the project's root, as the owner would type them there, and logs each one as their action in
``<BRAIN_HOME>/ledger/cockpit-<month>.jsonl`` (its command, folder, exit code, duration and the end of its output,
secrets dropped). The actions are the owner's: ``refused()`` says why they do not run in a Claude Code session's shell
(``CLAUDECODE`` set), the TUI shows that reason, and ``run`` checks it again. A permission is granted through its PR
(``brain permissions grant``, wi-brain-tui-permissions), never written from here.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import cockpit, config, decisions, paths, plan, queue, resume, secretscan, status, transcript, update

LOG = "cockpit"  # <BRAIN_HOME>/ledger/cockpit-<month>.jsonl
OUTPUT_MAX = 4000  # the end of a command's output kept in the log
TIMEOUT_S = 900.0
# The personal brain (its install.ps1; the root of a denial outside every project): $BRAIN_PERSONAL or the installer's
# pointer, else the checkout that holds this package
HERE = paths.personal_root() or Path(__file__).resolve().parents[3]
GUI_EDITORS = ("code", "code-insiders", "codium", "cursor")
LINE_EDITORS = ("vi", "vim", "nvim", "nano", "micro", "emacs")
_TICKS_RE = re.compile(r"`([^`\n]+)`")
# install.ps1 named in a text without backquotes, with its parameters (install.ps1's param block: switches, and the
# four that take a value): "3. .\install.ps1 -Apply. 4. brain permissions" -> .\install.ps1 -Apply
_INSTALL_RE = re.compile(r"(?<![\w\\/.-])(?:\.[\\/])?install\.ps1(?:\s+(?:-(?:Ref|Claude|Python|Extras)\s+[^\s;,)]+"
                         r"|-(?:Apply|ExportMemory|SkipCommand)\b))*", re.I)
_RUNNABLE_RE = re.compile(r"^(?:brain|(?:\.[\\/])?install\.ps1)$", re.I)
_SECTION_RE = re.compile(r"^\d+(?:\.\d+)*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_PR_RE = re.compile(r"^\s*([\w.-]+)\s*#(\d+)\s*$")
_PR_URL_RE = re.compile(r"https://github\.com/[\w.-]+/[\w.-]+/pull/\d+")
_REPO_RE = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?$")
_OWNERS: dict[str, re.Match | None] = {}  # a project root -> its GitHub remote, read once


@dataclass
class Action:
    """One of a row's actions: its commands, as the owner would type them (``steps``, words), in ``cwd``."""
    kind: str  # answer, done, apply
    label: str
    project: str
    ref: str
    cwd: Path | None
    steps: list[list[str]] = field(default_factory=list)  # answer: built from the choice (answer_steps)
    plan: list[str] = field(default_factory=list)
    options: list[dict] = field(default_factory=list)
    multi: bool = False
    note: bool = False  # done: an optional note says what was done
    preview: list[str] | None = None  # apply: the plan run first, its output shown in the confirmation
    handover: bool = False  # an engine install: run by a window once the cockpit exits, then it relaunches (brain.handover)


# --- what a row is ---

def _project(cp, name: str):
    return (getattr(cp, "choices", None) or {}).get(name)


def _store(cp, p) -> resume.Store | None:
    """The project's graph, as the cockpit last read it, else read now; None without one."""
    if p is None:
        return None
    st = (getattr(cp, "stores", None) or {}).get(p.name)
    if st is None:
        try:
            st = status._store(p)
        except (OSError, ValueError):
            return None
    return st


def _flat(text) -> str:
    return " ".join(str(text or "").split())


def _detail(panel: str, ref: str, title: str) -> dict:
    return {"panel": panel, "id": ref, "title": _flat(title), "sections": [], "links": [], "actions": [],
            "refused": ""}


def _section(d: dict, heading: str, lines) -> None:
    lines = [str(x) for x in lines if x not in (None, "")]
    if lines:
        d["sections"].append((heading, lines))


def of(name: str, r: dict, cp=None, *, project=None, store=None) -> dict:
    """A row's detail (``r``: an item of ``cockpit.entries(name, panel)``). ``project`` and ``store`` default to the
    cockpit's (its ``choices`` and the graph it last read)."""
    p = project if project is not None else _project(cp, r.get("project", ""))
    st = store if store is not None else _store(cp, p)
    if name == "queue":
        d = _queue(r, p, st)
    elif name == "frontier":
        d = item(r["id"], p, st, row=r)
    elif name == "milestones":
        d = milestone(r["id"], p, st, row=r)
    elif name == "sessions":
        d = session(r)
    elif name == "alerts":
        d = alert(r)
    else:
        raise KeyError(name)
    d["refused"] = refused()
    return d


def find(panels: dict, ref: str) -> tuple[str, dict] | None:
    """The row ``ref`` names in the panels (an id, a session id or its start, an alert's key): (panel, row)."""
    for name in ("queue", "frontier", "milestones", "alerts", "sessions"):
        for r in cockpit.entries(name, panels.get(name)):
            if ref in (r.get("id"), r.get("key")) or (name == "sessions" and r["session_id"].startswith(ref)):
                return name, r
    return None


# --- the queue ---

def _ddr(p, ref: str) -> dict | None:
    if p is None:
        return None
    try:
        return decisions.find(p.root, ref)[1]
    except (decisions.QueueError, OSError, ValueError):
        return None


def _titled(st: resume.Store | None, ids) -> list[str]:
    out = []
    for nid in ids or []:
        n = (st.nodes.get(nid) if st else None) or {}
        tag = f" [{n['status']}]" if n.get("status") else ""
        out.append(f"{nid}{tag}: {_flat(n.get('title'))}" if n.get("title") else str(nid))
    return out


def _queue(e: dict, p, st) -> dict:
    d = _detail("queue", e["id"], e.get("title") or e["id"])
    tag = e["kind"] + (f":{e['category']}" if e.get("category") else "")
    age = f" ({e['age_days']} d)" if e.get("age_days") is not None else ""
    head = [f"{tag} in {e['project']}, since {e.get('since') or '-'}{age}"
            + (", blocking" if e.get("blocking") else "") + (f", due {e['due']}" if e.get("due") else "")]
    ddr = _ddr(p, e["id"]) if e.get("source") == "ddr" else None
    if ddr:
        asked = ddr.get("asked") or {}
        head.append(f"asked {str(asked.get('at') or '')[:16].replace('T', ' ')} by {asked.get('by') or '?'}"
                    f" via {asked.get('via') or '?'}")
        d["title"] = _flat(ddr.get("title")) or d["title"]
        _section(d, e["id"], head)
        _section(d, "Question" if decisions.kind_of(ddr) == "decision" else "What", [_flat(ddr.get("question"))])
        _section(d, "Context", [_flat(ddr.get("context"))])
        _section(d, "Blocks", [_flat(ddr.get("blocks"))])
        _section(d, "Command", [ddr.get("command", "") + (f" (in {ddr['cwd']})" if ddr.get("cwd") else "")])
        if decisions.kind_of(ddr) == "decision":
            rec = (ddr.get("recommendation") or {}).get("option")
            opts = [f"{i}. {o['label']}" + (" (recommended)" if o["label"] == rec else "")
                    + (f": {_flat(o['consequences'])}" if o.get("consequences") else "")
                    for i, o in enumerate(ddr.get("options") or [], 1)]
            opts.append("Other: free text" + ("; several choices possible" if ddr.get("multi_select") else ""))
            _section(d, "Options", opts)
            _section(d, "Why the recommendation", [_flat((ddr.get("recommendation") or {}).get("why"))])
        ans = ddr.get("answer") or {}
        if ans:
            _section(d, f"Answer ({ddr.get('status')})", [
                f"{decisions._answer_text(ddr)}, by {ans.get('by') or '?'} via {ans.get('via') or '?'} on "
                f"{str(ans.get('at') or '')[:10]}", f"notes: {_flat(ans['notes'])}" if ans.get("notes") else "",
                f"applied in {', '.join((ddr.get('applied') or {}).get('in') or [])}" if ddr.get("applied") else ""])
        links = ddr.get("links") or {}
        _section(d, "Linked", [f"items: {', '.join(links['items'])}" if links.get("items") else "",
                               f"specs: {', '.join(links['specs'])}" if links.get("specs") else "",
                               f"ADRs: {', '.join(links['adrs'])}" if links.get("adrs") else ""])
        f = p.root / "records" / "ddr" / f"{e['id']}.yaml"
        if f.is_file():
            d["links"].append({"label": f"the DDR {f.name}", "kind": "file", "path": str(f), "line": None})
        for s in links.get("specs") or []:
            d["links"] += _spec_links(s, p, st)
        for a in links.get("adrs") or []:
            d["links"] += _node_links(a, p, st, "ADR")
    else:
        _section(d, e["id"], head)
        src = e.get("source") or ""
        if src.startswith("prop:"):
            _section(d, f"The prop {src[5:]} of {e.get('item')}", [_flat(e.get("title"))])
            _section(d, "The item", _titled(st, [e.get("item")]))
        elif src == "denial":
            _section(d, "The call", [e.get("title"), e.get("detail"),
                                     f"{e.get('count', 1)} time(s), last {e.get('last') or '-'}",
                                     f"sessions: {', '.join(e.get('sessions') or []) or '-'}",
                                     f"folders: {', '.join(e.get('folders') or []) or '-'}"])
        else:
            _section(d, "Question", [e.get("title"), e.get("detail")])
    if e.get("band"):
        held = [f"{h['id']} {h.get('priority') or '-'}" + (f" · {h['milestone']} p50 {h.get('p50') or '?'} · "
                                                            f"+{h['slip']:g} d per day of waiting" if h.get("milestone")
                                                            else "") for h in e.get("held") or [] if h.get("priority")
                or h.get("milestone")]
        _section(d, f"Band: {queue.BAND_NAMES.get(e['band'], e['band'])} ({e.get('band_why')})",
                 [queue.explain(e), *held])
    _section(d, f"Unblocks ({e.get('unblocks', 0)})", _titled(st, e.get("unblocked")))
    d["links"] += [{"label": f"the item {nid}", "kind": "item", "id": nid, "project": e["project"]}
                   for nid in (e.get("unblocked") or [])[:12]]
    how = [e.get("how")]
    if e.get("source") == "denial" and e["kind"] == "permission":
        how.append(f"the narrow rules proposed: brain permissions grant {e['id']} (a PR, never a direct write)")
    _section(d, "How", how)
    d["actions"] = queue_actions(e, p, ddr)
    return d


def ddr(ref: str, p, st=None) -> dict | None:
    """Any DDR of the project by its id (or a part only it has), pending or not: the detail its queue entry would
    have, with its answer when there is one; None when the project has none."""
    found = _ddr(p, ref)
    if found is None:
        return None
    e = {"id": found["id"], "kind": decisions.kind_of(found), "source": "ddr", "project": p.name,
         "title": found.get("title") or "", "since": str((found.get("asked") or {}).get("at") or "")[:10],
         "blocking": bool(found.get("blocking")), "due": found.get("due"), "unblocks": 0, "unblocked": []}
    d = _queue(e, p, st)
    d["refused"] = refused()
    return d


def commands(*texts) -> list[list[str]]:
    """The commands the owner alone runs that ``texts`` name, as words (quotes taken off): each backquoted span, or a
    text that is all a command, whose first word is ``brain`` or ``install.ps1``; else each install.ps1 named with
    its parameters. An apply (``install.ps1 -Apply``, ``--write``) comes first."""
    out: list[list[str]] = []
    for text in texts:
        text = str(text or "").strip()
        if not text:
            continue
        spans = _TICKS_RE.findall(text) or [text.split(";")[0].splitlines()[0]]
        if not any(split(s)[:1] and _RUNNABLE_RE.match(split(s)[0]) for s in spans):
            spans = [m.group(0) for m in _INSTALL_RE.finditer(text)]
        for span in spans:
            words = split(span)
            if words and _RUNNABLE_RE.match(words[0]) and words not in out:
                out.append(words)
    return sorted(out, key=lambda w: not any(x.lower() in ("-apply", "--write") for x in w))


def preview(words: list[str]) -> list[str] | None:
    """The plan of an apply, run before its confirmation: install.ps1 without -Apply (its own dry run); None for
    any other command (the confirmation shows the command itself)."""
    if re.split(r"[\\/]", words[0])[-1].lower() == "install.ps1" and any(w.lower() == "-apply" for w in words):
        return [w for w in words if w.lower() != "-apply"]
    return None


def split(text: str) -> list[str]:
    """A command's words, quoted ones kept whole ("a b" or 'a b'); backslashes kept (Windows paths)."""
    return [w[1:-1] if len(w) > 1 and w[0] == w[-1] and w[0] in "\"'" else w
            for w in re.findall(r"\"[^\"]*\"|'[^']*'|\S+", text)]


def shown(words: list[str]) -> str:
    """A command as the owner would type it: a word with a space or a quote quoted."""
    return " ".join(f'"{w}"' if not w or re.search(r"[\s\"'`;&|<>]", w) else w for w in words)


def _brain(root, *words: str) -> list[str]:
    return ["brain", "--root", str(root), *words]


def queue_actions(e: dict, p, ddr: dict | None = None, via: str = "brain tui") -> list[Action]:
    """A queue entry's actions: answer a decision, mark an action or a permission done, apply an action's command
    (its ``command`` field, else the one its text names; ``via`` goes in the done note)."""
    root = p.root if p is not None else None
    if root is None and not str(e["id"]).startswith("perm-"):
        return []
    root_or_here = root if root is not None else HERE
    out: list[Action] = []
    kind = e["kind"]
    if ddr is not None and ddr.get("status") != "pending":
        return out  # answered already: the model in charge applies it
    if ddr is not None and decisions.kind_of(ddr) == "decision":
        out.append(Action("answer", "Answer", e["project"], e["id"], root, options=list(ddr.get("options") or []),
                          multi=bool(ddr.get("multi_select")),
                          plan=[f"records {config.name_of()}'s answer in "
                                f"{root / 'records' / 'ddr' / (e['id'] + '.yaml')}",
                                "the model in charge applies it, then brain decision ack"]))
        return out
    if ddr is not None or str(e["id"]).startswith("perm-"):
        out.append(Action("done", "Done", e["project"], e["id"], root_or_here,
                          steps=[_brain(root_or_here, "queue", "done", e["id"])], note=True,
                          plan=["a DDR: answered (done), the model in charge checks the effect and acks it" if ddr
                                else "a denied call: stamped in the ledger until it is denied again"]))
    if kind == "action" and root is not None:
        texts = ((ddr.get("question"), ddr.get("context"), ddr.get("blocks")) if ddr else (e.get("title"),))
        given = [split(ddr["command"])] if ddr and ddr.get("command") else []  # its exact command first
        where = root / ddr["cwd"] if ddr and ddr.get("cwd") else root  # an absolute cwd replaces the root
        for words in (given or commands(*texts))[:1]:
            steps = [words]
            if ddr is not None:
                steps.append(_brain(root, "queue", "done", e["id"], "--note", f"applied in {via}: {shown(words)}"))
            plan_of = preview(words)  # an install.ps1 -Apply: its plan first, then run by a window (INST-2)
            out.append(Action("apply", "Apply", e["project"], e["id"], where, steps=steps, preview=plan_of,
                              handover=plan_of is not None,
                              plan=[f"runs {shown(words)} in {where}, as {config.name_of()}",
                                    "then marks the entry done" if ddr is not None else
                                    "then the model clears the item's prop by a PR",
                                    *(["in a new window once the cockpit has closed (an install cannot replace the "
                                       "files the cockpit holds), which then relaunches brain tui"]
                                      if plan_of is not None else [])]))
    return out


def answer_steps(a: Action, choices: list[str], other: str = "", notes: str = "") -> list[list[str]]:
    """The command an answer runs: the options by label (by number when a label starts with -), the free text and
    the notes; ValueError without a choice or a free text, or with several choices for a single-choice question."""
    labels = [o["label"] for o in a.options]
    picked = [c for c in choices if c in labels]
    if not picked and not other.strip():
        raise ValueError("pick an option, or write the other answer")
    if len(picked) > 1 and not a.multi:
        raise ValueError(f"{a.ref} takes one choice")
    words = _brain(a.cwd, "decision", "answer", a.ref,
                   *(str(labels.index(c) + 1) if c.startswith("-") else c for c in picked))
    if other.strip():
        words += ["--other", _flat(other)]
    if notes.strip():
        words += ["--notes", _flat(notes)]
    return [words + ["--via", "tui", "--by", config.owner_of()]]


def done_steps(a: Action, note: str = "") -> list[list[str]]:
    return [s + (["--note", _flat(note)] if note.strip() and a.kind == "done" else []) for s in a.steps]


# --- items, milestones, sessions, alerts ---

def _anchor(anchor: str) -> tuple[str, str]:
    path, _, frag = str(anchor or "").partition("#")
    return path, frag


def _slugs(text: str) -> tuple[str, str]:
    """A heading's anchors: GitHub's (words kept, accents too, punctuation dropped) and the engine's ASCII one."""
    low = text.strip().lower()
    return re.sub(r"[^\w\- ]", "", low).replace(" ", "-"), re.sub(r"[^a-z0-9]+", "-", low).strip("-")


def anchor_line(path: Path, frag: str) -> int | None:
    """The line of the heading an anchor names: a section number (3.6), a heading's slug (or its start), ``top``."""
    if not frag or frag == "top":
        return 1
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    heads = [(i, m.group(2)) for i, line in enumerate(lines, 1) for m in [_HEADING_RE.match(line)] if m]
    if _SECTION_RE.match(frag):
        return next((i for i, text in heads if re.match(rf"^§?{re.escape(frag)}(?:[.\s]|$)", text)), None)
    want = frag.lower()
    for i, text in heads:
        if want in _slugs(text):
            return i
    return next((i for i, text in heads if len(want) >= 12 and any(s.startswith(want) for s in _slugs(text))), None)


def _file_of(rel: str, p, repo: str = "") -> Path | None:
    """A path of the project's repos: under its root, else under a sibling folder named after the repo."""
    if p is None or not rel:
        return None
    for base in (p.root, p.root.parent / repo if repo else None):
        if base is not None and (base / rel).exists():
            return base / rel
    return None


def _node_links(nid: str, p, st, what: str) -> list[dict]:
    """A node's anchor as its file at its heading; a Doc's section number (``doc:repo:path::4.6``) first, since
    GitHub's anchor drops its dots."""
    n = (st.nodes.get(nid) if st else None) or {}
    rel, frag = _anchor(n.get("anchor") or "")
    f = _file_of(rel, p)
    if f is None:
        return []
    section = nid.rpartition("::")[2] if "::" in nid else ""
    line = anchor_line(f, section) if _SECTION_RE.match(section) else None
    label = (f"{what} {rel}" + (f" §{section}" if section else "")) if n.get("type") == "Doc" else f"{what} {nid}"
    return [{"label": label, "kind": "file", "path": str(f), "line": line or anchor_line(f, frag)}]


def _spec_links(ref: str, p, st) -> list[dict]:
    """A spec reference (``spec-x``, ``spec-x 4.14``, a Doc node id) as its file at its section."""
    nid, _, section = str(ref).partition(" ")
    n = (st.nodes.get(nid) if st else None) or {}
    rel, frag = _anchor(n.get("anchor") or "")
    f = _file_of(rel, p)
    if f is None:
        return []
    frag = section.strip().lstrip("§") or frag
    return [{"label": f"spec {nid}" + (f" §{frag}" if frag and frag != "top" else ""), "kind": "file",
             "path": str(f), "line": anchor_line(f, frag)}]


def _edges(st, nid: str, kind: str, out: bool = True) -> list[str]:
    if st is None:
        return []
    return sorted({str(e["to"] if out else e["from"]) for e in st.edges
                   if e.get("type") == kind and str(e["from"] if out else e["to"]) == nid})


def pr_url(pr: str, p) -> str:
    """A ``pr`` prop as a URL: a URL as is; ``brain #85``: that repo of the project root's GitHub owner."""
    text = str(pr or "").strip()
    m = _PR_URL_RE.search(text)
    if m:
        return m.group(0)
    m = _PR_RE.match(text.split(",")[0].split(";")[0])
    if not m or p is None:
        return ""
    if str(p.root) not in _OWNERS:
        try:
            remote = subprocess.run(["git", "-C", str(p.root), "remote", "get-url", "origin"], capture_output=True,
                                    text=True, timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            remote = ""
        _OWNERS[str(p.root)] = _REPO_RE.search(remote)
    owner = _OWNERS[str(p.root)]
    return f"https://github.com/{owner.group(1)}/{m.group(1)}/pull/{m.group(2)}" if owner else ""


def item(nid: str, p, st, row: dict | None = None) -> dict:
    """An item's detail: its props, spec sections, ADRs, PR, code and tests, what it waits on, what waits on it."""
    n = (st.nodes.get(nid) if st else None) or {}
    d = _detail("frontier", nid, n.get("title") or (row or {}).get("title") or nid)
    props = dict(n.get("props") or {})
    ms = [m for m in _edges(st, nid, "part_of") if (st.nodes.get(m) or {}).get("type") == "Milestone"]
    head = [f"{n.get('type') or 'item'} {n.get('status') or '?'}, priority "
            f"{props.get('priority') or (props.get('priority_proposed', '-') + '?')}"
            + (f", milestone {', '.join(ms)}" if ms else
               f", milestone {props['milestone_proposed']}?" if props.get("milestone_proposed") else "")]
    if row and row.get("unblocks") is not None:
        head.append(f"unblocks {row['unblocks']}" + (f", idea {row['since']}" if row.get("since") else ""))
    _section(d, nid, head)
    _section(d, "Props", [f"{k}: {_flat(v)}" for k, v in props.items()])
    specs = _edges(st, nid, "specified_by")
    documented = _edges(st, nid, "documented_in")
    docs = [x for x in documented if "docs/specs/" in x]
    _section(d, "Spec", _titled(st, specs) + [f"{x.split(':', 2)[-1].replace('::', ' §')}" for x in docs])
    others = [x for x in documented if x not in docs]
    _section(d, "Docs", [f"{x.split(':', 2)[-1].replace('::', ' §')}" for x in others])
    adrs = _edges(st, nid, "decided_by")
    _section(d, "ADRs (decided_by)", _titled(st, adrs))
    pr = props.get("pr")
    _section(d, "PR", [_flat(pr)])
    code = _edges(st, nid, "implemented_by")
    tests = _edges(st, nid, "tested_by")
    _section(d, "Code and tests", [*code, *tests])
    _section(d, "Waits on (depends_on, gated_by)", _titled(st, _edges(st, nid, "depends_on")
                                                       + _edges(st, nid, "gated_by")))
    down = sorted(cockpit.downstream(st).get(nid, ())) if st else []
    _section(d, "Waiting on it", _titled(st, [x for x in down if x not in ms]))
    for s in specs:
        d["links"] += _spec_links(s, p, st)
    for x in docs + others:
        d["links"] += _node_links(x, p, st, "section")
    for a in adrs:
        d["links"] += _node_links(a, p, st, "ADR")
    url = pr_url(pr, p) if pr else ""
    if url:
        d["links"].append({"label": f"PR {_flat(pr)}", "kind": "url", "url": url})
    for c in code:
        parts = c.split(":", 2)
        f = _file_of(parts[2], p, parts[1]) if len(parts) == 3 else None
        if f is not None:
            d["links"].append({"label": f"code {parts[2]}", "kind": "file", "path": str(f), "line": None})
    return d


def milestone(mid: str, p, st, row: dict | None = None) -> dict:
    n = (st.nodes.get(mid) if st else None) or {}
    d = _detail("milestones", mid, n.get("title") or (row or {}).get("title") or mid)
    if row:
        _section(d, mid, [f"{row.get('done', 0)} of {row.get('items', 0)} item(s) done, "
                          f"{cockpit.bar(row.get('done', 0), row.get('items', 0))}"])
    _section(d, "Trigger", [_flat((n.get("props") or {}).get("trigger"))])
    items = st.milestone_items(mid) if st else []
    by: dict[str, list[str]] = {}
    for i in items:
        by.setdefault(st.status(i) or "?", []).append(i)
    for s in ("doing", "blocked", "todo", "done", "dropped"):
        if by.get(s):
            _section(d, f"{s} ({len(by[s])})", _titled(st, by.pop(s)))
    for s, ids in by.items():
        _section(d, f"{s} ({len(ids)})", _titled(st, ids))
    d["links"] += [{"label": f"the item {i}", "kind": "item", "id": i, "project": (row or {}).get("project", "")}
                   for i in items if st.status(i) in resume.WORK_OPEN][:12]
    return d


def _transcript(sid: str) -> Path | None:
    root = paths.projects_dir()
    return next(iter(sorted(root.glob(f"*/{sid}.jsonl"))), None) if root.is_dir() else None


def session(r: dict) -> dict:
    d = _detail("sessions", r["session_id"], r.get("title") or r.get("branch") or r["session_id"])
    _section(d, r["session_id"], [f"{r['state']}, {r['project']}, last write {cockpit.ago(r.get('age_s', 0))} ago"
                                  f" ({r.get('last_write') or '-'})"])
    cost = f", ${r['cost_usd']:.2f} at API prices" if isinstance(r.get("cost_usd"), (int, float)) else ""
    _section(d, "Where", [f"folder: {r.get('folder') or '-'}", f"branch: {r.get('branch') or '-'}"])
    _section(d, "Model", [f"{cockpit.model_text(r)}, effort {r.get('effort') or '-'}; context "
                          f"{cockpit.context_text(r)}, output {cockpit.tokens(r.get('output_tokens'))}{cost}"])
    hook = plan.read(r["session_id"])
    f = _transcript(r["session_id"])
    steps = hook["steps"] if hook else (plan.Replay().steps(f) if f else [])
    mark = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}
    _section(d, f"Plan ({plan.label(steps) or 'none'}; from {'the hook' if hook else 'the transcript'})",
             [f"{mark.get(s['status'], '[ ]')} {i}. {s['content']}" for i, s in enumerate(steps, 1)])
    _section(d, "Transcript", [str(f) if f else "not on this machine"])
    if r.get("folder") and Path(r["folder"]).is_dir():
        d["links"].append({"label": "the session's folder", "kind": "file", "path": r["folder"], "line": None})
    if f:
        d["links"].append({"label": "the transcript", "kind": "file", "path": str(f), "line": None})
    return d


def alert(r: dict) -> dict:
    d = _detail("alerts", r.get("key", ""), r.get("message") or r.get("key", ""))
    _section(d, r.get("key", ""), [f"{r.get('level', '?')} in {r.get('project', '?')}, since "
                                   f"{str(r.get('since') or '-')[:16].replace('T', ' ')}"])
    _section(d, "Source", [f"{r.get('source') or '-'}" + (f", subject {r['subject']}" if r.get("subject") else "")])
    _section(d, "Message", [_flat(r.get("message"))])
    _section(d, "How", [f"brain alerts --project {r.get('project')}: every open alert and its history"])
    return d


# --- the text ---

def lookup(cp, ref: str) -> dict | None:
    """``brain tui --detail ID``: the row of the panels ``ref`` names, else a DDR or a graph node of a project in
    scope (an item or a milestone off the frontier, an answered DDR); None when nothing has that id."""
    found = find(cp.snapshot()["panels"], ref)
    if found is not None:
        return of(*found, cp)
    for p in cp.found:
        st = _store(cp, p)
        got = ddr(ref, p, st)
        if got is not None:
            return got
        n = (st.nodes.get(ref) if st else None) or {}
        if n.get("type") == "Milestone":
            return milestone(ref, p, st)
        if n:
            return item(ref, p, st)
    return None


def as_json(d: dict) -> str:
    return json.dumps({**d, "actions": [{**a.__dict__, "cwd": str(a.cwd or "")} for a in d["actions"]]},
                      ensure_ascii=False, indent=1, default=str)


def lines(d: dict, width: int = cockpit.WIDTH) -> list[str]:
    """A detail as text (``brain tui --detail ID``), each line wrapped at ``width`` (0: not wrapped)."""
    out = [f"{d['title']}"]
    for heading, body in d["sections"]:
        out += ["", heading]
        for x in body:
            out += (textwrap.wrap(x, width, initial_indent="  ", subsequent_indent="    ") or ["  "]) if width else [
                f"  {x}"]
    if d["links"]:
        out += ["", "Open (o in the TUI)"]
        out += ["  " + link_text(x) for x in d["links"]]
    if d["actions"]:
        out += ["", "Actions (in the TUI, after a confirmation)" + (f": refused here, {d['refused']}"
                                                                     if d.get("refused") else "")]
        for a in d["actions"]:
            cmd = ("; then ".join(shown(s) for s in a.steps) if a.steps else
                   shown(_brain(a.cwd, "decision", "answer", a.ref, "<option>...", "--via", "tui", "--by",
                                config.owner_of())))
            out.append(f"  {a.label}: {cmd}" + (f" (its plan first: {shown(a.preview)})" if a.preview else ""))
    return out


def link_text(x: dict) -> str:
    if x["kind"] == "url":
        return f"{x['label']}: {x['url']}"
    if x["kind"] == "item":
        return f"{x['label']} (its detail)"
    return f"{x['label']}: {x['path']}" + (f":{x['line']}" if x.get("line") else "")


# --- opening and running ---

def opener(x: dict, env: dict | None = None) -> tuple[list[str] | None, bool]:
    """The command that opens a file link, and whether it runs in the terminal (the TUI suspends while it does):
    $EDITOR (VS Code's ``-g path:line``, vi's or nano's ``+line``), else ``code -g``, else None (the system's
    opener)."""
    env = os.environ if env is None else env
    where = x["path"] + (f":{x['line']}" if x.get("line") else "")
    editor = split(env.get("EDITOR") or "")
    if editor:
        name = Path(editor[0]).stem.lower()
        if name in GUI_EDITORS:
            return editor + ["-g", where], False
        return editor + ([f"+{x['line']}"] if x.get("line") and name in LINE_EDITORS else []) + [x["path"]], True
    code = shutil.which("code")
    return ([code, "-g", where] if code else None), False


def open_link(x: dict) -> str:
    """Open a link on the desktop: a file in the editor, a URL in the browser. What was opened, or why not."""
    if x["kind"] == "url":
        webbrowser.open(x["url"])
        return f"opened {x['url']}"
    if x["kind"] != "file":
        return ""
    cmd, terminal = opener(x)
    try:
        if cmd and terminal:
            subprocess.run(cmd)  # in the terminal: the TUI suspends around it
        elif cmd:
            subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif hasattr(os, "startfile"):
            os.startfile(x["path"])  # noqa: S606 - the system's opener for a file the cockpit names
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", x["path"]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return f"could not open {x['path']}: {exc}"
    return f"opened {x['path']}" + (f" at line {x['line']}" if x.get("line") else "")


def refused(env: dict | None = None) -> str:
    """Why the actions do not run here ('' when they do): a Claude Code session's shell sets CLAUDECODE."""
    env = os.environ if env is None else env
    return (f"the actions are {config.name_of()}'s: not from a Claude Code session's shell (CLAUDECODE is set)"
            if env.get("CLAUDECODE") else "")


def script_argv(script: Path, args: list[str]) -> list[str]:
    """The process that runs a script: PowerShell for a .ps1, sh for a .sh, else the file itself."""
    if script.suffix.lower() == ".ps1":
        shell = "powershell" if os.name == "nt" else "pwsh"
        return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    return ["sh", str(script), *args] if script.suffix.lower() == ".sh" else [str(script), *args]


def argv(words: list[str], cwd: Path | None) -> list[str]:
    """The process a command's words start: brain with this interpreter (the TUI's own brain), the brain's declared
    installer (config.json engine.installer, from the brain's root ``cwd``), install.ps1 with PowerShell from the
    project's root (else this repo's)."""
    head = words[0]
    if head == "brain":
        return [sys.executable, "-m", "brain", *words[1:]]
    declared = update.installer(cwd) if cwd else None
    if declared and (cwd / head).resolve() == declared.resolve():
        return script_argv(declared, words[1:])
    if _RUNNABLE_RE.match(head):
        script = next((f for f in ((cwd / "install.ps1") if cwd else None, HERE / "install.ps1")
                       if f is not None and f.is_file()), None)
        if script is None:
            raise ValueError("install.ps1 not found in the project's root nor in the personal brain")
        return script_argv(script, words[1:])
    raise ValueError(f"{head}: the cockpit runs brain, install.ps1 and the brain's declared installer only")


def log(row: dict) -> Path:
    d = paths.ledger_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{LOG}-{row['at'][:7]}.jsonl"
    with open(f, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return f


def run(a: Action, steps: list[list[str]], runner=None, env: dict | None = None) -> list[dict]:
    """Run an action's steps in order (the next one only when the last exited 0), each logged as the owner's action;
    each step's {command, exit, seconds, output}. Refused in a Claude Code session's shell (``env``: os.environ)."""
    why = refused(env)
    if why:
        raise PermissionError(why)
    runner = runner or subprocess.run
    pkg = str(Path(__file__).resolve().parents[1])  # the child imports this brain, installed or not
    child = {**os.environ, "PYTHONIOENCODING": "utf-8",
             "PYTHONPATH": os.pathsep.join(x for x in (pkg, os.environ.get("PYTHONPATH")) if x)}
    out = []
    for words in steps:
        start, t0 = transcript.iso(datetime.now(timezone.utc)), time.monotonic()
        try:
            proc = runner(argv(words, a.cwd), cwd=str(a.cwd) if a.cwd else None, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL, timeout=TIMEOUT_S, env=child)
            code, text = proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            code, text = None, f"{type(exc).__name__}: {exc}"
        text, _ = secretscan.clean_text(text)
        res = {"command": shown(words), "exit": code, "seconds": round(time.monotonic() - t0, 2), "output": text}
        log({"at": start, "event": "tui-action", "action": a.kind, "by": config.owner_of(), "via": "tui",
             "project": a.project,
             "id": a.ref, "command": res["command"], "cwd": str(a.cwd or ""), "exit": code,
             "seconds": res["seconds"], "output": text[-OUTPUT_MAX:]})
        out.append(res)
        if code != 0:
            break
    return out


def summary(results: list[dict]) -> str:
    """One line per step: its exit and the end of its output."""
    return "\n".join(f"{'ok' if r['exit'] == 0 else 'failed (exit ' + str(r['exit']) + ')'}: {r['command']}"
                     + (f"\n{_tail(r['output'])}" if r["output"] else "") for r in results)


def _tail(text: str, n: int = 6) -> str:
    return "\n".join(text.splitlines()[-n:])

