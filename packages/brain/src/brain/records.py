"""Records in the brain repo: ``records/ddr/<id>.yaml``, ``records/sr/<yyyy-mm>/<id>.yaml``, ``records/ar/<yyyy-mm>.jsonl``.

Every write is secret-scanned and validated first. AR files are append-only. ``graph()`` turns the records into
generated graph nodes and edges (``nodes/_generated_records.yaml``, ``edges/_generated_records.yaml``):
- Session (an SR), DDR, Action (an AR) nodes;
- ``raised_by`` DDR -> Session, ``answered_in`` DDR -> ADR, ``about`` DDR -> WorkItem / Milestone / Spec,
  ``produced_by`` Action or ADR -> Session, ``touches`` Session or Action -> WorkItem / Milestone / Spec.
An edge whose endpoint is not in the store is left out (and counted), so the store always loads.

Reading is tolerant (docs/formats.md): AR lines are parsed one by one, and a line that is not a JSON object, that a newer
brain wrote (a higher ``v``, an unknown kind) or that its schema refuses is left out and counted, never a crash; a field
this engine does not know is kept, and a rewrite (``write(..., replace=True)``) carries it, so a round trip loses
nothing. Writing is strict: what the engine writes is valid under its schema, and a record a newer brain wrote is
never overwritten ("written by brain > X: brain update").
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

from . import defaults, graph, paths, schema, secretscan

RECORDS_DIR = "records"
HEADERS = {
    "ddr": "# DDR (decision discussion record). Schema: brain/schemas/ddr.schema.json\n",
    "sr": "# SR (session record), computed from the transcript at zero token. "
          "Schema: brain/schemas/sr.schema.json\n",
}


AR_KINDS = tuple(schema.load("ar")["properties"]["kind"]["enum"])


class Bad(NamedTuple):
    """A record or an AR line :func:`load` leaves out: where, why, and whether a newer brain wrote it (a log line then
    is skipped and counted, a warning in read mode; anything else is an error)."""
    where: Path
    reason: str
    newer: bool = False


def record_path(root: Path, kind: str, rec: dict) -> Path:
    base = root / RECORDS_DIR / kind
    if kind == "ddr":
        return base / f"{rec['id']}.yaml"
    if kind == "sr":
        return base / rec["start"][:7] / f"{rec['id']}.yaml"
    return base / f"{rec['at'][:7]}.jsonl"


def _dump_yaml(rec: dict) -> str:
    yaml = graph._yaml()
    return yaml.safe_dump(rec, sort_keys=False, allow_unicode=True, width=116, default_flow_style=False)


def validate(kind: str, rec: dict, carry: frozenset[str] | set[str] = frozenset()) -> dict:
    """The record after the secret scan; SystemExit with the errors when it is invalid (strict: an unknown field is
    an error, except those in ``carry``, which a rewrite keeps from the file it replaces)."""
    clean, dropped = secretscan.clean(rec)
    if dropped:
        print(f"brain: {dropped} line(s) dropped by the secret scan in {clean.get('id')}")
    errors, warnings = schema.check(kind, clean, schema.STRICT, carry)
    for w in warnings:
        print(f"brain: warning: {w}")
    if errors:
        raise SystemExit(f"brain: invalid {kind.upper()} {clean.get('id')}:\n  " + "\n  ".join(errors))
    return clean


def _steps(kind: str, path: str) -> list[str | int]:
    """``ddr.options[0].note`` -> ['options', 0, 'note'] (a :func:`brain.schema.field_path`)."""
    return [int(i) if i else k for k, i in re.findall(r"\.([^.\[]+)|\[(\d+)\]", path[len(kind):])]


def keep_unknown(kind: str, old: dict, rec: dict) -> tuple[dict, frozenset[str]]:
    """(``rec`` with the fields of ``old`` this engine does not know put back where ``rec`` lacks them, their paths):
    a rewrite built afresh (an SR from its transcript, a DDR from a file) keeps a newer brain's fields."""
    carried = set()
    for path in schema.unknown_fields(kind, old):
        steps = _steps(kind, path)
        src, dst = old, rec
        for step in steps[:-1]:
            src = src[step] if isinstance(src, (dict, list)) else None
            ok = isinstance(dst, dict) and step in dst or isinstance(dst, list) and isinstance(step, int) \
                and step < len(dst)
            dst = dst[step] if ok else None
            if not isinstance(dst, (dict, list)):
                break
        last = steps[-1] if steps else None
        if isinstance(dst, dict) and isinstance(src, dict) and isinstance(last, str) and last in src:
            dst.setdefault(last, src[last])
            carried.add(path)
    return rec, frozenset(carried)


