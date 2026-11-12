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
on its node: it lives here, written by ``brain adr pin``. A pin's ``holds`` is never edited: a change of the
invariant is an override, a new ADR (``brain adr new --reverses``), whose own pin follows; its ``touches`` may grow
as the code moves.

What reads the pins:

- ``brain impact --diff`` lists each pinned decision whose code the change touches, with its line and its date;
- ``brain review check HEAD --pr N`` (or ``--body FILE``) and ``brain merge-ready`` refuse until the PR body says, for
  each one, ``Keeps <id>`` or ``Overrides <id>: <why>``; an override needs the REVERSAL ADR that supersedes it;
- ``brain check`` warns on a pin of an unknown or pending decision, a superseded decision still pinned, a malformed
  row and two pins of one decision.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

from . import graph, inventory

FILE = "pins.yaml"
HEAD = ("# Decision pins (brain adr pin; the engine's docs/pins.md): each decision, the invariant it holds and the "
        "code it\n# governs. A holds line is never edited: an override is a new ADR (brain adr new --reverses).\n")
KEEP_RE = re.compile(r"^\s*(?:[-*]\s*)?(Keeps|Overrides)\s+`?([A-Za-z0-9_.-]+)`?\s*(?::\s*(.*?))?\s*$", re.I | re.M)
_SUPERSEDES_RE = re.compile(r"\*\*Supersedes\.\*\*[^\n]*?\(`([A-Za-z0-9_.-]+)`\)")
_GLOB = set("*?[")
ANSWERED = ("answered", "acked", "archived", "integrated")


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


def load(project) -> list[dict]:
    """The pins of ``project`` ([] without the file); :class:`PinError` when it does not parse or is not a list."""
    f = path_of(project)
    if not f.is_file():
        return []
    try:
        data = graph.load_yaml_file(f)
    except (OSError, ValueError) as exc:
        raise PinError(f"{f}: {exc}") from None
    except Exception as exc:   # yaml.YAMLError: the loader's own
        raise PinError(f"{f}: {exc}") from None
    if data is None:
        return []
    if not isinstance(data, list):
        raise PinError(f"{f}: a list of pins expected")
    return [p for p in data if isinstance(p, dict)]


def _touch_problem(t) -> str:
    if not isinstance(t, str) or not t.strip():
        return "a touch is a path or a CodeRef"
    if t.startswith("code:"):
        try:
            inventory.parse_code_ref(t)
        except ValueError:
            return f"{t}: not a CodeRef code:<repo>:<path>[::<symbol>]"
        return ""
    if t.startswith("/") or "\\" in t or ".." in t.split("/"):
        return f"{t}: a path relative to the repo, with /"
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

def decisions_of(project) -> dict[str, Decision]:
    """The project's ADRs and SDRs (with the REVERSAL that supersedes each, if any) and its DDRs."""
    from . import decisions as ddrs  # reads loads the logs; decisions the records
    from . import reads
    out: dict[str, Decision] = {}
    entries = reads.adr_entries(project)
    for e in entries:
        out[e["id"]] = Decision(e["id"], e["day"], e["title"], "sdr" if e["id"].startswith("sdr-") else "adr")
    for e in entries:
        if e["title"].upper().startswith("REVERSAL"):
            for old in _SUPERSEDES_RE.findall(e["text"]):
                if old in out and not out[old].superseded_by:
                    out[old].status, out[old].superseded_by = "superseded", e["id"]
    try:
        rows = ddrs.load(Path(project.root))
    except (OSError, ValueError):
        rows = []
    for _, d in rows:
        did = str(d.get("id") or "")
        if did:
            out[did] = Decision(did, str((d.get("answer") or {}).get("at") or "")[:10], str(d.get("title") or ""),
                                "ddr", str(d.get("status") or ""))
    return out


def why_not(pin: dict, known: dict[str, Decision]) -> str:
    """Why a well-formed pin's decision cannot be pinned ('' when it can)."""
    d = known.get(str(pin.get("decision")))
    if d is None:
        return "no such ADR, SDR or DDR"
    if d.kind == "ddr" and d.status not in ANSWERED:
        return f"a DDR {d.status or 'without a status'}: only an answered one is pinned"
    if d.superseded_by:
        return f"superseded by {d.superseded_by}: pin the REVERSAL instead"
    return ""


# --- writing (brain adr pin) ---

def _dump(pins: list[dict]) -> str:
    yaml = graph._yaml()
    rows = [{k: p[k] for k in ("decision", "holds", "touches", "since") if k in p} |
            {k: v for k, v in p.items() if k not in ("decision", "holds", "touches", "since")} for p in pins]
    body = yaml.safe_dump(sorted(rows, key=lambda p: str(p.get("decision"))), sort_keys=False, allow_unicode=True,
                          width=118, default_flow_style=False)
    return HEAD + body


