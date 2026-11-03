"""Data classes per store (wi-brain-data-classes; docs/specs/2026-11-02-vault-heirs-identity-brainstorm.md §3.1).

Every store of a personal brain declares its class in ``config.json`` (``classes.stores``), and the class says where
the store may go and how. The engine holds the classes and their matrix (:data:`POLICY`: a class by an exit gives
``clear``, ``sealed``, ``opt-in`` or ``never``); the personal brain holds the stores::

    "classes": {"stores": {
        "memory": {"class": "confidential", "paths": ["memory/**"], "to": ["devices", "cloud-model"],
                   "waive": {"git-private": "in clear in the private remote until the encrypted-git trial decides"}},
        "ledger": {"class": "sealed", "paths": ["$BRAIN_HOME/ledger"], "to": ["offsite", "backup"]},
        "repo":   {"class": "private", "paths": ["**"]}}}

A path is a glob over the brain repo's tracked files (``**`` any folders, ``*`` within a name), or a machine path
outside the repo: ``$BRAIN_HOME/...`` or ``~/...``. The first store whose glob matches a tracked file classes it,
in the order of the file, so specific stores come first and a catch-all last.

:func:`check` (``brain classes --check``, ``brain check --all``) refuses:

- a store without a valid class, an unknown exit, a waiver without its reason (15 characters or more);
- a tracked file that no store classes, and an engine store (:data:`KNOWN`: the ledgers, the sessions, the
  transcripts...) that no store declares: a store without a class;
- a destination its class forbids: an exit in ``to`` the class says ``never`` for, and the git reality: tracked
  files whose class does not allow the repo's remote in clear (``git-private``, or ``git-public`` when the remote is
  one of ``public.repos``);
- a class under the floor of its project's scope chain (``classes: {floor: ...}`` on the nodes of ``scopes.yaml``,
  spec-brain-scope-tree §3.9). Until the scope tree's registry exists, :func:`scope_chain` reads it when present and
  finds no floor otherwise.

A waiver (``waive: {exit: reason}``) keeps a known gap visible: ``brain classes`` and the check print it, it is never
silent. :func:`decide` is what an exit's adapter asks before a store leaves (the session archive, the data remote,
a notes service): ``clear``, ``sealed`` (only through ``brain vault seal``) or ``never``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import boundary, config, graph, paths, projects

CLASSES = ("public", "private", "confidential", "sealed", "resident", "secret")
TENANT = "tenant:"                      # tenant:<id>, a hosted team's store: sealed to its own recipients only
TENANT_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
RANK = {c: i for i, c in enumerate(CLASSES)}   # the floor's order; a tenant's store ranks as confidential

CLASS_TEXT = {
    "public": "free to publish once brain check --public passes: the engine, domain templates",
    "private": "the private repo in clear; off the machine otherwise only sealed: rules, graph, ADRs, specs",
    "confidential": "never in clear in git or with a third party: decisions touching money or people, memory, "
                    "heirs and members, a scope tree that names employers",
    "sealed": "never in git; off the machine only sealed client-side: transcripts, ledgers, session states, "
              "datasets, indexes, backups",
    "resident": "never leaves the machine, even sealed: data under a residency clause",
    "secret": "never in the brain: key values, tokens, passwords and key shares live in a keystore",
    "tenant": "a hosted team's store (tenant:<id>): its own private repo, sealed to its own recipients only",
}

EXITS = {
    "git-public": "a public git repo",
    "git-private": "the private repo's remote (a forge, GitHub)",
    "offsite": "a copy outside git that leaves the machine: a NAS, a data remote, a dataset host, an archive",
    "backup": "the backups",
    "devices": "the owner's other devices: a second machine, a phone's sync",
    "third-party": "a third-party notes or documents service",
    "cloud-model": "a cloud model's context",
    "local-model": "a local model's context",
}
HOW = ("clear", "sealed", "opt-in", "never")

# How each class may reach each exit: clear (as it is), sealed (only sealed client-side, brain vault seal), opt-in
# (only when the store names the exit in its ``to``), never.
_ROW = {
    "public":       ("clear", "clear", "clear", "clear", "clear", "clear", "clear", "clear"),
    "private":      ("never", "clear", "sealed", "sealed", "clear", "opt-in", "clear", "clear"),
    "confidential": ("never", "sealed", "sealed", "sealed", "clear", "never", "opt-in", "clear"),
    "sealed":       ("never", "never", "sealed", "sealed", "sealed", "never", "never", "opt-in"),
    "resident":     ("never", "never", "never", "never", "never", "never", "never", "clear"),
    "secret":       ("never", "never", "never", "never", "never", "never", "never", "never"),
    "tenant":       ("never", "clear", "sealed", "sealed", "never", "never", "opt-in", "clear"),
}
POLICY = {c: dict(zip(EXITS, row)) for c, row in _ROW.items()}

# The engine's own stores outside the repo: each must be covered by a declared store (a store without a class).
KNOWN = {
    "ledger": ("$BRAIN_HOME/ledger", "sealed"),
    "sessions": ("$BRAIN_HOME/sessions", "sealed"),
    "resume": ("$BRAIN_HOME/resume", "sealed"),
    "digest": ("$BRAIN_HOME/digest", "sealed"),
    "vault": ("$BRAIN_HOME/vault", "sealed"),
    "transcripts": ("~/.claude/projects", "sealed"),
}
TRANSCRIPTS = "~/.claude/projects"      # read under $CLAUDE_CONFIG_DIR when it is set (brain.paths.projects_dir)
STORE_KEYS = {"class", "paths", "to", "waive", "project", "why"}
REASON_MIN = 15
SEALED_SUFFIXES = (".age", ".gpg")      # a tracked file that is already sealed is not in clear
PLACEHOLDERS = (".gitkeep", ".keep")    # an empty one keeps a folder in git: no data, so never in clear
SCOPES = "scopes.yaml"


class ClassError(ValueError):
    """A bad classes block (brain classes exits 2)."""


@dataclass
class Store:
    name: str
    cls: str
    globs: list[str] = field(default_factory=list)      # over the repo's tracked files
    machine: list[str] = field(default_factory=list)    # $BRAIN_HOME/... or ~/..., as declared
    to: list[str] = field(default_factory=list)
    waive: dict[str, str] = field(default_factory=dict)
    project: str = ""
    why: str = ""
    regexes: list = field(default_factory=list, repr=False)

    @property
    def kind(self) -> str:
        """The class's row in :data:`POLICY`: tenant for tenant:<id>."""
        return "tenant" if self.cls.startswith(TENANT) else self.cls

    @property
    def rank(self) -> int:
        return RANK["confidential"] if self.kind == "tenant" else RANK[self.cls]


