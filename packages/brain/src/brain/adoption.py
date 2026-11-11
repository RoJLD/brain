"""Command adoption (wi-brain-command-adoption): ``brain perf --usage``, at zero token. It crosses the CLI registry
with the engine's exec ledger and a mini scan of the sessions' transcripts, so a command no one runs, or work a
session did by hand that a command answers, shows up; each gap comes with what to propose, of three kinds: hint (the
read hint), procedure (a line in a procedure), wire (a hook, a schedule or a procedure, documented, or retired). It
refuses nothing, and reruns after each wave.

- **The registry**: every command of ``brain --help`` and, for a family (``brain item show``), each subcommand, as
  the exec ledger names its runs (brain.selftime.command_task); an alias counts as its command, and a family run
  through its alias, which the ledger names without its subcommand (``brain doctor``), counts for each subcommand.
- **The exec ledger** (brain.selftime's, ``<BRAIN_HOME>/ledger/engine/``): runs per command and subcommand over the
  period (28 days by default), the ones that never ran.
- **The transcripts** (Claude Code's, this machine's, main and subagents, those written in the period): the brain
  commands a session ran itself in a shell (Bash, PowerShell; brain's options before the command skipped), so a
  command's runs split into **by a session** and **otherwise** (a hook, a scheduled task, a script: the ledger's runs
  less the sessions'); the Read, Grep and shell reads of a registered brain's graph YAML, decision logs, journals and
  generated views (brain.readhint's kinds), which a read command answers; the hand edits (Edit, Write, MultiEdit) of
  the files a command writes (the graph's YAML, a decision log, a journal) or regenerates (the views).
- **The features** (the brain's store, when it has one): a feature marked have whose commands (the command modules
  its implemented_by names) never ran in the period: shipped but unused, or unwired.
- **Sub-sessions and briefs**: the sub-sessions started in the period (the token ledger, brain usage) against the
  runs of ``brain brief``, and the waves composed against ``brain collisions`` and ``brain wave plan``.

Why ``brain perf --usage`` and not an audit lens: perf already reads the exec ledger and its period (``--since``);
brain audit reads a repo's code, not what ran on a machine. The report is one flag on an existing command.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import paths, perf, readhint

SHELLS = ("Bash", "PowerShell")
EDITORS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
WRITES = {   # a kind of brain file (brain.readhint.KINDS) -> the command that writes or regenerates it
    "graph": "brain item add|set|link, brain features add|link|set",
    "adr": "brain adr new",
    "journal": "brain journal add",
    "board": "brain sync (regenerated: never edited by hand)",
    "plan": "brain sync (regenerated: never edited by hand)",
    "queue": "brain sync (regenerated: never edited by hand)",
    "features": "brain features render --write (regenerated: never edited by hand)",
}
ANSWERS = {   # a kind -> the read command that answers a hand read of it
    "graph": "brain item show <id>, brain items --text WORDS",
    "adr": "brain adr show <id|title>",
    "journal": "brain journal last [N]",
    "board": "brain items (filters)",
    "plan": "brain next, brain items --wave X.Y.Z",
    "queue": "brain decision pending",
    "features": "brain features list|search|show",
}
SEGMENT = re.compile(r"[;&|\n]+|\$\(|`")
BRAIN = re.compile(r"(^|[\\/])brain(\.exe)?$", re.I)
OPTIONS = ("--root", "--project", "--store")   # brain's options that take a value, before the command
QUOTED = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")
PREFIXES = {"&", "sudo", "time", "exec", "nohup", "call", "do", "then", "else", "{", "("}


def units(parser: argparse.ArgumentParser) -> tuple[dict[str, str], dict[str, str]]:
    """({unit: its command module}, {alias unit: its unit}): every command of the parser and, for a family whose
    subcommands the exec ledger names (``<cmd>_cmd``, record's kind), each subcommand."""
    from .commands import _registry as registry
    top = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    out: dict[str, str] = {}
    alias: dict[str, str] = {}
    first: dict[int, str] = {}
    for name, sp in top.choices.items():
        canon = first.setdefault(id(sp), name)
        try:
            module = registry.owner(name).__name__.rsplit(".", 1)[-1]
        except KeyError:
            module = ""
        subs = next((a for a in sp._actions if isinstance(a, argparse._SubParsersAction)
                     and a.dest in (f"{name}_cmd", f"{canon}_cmd", "record_kind")), None)
        names = [] if subs is None else list(subs.choices.items())
        seen: dict[int, str] = {}
        for sub, ssp in names:
            s = seen.setdefault(id(ssp), sub)
            unit, mine = f"brain {canon} {s}", f"brain {name} {sub}"
            out.setdefault(unit, module)
            if mine != unit:
                alias[mine] = unit
        if name != canon:   # the ledger names a family run through its alias without its subcommand (brain doctor)
            alias[f"brain {name}"] = f"brain {canon}"
        if not names:
            out.setdefault(f"brain {canon}", module)
    return out, alias


def ran_count(unit: str, counts: Counter) -> int:
    """The runs of ``unit``, else of its family when the ledger names it without the subcommand (a family run through
    its alias: brain doctor list is recorded as brain doctor, counted as brain profile)."""
    words = unit.split()
    return int(counts.get(unit, 0)) or (int(counts.get(" ".join(words[:2]), 0)) if len(words) > 2 else 0)


def _command(words: list[str]) -> tuple[str, list[str]] | None:
    """(brain's command word, the words after it): brain's options before it skipped, those that take a value
    (--root, --project, --store, or an abbreviation argparse accepts) with their value."""
    i = 0
    while i < len(words):
        w = words[i]
        if w.startswith("--") and "=" not in w and len(w) > 2 and any(o.startswith(w) for o in OPTIONS):
            i += 2
        elif w.startswith("-"):
            i += 1
        else:
            return w, words[i + 1:]
    return None


def typed(command: str, known: dict[str, str], alias: dict[str, str]) -> list[str]:
    """The registry's units a shell command line runs (``brain [options] <command> [<subcommand>]``, the program
    ``brain`` or ``brain.exe`` by any path, or ``python -m brain``) at the start of a part of the line, after an
    assignment or a prefix (``&``, ``sudo``); a quoted text is one word (a commit message that names a command runs
    none), and from the first heredoc on the line is left out."""
    if not isinstance(command, str):
        return []
    text = QUOTED.sub(lambda m: re.sub(r"[;&|`\n]|\$\(", " ", m.group(0)), command.split("<<", 1)[0])
    out = []
    for seg in SEGMENT.split(text):
        words = seg.split()
        while words and (words[0].lower() in PREFIXES or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])):
            words.pop(0)
        if len(words) > 2 and words[0].lower() in ("python", "python3", "py") and words[1:3] == ["-m", "brain"]:
            words = words[2:]
        if not words or not BRAIN.search(words[0].strip("'\"")):
            continue
        parts = _command([w.strip("'\"") for w in words[1:]])
        if parts is None:
            continue
        cmd, after = parts
        sub = next((w for w in after[:1] if not w.startswith("-")), "")
        for unit in (f"brain {cmd} {sub}", f"brain {cmd}"):
            unit = alias.get(unit, unit)
            if unit in known:
                out.append(unit)
                break
    return out