def ar_ids(root: Path) -> set[str]:
    """The ids of every AR line, a newer brain's included (so none is appended twice); a bad line is passed over."""
    ids = set()
    for f in (root / RECORDS_DIR / "ar").glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line) if line.strip() else None
            except (ValueError, RecursionError):
                continue
            if isinstance(rec, dict) and isinstance(rec.get("id"), str):
                ids.add(rec["id"])
    return ids


def parse_ar(line: str) -> tuple[dict | None, str, bool]:
    """(the AR, why it is left out, whether a newer brain wrote it) for one line; never an exception."""
    try:
        rec = json.loads(line)
    except (ValueError, RecursionError) as exc:
        return None, f"not a JSON line ({type(exc).__name__}: {str(exc)[:80]})", False
    if not isinstance(rec, dict):
        return None, f"ar: a record is a mapping, got {type(rec).__name__}", False
    refused = schema.newer("ar", rec.get("v"), schema.known_v("ar"))
    if refused:
        return None, f"{refused} (line skipped)", True
    kind = rec.get("kind")
    if isinstance(kind, str) and kind and kind not in AR_KINDS:
        return None, f"ar.kind: {kind!r} is a newer brain's kind (line skipped): brain update", True
    errors, _ = schema.validate("ar", rec, schema.READ)
    if errors:
        return None, "; ".join(errors), False
    return rec, "", False


def append_ars(root: Path, ars: list[dict], have: set[str] | None = None) -> list[dict]:
    """Validate and append the ARs whose id is not recorded yet (``have``: the recorded ids, updated); the ones
    written."""
    have = ar_ids(root) if have is None else have
    written = []
    for rec in ars:
        rec = validate("ar", rec)
        if rec["id"] in have:
            continue
        path = record_path(root, "ar", rec)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        have.add(rec["id"])
        written.append(rec)
    return written


def write(root: Path, kind: str, rec: dict, replace: bool = False) -> Path | None:
    """Validate and write one record; None when an AR with that id is already there. A rewrite keeps the fields of
    the file it replaces that this engine does not know, and never replaces a record a newer brain wrote."""
    carry: frozenset[str] = frozenset()
    if kind != "ar" and replace:
        try:
            old_path = record_path(root, kind, rec)
        except (KeyError, TypeError):
            old_path = None
        if old_path is not None and old_path.is_file():
            try:
                old = graph.load_yaml_file(old_path)
            except Exception:    # an unreadable file: the new record replaces it, nothing of it can be carried
                old = None
            if isinstance(old, dict):
                refused = schema.newer(kind, old.get("v"), schema.known_v(kind))
                if refused:
                    raise SystemExit(f"brain: {old_path.relative_to(root).as_posix()}: {refused}")
                rec, carry = keep_unknown(kind, old, rec)
    rec = validate(kind, rec, carry)
    path = record_path(root, kind, rec)
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "ar":
        if rec["id"] in ar_ids(root):
            return None
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
        return path
    if path.exists() and not replace:
        raise SystemExit(f"brain: {path.relative_to(root)} exists (use --replace to rewrite it)")
    path.write_text(HEADERS[kind] + _dump_yaml(rec), encoding="utf-8", newline="\n")
    return path


def load(root: Path, bad: list[Bad] | None = None) -> dict[str, list[tuple[Path, dict]]]:
    """The records that can be read, as they are (a field this engine does not know is kept). What is left out goes
    to ``bad``: a file or a line that is not a mapping, a DDR or SR a newer brain wrote (refused), an AR line
    :func:`parse_ar` leaves out (an AR line's place is ``<file>:<line>``)."""
    bad = [] if bad is None else bad
    out: dict[str, list[tuple[Path, dict]]] = {"ddr": [], "sr": [], "ar": []}
    base = root / RECORDS_DIR
    for kind, pattern in (("ddr", "*.yaml"), ("sr", "*/*.yaml")):
        for f in sorted((base / kind).glob(pattern)):
            try:
                rec = graph.load_yaml_file(f)
            except Exception as exc:   # a YAML error, a conflict marker: reported, the other records still load
                bad.append(Bad(f, f"not readable YAML ({type(exc).__name__})"))
                continue
            if not isinstance(rec, dict):
                bad.append(Bad(f, f"{kind}: a record is a mapping, got {type(rec).__name__}"))
                continue
            refused = schema.newer(kind, rec.get("v"), schema.known_v(kind))
            if refused:
                bad.append(Bad(f, refused))
                continue
            out[kind].append((f, rec))
    for f in sorted((base / "ar").glob("*.jsonl")):
        for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.strip():
                rec, why, newer = parse_ar(line)
                if rec is None:
                    bad.append(Bad(f.with_name(f"{f.name}:{i}"), why, newer))
                else:
                    out["ar"].append((f.with_name(f"{f.name}:{i}"), rec))
    return out