def class_ok(cls) -> bool:
    if not isinstance(cls, str):
        return False
    if cls.startswith(TENANT):
        return bool(TENANT_ID.match(cls[len(TENANT):]))
    return cls in CLASSES


def how(cls: str, exit_: str) -> str:
    """The matrix: clear, sealed, opt-in or never for a class and an exit."""
    return POLICY["tenant" if cls.startswith(TENANT) else cls][exit_]


def is_machine(path: str) -> bool:
    return path.startswith(("$BRAIN_HOME", "~"))


def expand(path: str) -> Path:
    """A machine path: $BRAIN_HOME/... under brain_home(), ~/... under the home folder (~/.claude/projects/... under
    $CLAUDE_CONFIG_DIR when the variable is set)."""
    if path.rstrip("/") == "$BRAIN_HOME":
        return paths.brain_home()
    if path.startswith("$BRAIN_HOME/"):
        return paths.brain_home() / path[len("$BRAIN_HOME/"):]
    if path.rstrip("/") == TRANSCRIPTS or path.startswith(TRANSCRIPTS + "/"):
        return paths.projects_dir() / path[len(TRANSCRIPTS) + 1:]
    return Path(path).expanduser()


def stores(cfg: config.Config) -> tuple[list[Store], list[str]]:
    """The declared stores in their order, and what is wrong in their shape."""
    block = cfg.data.get("classes")
    if block is None:
        return [], []
    errors: list[str] = []
    if not isinstance(block, dict) or not isinstance(block.get("stores"), dict):
        return [], ["classes: a mapping with stores: {name: {class, paths, to, waive}}"]
    out = []
    for name, d in block["stores"].items():
        where = f"classes.stores.{name}"
        if not isinstance(d, dict):
            errors.append(f"{where}: a mapping with class and paths")
            continue
        unknown = set(d) - STORE_KEYS
        if unknown:
            errors.append(f"{where}: unknown key(s) {', '.join(sorted(unknown))} (known: {', '.join(sorted(STORE_KEYS))})")
        cls = d.get("class")
        if not class_ok(cls):
            errors.append(f"{where}: class {cls!r} is not one of {', '.join(CLASSES)} or {TENANT}<id>")
            continue
        globs = d.get("paths")
        if not isinstance(globs, list) or not globs or not all(isinstance(g, str) and g for g in globs):
            errors.append(f"{where}: paths is a non-empty list of globs or machine paths")
            continue
        to = d.get("to") or []
        if not isinstance(to, list) or any(t not in EXITS for t in to):
            errors.append(f"{where}: to names exits among {', '.join(EXITS)}")
            to = [t for t in to if t in EXITS] if isinstance(to, list) else []
        waive = d.get("waive") or {}
        if not isinstance(waive, dict):
            errors.append(f"{where}: waive is {{exit: reason}}")
            waive = {}
        for exit_, reason in waive.items():
            if exit_ not in EXITS:
                errors.append(f"{where}: waive names an unknown exit {exit_!r}")
            elif not isinstance(reason, str) or len(reason.strip()) < REASON_MIN:
                errors.append(f"{where}: waive.{exit_} needs its reason ({REASON_MIN} characters or more)")
        s = Store(name, cls, [g for g in globs if not is_machine(g)], [g for g in globs if is_machine(g)],
                  list(to), {k: str(v) for k, v in waive.items() if k in EXITS}, str(d.get("project") or ""),
                  str(d.get("why") or ""))
        s.regexes = [boundary.glob_regex(g.rstrip("/")) for g in s.globs]
        out.append(s)
    return out, errors