@functools.lru_cache(maxsize=4096)
def _owned(folder: str) -> bool:
    """A file in ``folder`` is under a registered brain's root or a worktree of its checkout (brain.readhint)."""
    try:
        return readhint.owner(Path(folder) / "x") is not None
    except Exception:  # noqa: BLE001 - a folder that cannot be read is not a brain's
        return False


def _brain_kind(raw: str, cwd: str) -> str:
    """The brain file kind of a path a call names, '' when it is none of a registered brain's."""
    kind = readhint.kind_of(raw)
    if not kind:
        return ""
    p = Path(raw.replace("\\", "/").split("*", 1)[0].rstrip("/") or ".")
    if not p.is_absolute():
        p = Path(cwd or ".") / p
    return kind if _owned(os.path.normpath(str(p.parent))) else ""


def transcripts(since: datetime) -> list[Path]:
    """This machine's main transcripts and their subagents' written since ``since``."""
    root = paths.projects_dir()
    out = []
    for t in sorted(root.glob("*/*.jsonl")) if root.is_dir() else []:
        out += [f for f in [t, *sorted(t.with_suffix("").glob("subagents/**/agent-*.jsonl"))] if _mtime(f) >= since]
    return out


def _mtime(f: Path) -> datetime:
    try:
        return datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)
    except OSError:
        return datetime.min.replace(tzinfo=timezone.utc)