def check(root: Path, mode: str | None = None) -> tuple[list[str], list[str]]:
    """Every record valid, ids unique and matching their file, no line matching a secret pattern. ``mode``
    (default :func:`brain.schema.mode`): in read mode a field this engine does not know and an AR line a newer brain
    wrote are warnings; in strict mode (CI) they are errors."""
    mode = mode or schema.mode()
    errors, warnings = [], []
    seen: dict[str, Path] = {}
    bad: list[Bad] = []
    recs = load(root, bad)
    for b in bad:
        rel = b.where.relative_to(root).as_posix() if b.where.is_relative_to(root) else str(b.where)
        (warnings if b.newer and mode == schema.READ else errors).append(f"{rel}: {b.reason}")
    for kind, items in recs.items():
        for f, rec in items:
            rel = f.relative_to(root).as_posix() if f.is_relative_to(root) else str(f)
            e, w = schema.check(kind, rec, mode)
            if kind == "ddr" and isinstance(rec, dict):
                e = e + defaults.check(rec)   # the low-stakes mark where a default never decides
            errors += [f"{rel}: {x}" for x in e]
            warnings += [f"{rel}: {x}" for x in w]
            rid = (rec or {}).get("id") if isinstance(rec, dict) else None
            if rid in seen:
                errors.append(f"{rel}: duplicate id {rid} (also {seen[rid]})")
            elif rid:
                seen[rid] = rel
            if kind in ("ddr", "sr") and rid and f.stem != rid:
                errors.append(f"{rel}: file name must be {rid}.yaml")
    for f in sorted((root / RECORDS_DIR).rglob("*")):
        if f.is_file() and f.suffix in (".yaml", ".jsonl", ".json", ".md"):
            for line, name in secretscan.scan_lines(f.read_text(encoding="utf-8", errors="replace")):
                errors.append(f"{f.relative_to(root).as_posix()}:{line}: matches secret pattern {name}")
    return errors, warnings


# --- ledger -> repo ---

