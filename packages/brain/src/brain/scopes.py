"""The scope tree as data (wi-brain-scope-tree, spec-brain-scope-tree §3.1, §3.2, §3.13).

One kind of node, one parent each, Global at the root (the brain itself). A node with a root of its own (a project of
the registry) is a **project**; one without is a **container** (a sphere, an organisation, a unit, a folder). Where
each lives:

- a project's place is the ``parent:`` key of its entry in ``projects.yaml``; without it, it sits under Global;
- the containers are declared once in ``scopes.yaml``, beside the registry: ``$BRAIN_SCOPES`` names another file,
  else config.json's ``scopes`` (relative to it), else ``scopes.yaml`` beside config.json::

    v: 1
    scopes:
      pro:     {type: sphere, title: Professional}
      acme:    {type: company, title: ACME SA, parent: pro, classes: {floor: confidential}}
      finance: {type: unit, title: Finance, parent: acme, also_under: [ops]}

  ``type`` (required), ``title``, ``parent`` (default: global) and ``status`` (``active``, the default, or
  ``archived``); ``classes: {floor: <class>}`` (brain classes, brain vault read it); ``vault: {recipients}``
  (brain vault); ``lifecycle`` (spec-brain-product-lifecycle); ``also_under``: shortcuts shown under other nodes,
  for display only (SCOPE-5: they inherit nothing and count once). The settings the inheritance resolver will read
  (:data:`RESERVED`: rules, notify, quiet, capabilities, never, budgets, members, language) are accepted as declared
  and not read yet (wi-brain-scope-inheritance);
- the type catalogue is :data:`TYPES`, renamed or extended per brain by config.json's ``scope_types`` (SCOPE-4):
  ``{id: {en, fr, children}}``; ids are stable, labels are for display, filters use the ids.

With no ``scopes.yaml`` and no ``parent:``, every project sits flat under Global, as before: nothing changes
(:attr:`Tree.present` is False). :func:`check` (``brain check --all`` and a brain's own root) refuses an unknown
parent, a cycle, an id used twice across projects and containers, an unknown type or one its parent's type does not
accept, a class floor under an ancestor's (a guard only tightens) or not a class; it warns past :data:`DEPTH_WARN`
levels under Global. ``brain scopes`` prints the tree; ``--scope <ref>`` on the views selects a node's subtree
(:func:`select`); ``brain sync`` writes the generated view ``notes/scopes_graph.md`` (:func:`write_view`).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import config, graph, projects, schema

FILE = "scopes.yaml"
ENV = "BRAIN_SCOPES"
GLOBAL = "global"
VIEW = "notes/scopes_graph.md"
DEPTH_WARN = 6
STATUSES = ("active", "archived")
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TYPE_ID = re.compile(r"^[a-z][a-z0-9-]*$")
# a container's keys: its place and its own settings (spec 3.1, 3.5); RESERVED is read by wi-brain-scope-inheritance
NODE_KEYS = {"type", "title", "parent", "status", "classes", "vault", "lifecycle", "also_under"}
RESERVED = {"rules", "notify", "quiet", "capabilities", "never", "budgets", "members", "language"}
TYPE_KEYS = {"en", "fr", "children"}
# The default catalogue (spec 3.2): id -> its labels; config.json scope_types renames or adds (SCOPE-4).
TYPES: dict[str, dict] = {
    "sphere": {"en": "Sphere", "fr": "Sphère"},
    "company": {"en": "Company", "fr": "Entreprise"},
    "institution": {"en": "Institution", "fr": "Institution"},
    "government": {"en": "Government", "fr": "Administration"},
    "association": {"en": "Association", "fr": "Association"},
    "unit": {"en": "Unit", "fr": "Service"},
    "office": {"en": "Office", "fr": "Bureau"},
    "team": {"en": "Team", "fr": "Équipe"},
    "folder": {"en": "Folder", "fr": "Dossier"},
    "project": {"en": "Project", "fr": "Projet"},
    "tenant": {"en": "Tenant", "fr": "Locataire"},
}
LANGS = ("en", "fr")
KINDS = ("container", "project", "read", "mount")   # read: a read-only project; mount: a tenant (another brain)


class ScopeError(ValueError):
    """A reference that names no node (brain exits 2)."""


@dataclass
class Node:
    id: str
    type: str
    kind: str                       # container, project, read (a read-only project) or mount (a tenant)
    parent: str = GLOBAL
    title: str = ""
    status: str = "active"
    data: dict = field(default_factory=dict)   # the node's mapping as declared (a container's, or the registry entry)

    @property
    def is_project(self) -> bool:
        return self.kind != "container"


@dataclass
class Tree:
    nodes: dict[str, Node] = field(default_factory=dict)   # every node but Global, in declaration order
    types: dict[str, dict] = field(default_factory=dict)
    file: Path | None = None
    problems: list[str] = field(default_factory=list)      # what made the file unreadable (check() reports it)

    @property
    def present(self) -> bool:
        """A tree is declared: a scopes.yaml, or a parent: in the registry. Without one, every project is flat."""
        return self.file is not None or any(n.parent != GLOBAL for n in self.nodes.values())

    def chain(self, nid: str) -> list[str]:
        """The ancestors of ``nid``, nearest first, up to (not including) Global; a cycle or an unknown parent ends
        it (check() reports both)."""
        out: list[str] = []
        node = self.nodes.get(nid)
        while node is not None and node.parent != GLOBAL and node.parent not in out and node.parent != nid:
            out.append(node.parent)
            node = self.nodes.get(node.parent)
        return out

    def depth(self, nid: str) -> int:
        return 0 if nid == GLOBAL else len(self.chain(nid)) + 1

    def children(self, nid: str, archived: bool = True) -> list[str]:
        """The direct children of ``nid`` (Global's: every node whose parent is global or unknown), containers
        first, in declaration order."""
        def under(n: Node) -> bool:
            if nid == GLOBAL:
                return n.parent == GLOBAL or n.parent not in self.nodes or self._cyclic(n.id)
            return n.parent == nid and not self._cyclic(n.id)
        kids = [n for n in self.nodes.values() if under(n) and (archived or n.status != "archived")]
        return [n.id for n in sorted(kids, key=lambda n: n.is_project)]

    def _cyclic(self, nid: str) -> bool:
        seen = {nid}
        node = self.nodes.get(nid)
        while node is not None and node.parent != GLOBAL:
            if node.parent in seen:
                return True
            seen.add(node.parent)
            node = self.nodes.get(node.parent)
        return False

    def subtree(self, nid: str, archived: bool = True) -> list[str]:
        """``nid`` and every node under it, depth first (Global itself is not a node)."""
        out = [] if nid == GLOBAL else [nid]
        for kid in self.children(nid, archived):
            out += self.subtree(kid, archived)
        return out

    def path(self, nid: str) -> str:
        """The node's path of ids from Global (``pro/acme/finance``): for display; commands keep the id."""
        return GLOBAL if nid == GLOBAL else "/".join([*reversed(self.chain(nid)), nid])

    def label(self, type_id: str, lang: str = "en") -> str:
        t = self.types.get(type_id) or {}
        return str(t.get(lang) or t.get("en") or type_id)

    def projects_under(self, nid: str) -> list[str]:
        """The projects in the subtree of ``nid`` (itself when it is one), depth first; shortcuts are not followed."""
        return [x for x in self.subtree(nid) if self.nodes[x].is_project]


def scopes_file(cfg: config.Config) -> Path | None:
    """$BRAIN_SCOPES, else config.json's scopes, else scopes.yaml beside config.json; None when there is none."""
    env = os.environ.get(ENV)
    if env:
        f = Path(env).expanduser()
    elif isinstance(cfg.data.get("scopes"), str) and cfg.data["scopes"]:
        f = cfg.root / cfg.data["scopes"]
    else:
        f = cfg.root / FILE
    return f if f.is_file() else None


def raw(cfg: config.Config) -> tuple[dict, Path | None, list[str]]:
    """(scopes.yaml as declared, its file, why it cannot be read); ({}, None, []) without one."""
    f = scopes_file(cfg)
    if not f:
        return {}, None, []
    try:
        data = graph.load_yaml_file(f)
    except Exception as exc:  # noqa: BLE001 - a broken file is reported, never raised: another command still runs
        return {}, f, [f"{f.name}: not readable YAML ({exc})"]
    data = {} if data is None else data
    if not isinstance(data, dict):
        return {}, f, [f"{f.name}: a mapping with v and scopes, got {type(data).__name__}"]
    return data, f, []


def nodes_of(cfg: config.Config) -> dict[str, dict]:
    """{container id: its mapping} from scopes.yaml, {} without one (brain classes and brain vault read it)."""
    data, _, _ = raw(cfg)
    nodes = data.get("scopes")
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in nodes.items()} if isinstance(nodes, dict) else {}


