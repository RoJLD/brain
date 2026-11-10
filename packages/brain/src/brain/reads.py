"""What a session asks of a brain instead of reading its files by hand (wi-brain-read-commands): one item and all that
bears on it, the backlog filtered, an ADR's text or the ADRs that decide a node, a spec or one of its sections, the
journal's last entries. ``brain item show``, ``brain items``, ``brain adr show``, ``brain spec show`` and ``brain
journal last`` print them, each with ``--json``; the PreToolUse hint (brain.readhint) names them when a session reads
those files by hand.

The graph is research_graph's (query.show_item and list_items, LayeredGraph.decisions, history.timeline), loaded in
this process with the other stores its edges name (brain.crossstore): research_graph need not be on the PATH. The
DDRs are the records' (brain.decisions), the waves brain.waves'; the logs and the specs are read as text (brain.notes,
brain.links' headings). Nothing here writes.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import crossstore, decisions, graph, links, notes, records, waves

OPEN = ("doing", "todo", "blocked")   # research_graph items' default statuses
DOC_ID = re.compile(r"^doc:[^:]+:(.+?)(?:::(.+))?$")   # a Doc node of brain.links: doc:<repo>:<path>[::<key>]
NUMBERED = re.compile(r"^\d+(?:\.\d+)*\.?\s*")   # a heading's number, before its words


class ReadError(Exception):
    pass


# --- the graph ---

def load(root: Path, store: Path):
    """The store's graph, with the other stores' nodes its edges name."""
    from research_graph.loader import ValidationError, load_store
    try:
        return load_store(store, foreign=crossstore.foreign_nodes(root, store))
    except ValidationError as exc:
        raise ReadError(f"{store}: does not load: {'; '.join(exc.errors[:3])} (brain check says why)") from None


def holder(root: Path, stores: list[Path], nid: str):
    """(store, graph) of the first store that holds ``nid`` as its own node (not another store's)."""
    from research_graph.model import store_of
    for store in stores:
        g = load(root, store)
        if nid in g and not store_of(g, nid):
            return store, g
    raise ReadError(f"{nid}: no such node in {', '.join(s.as_posix() for s in stores) or 'no store'}")


def _named(d: dict) -> set[str]:
    """The ids a DDR names: its links' lists and where it was applied (applied.in)."""
    named = {str(x) for v in (d.get("links") or {}).values() if isinstance(v, list) for x in v}
    return named | {str(x) for x in ((d.get("applied") or {}).get("in") or [])}


def _ddr_row(d: dict) -> dict:
    answer = d.get("answer") or {}
    picked = [*answer.get("choices", []), *([f"other: {answer['other']}"] if answer.get("other") else [])]
    return {"id": str(d.get("id")), "status": str(d.get("status") or ""), "title": str(d.get("title") or ""),
            "answer": "; ".join(" ".join(str(x).split()) for x in picked)}


def ddrs_naming(root: Path, nid: str) -> list[dict]:
    """The DDRs whose links (items, specs, adrs...) or applied.in name ``nid``: id, status, title, answer."""
    if not (root / records.RECORDS_DIR / "ddr").is_dir():
        return []
    return sorted((_ddr_row(d) for _, d in decisions.load(root) if nid in _named(d)), key=lambda r: r["id"])


def item(root: Path, stores: list[Path], nid: str, *, git: bool = True) -> tuple[dict, list | None]:
    """Everything about ``nid``: research_graph's item (row, props, edges both ways, the ids its props name, blockers),
    the decisions behind it (direct, inherited, specs), the DDRs that name it, and its history from git (None without
    ``git``, or when git cannot read it: ``history_error``)."""
    from research_graph import history, query
    from research_graph.model import LayeredGraph
    store, g = holder(root, stores, nid)
    detail = query.show_item(g, nid, default_repo=root.resolve().name)
    detail["decisions"] = LayeredGraph(g).decisions(nid)
    detail["ddrs"] = ddrs_naming(root, nid)
    detail["store_path"] = store.as_posix()
    events, detail["history_error"] = None, None
    if git:
        node = g.nodes[nid]
        try:   # an overlay node's history is its own repository's
            events = [e for e in history.timeline(node.get("overlay") or store, types={node.get("type")})
                      if e.id == nid]
        except history.GitError as exc:
            detail["history_error"] = str(exc)
    return detail, events


def _wave_ids(root: Path, store: Path, ref: str) -> set[str]:
    """The items of wave ``ref`` (its id or its release): those whose wave it is now (brain.waves), and those in no
    wave whose free-text props.wave names it."""
    plan = waves.load(store, root)
    wid = plan.resolve(ref)
    ids = set(plan.items_of(wid)) if wid else set()
    release = plan.label(wid) if wid else ref.removeprefix("wave-")
    for nid, node in plan.nodes.items():
        text = str((node.get("props") or {}).get("wave") or "").strip() if isinstance(node.get("props"), dict) else ""
        if not text or not plan.is_item(nid) or plan.wave_of(nid):
            continue
        m = waves.RELEASE_IN_RE.match(text)
        if text == ref or (m and m.group(1) == release):
            ids.add(nid)
    return ids


def items(root: Path, store: Path, *, statuses=None, every: bool = False, priorities=None, repo: str | None = None,
          props: dict | None = None, text: str | None = None, types=None, wave: str = "",
          milestones=None) -> list[dict]:
    """research_graph's item rows matching every filter, by status, priority and id: statuses (default the open
    ones; ``every``: all), priorities (P0..P3, P1? a proposal, none), repo, props (key -> None or a substring of its
    value), text (every word), types (default WorkItem), the wave (id or release), milestones (part_of one of them)."""
    from research_graph import query
    g = load(root, store)
    rows = query.list_items(g, statuses=None if every else (statuses or OPEN), priorities=priorities, repo=repo,
                            props=props or None, text=text, ids=_wave_ids(root, store, wave) if wave else None,
                            types=types or ("WorkItem",), default_repo=root.resolve().name)
    if milestones:
        rows = [r for r in rows if set(milestones) & set(r["milestones"])]
    return rows


def render_item(d: dict, events: list | None) -> list[str]:
    """``brain item show``'s text: research_graph's item, every prop in full, then its decisions and DDRs."""
    from research_graph import report
    out = [f"{report.name(d)}  [{d['type']} {d['status']}]  priority {report.priority_label(d)}",
           f"  {' '.join(str(d['title']).split())}"]
    out += [f"  {k}: {v}" for k, v in (("anchor", d.get("anchor")), ("repo", ", ".join(d.get("repos") or [])),
                                        ("store", d.get("store_path"))) if v]
    if d.get("props"):
        out.append("props:")
        out += [f"  {k}: {' '.join(str(v).split())}" for k, v in d["props"].items()]
    for key, heading in (("out", "links out"), ("in", "links in"), ("mentions", "named in its props (no edge yet)"),
                         ("mentioned_by", "named by")):
        if d.get(key):
            out.append(f"{heading}:")
            out += [f"  {e['edge'] + ' ' * max(1, 14 - len(e['edge'])) if e.get('edge') else ''}{report.name(e)} "
                    f"[{e['type']} {e['status']}]  {report.short(e['title'], 80)}" for e in d[key]]
    if d.get("blockers"):
        out.append("blocked by: " + report.names(d, d["blockers"]))
    if d.get("waiting_on_it"):
        out.append("open items waiting on it: " + report.names(d, d["waiting_on_it"]))
    out += _decision_lines(d["decisions"]) + _ddr_lines(d["ddrs"])
    if d.get("history_error"):
        out.append(f"history: unavailable ({d['history_error']})")
    elif events is not None:
        out.append(f"history (git, first-parent): {len(events)} change(s)")
        out += ["  " + report.event_line(e, with_id=False) for e in events]
    return out


def _decision_lines(dec: dict) -> list[str]:
    from research_graph import report
    out = []
    for key, heading in (("direct", "decided by"), ("inherited", "decisions inherited")):
        if dec.get(key):
            out.append(f"{heading} (brain adr show <id> prints one):")
            out += [f"  {report.name(e)} [{e['type']} {e['status']}]  {report.short(e['title'], 90)}"
                    + (f"  -> superseded by {e['superseded_by']}" if e.get("superseded_by") else "")
                    + (f"  (via {e['via']})" if e.get("via") else "") for e in dec[key]]
    if dec.get("specs"):
        out.append("specs (brain spec show <id> [--section N]):")
        out += [f"  {report.name(s)} [{s['status']}]  {s.get('anchor') or ''}" for s in dec["specs"]]
    return out


def _ddr_lines(ddrs: list[dict]) -> list[str]:
    if not ddrs:
        return []
    return ["DDRs that name it:"] + [f"  {r['id']} [{r['status']}]  {' '.join(r['title'].split())}"
                                     + (f"  -> {r['answer']}" if r["answer"] else "") for r in ddrs]


# --- the decision logs ---

def logs(project) -> list[Path]:
    """The project's decision logs that exist (decision_logs, else its decisions file)."""
    return [p for p in (project.decision_logs or [project.decisions]) if p and p.is_file()]


def adr_entries(project) -> list[dict]:
    """Every ADR and SDR of the project's logs (brain.notes.adr_entries), each with its log's path."""
    out = []
    for log in logs(project):
        kind = "sdr" if log.name == "scientific_decisions.md" else "adr"
        out += [{**e, "file": _rel(project.root, log)} for e in notes.adr_entries(notes.read(log)[0], kind)]
    return out


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()


def _match(entries: list[dict], ref: str) -> list[dict]:
    """The ADRs ``ref`` names: by id, else by exact title (its "(ADR)" suffix optional), else by the start of an id
    (adr-2026-11-10-...), one only."""
    hits = [e for e in entries if e["id"] == ref] or \
        [e for e in entries if ref in (e["title"], notes.ADR_SUFFIX_RE.sub("", e["title"]))]
    if hits or not ref.startswith(("adr-", "sdr-")):
        return hits
    hits = [e for e in entries if e["id"].startswith(ref)]
    if len(hits) > 1:
        more = f" and {len(hits) - 10} more" if len(hits) > 10 else ""
        raise ReadError(f"{ref}: {len(hits)} ADRs start so ({', '.join(e['id'] for e in hits[:10])}{more}): give one")
    return hits


def adr_show(project, root: Path, stores: list[Path], ref: str) -> dict:
    """The ADR ``ref`` names (its id, its title or the start of its id), else the ADRs that decide the node ``ref``
    (a rule, an item, a spec: its direct decisions, each with its text): {ref, node, adrs, inherited}."""
    entries = adr_entries(project)
    hits = _match(entries, ref)
    if hits:
        return {"ref": ref, "node": None, "adrs": hits, "inherited": []}
    from research_graph.model import LayeredGraph
    try:
        _, g = holder(root, stores, ref)
    except ReadError:
        logs_read = ", ".join(sorted({x["file"] for x in entries})) or "no decision log"
        raise ReadError(f"{ref}: no ADR of {logs_read} with this id or title, and no node of the project's "
                        "stores") from None
    dec = LayeredGraph(g).decisions(ref)
    by_id = {e["id"]: e for e in entries}
    adrs = [{**by_id.get(x["id"], {"id": x["id"], "text": ""}), "title": x["title"], "status": x["status"],
             **({"superseded_by": x["superseded_by"]} if x.get("superseded_by") else {})} for x in dec["direct"]]
    node = g.nodes[ref]
    return {"ref": ref, "node": {"id": ref, "type": node.get("type"), "title": node.get("title") or ""},
            "adrs": adrs, "inherited": dec["inherited"]}


def render_adrs(out: dict, titles: bool = False) -> list[str]:
    lines = []
    if out["node"]:
        n = out["node"]
        lines.append(f"{n['id']} [{n['type']}]: decided by {len(out['adrs'])} ADR(s)" +
                     (f"; {len(out['inherited'])} inherited (brain item show {n['id']})" if out["inherited"] else ""))
    for e in out["adrs"]:
        head = f"{e['id']}" + (f"  ({e['file']}:{e['line']})" if e.get("file") else "") + \
            (f"  -> superseded by {e['superseded_by']}" if e.get("superseded_by") else "")
        if titles or not e.get("text"):
            lines.append(f"{head}  {e.get('day', '')} {' '.join(str(e['title']).split())}".rstrip()
                         + ("" if titles or e.get("text") else "  (not in this project's decision logs)"))
        else:
            lines += [f"== {head}", e["text"], ""]
    return lines[:-1] if lines and lines[-1] == "" else lines


# --- specs ---

def spec_file(root: Path, stores: list[Path], ref: str) -> tuple[Path, str]:
    """(the spec's file, the section a Doc id names) of a Spec or Doc node id, a Doc id (doc:<repo>:<path>::<key>)
    or a path."""
    m = DOC_ID.match(ref)
    if m:
        return root / m.group(1), m.group(2) or ""
    for store in stores:
        hit = graph.node_index(store).get(ref)
        if hit:
            anchor = str(hit[1].get("anchor") or "")
            if not anchor:
                raise ReadError(f"{ref}: a {hit[1].get('type')} with no anchor (no file to read)")
            return root / anchor.split("#", 1)[0], ""
    path = Path(ref) if Path(ref).is_absolute() else root / ref
    if path.is_file():
        return path, ""
    raise ReadError(f"{ref}: no Spec or Doc node of the project's stores, and no such file")


def headings(text: str) -> list[dict]:
    """The headings of a markdown text outside code fences: {level, title, key (a numbered heading's number, else
    its words: brain.links' Doc keys), line (from 1)}."""
    out, fence = [], False
    for i, line in enumerate(text.split("\n")):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        m = None if fence else links.HEADING.match(line)
        if m:
            title = m.group(2).strip()
            out.append({"level": len(m.group(1)), "title": title, "key": links.short_key(title), "line": i + 1})
    return out


def _heading(heads: list[dict], ref: str) -> dict | None:
    """The heading ``ref`` names: by its key, else by the start of its title, its number left out or not."""
    want = ref.strip().rstrip(".").lower()
    by_key = [h for h in heads if h["key"].lower() == want]
    by_title = [h for h in heads if want and any(t.lower().startswith(want)
                                                 for t in (h["title"], NUMBERED.sub("", h["title"])))]
    return (by_key or by_title or [None])[0]


def section(text: str, ref: str) -> tuple[dict, str]:
    """(heading, text) of the section ``ref`` names: its number (2.1), its key, or the start of its title (case
    ignored), down to the next heading of its level or above."""
    heads = headings(text)
    hit = _heading(heads, ref)
    if hit is None:
        raise ReadError(f"section {ref!r}: no such heading ({', '.join(h['key'] for h in heads[:15]) or 'none'}"
                        f"{'...' if len(heads) > 15 else ''}; --toc lists them)")
    end = next((h["line"] for h in heads if h["line"] > hit["line"] and h["level"] <= hit["level"]), None)
    lines = text.split("\n")
    return hit, "\n".join(lines[hit["line"] - 1:(end - 1) if end else len(lines)]).rstrip()


def spec_show(root: Path, stores: list[Path], ref: str, sec: str = "", toc: bool = False) -> dict:
    """{file, section, title, text, toc}: the whole spec, its section ``sec`` (or the one a Doc id names), or with
    ``toc`` its headings only."""
    path, from_id = spec_file(root, stores, ref)
    if not path.is_file():
        raise ReadError(f"{ref}: {path} is not on this machine")
    text = notes.read(path)[0]
    out = {"file": _rel(root, path), "section": "", "title": "", "text": "", "toc": []}
    if toc:
        out["toc"] = headings(text)
        return out
    sec = sec or from_id
    if sec:
        head, out["text"] = section(text, sec)
        out["section"], out["title"] = head["key"], head["title"]
    else:
        out["text"] = text.rstrip()
    return out


# --- the journal ---

def journal_last(path: Path, n: int = 1) -> list[dict]:
    """The journal's last ``n`` dated entries (all of them with 0), oldest first."""
    if not path or not path.is_file():
        raise ReadError(f"{path}: no journal here")
    entries = notes.dated_sections(notes.read(path)[0])
    return entries[-n:] if n else entries