def scan(files: list[Path], since: datetime, until: datetime, known: dict[str, str], alias: dict[str, str]) -> dict:
    """{typed: {unit: runs}, reads: {kind: n}, edits: {kind: n}, sessions: n} from the transcripts' tool calls in
    [since, until)."""
    counts = {"typed": Counter(), "reads": Counter(), "edits": Counter()}
    sessions = set()
    for f in files:
        for rec, tool, inp in _tool_calls(f, since, until):
            sessions.add(str(rec.get("sessionId") or f))
            _count(counts, tool, inp, str(rec.get("cwd") or ""), known, alias)
    return {**{k: dict(v) for k, v in counts.items()}, "sessions": len(sessions)}


def _tool_calls(f: Path, since: datetime, until: datetime):
    """(record, tool, input) for each tool call an assistant message of ``f`` made in [since, until), the file read a
    line at a time (a line with no tool call is not parsed); a record whose time cannot be read is skipped."""
    for rec in _records(f):
        content = (rec.get("message") if isinstance(rec.get("message"), dict) else {}).get("content")
        if rec.get("type") != "assistant" or not isinstance(content, list):
            continue
        try:
            at = datetime.fromisoformat(str(rec.get("timestamp")).replace("Z", "+00:00"))
            at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
            if not since <= at < until:
                continue
        except (TypeError, ValueError):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                inp = block.get("input")
                yield rec, str(block.get("name") or ""), inp if isinstance(inp, dict) else {}


def _records(f: Path):
    try:
        with open(f, "rb") as fh:
            for raw in fh:
                if b'"tool_use"' not in raw:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except OSError:
        return


def _count(counts: dict[str, Counter], tool: str, inp: dict, cwd: str, known: dict[str, str],
           alias: dict[str, str]) -> None:
    """One tool call counted: the brain commands a shell call runs, a hand edit or a hand read of a brain's file."""
    if tool in SHELLS:
        counts["typed"].update(typed(str(inp.get("command") or ""), known, alias))
    if tool in EDITORS:
        kind = _brain_kind(str(inp.get("file_path") or inp.get("notebook_path") or ""), cwd)
        counts["edits"].update([kind] if kind else [])
    elif tool in ("Read", "Grep", *SHELLS):
        kind = next((k for k in (_brain_kind(p, cwd) for p in readhint._targets(tool, inp)[0]) if k), "")
        counts["reads"].update([kind] if kind else [])


def runs(since: datetime, until: datetime, alias: dict[str, str]) -> Counter:
    """The exec ledger's runs per task in [since, until), an alias counted as its command."""
    got, _ = perf.load(None, since, until, engine=True)
    return Counter(alias.get(r.task, r.task) for r in got)