def types_of(cfg: config.Config) -> dict[str, dict]:
    """The type catalogue: :data:`TYPES`, each entry of config.json scope_types merged over it (a rename keeps the
    id), new ids added."""
    out = {k: dict(v) for k, v in TYPES.items()}
    given = cfg.data.get("scope_types")
    for tid, spec in (given.items() if isinstance(given, dict) else []):
        if isinstance(spec, dict):
            out[str(tid)] = {**out.get(str(tid), {}), **spec}
    return out


def load(root: Path | None = None, cfg: config.Config | None = None) -> Tree:
    """The tree: the registry's entries as projects (a tenant mount and a read-only project are nodes too: they
    have a place, never a store the brain reads), then scopes.yaml's containers. Loading never fails."""
    cfg = cfg or config.load(root)
    data, f, problems = raw(cfg)
    tree = Tree(types=types_of(cfg), file=f, problems=problems)
    reg_root = root if root is not None else cfg.root
    try:
        reg = projects.raw(reg_root)
    except Exception:  # noqa: BLE001 - a broken registry is projects.check's to report
        reg = {}
    for name, entry in reg.items():
        if not isinstance(entry, dict) and entry is not None:
            continue
        entry = entry or {}
        kind = "mount" if projects.is_mount(entry) else "read" if projects.is_read_only(entry) else "project"
        parent = entry.get("parent")
        title = entry.get("title")
        tree.nodes[str(name)] = Node(str(name), "tenant" if kind == "mount" else "project", kind,
                                     parent if isinstance(parent, str) and parent else GLOBAL,
                                     title if isinstance(title, str) else "", data=entry)
    declared = data.get("scopes")
    for nid, spec in (declared.items() if isinstance(declared, dict) else []):
        nid = str(nid)
        if nid in tree.nodes or nid == GLOBAL:
            continue   # check() reports the id used twice; the project keeps it
        spec = spec if isinstance(spec, dict) else {}
        parent, title, status = spec.get("parent"), spec.get("title"), spec.get("status")
        tree.nodes[nid] = Node(nid, str(spec.get("type") or ""), "container",
                               parent if isinstance(parent, str) and parent else GLOBAL,
                               title if isinstance(title, str) else "",
                               status if status in STATUSES else "active", spec)
    return tree


