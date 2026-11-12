"""Decision pins (wi-brain-decision-pins; spec-brain-three-repos §3 no. 3, TR-2): an ADR or an answered DDR pinned to
the code it governs, so that a change to that code says whether it keeps the decision or overrides it.

A pin is one row of ``pins.yaml`` beside the project's decision log (``notes/pins.yaml`` by default):

    - decision: adr-2026-11-03-...     # an ADR or SDR of the project's logs, or an answered DDR
      holds: keep the retry count at 4   # one line: the invariant the decision keeps
      touches:                          # paths (a file, a folder ending with /, a glob) or CodeRefs
        - packages/brain/src/brain/net.py
        - code:brain:packages/brain/src/brain/net.py::backoff
      since: 2026-11-12

The decision log is append-only and its ADR nodes are generated from it, so a pin cannot live in the ADR's entry or
on its node: it lives here, written by ``brain adr pin`` (which rewrites the file: no hand comment survives). A pin's
``holds`` is never edited: a change of the invariant is an override, a new ADR (``brain adr new --reverses ID``, an
ADR's or an answered DDR's id), whose own pin follows; its ``touches`` may grow as the code moves.

What reads the pins:

- ``brain impact --diff`` lists each pinned decision whose code the change touches, with its line and its date;
- ``brain review check HEAD --pr N`` (or ``--body FILE``) and ``brain merge-ready`` refuse until the PR body says, for
  each one, ``Keeps <id>`` (a decision in force) or ``Overrides <id>: <why>`` (a decision a later ADR supersedes,
  in the log at the head); a change of a pin's own row counts as touching it;
- ``brain check`` warns on a pin of an unknown or pending decision, a superseded decision still pinned, a malformed
  row and two rows of one decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import graph, inventory

FILE = "pins.yaml"
HEAD = ("# Decision pins (brain adr pin; the engine's docs/pins.md): each decision, the invariant it holds and the "
        "code it\n# governs. A holds line is never edited: an override is a new ADR (brain adr new --reverses).\n")
# A PR body's line: a list mark (-, *, +, 1.) allowed, then Keeps or Overrides, the ids, then a reason after a colon
# or a dash. Fenced code and HTML comments are stripped first: what the rendered PR does not show does not count.
LINE_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])?[ \t]*(keeps|overrides)\b[ \t]+(.+?)[ \t]*$", re.I | re.M)
REASON_RE = re.compile(r"\s*(?::|\s[—–-]\s)\s*")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*[A-Za-z0-9]")
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$", re.M | re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_SUPERSEDES_RE = re.compile(r"\*\*Supersedes\.\*\*(.*?)(?=\n[ \t]*\n|\n\*\*|\Z)", re.S)
_ID_IN_RE = re.compile(r"\(`([A-Za-z0-9_.-]+)`\)")
_GLOB = set("*?[")
ANSWERED = ("answered", "integrated", "archived")   # a DDR's statuses once the owner answered it


class PinError(ValueError):
    pass


@dataclass
class Decision:
    id: str
    day: str
    title: str
    kind: str               # adr, sdr, ddr
    status: str = "active"  # an ADR's: active, or superseded; a DDR's own
    superseded_by: str = ""


def path_of(project) -> Path:
    """The pins file of ``project``: beside its decision log."""
    log = getattr(project, "decisions", None)
    return (Path(log).parent if log else Path(project.root) / "notes") / FILE


def parse(text: str, where: str = FILE) -> tuple[list[dict], int]:
    """(the rows of a pins file's text, how many entries were not mappings); :class:`PinError` when it does not parse
    or is not a list. A ``touches`` given as one string is read as a list of one."""
    yaml = graph._yaml()
    try:
        data = yaml.safe_load(text) if text.strip() else None
    except yaml.YAMLError as exc:
        raise PinError(f"{where}: {exc}") from None
    if data is None:
        return [], 0
    if not isinstance(data, list):
        raise PinError(f"{where}: a list of pins expected")
    rows = [dict(p, touches=[p["touches"]]) if isinstance(p, dict) and isinstance(p.get("touches"), str) else p
            for p in data]
    return [p for p in rows if isinstance(p, dict)], sum(1 for p in rows if not isinstance(p, dict))


def load(project, dropped: list | None = None) -> list[dict]:
    """The pins of ``project`` ([] without the file); :class:`PinError` when it does not parse or is not a list;
    ``dropped`` gets the count of entries that are not mappings."""
    f = path_of(project)
    if not f.is_file():
        return []
    try:
        text = f.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PinError(f"{f}: {exc}") from None
    rows, bad = parse(text, str(f))
    if dropped is not None:
        dropped.append(bad)
    return rows


def _touch_problem(t) -> str:
    if not isinstance(t, str) or not t.strip():
        return "a touch is a path or a CodeRef"
    if t.startswith("code:"):
        try:
            inventory.parse_code_ref(t)
        except ValueError:
            return f"{t}: not a CodeRef code:<repo>:<path>[::<symbol>]"
        return ""
    if t.startswith(("/", "./")) or "\\" in t or ".." in t.split("/"):
        return f"{t}: a path relative to the repo, with /, without ./"
    return ""


def problems(pin: dict) -> list[str]:
    """What is wrong with one pin's shape ([] when well formed); the decision is resolved apart."""
    out = []
    if not str(pin.get("decision") or "").strip():
        out.append("no decision")
    holds = pin.get("holds")
    if not isinstance(holds, str) or not holds.strip() or "\n" in holds.strip():
        out.append("holds is one line: the invariant the decision keeps")
    touches = pin.get("touches")
    if not isinstance(touches, list) or not touches:
        out.append("touches is a list of paths or CodeRefs")
    else:
        out += [p for p in (_touch_problem(t) for t in touches) if p]
    return out


# --- the decisions a pin may name ---

def decisions_of(project, logs: list[tuple[str, str]] | None = None) -> dict[str, Decision]:
    """The project's ADRs and SDRs and its DDRs, each with the later ADR that supersedes it, if any; ``logs``: the
    decision logs' texts with their kind (adr or sdr), a head's instead of the files."""
    from . import decisions as ddrs  # the records
    if logs is None:
        from . import reads
        logs = [(_read(log), "sdr" if log.name == "scientific_decisions.md" else "adr") for log in reads.logs(project)]
    out: dict[str, Decision] = {}
    try:
        rows = ddrs.load(Path(project.root))
    except (OSError, ValueError):
        rows = []
    for _, d in rows:
        did = str(d.get("id") or "")
        if did:
            out[did] = Decision(did, str((d.get("answer") or {}).get("at") or "")[:10], str(d.get("title") or ""),
                                "ddr", str(d.get("status") or ""))
    return _adrs(logs, out)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _adrs(logs: list[tuple[str, str]], out: dict[str, Decision]) -> dict[str, Decision]:
    """The ADRs and SDRs of the logs into ``out``; each decision a later entry's Supersedes field names (by its id in
    backquotes, wherever the field wraps; an ADR or a DDR) superseded by that entry."""
    from . import notes
    entries = [e for text, kind in logs for e in notes.adr_entries(text, kind)]
    for e in entries:
        out[e["id"]] = Decision(e["id"], e["day"], e["title"], "sdr" if e["id"].startswith("sdr-") else "adr")
    for e in entries:
        for field in _SUPERSEDES_RE.findall(e["text"]):
            for old in _ID_IN_RE.findall(" ".join(field.split())):
                if old in out and old != e["id"] and not out[old].superseded_by:
                    out[old].superseded_by = e["id"]
                    out[old].status = "superseded" if out[old].kind != "ddr" else out[old].status
    return out


def why_not(pin: dict, known: dict[str, Decision]) -> str:
    """Why a well-formed pin's decision cannot be pinned now ('' when it can)."""
    d = known.get(str(pin.get("decision")))
    if d is None:
        return "no such ADR, SDR or DDR"
    if d.kind == "ddr" and d.status not in ANSWERED:
        return f"a DDR {d.status or 'without a status'}: only an answered one is pinned"
    if d.superseded_by:
        return f"superseded by {d.superseded_by}: pin the decision in force instead"
    return ""


def _unpinnable(pin: dict, known: dict[str, Decision]) -> bool:
    """A pin the gate leaves out: malformed, or naming no decision or a DDR not answered (brain check says it). A
    superseded decision stays: the change that touches its code says it overrides it."""
    return bool(problems(pin)) or (why_not(pin, known) != "" and not known.get(str(pin.get("decision")), Decision(
        "", "", "", "")).superseded_by)


# --- writing (brain adr pin) ---

def _dump(pins: list[dict]) -> str:
    yaml = graph._yaml()
    rows = [{k: p[k] for k in ("decision", "holds", "touches", "since") if k in p} |
            {k: v for k, v in p.items() if k not in ("decision", "holds", "touches", "since")} for p in pins]
    body = yaml.safe_dump(sorted(rows, key=lambda p: str(p.get("decision"))), sort_keys=False, allow_unicode=True,
                          width=118, default_flow_style=False)
    return HEAD + body


def add(project, decision: str, touches: list[str], holds: str = "", day: str = "") -> tuple[dict, str]:
    """Pin ``decision`` (or add ``touches`` to its pin, every row of it merged into one); returns (the pin, 'pinned'
    or 'extended'). :class:`PinError` on a decision that cannot be pinned, a malformed row, a file with entries that
    are not pins (it is not rewritten), or a ``holds`` that differs from the pin's (an override: a new ADR)."""
    dropped: list[int] = []
    pins = load(project, dropped)
    if dropped and dropped[0]:
        raise PinError(f"{path_of(project)}: {dropped[0]} entry(ies) that are not pins: fix the file by hand first")
    known = decisions_of(project)
    mine = [p for p in pins if p.get("decision") == decision]
    if mine:
        old = str(mine[0].get("holds") or "").strip()
        if holds and " ".join(holds.split()) != " ".join(old.split()):
            raise PinError(f"{decision} holds {old!r}: a holds line is never edited; an override is a new ADR (brain "
                           f"adr new --reverses {decision}), pinned in its turn")
        merged = [t for p in mine for t in (p.get("touches") or [])]
        new = dict(mine[0], touches=list(dict.fromkeys([*merged, *touches])))
        verb = "extended"
    else:
        new = {"decision": decision, "holds": " ".join(str(holds).split()), "touches": list(dict.fromkeys(touches)),
               "since": day}
        verb = "pinned"
    bad = problems(new) or ([why_not(new, known)] if why_not(new, known) else [])
    if bad:
        raise PinError(f"{decision}: {'; '.join(bad)}")
    rest = [p for p in pins if p.get("decision") != decision]
    f = path_of(project)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(_dump(rest + [new]), encoding="utf-8", newline="\n")
    return new, verb


# --- matching a change ---

def glob_re(pattern: str) -> re.Pattern:
    """A path glob: ``*`` and ``?`` within one folder, ``**`` across folders, ``[...]`` a class."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j < 0:
                out.append(re.escape(c))
            else:
                out.append("[" + pattern[i + 1:j].replace("\\", "\\\\") + "]")
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


def _path_hit(touch: str, files: set[str]) -> list[str]:
    if touch.endswith("/"):
        return sorted(f for f in files if f.startswith(touch))
    if _GLOB & set(touch):
        rx = glob_re(touch)
        return sorted(f for f in files if rx.match(f))
    return [touch] if touch in files else []


def hits(pin: dict, files: set[str], repos: set[str], refs: set[str] | None = None,
         known: set[str] = frozenset()) -> list[str]:
    """What of ``pin``'s touches a change hits: ``files`` (repo-relative, the change's both sides) of a repo named one
    of ``repos`` (a plain path counts in every repo of the project); ``refs``, the CodeRefs the impact found touched:
    a CodeRef with a symbol that the graph knows (``known``) counts then only when it is among them; otherwise, and
    without ``refs``, at the file level."""
    out = []
    for t in pin.get("touches") or ():
        if not isinstance(t, str):
            continue
        if t.startswith("code:"):
            try:
                repo, path, symbol = inventory.parse_code_ref(t)
            except ValueError:
                continue
            if repo.lower() not in repos:
                continue
            if symbol and refs is not None and t in known:
                out += [t] if t in refs else []
            elif path in files:
                out.append(t)
        else:
            out += _path_hit(t, files)
    return list(dict.fromkeys(out))


def touched(project, files, repos, refs: set[str] | None = None, known: set[str] = frozenset(),
            pins: list[dict] | None = None, decided: dict[str, Decision] | None = None,
            changed_rows: set[str] = frozenset()) -> list[dict]:
    """The pinned decisions a change touches: [{id, holds, day, since, hits, title, superseded_by}], by id. ``pins``
    and ``decided`` (default: the project's files) are a change's own, read at its base and head; ``changed_rows``:
    the decisions whose row the change edits or removes, touched as such. The pins that are malformed or name no
    decision, or a DDR not answered, are left out (brain check names them); a superseded one stays."""
    if pins is None:
        try:
            pins = load(project)
        except PinError:
            return []
    if not pins and not changed_rows:
        return []
    decided = decisions_of(project) if decided is None else decided
    files, repos = set(files), {r.lower() for r in repos}
    out = []
    for p in pins:
        did = str(p.get("decision") or "")
        if _unpinnable(p, decided):
            continue
        h = hits(p, files, repos, refs, known) + ([FILE] if did in changed_rows else [])
        if h:
            d = decided[did]
            out.append({"id": d.id, "holds": str(p["holds"]).strip(), "day": d.day, "since": str(p.get("since") or ""),
                        "hits": h, "title": d.title, "superseded_by": d.superseded_by})
    return sorted(out, key=lambda x: x["id"])


# --- the PR body ---

def answers(body: str) -> dict[str, dict[str, str]]:
    """{decision: {'keeps' or 'overrides': the reason}} from a PR body's lines ``Keeps <id>[, <id>...]`` and
    ``Overrides <id>: why`` (a list mark, backquotes and bold allowed; the reason after a colon or a dash; ids read in
    lower case). Fenced code and HTML comments are left out."""
    text = _COMMENT_RE.sub("", _FENCE_RE.sub("", body or ""))
    out: dict[str, dict[str, str]] = {}
    for m in LINE_RE.finditer(text):
        word, rest = m.group(1).lower(), m.group(2)
        parts = REASON_RE.split(rest, maxsplit=1)
        ids, why = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        for did in ID_RE.findall(ids.replace("`", " ").replace("*", " ")):
            if did.lower() in ("and", "or"):
                continue
            out.setdefault(did.lower(), {})[word] = why
    return out


def verdict(project, pinned: list[dict], body: str | None) -> list[str]:
    """What blocks the merge ([] when nothing): each pinned decision the change touches needs, in the PR body,
    ``Keeps <id>`` when it is in force, ``Overrides <id>: <why>`` when a later ADR supersedes it (the override written
    first, as a new ADR); one id both kept and overridden blocks."""
    if not pinned:
        return []
    if body is None:
        return [f"{len(pinned)} pinned decision(s) touched ({', '.join(p['id'] for p in pinned)}): the PR body is "
                "needed (--pr N or --body FILE)"]
    said = answers(body)
    out = []
    for p in pinned:
        words = said.get(p["id"].lower(), {})
        if "keeps" in words and "overrides" in words:
            out.append(f"{p['id']}: the PR body both keeps and overrides it")
        elif p.get("superseded_by"):
            if "overrides" not in words:
                out.append(f"{p['id']} is superseded by {p['superseded_by']}: the PR body says Overrides {p['id']}: "
                           "<why>")
            elif not words["overrides"]:
                out.append(f"Overrides {p['id']}: the reason is missing")
        elif "overrides" in words:
            out.append(f"Overrides {p['id']}: no later ADR supersedes it yet (brain adr new --reverses {p['id']})")
        elif "keeps" not in words:
            out.append(f"{p['id']} ({p['holds']}): the PR body says neither Keeps {p['id']} nor Overrides "
                       f"{p['id']}: <why>")
    return out


# --- brain check ---

def check_lines(project) -> list[str]:
    """``brain check``'s warnings about the project's pins; nothing without a pins file."""
    f = path_of(project)
    dropped: list[int] = []
    try:
        pins = load(project, dropped)
    except PinError as exc:
        return [f"warning: {exc}"]
    if not pins and not (dropped and dropped[0]):
        return []
    known = decisions_of(project)
    bad, seen, twice = [], set(), []
    for p in pins:
        did = str(p.get("decision") or "?")
        why = "; ".join(problems(p)) or why_not(p, known)
        if why:
            bad.append(f"{did} ({why})")
        if did in seen:
            twice.append(did)
        seen.add(did)
    if dropped and dropped[0]:
        bad.append(f"{dropped[0]} entry(ies) that are not pins")
    rel = notes_rel(project, f)
    out = [f"warning: {len(bad)} pin(s) in {rel} to fix (docs/pins.md): {', '.join(bad[:10])}"] if bad else []
    if twice:
        out.append(f"warning: {rel} pins one decision twice: {', '.join(sorted(set(twice)))}")
    return out


def notes_rel(project, f: Path) -> str:
    try:
        return f.relative_to(Path(project.root)).as_posix()
    except ValueError:
        return f.as_posix()