def unused_features(store: Path | None, known: dict[str, str], ran: Counter) -> list[dict]:
    """The features marked have whose command modules (implemented_by commands/<module>.py) all never ran."""
    if store is None:
        return []
    from . import features
    try:
        m = features.load_store(store)
    except Exception:  # noqa: BLE001 - a brain without features has none to cross
        return []
    by_module: dict[str, list[str]] = {}
    for unit, module in known.items():
        by_module.setdefault(module, []).append(unit)
    out = []
    for fid, node in sorted(m.features.items()):
        if node.get("status") != "have" and (node.get("props") or {}).get("status") != "have":
            continue
        mods = {re.sub(r"\.py(::.*)?$", "", ref.rsplit("/commands/", 1)[1]) for ref in m.code(fid)
                if "/commands/" in ref}
        cmds = sorted(u for mod in mods for u in by_module.get(mod, []))
        if cmds and not any(ran_count(u, ran) for u in cmds):
            out.append({"feature": fid, "commands": cmds})
    return out


def _subsessions(since: datetime, until: datetime) -> int | None:
    """The sub-sessions started in the period, from the token ledger (None when it cannot be read)."""
    try:
        from . import usage
        rows = usage.load()
    except Exception:  # noqa: BLE001 - no token ledger on this machine: the line is left out
        return None
    rows = rows.values() if isinstance(rows, dict) else rows
    a, b = since.strftime("%Y-%m-%d"), until.strftime("%Y-%m-%d")
    return sum(1 for r in rows if isinstance(r, dict) and ((r.get("brief") or {}).get("side"))
               and usage.in_window(r, a, b + "~"))


def report(known: dict[str, str], ran: Counter, sessions: dict, since: datetime, until: datetime,
           feats: list[dict] | None = None, subsessions: int | None = None, hints_on: bool = False) -> dict:
    """The adoption report: per unit its runs, those a session typed and the others; the never run; the hand reads
    and edits; the unused features; each gap's proposal."""
    by_session = sessions.get("typed") or {}
    rows = []
    for unit in sorted(known):
        n, t = int(ran.get(unit, 0)), int(by_session.get(unit, 0))
        rows.append({"command": unit, "module": known[unit], "runs": n, "by_session": min(t, n) if n else t,
                     "otherwise": max(n - t, 0)})
    rows.sort(key=lambda r: (-r["runs"], r["command"]))
    never = [r["command"] for r in rows if not ran_count(r["command"], ran) and not r["by_session"]]
    proposals = (_by_hand(sessions, hints_on) + _coordination(ran, subsessions)
                 + [{"kind": "wire", "count": len(f["commands"]),
                     "what": f"{f['feature']} is have, and its commands never ran: {', '.join(f['commands'])}",
                     "propose": "wire it (a hook, a procedure), document it, or mark it partial or retire it"}
                    for f in feats or []])
    if never:
        proposals.append({"kind": "wire", "count": len(never),
                          "what": f"{len(never)} command(s) never ran in the period",
                          "propose": "each wired (a hook, a schedule, a procedure), documented, or retired"})
    return {"since": since.isoformat(timespec="seconds"), "until": until.isoformat(timespec="seconds"),
            "sessions": sessions.get("sessions", 0), "subsessions": subsessions, "commands": rows, "never_run": never,
            "reads": sessions.get("reads") or {}, "edits": sessions.get("edits") or {}, "features": feats or [],
            "proposals": proposals}


def _by_hand(sessions: dict, hints_on: bool) -> list[dict]:
    """The proposals for the hand reads (the read hint, or a procedure line when it is on) and the hand edits."""
    proposals = []
    for kind, n in sorted((sessions.get("reads") or {}).items(), key=lambda kv: -kv[1]):
        how = ("a procedure line (the read hint is on and still read past)" if hints_on else
               "the read hint (config.json hints.read: true)")
        proposals.append({"kind": "procedure" if hints_on else "hint", "count": n,
                          "what": f"{n} hand read(s) of the {readhint.WHAT[kind]}: {ANSWERS[kind]} answers",
                          "propose": how})
    for kind, n in sorted((sessions.get("edits") or {}).items(), key=lambda kv: -kv[1]):
        proposals.append({"kind": "procedure", "count": n,
                          "what": f"{n} hand edit(s) of the {readhint.WHAT[kind]}: {WRITES[kind]} writes it",
                          "propose": "a procedure line, or a guard hint on the edit"})
    return proposals