# --- the check (brain check --all, a brain's own root) ---

def check(root: Path | None = None, cfg: config.Config | None = None) -> tuple[list[str], list[str]]:
    """(errors, warnings) of the scope tree; ([], []) for a brain without one (flat under Global)."""
    cfg = cfg or config.load(root)
    tree = load(root, cfg)
    errors = list(tree.problems)
    warnings: list[str] = []
    errors += _types_errors(cfg, tree)
    data, f, _ = raw(cfg)
    if f is not None and not tree.problems:
        errors += _file_errors(data, f, tree)
    for n in tree.nodes.values():
        where = f"scope {n.id}" if n.kind == "container" else f"project {n.id}"
        if n.kind != "container" and "parent" in n.data and not (isinstance(n.data["parent"], str)
                                                               and n.data["parent"]):
            errors.append(f"{where}: parent is a node id (a container of {FILE} or a project), or global")
        if n.parent != GLOBAL and n.parent not in tree.nodes:
            errors.append(f"{where}: its parent {n.parent!r} is no node (a container of {FILE}, a project, or global)")
        elif n.parent != GLOBAL and tree._cyclic(n.id):
            errors.append(f"{where}: its parents loop back to it ({' -> '.join([n.id, *tree.chain(n.id), n.id])})")
        elif n.parent != GLOBAL:
            errors += _accepts(tree, n, where)
        depth = tree.depth(n.id)
        if depth > DEPTH_WARN and not tree._cyclic(n.id):
            warnings.append(f"{where} is {depth} levels under global (more than {DEPTH_WARN}): each level that "
                            "carries rules costs every session of its subtree")
        if n.status == "active" and n.parent in tree.nodes and tree.nodes[n.parent].status == "archived":
            warnings.append(f"{where} is active under the archived {n.parent}")
    errors += _floor_errors(tree)
    return errors, warnings