def add(project, decision: str, touches: list[str], holds: str = "", day: str = "") -> tuple[dict, str]:
    """Pin ``decision`` (or add ``touches`` to its pin); returns (the pin, 'pinned' or 'extended'). :class:`PinError`
    on a decision that cannot be pinned, a malformed row, or a ``holds`` that differs from the pin's (an override:
    a new ADR, never an edit)."""
    pins = load(project)
    known = decisions_of(project)
    mine = next((p for p in pins if p.get("decision") == decision), None)
    if mine is not None:
        if holds and holds.strip() != str(mine.get("holds") or "").strip():
            raise PinError(f"{decision} holds {mine.get('holds')!r}: a holds line is never edited; an override is a "
                           f"new ADR (brain adr new --reverses {decision}), pinned in its turn")
        new = dict(mine, touches=list(dict.fromkeys([*(mine.get("touches") or []), *touches])))
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

def _path_hit(touch: str, files: set[str]) -> list[str]:
    if touch.endswith("/"):
        return sorted(f for f in files if f.startswith(touch))
    if _GLOB & set(touch):
        return sorted(f for f in files if fnmatch.fnmatchcase(f, touch))
    return [touch] if touch in files else []


def hits(pin: dict, files: set[str], repos: set[str], refs: set[str] | None = None,
         known: set[str] = frozenset()) -> list[str]:
    """What of ``pin``'s touches a change hits: ``files`` (repo-relative, the change's both sides) of a repo named one
    of ``repos``; ``refs``, the CodeRefs the impact found touched: a CodeRef with a symbol that the graph knows
    (``known``) counts then only when it is among them; otherwise, and without ``refs``, at the file level."""
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


def touched(project, files, repos, refs: set[str] | None = None, known: set[str] = frozenset()) -> list[dict]:
    """The pinned decisions a change touches: [{id, holds, day, since, hits, title}], by id; the pins that are
    malformed or name a decision that cannot be pinned are left out (brain check names them)."""
    try:
        pins = load(project)
    except PinError:
        return []
    if not pins:
        return []
    known = decisions_of(project)
    files, repos = set(files), {r.lower() for r in repos}
    out = []
    for p in pins:
        if problems(p) or why_not(p, known):
            continue
        h = hits(p, files, repos, refs, known)
        if h:
            d = known[str(p["decision"])]
            out.append({"id": d.id, "holds": str(p["holds"]).strip(), "day": d.day, "since": str(p.get("since") or ""),
                        "hits": h, "title": d.title})
    return sorted(out, key=lambda x: x["id"])


# --- the PR body ---

def answers(body: str) -> dict[str, tuple[str, str]]:
    """{decision: ('keeps' or 'overrides', the reason)} from a PR body's ``Keeps <id>`` and ``Overrides <id>: why``
    lines (a list mark and backquotes allowed)."""
    return {m.group(2): (m.group(1).lower(), (m.group(3) or "").strip()) for m in KEEP_RE.finditer(body or "")}


def verdict(project, pinned: list[dict], body: str | None) -> list[str]:
    """What blocks the merge ([] when nothing): each pinned decision the change touches needs ``Keeps <id>`` or
    ``Overrides <id>: <why>`` in the PR body, and an override the REVERSAL ADR that supersedes it."""
    if not pinned:
        return []
    if body is None:
        return [f"{len(pinned)} pinned decision(s) touched ({', '.join(p['id'] for p in pinned)}): the PR body is "
                "needed (--pr N or --body FILE)"]
    said = answers(body)
    known = decisions_of(project) if any(said.get(p["id"], ("",))[0] == "overrides" for p in pinned) else {}
    out = []
    for p in pinned:
        word, why = said.get(p["id"], ("", ""))
        if not word:
            out.append(f"{p['id']} ({p['holds']}): the PR body says neither Keeps {p['id']} nor Overrides "
                       f"{p['id']}: <why>")
        elif word == "overrides" and not why:
            out.append(f"Overrides {p['id']}: the reason is missing")
        elif word == "overrides" and not (known.get(p["id"]) and known[p["id"]].superseded_by):
            out.append(f"Overrides {p['id']}: no REVERSAL ADR supersedes it (brain adr new --reverses {p['id']})")
    return out


# --- brain check ---

def check_lines(project) -> list[str]:
    """``brain check``'s warnings about the project's pins; nothing without a pins file."""
    f = path_of(project)
    try:
        pins = load(project)
    except PinError as exc:
        return [f"warning: {exc}"]
    if not pins:
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

