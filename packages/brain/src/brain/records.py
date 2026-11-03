"""Records in the brain repo: ``records/ddr/<id>.yaml``, ``records/sr/<yyyy-mm>/<id>.yaml``, ``records/ar/<yyyy-mm>.jsonl``.

Every write is secret-scanned and validated first. AR files are append-only. ``graph()`` turns the records into
generated graph nodes and edges (``nodes/_generated_records.yaml``, ``edges/_generated_records.yaml``):
- Session (an SR), DDR, Action (an AR) nodes;
- ``raised_by`` DDR -> Session, ``answered_in`` DDR -> ADR, ``about`` DDR -> WorkItem / Milestone / Spec,
  ``produced_by`` Action or ADR -> Session, ``touches`` Session or Action -> WorkItem / Milestone / Spec.
An edge whose endpoint is not in the store is left out (and counted), so the store always loads.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import defaults, graph, paths, schema, secretscan

RECORDS_DIR = "records"
HEADERS = {
    "ddr": "# DDR (decision discussion record). Schema: brain/schemas/ddr.schema.json\n",
    "sr": "# SR (session record), computed from the transcript at zero token. "
          "Schema: brain/schemas/sr.schema.json\n",
}


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


def validate(kind: str, rec: dict) -> dict:
    """The record after the secret scan; SystemExit with the errors when it is invalid."""
    clean, dropped = secretscan.clean(rec)
    if dropped:
        print(f"brain: {dropped} line(s) dropped by the secret scan in {clean.get('id')}")
    errors, warnings = schema.check(kind, clean)
    for w in warnings:
        print(f"brain: warning: {w}")
    if errors:
        raise SystemExit(f"brain: invalid {kind.upper()} {clean.get('id')}:\n  " + "\n  ".join(errors))
    return clean


def ar_ids(root: Path) -> set[str]:
    ids = set()
    for f in (root / RECORDS_DIR / "ar").glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                ids.add(json.loads(line)["id"])
    return ids


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
    """Validate and write one record; None when an AR with that id is already there."""
    rec = validate(kind, rec)
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


def load(root: Path) -> dict[str, list[tuple[Path, dict]]]:
    out: dict[str, list[tuple[Path, dict]]] = {"ddr": [], "sr": [], "ar": []}
    base = root / RECORDS_DIR
    for f in sorted((base / "ddr").glob("*.yaml")):
        out["ddr"].append((f, graph.load_yaml_file(f)))
    for f in sorted((base / "sr").glob("*/*.yaml")):
        out["sr"].append((f, graph.load_yaml_file(f)))
    for f in sorted((base / "ar").glob("*.jsonl")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                out["ar"].append((f.with_name(f"{f.name}:{i}"), json.loads(line)))
    return out


def check(root: Path) -> tuple[list[str], list[str]]:
    """Every record valid, ids unique and matching their file, no line matching a secret pattern."""
    errors, warnings = [], []
    seen: dict[str, Path] = {}
    for kind, items in load(root).items():
        for f, rec in items:
            rel = f.relative_to(root).as_posix() if f.is_relative_to(root) else str(f)
            e, w = schema.check(kind, rec)
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
            for line, name in secretscan.scan_lines(f.read_text(encoding="utf-8")):
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
    """(nodes, edges, links left out) generated from the records."""
    recs = load(root)
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


def write_graph(root: Path, store: Path) -> tuple[int, int, int]:
    nodes, edges, left_out = graph_view(root, store)
    head = ("# GENERATED by `brain sync` from records/ (DDR, SR, AR). Do not edit: change the records, then run "
            "brain sync.\n")
    (store / "nodes" / "_generated_records.yaml").write_text(
        head + "".join(graph.render_node(n) for n in nodes) if nodes else head + "[]\n", encoding="utf-8",
        newline="\n")
    (store / "edges").mkdir(exist_ok=True)
    (store / "edges" / "_generated_records.yaml").write_text(
        head + "".join(graph.render_edge(e) for e in edges) if edges else head + "[]\n", encoding="utf-8",
        newline="\n")
    return len(nodes), len(edges), left_out