def _types_errors(cfg: config.Config, tree: Tree) -> list[str]:
    given = cfg.data.get("scope_types")
    if given is None:
        return []
    if not isinstance(given, dict):
        return [f"{config.FILE}: scope_types is a mapping of type id -> {{en, fr, children}}"]
    errors = []
    for tid, spec in given.items():
        where = f"{config.FILE}: scope_types {tid}"
        if not TYPE_ID.match(str(tid)):
            errors.append(f"{where}: a type id is lowercase letters, digits and '-', starting with a letter")
        if not isinstance(spec, dict):
            errors.append(f"{where}: a mapping of {', '.join(sorted(TYPE_KEYS))}")
            continue
        for lang in LANGS:
            if lang in spec and not (isinstance(spec[lang], str) and spec[lang].strip()):
                errors.append(f"{where}: {lang} is a label")
        kids = spec.get("children")
        if kids is not None and not (isinstance(kids, list) and all(isinstance(k, str) for k in kids)):
            errors.append(f"{where}: children is a list of type ids")
        else:
            errors += [f"{where}: children names the unknown type {k!r}" for k in kids or [] if k not in tree.types]
        unknown = sorted(set(map(str, spec)) - TYPE_KEYS)
        if unknown:
            errors += schema.tolerate(f"{where}: unknown key(s) {', '.join(unknown)} (known: "
                                      f"{', '.join(sorted(TYPE_KEYS))})")
    return errors