def ledger_records(kind: str, session: str = "", since: str = "") -> list[dict]:
    out = []
    for f in sorted(paths.ledger_dir().glob(f"{kind}-*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            owner = (rec.get("session") or {}).get("id") or (rec.get("asked") or {}).get("by")
            when = rec.get("at") or (rec.get("asked") or {}).get("at") or ""
            if (not session or owner == session) and (not since or when >= since):
                out.append(rec)
    return out


def import_ledger(root: Path, kinds=("ar", "ddr"), session: str = "", since: str = "") -> dict[str, int]:
    counts = {}
    for kind in kinds:
        n = 0
        for rec in ledger_records(kind, session, since):
            if kind == "ddr" and record_path(root, "ddr", rec).exists():
                continue
            if write(root, kind, rec) is not None:
                n += 1
        counts[kind] = n
    return counts


# --- records -> graph ---

def _title(text: str, n: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def graph_view(root: Path, store: Path) -> tuple[list[dict], list[dict], int]:
    """(nodes, edges, links left out) generated from the records (what :func:`load` leaves out is counted in a note:
    brain record check lists it)."""
    bad: list[Bad] = []
    recs = load(root, bad)
    if bad:
        print(f"brain: note: {len(bad)} record(s) or AR line(s) left out of the graph (brain record check lists them)",
              file=sys.stderr)
    known = set(graph.node_index(store).keys())
    for f in ("_generated_records.yaml",):
        for n in graph.load_yaml_list(store / "nodes" / f):
            known.discard(n.get("id"))
    nodes, edges = [], []
    by_session: dict[str, str] = {}
    for f, sr in recs["sr"]:
        by_session[sr["session_id"]] = sr["id"]
        props = {k: sr[k] for k in ("model", "effort", "branch", "start") if sr.get(k)}
        if sr.get("tokens"):
            props["tokens_out"] = sr["tokens"].get("output", 0)
        if sr.get("prs"):
            props["prs"] = ", ".join(f"{p['repo']}#{p['number']}" for p in sr["prs"])
        nodes.append({"id": sr["id"], "type": "Session", "status": sr["status"],
                      "title": _title(sr.get("summary") or sr.get("title") or sr["session_id"]),
                      "anchor": f"{f.relative_to(root).as_posix()}#{sr['id']}", "props": props})
    for f, d in recs["ddr"]:
        props = {"recommendation": (d.get("recommendation") or {}).get("option") or "none"}
        if d.get("kind", "decision") != "decision":  # an action or a permission (brain queue add): no options
            props = {"kind": d["kind"]}
        if d.get("answer"):
            props["answer"] = ", ".join(d["answer"].get("choices") or []) or _title(d["answer"].get("other", ""), 60)
        if d.get("blocking"):
            props["blocking"] = True
        nodes.append({"id": d["id"], "type": "DDR", "status": d["status"], "title": _title(d["title"]),
                      "anchor": f"{f.relative_to(root).as_posix()}#{d['id']}", "props": props})
    for f, a in recs["ar"]:
        what = {"commit": lambda: f"commit {a.get('sha', '')[:7]} {a.get('subject', '')}",
                "push": lambda: f"push {a.get('branch', '')}",
                "pr": lambda: f"PR #{a['pr']['number']} {a['pr'].get('action', '')}",
                "tag": lambda: f"tag {a.get('tag', '')}",
                "adr": lambda: f"ADR {a['adr'].get('title') or a['adr']['id']}",
                "ddr": lambda: f"DDR {a.get('ddr', '')}"}[a["kind"]]()
        props = {"kind": a["kind"], "at": a["at"], "model": a["session"].get("model", "")}
        if a.get("repo"):
            props["repo"] = a["repo"]
        nodes.append({"id": a["id"], "type": "Action", "status": "recorded",
                      "title": _title(f"{what} ({a['repo']})" if a.get("repo") else what),
                      "anchor": f"{RECORDS_DIR}/ar/{f.name.split(':')[0]}#{a['id']}",
                      "props": {k: v for k, v in props.items() if v}})
    ids = known | {n["id"] for n in nodes}
    left_out = 0

    def link(src: str, dst: str, etype: str) -> None:
        nonlocal left_out
        if src in ids and dst in ids and src != dst:
            edges.append({"from": src, "to": dst, "type": etype})
        else:
            left_out += 1

    for _, sr in recs["sr"]:
        for item in sr.get("items", []):
            link(sr["id"], item, "touches")
    for _, d in recs["ddr"]:
        asker = (d.get("asked") or {}).get("by")
        links = d.get("links") or {}
        session = links.get("session") or by_session.get(asker or "")
        if session:
            link(d["id"], session, "raised_by")
        for adr in links.get("adrs", []):
            link(d["id"], adr, "answered_in")
        for x in links.get("items", []) + links.get("specs", []):
            link(d["id"], x, "about")
    for _, a in recs["ar"]:
        session = by_session.get(a["session"]["id"])
        if session:
            link(a["id"], session, "produced_by")
            if a["kind"] == "adr":
                link(a["adr"]["id"], session, "produced_by")
        for item in a.get("items", []):
            link(a["id"], item, "touches")
    seen, unique = set(), []
    for e in edges:  # one edge per node pair (research_graph keeps a DiGraph)
        if (e["from"], e["to"]) not in seen:
            seen.add((e["from"], e["to"]))
            unique.append(e)
    return nodes, unique, left_out


GRAPH_FILES = ("nodes/_generated_records.yaml", "edges/_generated_records.yaml")   # relative to the store


def _graph_texts(root: Path, store: Path) -> tuple[str, str, int, int, int]:
    """(the nodes file's text, the edges file's, the counts of nodes, edges and links left out)."""
    nodes, edges, left_out = graph_view(root, store)
    head = ("# GENERATED by `brain sync` from records/ (DDR, SR, AR). Do not edit: change the records, then run "
            "brain sync.\n")
    return (head + "".join(graph.render_node(n) for n in nodes) if nodes else head + "[]\n",
            head + "".join(graph.render_edge(e) for e in edges) if edges else head + "[]\n",
            len(nodes), len(edges), left_out)


def write_graph(root: Path, store: Path) -> tuple[int, int, int]:
    nodes, edges, n, e, left_out = _graph_texts(root, store)
    (store / "nodes" / "_generated_records.yaml").write_text(nodes, encoding="utf-8", newline="\n")
    (store / "edges").mkdir(exist_ok=True)
    (store / "edges" / "_generated_records.yaml").write_text(edges, encoding="utf-8", newline="\n")
    return n, e, left_out


def graph_stale(root: Path, store: Path) -> list[str]:
    """The records' graph files (relative to the store) that exist and differ from a derivation now (brain check on
    the default branch: brain.views)."""
    nodes, edges, *_ = _graph_texts(root, store)
    out = []
    for rel, text in zip(GRAPH_FILES, (nodes, edges), strict=True):
        f = store / rel
        if f.is_file() and f.read_text(encoding="utf-8").replace("\r\n", "\n") != text:
            out.append(rel)
    return out