def _coordination(ran: Counter, subsessions: int | None) -> list[dict]:
    """The sub-sessions started against the briefs brain brief wrote and the lots brain wave plan composed."""
    if not subsessions:
        return []
    briefs = int(ran.get("brain brief", 0))
    lots = int(ran.get("brain collisions", 0)) + int(ran.get("brain wave plan", 0))
    out = []
    if briefs < subsessions:
        out.append({"kind": "procedure", "count": subsessions - briefs,
                    "what": f"{subsessions} sub-session(s) started, brain brief ran {briefs} time(s)",
                    "propose": "the coordinator's procedure: each brief from brain brief"})
    if not lots:
        out.append({"kind": "procedure", "count": subsessions,
                    "what": "sub-sessions started with no run of brain collisions or brain wave plan",
                    "propose": "the coordinator's procedure: lots composed by brain wave plan"})
    return out


def render(rep: dict, top: int = perf.TOP) -> list[str]:
    rows = [r for r in rep["commands"] if r["runs"] or r["by_session"]]
    out = [f"adoption: {len(rep['commands'])} command(s) and subcommand(s), {len(rows)} ran since "
           f"{rep['since'][:10]}, {len(rep['never_run'])} never; {rep['sessions']} session(s) scanned", ""]
    shown = rows if top <= 0 else rows[:top]
    if shown:
        out += perf._table(["command", "runs", "by a session", "otherwise"],
                           [[r["command"], r["runs"], r["by_session"], r["otherwise"]] for r in shown], "lrrr")
        if len(shown) < len(rows):
            out.append(f"  ... {len(rows) - len(shown)} more (--top 0: all)")
        out.append("")
    if rep["never_run"]:
        out += ["never ran:", *[f"  {c}" for c in rep["never_run"]], ""]
    if rep["proposals"]:
        out.append("gaps and what to propose (nothing refused):")
        out += [f"  [{p['kind']}] {p['what']} -> {p['propose']}" for p in rep["proposals"]]
    else:
        out.append("no gap found")
    return out


def _store(root: Path | None) -> Path | None:
    try:
        root = root or paths.find_root()
    except Exception:  # noqa: BLE001 - run outside a brain: no features to cross
        return None
    store = Path(root) / "notes" / "graph" if root else None
    return store if store and (store / "schema.yaml").is_file() else None


def _hints_on() -> bool:
    try:
        from . import config
        return (config.load().data.get("hints") or {}).get("read") is True
    except Exception:  # noqa: BLE001
        return False


def main(since: str | None = None, top: int = perf.TOP, as_json: bool = False, out=None,
         now: datetime | None = None, root: Path | None = None, files: list[Path] | None = None) -> int:
    from . import cli
    out = out or sys.stdout
    now = now or datetime.now(timezone.utc)
    try:
        start = perf.parse_since(since, now)
    except perf.PerfError as exc:
        print(f"brain perf: {exc}", file=sys.stderr)
        return 2
    known, alias = units(cli.build_parser())
    ran = runs(start, now + timedelta(seconds=1), alias)
    seen = scan(transcripts(start) if files is None else files, start, now + timedelta(seconds=1), known, alias)
    used = ran + Counter(seen["typed"])   # a command a session ran counts, whatever the ledger kept
    rep = report(known, ran, seen, start, now, unused_features(_store(root), known, used), _subsessions(start, now),
                 _hints_on())
    if as_json:
        print(json.dumps(rep, ensure_ascii=False, indent=1), file=out)
    else:
        print("\n".join(render(rep, top)), file=out)
    return 0