def _file_errors(data: dict, f: Path, tree: Tree) -> list[str]:
    errors = []
    v = data.get("v")
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        errors.append(f"{f.name}: v is a whole number")
    else:
        newer = schema.newer(f.name, v, 1)
        errors += [newer] if newer else []
    unknown = sorted(set(map(str, data)) - {"v", "scopes"})
    if unknown:
        errors += schema.tolerate(f"{f.name}: unknown key(s) {', '.join(unknown)} (known: v, scopes)")
    declared = data.get("scopes")
    if declared is None:
        return errors
    if not isinstance(declared, dict):
        return errors + [f"{f.name}: scopes is a mapping of id -> {{type, title, parent, status, ...}}"]
    for nid, spec in declared.items():
        nid = str(nid)
        where = f"scope {nid}"
        if nid == GLOBAL:
            errors.append(f"{where}: global is the root, the brain itself: it is never declared")
            continue
        if not ID.match(nid):
            errors.append(f"{where}: an id is lowercase letters, digits and '-' (kebab-case)")
        node = tree.nodes.get(nid)
        if node is not None and node.kind != "container":
            errors.append(f"{where}: {nid} is a project of the registry too: an id is unique across projects and "
                          "containers (a project is never declared in scopes.yaml; give it parent: in projects.yaml)")
            continue
        if not isinstance(spec, dict):
            errors.append(f"{where}: a mapping with type, title, parent, status")
            continue
        unknown = sorted(set(map(str, spec)) - NODE_KEYS - RESERVED)
        if unknown:
            errors += schema.tolerate(f"{where}: unknown key(s) {', '.join(unknown)} (known: "
                                      f"{', '.join(sorted(NODE_KEYS | RESERVED))})")
        t = spec.get("type")
        if not isinstance(t, str) or not t:
            errors.append(f"{where}: a container declares its type (brain scopes --types lists them)")
        elif t not in tree.types:
            errors.append(f"{where}: unknown type {t!r} (known: {', '.join(tree.types)}; config.json scope_types "
                          "adds one)")
        elif t == "tenant":
            errors.append(f"{where}: a tenant is another brain, mounted by a tenant: entry of projects.yaml, never "
                          "a container")
        for key in ("title", "parent"):
            if key in spec and not (isinstance(spec[key], str) and spec[key]):
                errors.append(f"{where}: {key} is a string")
        if "status" in spec and spec["status"] not in STATUSES:
            errors.append(f"{where}: status is active or archived, not {spec['status']!r}")
        also = spec.get("also_under")
        if also is not None:
            if not (isinstance(also, list) and all(isinstance(a, str) for a in also)):
                errors.append(f"{where}: also_under is a list of node ids (shortcuts, for display only)")
            else:
                for a in also:
                    if a == nid or a == (spec.get("parent") or GLOBAL):
                        errors.append(f"{where}: also_under {a!r} is the node itself or its parent")
                    elif a != GLOBAL and a not in tree.nodes:
                        errors.append(f"{where}: also_under names {a!r}, no node")
    return errors


def _accepts(tree: Tree, n: Node, where: str) -> list[str]:
    """The parent's type accepts ``n``'s type when the catalogue constrains its children."""
    parent = tree.nodes[n.parent]
    kids = (tree.types.get(parent.type) or {}).get("children")
    if isinstance(kids, list) and n.type and n.type in tree.types and n.type not in kids:
        return [f"{where}: a {n.type} under {parent.id}, whose type {parent.type} accepts {', '.join(kids) or 'none'} "
                "(config.json scope_types children)"]
    return []


def floors(tree: Tree, nid: str) -> list[tuple[str, str]]:
    """(node, class) of every class floor along ``nid``'s chain, ``nid`` first then up."""
    out = []
    for x in [nid, *tree.chain(nid)]:
        node = tree.nodes.get(x)
        classes = node.data.get("classes") if node is not None else None
        if isinstance(classes, dict) and classes.get("floor") is not None:
            out.append((x, classes["floor"]))
    return out


def floor(tree: Tree, nid: str) -> tuple[str, str]:
    """(the strictest class floor along ``nid``'s chain, itself included, and the node that sets it), ('', '')."""
    from .classes import CLASSES, RANK
    best, where = "", ""
    for x, cls in floors(tree, nid):
        if cls in CLASSES and (not best or RANK[cls] > RANK[best]):
            best, where = cls, x
    return best, where


def _floor_errors(tree: Tree) -> list[str]:
    from .classes import CLASSES, RANK
    errors = []
    for n in tree.nodes.values():
        if n.kind != "container":
            continue
        cls = n.data.get("classes")
        if cls is None:
            continue
        if not isinstance(cls, dict) or set(map(str, cls)) - {"floor"}:
            errors.append(f"scope {n.id}: classes is {{floor: <class>}}")
            continue
        mine = cls.get("floor")
        if mine not in CLASSES:
            errors.append(f"scope {n.id}: classes.floor is one of {', '.join(CLASSES)}, not {mine!r}")
            continue
        above = [(x, c) for x, c in floors(tree, n.id)[1:] if c in CLASSES and RANK[c] > RANK[mine]]
        if above:
            x, c = above[0]
            errors.append(f"scope {n.id}: its class floor {mine} is under {c}, the floor {x} sets above it: a guard "
                          "only tightens going down (remove it, or raise it)")
    return errors