def classify(declared: list[Store], files: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """({store: [tracked files]}, [files no store classes]): the first store whose glob matches wins."""
    by: dict[str, list[str]] = {s.name: [] for s in declared}
    orphans = []
    for f in files:
        for s in declared:
            if any(r.match(f) for r in s.regexes):
                by[s.name].append(f)
                break
        else:
            orphans.append(f)
    return by, orphans


def store_of(declared: list[Store], path: str) -> Store | None:
    """The store that classes a repo path (/-separated, relative) or a machine path ($BRAIN_HOME/..., ~/...)."""
    if is_machine(path):
        target = expand(path)
        for s in declared:
            for m in s.machine:
                base = expand(m)
                if target == base or base in target.parents:
                    return s
        return None
    for s in declared:
        if any(r.match(path) for r in s.regexes):
            return s
    return None


def tracked(root: Path) -> list[str]:
    try:
        return boundary.tracked(root)
    except (boundary.BoundaryError, OSError, subprocess.SubprocessError):
        return []


def remote_exit(root: Path, cfg: config.Config) -> str:
    """git-public when the repo's origin is one of public.repos, git-private when it has another remote, '' when it
    pushes nowhere."""
    try:
        out = subprocess.run(["git", "-C", str(root), "remote", "-v"], capture_output=True, text=True,
                             timeout=10, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    urls = {line.split()[1] for line in out.splitlines() if len(line.split()) >= 2}
    if not urls:
        return ""
    pub = cfg.data.get("public") if isinstance(cfg.data.get("public"), dict) else {}
    for repo in pub.get("repos") or []:
        name = str(repo).lower()
        if any(re.search(rf"[:/]{re.escape(name)}(?:\.git)?/?$", u.lower()) for u in urls):
            return "git-public"
    return "git-private"


# --- the scope tree (spec-brain-scope-tree §3.9, §3.13): read when present ---
def scopes_file(cfg: config.Config) -> Path | None:
    """$BRAIN_SCOPES, else config.json's scopes, else scopes.yaml beside the registry; None when there is none."""
    env = os.environ.get("BRAIN_SCOPES")
    if env:
        f = Path(env).expanduser()
    elif isinstance(cfg.data.get("scopes"), str):
        f = cfg.root / cfg.data["scopes"]
    else:
        f = cfg.root / SCOPES
    return f if f.is_file() else None


def scope_nodes(cfg: config.Config) -> dict[str, dict]:
    """{node id: its mapping} from scopes.yaml (``scopes:``), {} when there is no tree yet."""
    f = scopes_file(cfg)
    if not f:
        return {}
    data = graph.load_yaml_file(f) or {}
    nodes = data.get("scopes") if isinstance(data, dict) else None
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in nodes.items()} if isinstance(nodes, dict) else {}


def own_project(cfg: config.Config) -> str:
    """The registry's project whose root is the brain's root (the brain's own stores belong to it), else ''."""
    try:
        for name, p in projects.load(cfg.root).items():
            if p.root.resolve() == cfg.root.resolve():
                return name
    except Exception:  # noqa: BLE001 - a broken registry is projects.check's to report
        return ""
    return ""


def scope_chain(cfg: config.Config, project: str, nodes: dict[str, dict] | None = None) -> list[str]:
    """The node ids above a project, nearest first, up to (not including) global: its ``parent:`` in the registry,
    then each node's ``parent``. [] without a tree or a parent."""
    nodes = scope_nodes(cfg) if nodes is None else nodes
    if not nodes or not project:
        return []
    try:
        entry = projects.raw(cfg.root).get(project) or {}
    except Exception:  # noqa: BLE001
        entry = {}
    node = entry.get("parent") if isinstance(entry, dict) else None
    chain: list[str] = []
    while isinstance(node, str) and node and node != "global" and node not in chain:
        chain.append(node)
        node = (nodes.get(node) or {}).get("parent")
    return chain


def floor(cfg: config.Config, project: str, nodes: dict[str, dict] | None = None) -> tuple[str, str]:
    """(the strictest class floor along the project's scope chain, the node that sets it), ('', '') without one."""
    nodes = scope_nodes(cfg) if nodes is None else nodes
    best, where = "", ""
    for node in scope_chain(cfg, project, nodes):
        f = ((nodes.get(node) or {}).get("classes") or {}).get("floor")
        if f in CLASSES and (not best or RANK[f] > RANK[best]):
            best, where = f, node
    return best, where


@dataclass
class Report:
    stores: list[Store]
    errors: list[str] = field(default_factory=list)
    waived: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    files: dict[str, list[str]] = field(default_factory=dict)
    remote: str = ""
    declared: bool = False


def check(root: Path | None = None, cfg: config.Config | None = None) -> Report:
    """Every store has a class and goes only where its class allows; see the module's docstring."""
    cfg = cfg or config.load(root)
    declared, errors = stores(cfg)
    rep = Report(declared, errors, declared="classes" in cfg.data)
    if cfg.file is None:
        rep.notes.append("no config.json: no class declared")
        return rep
    if not rep.declared:
        rep.errors.append(f"{config.FILE} declares no data classes (classes.stores): every store needs one "
                          "(brain classes --suggest prints a starting set)")
        return rep
    files = tracked(cfg.root)
    rep.files, orphans = classify(declared, files)
    if orphans:
        rep.errors.append(f"{len(orphans)} tracked file(s) have no class (no store's glob matches): "
                          + ", ".join(orphans[:5]) + (" ..." if len(orphans) > 5 else ""))
    for name, (path, suggested) in KNOWN.items():
        if not store_of(declared, path):
            rep.errors.append(f"the engine's store {name} ({path}) has no class (declare it; suggested: {suggested})")
    rep.remote = remote_exit(cfg.root, cfg)
    by_name = {s.name: s for s in declared}
    for s in declared:
        for exit_ in s.to:
            if how(s.cls, exit_) == "never":
                _refuse(rep, s, exit_, f"store {s.name} ({s.cls}) declares {exit_}, which its class forbids")
        clear = [f for f in rep.files.get(s.name, []) if not f.endswith(SEALED_SUFFIXES)
                 and not placeholder(cfg.root, f)]
        if clear and rep.remote and how(s.cls, rep.remote) not in ("clear",):
            allowed = how(s.cls, rep.remote)
            _refuse(rep, s, rep.remote,
                    f"store {s.name} ({s.cls}): {len(clear)} tracked file(s) go to {rep.remote} in clear, which its "
                    + ("class forbids" if allowed == "never" else f"class allows {allowed} only"),
                    " (untrack them, seal them, or waive it with its reason)")
    _floors(cfg, rep, by_name)
    return rep


def placeholder(root: Path, path: str) -> bool:
    """An empty .gitkeep (or .keep) that only keeps a folder in git: it holds no data, whatever the folder's class."""
    f = root / path
    return f.name in PLACEHOLDERS and f.is_file() and f.stat().st_size == 0


def _refuse(rep: Report, s: Store, exit_: str, line: str, advice: str = "") -> None:
    if exit_ in s.waive:
        rep.waived.append(f"{line}; reason: {s.waive[exit_]}")
    else:
        rep.errors.append(line + advice)


def _floors(cfg: config.Config, rep: Report, by_name: dict[str, Store]) -> None:
    nodes = scope_nodes(cfg)
    if not nodes:
        rep.notes.append("no scope tree (scopes.yaml): no class floor to check")
        return
    own = own_project(cfg)
    for s in by_name.values():
        fl, node = floor(cfg, s.project or own, nodes)
        if fl and s.rank < RANK[fl]:
            rep.errors.append(f"store {s.name} ({s.cls}) is under the floor {fl} that scope {node} sets for "
                              f"project {s.project or own}")


def decide(cfg: config.Config, store: str, exit_: str) -> str:
    """What an exit's adapter may do with a store: clear, sealed or never (opt-in resolved by the store's ``to``,
    a waiver counting as the owner's explicit yes). Unknown store or exit: never."""
    declared, _ = stores(cfg)
    s = next((x for x in declared if x.name == store), None)
    if s is None or exit_ not in EXITS:
        return "never"
    h = how(s.cls, exit_)
    if h == "opt-in":
        return "clear" if exit_ in s.to or exit_ in s.waive else "never"
    if h != "clear" and exit_ in s.waive:
        return "clear"
    return h


def suggest(cfg: config.Config) -> dict:
    """A starting classes block: the engine's machine stores, the brain's own folders by their usual class, and a
    catch-all; brain classes --suggest prints it to edit, never writes it."""
    root = cfg.root
    folders = {"memory": "confidential", "records/ddr": "confidential", "notes": "private", "docs": "private",
               "records": "private"}
    out: dict = {}
    for rel, cls in folders.items():
        if (root / rel).is_dir():
            out[rel.replace("/", "-")] = {"class": cls, "paths": [f"{rel}/**"]}
    for name, (path, cls) in KNOWN.items():
        out[name] = {"class": cls, "paths": [path], "to": ["offsite", "backup"]}
    out["repo"] = {"class": "private", "paths": ["**"]}
    return {"stores": out}


def matrix() -> list[str]:
    """The class by exit matrix as text lines."""
    w = max(len(c) for c in POLICY)
    head = " " * (w + 2) + "  ".join(f"{e:<11}" for e in EXITS)
    rows = [f"{c:<{w}}  " + "  ".join(f"{POLICY[c][e]:<11}" for e in EXITS) for c in POLICY]
    return [head, *rows]


def render(rep: Report) -> list[str]:
    lines = []
    for s in rep.stores:
        where = ([f"{len(rep.files.get(s.name, []))} tracked"] if s.globs else []) + s.machine
        exits = ", ".join(f"{e}:{how(s.cls, e)}" for e in s.to) or "-"
        lines.append(f"{s.name:<14} {s.cls:<13} {'; '.join(where):<34} to {exits}"
                     + (f"  waived: {', '.join(s.waive)}" if s.waive else ""))
    if rep.remote:
        lines.append(f"remote: {rep.remote}")
    lines += [f"note: {n}" for n in rep.notes]
    lines += [f"waived: {w}" for w in rep.waived]
    lines += [f"error: {e}" for e in rep.errors]
    lines.append(f"classes: {len(rep.stores)} store(s), " + (f"{len(rep.errors)} error(s)" if rep.errors else "OK")
                 + (f", {len(rep.waived)} waived" if rep.waived else ""))
    return lines


def as_dict(rep: Report) -> dict:
    return {"stores": [{"name": s.name, "class": s.cls, "paths": s.globs + s.machine, "tracked": len(rep.files.get(
        s.name, [])), "to": {e: how(s.cls, e) for e in s.to}, "waive": s.waive, "project": s.project}
        for s in rep.stores], "remote": rep.remote, "errors": rep.errors, "waived": rep.waived, "notes": rep.notes}


def main(root: Path | None, *, check_only: bool = False, as_json: bool = False, which: list[str] | None = None,
         suggest_: bool = False, matrix_: bool = False) -> int:
    """``brain classes``: the stores and their classes (exit 1 on an error), ``PATH...`` the store of each path,
    ``--suggest`` a starting block, ``--matrix`` the class by exit matrix."""
    cfg = config.load(root)
    if matrix_:
        print("\n".join(matrix()))
        return 0
    if suggest_:
        print(json.dumps({"classes": suggest(cfg)}, indent=2))
        return 0
    if which:
        declared, errs = stores(cfg)
        for e in errs:
            print(f"error: {e}")
        for p in which:
            s = store_of(declared, p)
            print(f"{p}: " + (f"{s.name} ({s.cls})" if s else "no store: no class"))
        return 1 if errs else 0
    rep = check(root, cfg)
    if as_json:
        print(json.dumps(as_dict(rep), indent=2))
    elif check_only:
        for line in [f"waived: {w}" for w in rep.waived] + [f"error: {e}" for e in rep.errors]:
            print(line)
        print(f"classes: {len(rep.stores)} store(s), " + (f"{len(rep.errors)} error(s)" if rep.errors else "OK"))
    else:
        print("\n".join(render(rep)))
    return 1 if rep.errors else 0
