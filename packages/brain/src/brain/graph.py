"""Token-free edits of a research_graph store (the graph engine's YAML format): ``brain item add|set|close``, and
the runner of the ``research_graph`` engine for ``sync``, ``check`` and ``kanban``.

Edits are textual and local: a new node is appended at the end of its file, a changed node's block is re-rendered
in place, an edge is appended at the end of its edges file. Nothing else moves, so comments and order survive, and a
file keeps its line endings (CRLF checkouts). Each edit re-parses the file and refuses to write when anything but the
target node would change.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import traceback
from datetime import date
from pathlib import Path

from . import notes, paths

GENERATED_PREFIX = "_generated_"
NODE_KEYS = ("id", "type", "status", "title", "level", "repo", "anchor", "props")
_PLAIN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-/]*$")
_RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "y", "n"}
_NODE_START_RE = re.compile(r"^- \{id:\s*([^,\s}]+)")
_EMPTY_FLOW_RE = re.compile(r"(?m)^\[\][ \t]*\n?")


class GraphError(Exception):
    pass


def _yaml():
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit("brain: this command needs PyYAML (pip install pyyaml)") from exc
    return yaml


def load_yaml(text: str):
    """The data of a YAML text, through libyaml when PyYAML has it (research_graph.yamlio: the one helper of every
    load, wi-brain-yaml-fast-load)."""
    _yaml()
    from research_graph import yamlio

    return yamlio.loads(text)


def load_yaml_file(path: Path):
    """The data of the YAML file ``path``, through libyaml and the per-process memo keyed by (path, size, mtime_ns):
    a fresh copy on each read, so the caller may change it (research_graph.yamlio)."""
    _yaml()
    from research_graph import yamlio

    return yamlio.load(path)


def load_yaml_all(text: str) -> list:
    """The documents of a multi-document YAML text, through libyaml."""
    y = _yaml()
    from research_graph import yamlio

    return list(y.load_all(text, Loader=yamlio.LOADER))


def fmt(value) -> str:
    """A YAML flow scalar, list or mapping: plain when unambiguous, else double-quoted (JSON escapes)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if value is None:
        return "null"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(fmt(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{fmt(k)}: {fmt(v)}" for k, v in value.items()) + "}"
    s = str(value)
    if _PLAIN_RE.match(s) and s.lower() not in _RESERVED:
        return s
    return json.dumps(s, ensure_ascii=False)


def render_node(node: dict, width: int = 118) -> str:
    """The node as the stores write it: id, type and status first, then title, repo, anchor and props on their
    lines."""
    head = [f"{k}: {fmt(node[k])}" for k in ("id", "type", "status") if k in node]
    rest = [k for k in NODE_KEYS[3:] if k in node] + [k for k in node if k not in NODE_KEYS]
    if not rest:
        return "- {" + ", ".join(head) + "}\n"
    lines = ["- {" + ", ".join(head) + ","]
    for i, k in enumerate(rest):
        end = "}" if i == len(rest) - 1 else ","
        v = node[k]
        if k == "props" and isinstance(v, dict) and v:
            parts = [f"{fmt(pk)}: {fmt(pv)}" for pk, pv in v.items()]
            line, indent = "   props: {", " " * 11
            out = []
            for j, p in enumerate(parts):
                piece = p + ("}" if j == len(parts) - 1 else ", ")
                if len(line) + len(piece) > width and line.strip() not in ("props: {",):
                    out.append(line.rstrip())
                    line = indent
                line += piece
            out.append(line + end)
            lines.extend(out)
        else:
            lines.append(f"   {k}: {fmt(v)}{end}")
    return "\n".join(lines) + "\n"


def render_edge(edge: dict) -> str:
    return "- {" + ", ".join(f"{k}: {fmt(edge[k])}" for k in ("from", "to", "type", "props") if edge.get(k)) + "}\n"


def load_yaml_list(path: Path) -> list:
    data = load_yaml_file(path) if path.exists() else None
    return data if isinstance(data, list) else []


def load_schema(store: Path) -> dict:
    return load_yaml_file(store / "schema.yaml") or {}


def node_index(store: Path, generated: bool = True) -> dict[str, tuple[Path, dict]]:
    out: dict[str, tuple[Path, dict]] = {}
    for f in sorted((store / "nodes").glob("*.yaml")):
        if not generated and f.name.startswith(GENERATED_PREFIX):
            continue
        for n in load_yaml_list(f):
            if isinstance(n, dict) and n.get("id"):
                out[str(n["id"])] = (f, n)
    return out


def _block(lines: list[str], nid: str) -> tuple[int, int]:
    """Line span [start, end) of a node's block: its ``- {id: <nid>`` line and the indented lines after it."""
    for i, line in enumerate(lines):
        m = _NODE_START_RE.match(line)
        if m and m.group(1) == nid:
            j = i + 1
            while j < len(lines) and lines[j].startswith(" ") and lines[j].strip():
                j += 1
            return i, j
    raise GraphError(f"{nid}: no '- {{id: {nid}, ...' block found (only flow-style nodes can be edited)")


def _read(path: Path) -> tuple[str, str]:
    return notes.read(path) if path.exists() else ("", "\n")


def _open_list(text: str) -> str:
    """A list file's text, ready for one more block entry: an empty flow list (``[]`` on its own line, as research_graph
    init writes an empty layer) is taken out, the comments kept."""
    if _EMPTY_FLOW_RE.search(text) and (load_yaml(text) or []) == []:
        text = _EMPTY_FLOW_RE.sub("", text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def _write_checked(path: Path, text: str, expect: list, nl: str = "\n") -> None:
    got = load_yaml(text)
    if got != expect:
        raise GraphError(f"{path}: the edit would change more than the target node; nothing written")
    path.parent.mkdir(parents=True, exist_ok=True)   # a layer file of its own (edges/decisions.yaml) may be the first
    notes.write(path, text, nl)


def _statuses(store: Path, node_type: str) -> set[str]:
    schema = load_schema(store)
    by_type = schema.get("status_by_type") or {}
    return set(by_type.get(node_type) or schema.get("statuses") or [])


def _check_status(store: Path, node: dict) -> None:
    allowed = _statuses(store, node.get("type", ""))
    if node.get("status") not in allowed:
        raise GraphError(f"{node['id']}: status {node.get('status')!r} not allowed for {node.get('type')} "
                         f"({', '.join(sorted(allowed))})")


def append_edges(store: Path, edges: list[dict], file: str = "edges/work.yaml", note: str = "") -> None:
    if not edges:
        return
    f = store / file
    text, nl = _read(f)
    before = load_yaml_list(f)
    text = _open_list(text)
    block = (f"\n# {note}\n" if note else "\n") + "".join(render_edge(e) for e in edges)
    _write_checked(f, text + block, before + edges, nl)


def add_item(store: Path, nid: str, title: str, *, node_type: str = "WorkItem", status: str = "todo",
             props: dict | None = None, spec: str = "", after: list[str] | None = None, milestone: str = "",
             adr: str = "", anchor: str = "", file: str = "nodes/work.yaml", edges_file: str = "edges/work.yaml",
             today: str | None = None) -> dict:
    index = node_index(store)
    if nid in index:
        raise GraphError(f"{nid}: already exists in {index[nid][0].name}")
    schema = load_schema(store)
    if node_type not in (schema.get("node_types") or []):
        raise GraphError(f"{node_type}: not a node type of {store / 'schema.yaml'}")
    node: dict = {"id": nid, "type": node_type, "status": status, "title": title}
    if anchor:
        node["anchor"] = anchor
    if props:
        node["props"] = props
    _check_status(store, node)
    edges = []
    for target, etype in ([(spec, "specified_by")] + [(a, "depends_on") for a in after or []]
                          + [(milestone, "part_of"), (adr, "decided_by")]):
        if not target:
            continue
        if target not in index:
            raise GraphError(f"{target}: unknown node (edge {etype} from {nid})")
        edges.append({"from": nid, "to": target, "type": etype})
    f = store / file
    text, nl = _read(f)
    before = load_yaml_list(f)
    text = _open_list(text)
    _write_checked(f, text + render_node(node), before + [node], nl)
    append_edges(store, edges, edges_file, f"{today or date.today().isoformat()}: {nid} (brain item add)")
    return node


def _edit(store: Path, nid: str, change) -> dict:
    index = node_index(store, generated=False)
    if nid not in index:
        raise GraphError(f"{nid}: unknown node")
    f, node = index[nid]
    new = json.loads(json.dumps(node))
    change(new)
    _check_status(store, new)
    text, nl = _read(f)
    lines = text.splitlines(keepends=True)
    start, end = _block([ln.rstrip("\r\n") for ln in lines], nid)
    before = load_yaml_list(f)
    expect = [new if isinstance(n, dict) and n.get("id") == nid else n for n in before]
    _write_checked(f, "".join(lines[:start]) + render_node(new) + "".join(lines[end:]), expect, nl)
    return new


def link(store: Path, src: str, etype: str, dst: str, edges_file: str = "edges/work.yaml",
         today: str | None = None, pending: set[str] | frozenset = frozenset(), via: str = "brain item link",
         props: dict | None = None) -> dict:
    """Append one edge between two existing nodes, unless the pair is already linked (one edge per pair).
    ``pending``: ids the next sync generates (an ADR just appended to its log), accepted as endpoints. ``props``: the
    edge's props (an enforced_by edge's scope)."""
    index = node_index(store)
    for nid in (src, dst):
        if nid not in index and nid not in pending:
            raise GraphError(f"{nid}: unknown node")
    if etype not in (load_schema(store).get("edge_types") or []):
        raise GraphError(f"{etype}: not an edge type of {store / 'schema.yaml'}")
    files = [store / "edges.yaml", *sorted((store / "edges").glob("*.yaml"))]
    for f in files:
        for e in load_yaml_list(f):
            if isinstance(e, dict) and (e.get("from"), e.get("to")) == (src, dst):
                raise GraphError(f"{src} -> {dst}: already linked ({e.get('type')}) in {f.name}")
    edge = {"from": src, "to": dst, "type": etype}
    if props:
        edge["props"] = dict(props)
    append_edges(store, [edge], edges_file, f"{today or date.today().isoformat()}: {src} ({via})")
    return edge


def unlink(store: Path, src: str, dst: str) -> tuple[dict, Path]:
    """Remove the curated edge between two nodes (one edge per pair; a generated file is never edited), and the
    ``# <day>: <id> (<command>)`` line above it when nothing else is left under that line. (edge, its file)."""
    files = [store / "edges.yaml", *sorted(f for f in (store / "edges").glob("*.yaml")
                                           if not f.name.startswith("_generated"))]
    for f in files:
        before = load_yaml_list(f)
        found = [e for e in before if isinstance(e, dict) and (e.get("from"), e.get("to")) == (src, dst)]
        if not found:
            continue
        text, nl = _read(f)
        lines = text.split("\n")
        hit = next(i for i, line in enumerate(lines) if line.lstrip().startswith("- {")
                   and (load_yaml(line) or [{}])[0] in found)
        start, end = hit, hit + 1
        if hit and lines[hit - 1].startswith("# ") and (end >= len(lines) or not lines[end].lstrip().startswith("- ")):
            start = hit - 1  # its note, left alone
            if start and not lines[start - 1].strip():
                start -= 1
        _write_checked(f, "\n".join(lines[:start] + lines[end:]), [e for e in before if e is not found[0]], nl)
        return found[0], f
    raise GraphError(f"{src} -> {dst}: no curated edge")


def set_item(store: Path, nid: str, assignments: list[str]) -> dict:
    """``key=value`` pairs: status, title, anchor and type set the node; ``props.<k>`` or any other key sets a
    prop; an empty value removes the prop."""
    def change(node: dict) -> None:
        for a in assignments:
            if "=" not in a:
                raise GraphError(f"{a!r}: expected key=value")
            key, value = a.split("=", 1)
            key = key.strip()
            if key in ("status", "title", "anchor", "type"):
                node[key] = value
                continue
            key = key[6:] if key.startswith("props.") else key
            props = node.setdefault("props", {})
            if value == "":
                props.pop(key, None)
            else:
                props[key] = value
            if not props:
                node.pop("props")
    return _edit(store, nid, change)


def close_item(store: Path, nid: str, pr: str, outcome: str = "", today: str | None = None,
               status: str = "done") -> dict:
    def change(node: dict) -> None:
        node["status"] = status
        props = node.setdefault("props", {})
        if pr:
            props["pr"] = pr
        props["done" if status == "done" else status] = f"{today or date.today().isoformat()} {outcome}".strip()
    return _edit(store, nid, change)


# --- research_graph, the graph engine ---
# brain imports the research_graph package (installed into its venv from the pin in pyproject.toml) and runs its CLI
# in this process. Until install.ps1 -Apply has installed it, or when $BRAIN_GRAPH_PYTHON is set, it runs the legacy
# copy (LEGACY, in a registered project) in another Python, as it did before the package existed.

LEGACY = "quant_lab.research_graph"
_hinted = False


def engine():
    """The engine's CLI module when this Python has it and $BRAIN_GRAPH_PYTHON is not set, else None."""
    if os.environ.get("BRAIN_GRAPH_PYTHON"):
        return None
    try:
        from research_graph import cli
    except ImportError:
        return None
    return cli


@contextlib.contextmanager
def _cwd(path: Path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def _run_engine(cli, root: Path, argv: list[str]) -> int:
    """The CLI's exit code, run from ``root`` as the subprocess was; a crash is printed and counts as 1."""
    try:
        with _cwd(root):
            return cli.main(argv) or 0
    except SystemExit as exc:  # argparse
        return exc.code if isinstance(exc.code, int) else 1
    except Exception:
        traceback.print_exc()
        return 1


def _legacy_cmd(root: Path) -> list[str]:
    global _hinted
    if not _hinted and not os.environ.get("BRAIN_GRAPH_PYTHON"):
        print("brain: the research_graph package is not in brain's venv (install.ps1 -Apply installs it); running "
              f"the legacy copy ({LEGACY})", file=sys.stderr)
        _hinted = True
    return [graph_python(root), "-m", LEGACY]


def _venv_python(base: Path) -> Path | None:
    for rel in ("Scripts/python.exe", "bin/python"):
        p = base / ".venv" / rel
        if p.exists():
            return p
    return None


def graph_python(root: Path) -> str:
    """Python for the fallback, one that can import :data:`LEGACY`: $BRAIN_GRAPH_PYTHON, else the ``.venv`` of the
    first registered project that holds that package (brain.projects: relative roots from the main checkout when this
    is a worktree), else this Python."""
    env = os.environ.get("BRAIN_GRAPH_PYTHON")
    if env:
        return env
    from . import projects  # here: brain.projects imports this module
    for proj in projects.load(root).values():
        p = _venv_python(proj.root) if (proj.root / LEGACY.replace(".", "/")).is_dir() else None
        if p:
            return str(p)
    return sys.executable


def research_graph_json(root: Path, store: Path, *args: str):
    """The parsed ``--json`` output of a research_graph subcommand, or None when it cannot run (its error on
    stderr)."""
    argv = ["--store", str(store), "--repo-root", str(root), *args, "--json"]
    cli = engine()
    if cli is not None:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = _run_engine(cli, root, argv)
        stdout, stderr = out.getvalue(), err.getvalue()
    else:
        try:
            res = subprocess.run(_legacy_cmd(root) + argv, cwd=root, capture_output=True, text=True,
                                 encoding="utf-8", timeout=120, env=dict(os.environ, PYTHONIOENCODING="utf-8"),
                                 stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"brain: research_graph {' '.join(args)}: {exc}", file=sys.stderr)
            return None
        code, stdout, stderr = res.returncode, res.stdout, res.stderr
    if code:
        print(f"brain: research_graph {' '.join(args)} failed: {stderr.strip()[-300:]}", file=sys.stderr)
        return None
    try:
        return json.loads(stdout)
    except ValueError:
        print(f"brain: research_graph {' '.join(args)}: no JSON in its output", file=sys.stderr)
        return None


def research_graph(root: Path, store: Path, *args: str) -> int:
    """research_graph's exit code for ``args`` on ``store``, run from ``root``. ``args`` may start with the store's
    layout options, before the subcommand (brain.projects.layout: ``--views``, ``--decisions``, ``--no-decisions``)."""
    argv = ["--store", str(store), "--repo-root", str(root), *args]
    print("$ research_graph " + " ".join(args), flush=True)
    cli = engine()
    if cli is not None:
        return _run_engine(cli, root, argv)
    return subprocess.run(_legacy_cmd(root) + argv, cwd=root).returncode