# --- a reference resolved, the projects it selects ---

def resolve(tree: Tree, ref: str, here: str = "") -> str:
    """The node id ``ref`` names: an id, a path of ids (``pro/acme``), ``global`` (or ``/``), ``.`` (``here``, the
    project of the folder) or ``..`` (its parent). ScopeError when it names none."""
    ref = (ref or "").strip()
    if ref in (GLOBAL, "/", ""):
        return GLOBAL
    if ref in (".", ".."):
        if not here or here not in tree.nodes:
            raise ScopeError(f"--scope {ref}: no registered project here (run it from a project's checkout, or name "
                             "a node)")
        return here if ref == "." else tree.nodes[here].parent
    if "/" in ref:
        parts = [p for p in ref.strip("/").split("/") if p]
        node = GLOBAL
        for part in parts[1:] if parts and parts[0] == GLOBAL else parts:
            if part not in tree.children(node):
                raise ScopeError(f"--scope {ref}: {part!r} is not a child of {node} (brain scopes shows the tree)")
            node = part
        return node
    if ref not in tree.nodes:
        raise ScopeError(f"--scope {ref}: no node of that id (brain scopes shows the tree; known: "
                         f"{', '.join(sorted(tree.nodes)) or 'none'})")
    return ref


def select(ref: str, root: Path | None = None, here: str = "") -> tuple[str, list[str]]:
    """(the node ``ref`` names, the registered projects of its subtree that the brain loads, depth first): what
    ``--scope`` hands a view. A read-only project and a tenant mount are left out (no command reads into them)."""
    tree = load(root)
    nid = resolve(tree, ref, here)
    loaded = projects.load(root)
    if nid == GLOBAL:
        return nid, list(loaded)
    return nid, [x for x in tree.projects_under(nid) if x in loaded]


# --- the views: brain scopes, notes/scopes_graph.md ---

def describe(tree: Tree, lang: str = "en", archived: bool = False) -> dict:
    """The tree with stable keys: what brain scopes --json prints."""
    def one(nid: str) -> dict:
        n = tree.nodes[nid]
        return {"id": nid, "kind": n.kind, "type": n.type, "label": tree.label(n.type, lang), "title": n.title,
                "parent": n.parent, "path": tree.path(nid), "depth": tree.depth(nid), "status": n.status,
                "children": tree.children(nid, archived),
                "projects": len([x for x in tree.projects_under(nid) if x != nid]),
                "also_under": list(n.data.get("also_under") or []) if n.kind == "container" else []}
    ids = tree.subtree(GLOBAL, archived)
    return {"present": tree.present, "file": str(tree.file) if tree.file else None,
            "global": {"children": tree.children(GLOBAL, archived), "projects": len(tree.projects_under(GLOBAL))},
            "nodes": [one(x) for x in ids],
            "types": {k: {lang_: v.get(lang_, "") for lang_ in LANGS} for k, v in tree.types.items()}}


def render(tree: Tree, lang: str = "en", archived: bool = False, depth: int | None = None,
           top: str = GLOBAL) -> list[str]:
    """The tree in text from ``top`` (Global by default): each node's id, title, type label and the projects under
    it, ``depth`` levels down; a shortcut (also_under) is shown with an arrow, for display only."""
    if top == GLOBAL:
        count = len(tree.projects_under(GLOBAL))
        out = [f"Global ({count} project{'s' if count != 1 else ''})"]
    else:
        out = [f"{tree.path(top)}: " + _line(tree, top, lang, False)]
    shortcuts: dict[str, list[str]] = {}
    for n in tree.nodes.values():
        for a in (n.data.get("also_under") or []) if n.kind == "container" else []:
            if isinstance(a, str):
                shortcuts.setdefault(a, []).append(n.id)

    def walk(nid: str, prefix: str, level: int) -> None:
        kids = tree.children(nid, archived)
        links = [x for x in shortcuts.get(nid, []) if x in tree.nodes]
        rows = [(k, False) for k in kids] + [(x, True) for x in links]
        for i, (kid, link) in enumerate(rows):
            last = i == len(rows) - 1
            out.append(prefix + ("└─ " if last else "├─ ") + _line(tree, kid, lang, link))
            if not link and (depth is None or level < depth):
                walk(kid, prefix + ("   " if last else "│  "), level + 1)

    if depth is None or depth > 0:
        walk(top, "", 1)
    if not tree.present:
        out.append(f"(no scope tree: every project sits under Global; {FILE} declares the containers, parent: in "
                   "projects.yaml places a project)")
    return out


def _line(tree: Tree, nid: str, lang: str, link: bool) -> str:
    n = tree.nodes[nid]
    bits = [nid]
    if n.kind == "container" and n.title and n.title != nid:
        bits.append(f"« {n.title} »")
    what = tree.label(n.type, lang) if n.type else "?"
    what += {"read": ", read only", "mount": ", mount"}.get(n.kind, "")
    bits.append(f"({what})")
    under = len([x for x in tree.projects_under(nid) if x != nid])
    if under:
        bits.append(f"{under} project{'s' if under != 1 else ''}")
    if n.status == "archived":
        bits.append("archived")
    if link:
        bits = ["↪", nid, f"(shortcut; its place is {tree.path(nid)})"]
    return " ".join(bits)


def view_text(tree: Tree, lang: str = "en") -> str:
    """notes/scopes_graph.md: the tree and the types in use, generated by brain sync, never edited by hand."""
    used = sorted({n.type for n in tree.nodes.values() if n.type})
    lines = ["# Scope tree", "",
             f"Generated by `brain sync` from `{tree.file.name if tree.file else FILE}` and the registry's `parent:` "
             "keys (wi-brain-scope-tree); do not edit. `brain scopes` prints it, `--scope <id>` selects a subtree.",
             "", "```text", *render(tree, lang, archived=True), "```", "",
             "| Type | Label (en) | Label (fr) | Nodes |", "|---|---|---|---|"]
    for t in used:
        spec = tree.types.get(t) or {}
        lines.append(f"| `{t}` | {spec.get('en', '')} | {spec.get('fr', '')} | "
                     f"{sum(1 for n in tree.nodes.values() if n.type == t)} |")
    return "\n".join(lines) + "\n"


def view_file(cfg: config.Config) -> Path:
    return cfg.root / VIEW


def view_applies(root: Path, cfg: config.Config | None = None) -> bool:
    """brain sync keeps notes/scopes_graph.md at a brain's own root (its config.json's folder), once a tree is
    declared: a brain without one gets no view."""
    cfg = cfg or config.load(root)
    if cfg.file is None or os.path.normcase(str(cfg.root.resolve())) != os.path.normcase(str(Path(root).resolve())):
        return False
    return load(root, cfg).present


def write_view(root: Path, cfg: config.Config | None = None) -> bool:
    """Write notes/scopes_graph.md; True when it changed."""
    cfg = cfg or config.load(root)
    f = view_file(cfg)
    text = view_text(load(root, cfg))
    if f.is_file() and f.read_text(encoding="utf-8").replace("\r\n", "\n") == text:
        return False
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8", newline="\n")
    return True


def view_stale(root: Path, cfg: config.Config | None = None) -> bool:
    cfg = cfg or config.load(root)
    f = view_file(cfg)
    return not f.is_file() or f.read_text(encoding="utf-8").replace("\r\n", "\n") != view_text(load(root, cfg))
