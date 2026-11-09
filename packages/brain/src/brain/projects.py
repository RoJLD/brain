"""The projects the brain command knows (``brain --project NAME``, ``brain <view> --all``, ``brain projects``): the
registry ``projects.yaml`` at the Brain repo's root, or the file ``$BRAIN_PROJECTS`` names (wi-brain-project-views,
spec 2026-10-30 §3.14).

One entry per project, its paths relative to the project's root (these are the defaults)::

  quant: {root: ../demo, stores: [notes/graph], journal: notes/journal.md, decisions: notes/decisions.md}

:data:`KEYS` documents every key an entry may hold (``brain projects --keys`` prints them) and :func:`check` refuses
another one (``brain check --all``); loading never fails on them, so a bad entry never stops another command.
``title`` says in one line what the project is. ``journal`` and ``decisions`` take a path or a list: the first is the
one ``brain journal add`` and ``brain adr new`` write, every one is read by the views. ``ledgers`` names the
project's other append-only ledgers (``{name: path}``), whose size and last write ``brain status`` shows.
``shared_ids`` waives an id that a store of this project shares with another store (``{id: reason}``): ids are unique
across every store of every project, checked by :func:`collisions`. ``plugin`` is reserved for the CLI plugin that
will bring the project's own subcommands (wi-brain-command-plugins); no command reads it yet.

``production`` lists the checkouts a service or a scheduled task runs from, relative to the root (no default): the
core plugin's guards refuse tool edits and git changes there (brain.guards). ``stacks`` declares the project's stacks,
inline or as a YAML file relative to the root, for ``brain up / down / health`` (brain.stacks). ``repos`` lists the
repos the project spans, for ``brain audit`` (brain.audit): a path relative to the root, or a mapping ``{path, name,
entry, roots, waive, item, lang, scout_limit}`` (default: the root, plus every production checkout not listed);
``audit: {spec: <id>}`` names the spec the audit's debt items link to. They are read by :func:`repos_of`, which
raises RepoError on a bad entry (exit code 2), so another command never fails on them. ``code_index`` lists
the repos ``brain index`` has GitNexus index, relative to the root (brain.codeindex). ``notify`` declares the
notification channels and the project's routes per level, inline or as a YAML file relative to the root, for ``brain
notify`` (brain.notify). ``alerts`` declares where the project's alerts come from (scheduled tasks, stacks,
alert files, event folders) and their levels, inline or as a YAML file relative to the root, for ``brain alerts`` and
``brain status`` (brain.alerts). ``schedules`` declares the brain commands the machines' schedulers run (the alerts
pass, a daily canary), inline or as a YAML file relative to the root, for ``brain schedule`` and the installer's
schedule step (brain.schedule).

An entry with a ``tenant`` key is a **mount**, not a project: an HMaaS tenant is another brain, with its own root,
registry and keys, mounted opaque in the operator's registry (wi-brain-hmaas-multitenant, spec-brain-hmaas §6;
SCOPE-6). It holds ``title`` and ``tenant`` only, ``{export: <path>}`` naming where the tenant drops its contract
export (relative to ``$BRAIN_HOME``). :func:`load` never returns a mount, so no command reads into it; :func:`get`
refuses one; :func:`mounts` lists them, and ``brain status --all`` counts them without opening anything.

A relative root is read from the registry's folder, else from its main checkout's when the registry sits in a git
worktree (a worktree under a scratchpad has no ``../demo`` beside it). The registry is found through
``$BRAIN_PROJECTS``, else the places of :func:`brain.paths.bases`: ``$CLAUDE_BRAIN_DIR`` (a project's name for the
Brain checkout), ``$BRAIN_PERSONAL``, the repo acted on, the pointer ``<BRAIN_HOME>/personal.json`` (a hook's case:
the plugin runs from a cached copy), then a checkout that still holds this package.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import graph, paths, schema

REGISTRY = "projects.yaml"
DEFAULTS = {"stores": ["notes/graph"], "journal": "notes/journal.md", "decisions": "notes/decisions.md"}
# Every key of a project's entry, with what it holds: brain projects --keys prints them, check() refuses another one.
KEYS = {
    "root": "the project's main checkout, relative to the registry's folder (default: .)",
    "title": "one line saying what the project is, for the views",
    "stores": "its graph stores, relative to the root (default [notes/graph]); brain item writes the first",
    "journal": "its journals: a path or a list (default notes/journal.md); brain journal add writes the first",
    "decisions": "its decision logs (ADR, SDR): a path or a list (default notes/decisions.md); brain adr new writes "
                 "the first",
    "ledgers": "its other append-only ledgers, {name: path relative to the root}; brain status shows their size and "
               "last write",
    "production": "the checkouts a service or a scheduled task runs from, relative to the root; the core plugin's "
                  "guards refuse edits and git changes there (brain.guards)",
    "repos": "the repos it spans, for brain audit: a path or {path, name, entry, roots, waive, item, lang, "
             "scout_limit} (default: the root and the production checkouts)",
    "audit": "{spec: <id>, max_lines: N, complexity: N}: the spec brain audit's debt items link to; brain audit "
             "--diff's structure thresholds (default 1000 lines per code file, cyclomatic complexity 15)",
    "code_index": "the repos brain index has GitNexus index, relative to the root: a path or {path, branch}",
    "stacks": "what brain up / down / health start, stop and check: a mapping, or a YAML file relative to the root",
    "notify": "brain notify's channels and the project's routes per level: a mapping, or a YAML file relative to the "
              "root (brain.notify)",
    "alerts": "where brain alerts reads its alerts: scheduler folders, tasks and their cadences, stacks, alert files, "
              "event folders, levels; a mapping, or a YAML file relative to the root (brain.alerts)",
    "schedules": "the brain commands a machine's scheduler runs, {name: {command, every, at, at_logon, machines, "
                 "timeout, enabled}}: a mapping, or a YAML file relative to the root; installed by brain schedule "
                 "install --apply, the installer's schedule step (brain.schedule)",
    "shared_ids": "ids its stores may share with another store, {id: reason of 15 characters or more}; any other id "
                  "found in two stores fails brain check --all",
    "usage": "the usage governor's caps for this project, {sessions: N, brainstorms: N}: lower than config.json "
             "usage.guard's, never higher (brain.governor)",
    "plugin": "reserved (wi-brain-command-plugins): the CLI plugin that brings its subcommands; no command reads it "
              "yet",
    "tenant": "makes the entry a tenant mount: another brain, opaque, that no command reads into; {export: where the "
              "tenant drops its contract export, relative to BRAIN_HOME}; a mount holds title and tenant only",
}
# What a mount's tenant: mapping may hold (wi-brain-tenant-export reads the export; a mount only says where it lands).
TENANT_KEYS = {"export": "the file the tenant's contract export is dropped into: absolute, ~, or relative to BRAIN_HOME"}
MOUNT_KEYS = {"title", "tenant"}
REPO_KEYS = {"path", "name", "entry", "roots", "waive", "item", "lang", "scout_limit"}
AUDIT_KEYS = {"spec", "max_lines", "complexity"}
REPO_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")
WAIVE_REASON = 15


@dataclass
class Project:
    name: str
    root: Path
    stores: list[Path] = field(default_factory=list)
    journal: Path | None = None      # the journal brain journal add writes: journals[0]
    decisions: Path | None = None    # the log brain adr new writes: decision_logs[0]
    registered: bool = True
    production: list[Path] = field(default_factory=list)
    stacks: dict | str | None = None
    repos: list = field(default_factory=list)    # the repos: entries as declared; parsed by repos_of()
    audit: dict = field(default_factory=dict)
    code_index: list = field(default_factory=list)
    notify: dict | str | None = None
    alerts: dict | str | None = None
    schedules: dict | str | None = None
    title: str = ""
    journals: list[Path] = field(default_factory=list)
    decision_logs: list[Path] = field(default_factory=list)
    ledgers: dict[str, Path] = field(default_factory=dict)
    shared_ids: dict = field(default_factory=dict)
    plugin: object = None            # reserved (wi-brain-command-plugins), kept as declared


@dataclass
class Repo:
    """A repo of a project, as brain audit reads it."""
    name: str
    path: Path
    production: bool = False
    entry: list[str] | None = None        # seeds of the production closure; None: the default (console scripts)
    roots: list[str] | None = None        # package roots; None: discovered
    waive: dict[str, str] = field(default_factory=dict)   # glob -> reason: units left out of the counts
    item: str = ""                        # the item that holds its debt (default wi-debt-<name>)
    lang: str = "py"                      # ts: module checks delegated to the repo's own checker
    scout_limit: int = 3
    folder: str = ""                      # its main checkout's folder name, case kept (a CodeRef's <repo> token)


@dataclass
class Mount:
    """A tenant mounted opaque: its name, its title and where its contract export lands; nothing else is known."""
    name: str
    title: str = ""
    export: Path | None = None


class RepoError(ValueError):
    """A bad repos: or audit: entry in the registry (brain audit exits 2)."""


def registry_file(root: Path | None = None) -> Path | None:
    env = os.environ.get("BRAIN_PROJECTS")
    if env:
        return Path(env).expanduser()
    for base in paths.bases(root):
        if (base / REGISTRY).is_file():
            return base / REGISTRY
    return None


def _paths(value) -> list[str]:
    """A path or a list of paths, as declared; anything else is left out (check() reports it)."""
    value = [value] if isinstance(value, str) else value
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def _project(name: str, entry: dict, root: Path) -> Project:
    e = {**DEFAULTS, **(entry if isinstance(entry, dict) else {})}
    journals = [root / j for j in _paths(e["journal"]) or [DEFAULTS["journal"]]]
    logs = [root / d for d in _paths(e["decisions"]) or [DEFAULTS["decisions"]]]
    ledgers = e.get("ledgers") if isinstance(e.get("ledgers"), dict) else {}
    return Project(name, root, [root / s for s in _paths(e["stores"])], journals[0], logs[0],
                   production=[Path(os.path.normpath(root / p)) for p in _paths(e.get("production"))],
                   stacks=e.get("stacks"), repos=e.get("repos") or [], audit=e.get("audit") or {},
                   code_index=list(e.get("code_index") or []), notify=e.get("notify"), alerts=e.get("alerts"),
                   schedules=e.get("schedules"),
                   title=str(e.get("title") or ""), journals=journals, decision_logs=logs,
                   ledgers={str(k): root / v for k, v in ledgers.items() if isinstance(v, str) and v},
                   shared_ids=dict(e["shared_ids"]) if isinstance(e.get("shared_ids"), dict) else {},
                   plugin=e.get("plugin"))


def _resolve_root(rel: str, base: Path) -> Path:
    p = Path(os.path.expanduser(rel))
    if p.is_absolute():
        return p.resolve()
    here = (base / p).resolve()
    if here.exists():
        return here
    main = paths.main_checkout(base)
    return (main / p).resolve() if main else here


def raw(root: Path | None = None) -> dict:
    """The registry as declared ({} when there is none or it is not a mapping)."""
    f = registry_file(root)
    if not f or not f.is_file():
        return {}
    data = graph.load_yaml(f.read_text(encoding="utf-8")) or {}   # libyaml: a guard reads it on every call
    return data if isinstance(data, dict) else {}


def is_mount(entry) -> bool:
    """A tenant mount: an entry with a ``tenant`` key (another brain, never read into)."""
    return isinstance(entry, dict) and "tenant" in entry


def load(root: Path | None = None) -> dict[str, Project]:
    """The registered projects; a tenant mount is not one, so no command that walks them reads into it."""
    f = registry_file(root)
    out = {}
    for name, entry in raw(root).items():
        if is_mount(entry):
            continue
        entry = entry if isinstance(entry, dict) else {}
        out[str(name)] = _project(str(name), entry, _resolve_root(str(entry.get("root") or "."), f.parent))
    return out


def _export_path(value) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    p = Path(os.path.expanduser(value))
    return p if p.is_absolute() else paths.brain_home() / p


def mounts(root: Path | None = None) -> dict[str, Mount]:
    """The tenant mounts, in the registry's order: each one's title and export file; nothing is read from them."""
    out = {}
    for name, entry in raw(root).items():
        if is_mount(entry):
            tenant = entry["tenant"] if isinstance(entry["tenant"], dict) else {}
            out[str(name)] = Mount(str(name), str(entry.get("title") or ""), _export_path(tenant.get("export")))
    return out


def get(name: str, root: Path | None = None) -> Project:
    """A registered project; with ``root`` (``--root``, say a worktree), the same layout at that root."""
    reg = load(root)
    if name not in reg:
        if is_mount(raw(root).get(name)):
            raise SystemExit(f"brain: {name!r} is a tenant mount: another brain, opaque, that the operator does not "
                             "read into (its state comes from its contract export)")
        where = registry_file(root)
        raise SystemExit(f"brain: unknown project {name!r} (registry {where or 'not found'}; known: "
                         f"{', '.join(reg) or 'none'})")
    if root is None:
        return reg[name]
    return _project(name, raw(root).get(name) or {}, root)


def cwd_worktree(project: Project, cwd: str | Path | None = None) -> Path | None:
    """The git worktree ``cwd`` is in, when it is a linked worktree of the repo ``project``'s root is in (same git
    common dir, not the project's own checkout), else None: a worktree of another repo (a code repo of the project,
    say) or a plain folder is never the project's root."""
    cwd = Path(cwd or os.getcwd())
    try:
        top = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             timeout=5, stdin=subprocess.DEVNULL).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not top:
        return None
    top = Path(top).resolve()
    if top == project.root.resolve():
        return None
    a, b = paths.main_checkout(top), paths.main_checkout(project.root)
    if a is None or b is None or os.path.normcase(str(a.resolve())) != os.path.normcase(str(b.resolve())):
        return None
    return top


def for_root(root: Path) -> Project:
    """The registered project whose root is ``root``, else one with the default layout named after the folder."""
    root = root.resolve()
    for p in load(root).values():
        if p.root == root:
            return p
    p = _project(root.name, {}, root)
    p.registered = False
    return p


def _strings(value, where: str) -> list[str]:
    value = [value] if isinstance(value, str) else value
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise RepoError(f"{where}: a list of strings")
    return list(value)


def _norm(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _repo_folder(path: Path) -> str:
    """The folder name of the repo's main checkout (a worktree's repo keeps its name), its case kept."""
    main = paths.main_checkout(path) if (path / ".git").is_file() else None   # a linked worktree
    return (main or path).name


def _check_audit(p: Project) -> None:
    """audit: {spec, max_lines, complexity}, the thresholds whole numbers of 1 or more."""
    if not isinstance(p.audit, dict) or set(p.audit) - AUDIT_KEYS:
        raise RepoError(f"project {p.name}: audit is a mapping of {', '.join(sorted(AUDIT_KEYS))}")
    for key in ("max_lines", "complexity"):
        v = p.audit.get(key)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 1):
            raise RepoError(f"project {p.name}: audit {key} is a whole number of 1 or more")


def repos_of(p: Project) -> list[Repo]:
    """The repos ``p`` spans, for brain audit: its ``repos:`` entries, then each production checkout not listed (the
    root alone by default). A relative path is read from the root, else from its main checkout (a worktree)."""
    if not isinstance(p.repos, list):
        raise RepoError(f"project {p.name}: repos is a list of paths or mappings")
    _check_audit(p)
    prod = {_norm(_resolve_root(os.path.relpath(x, p.root), p.root)) for x in p.production}
    decl = list(p.repos or ["."])
    decl += [os.path.relpath(x, p.root) for x in p.production]
    out: list[Repo] = []
    seen: set[str] = set()
    for i, entry in enumerate(decl):
        where = f"project {p.name}: repos[{i}]"
        entry = {"path": entry} if isinstance(entry, str) else entry
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise RepoError(f"{where}: a path, or a mapping with a path")
        unknown = set(entry) - REPO_KEYS
        if unknown:   # read mode: a newer brain's key is kept and passed over (projects.check notes it)
            for message in schema.tolerate(f"{where}: unknown key(s) {', '.join(sorted(unknown))} "
                                           f"(known: {', '.join(sorted(REPO_KEYS))})", notes=[]):
                raise RepoError(message)
        path = _resolve_root(entry["path"], p.root)
        if _norm(path) in seen:
            if i < len(p.repos or ["."]):
                raise RepoError(f"{where}: {entry['path']} is listed twice")
            continue
        seen.add(_norm(path))
        folder = _repo_folder(path)
        name = str(entry.get("name") or folder).lower()
        if not REPO_NAME.fullmatch(name):
            raise RepoError(f"{where}: a name is lowercase letters, digits, '.', '_' and '-' ({name!r})")
        waive = entry.get("waive") or {}
        if not isinstance(waive, dict):
            raise RepoError(f"{where}: waive is a mapping of glob -> reason")
        for glob, reason in waive.items():
            if not isinstance(reason, str) or len(reason.strip()) < WAIVE_REASON:
                raise RepoError(f"{where}: waive {glob!r}: a reason of {WAIVE_REASON} characters at least")
        lang = str(entry.get("lang", "py"))
        if lang not in ("py", "ts"):
            raise RepoError(f"{where}: lang is py or ts")
        limit = entry.get("scout_limit", 3)
        if not isinstance(limit, int) or limit < 0:
            raise RepoError(f"{where}: scout_limit is a whole number")
        out.append(Repo(name, path, _norm(path) in prod,
                        _strings(entry["entry"], f"{where} entry") if entry.get("entry") is not None else None,
                        _strings(entry["roots"], f"{where} roots") if entry.get("roots") is not None else None,
                        {str(k): str(v) for k, v in waive.items()}, str(entry.get("item") or ""), lang, limit,
                        folder))
    names = [r.name for r in out]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise RepoError(f"project {p.name}: repo name(s) used twice: {', '.join(dup)} (give a name:)")
    return out


# --- the registry checked, ids across stores, a project described ---

def _is_paths(value) -> bool:
    value = [value] if isinstance(value, str) else value
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def _check_mount(where: str, entry: dict) -> list[str]:
    """A mount holds title and tenant only: a root, a store or a ledger would be a way to read into another brain."""
    errors = []
    extra = sorted(set(map(str, entry)) - MOUNT_KEYS)
    if extra:
        errors.append(f"{where}: a tenant mount is opaque and holds title and tenant only, not {', '.join(extra)} "
                      "(the operator never reads into another brain)")
    if "title" in entry and not isinstance(entry["title"], str):
        errors.append(f"{where}: title is a string")
    tenant = entry["tenant"]
    if not isinstance(tenant, dict):
        return errors + [f"{where}: tenant is a mapping ({{}} when nothing is declared)"]
    unknown = sorted(set(map(str, tenant)) - set(TENANT_KEYS))
    if unknown:
        errors.append(f"{where}: tenant: unknown key(s) {', '.join(unknown)} (known: {', '.join(TENANT_KEYS)})")
    if "export" in tenant and _export_path(tenant["export"]) is None:
        errors.append(f"{where}: tenant.export is a path")
    return errors


def check(root: Path | None = None) -> list[str]:
    """What is wrong in the registry: an entry that is not a mapping, an unknown key, a value of the wrong shape, a bad
    repos: or audit: entry, a shared id without its reason, a tenant mount that holds more than its title and export.
    Stacks and code_index entries are checked by their own loaders (brain.stacks, brain.codeindex)."""
    errors = []
    for name, entry in raw(root).items():
        where = f"project {name}"
        if entry is None:
            continue
        if not isinstance(entry, dict):
            errors.append(f"{where}: an entry is a mapping (brain projects --keys)")
            continue
        if is_mount(entry):
            errors += _check_mount(f"tenant {name}", entry)
            continue
        unknown = sorted(set(map(str, entry)) - set(KEYS))
        if unknown:   # read mode: a newer brain's key, noted and kept; strict (CI): an error
            errors += schema.tolerate(f"{where}: unknown key(s) {', '.join(unknown)} (brain projects --keys lists them)")
        errors += [f"{where}: {k} is a string" for k in ("root", "title") if k in entry
                   and not isinstance(entry[k], str)]
        errors += [f"{where}: {k} is a path or a list of paths" for k in ("stores", "journal", "decisions",
                                                                         "production") if k in entry
                   and not _is_paths(entry[k])]
        ledgers = entry.get("ledgers")
        if ledgers is not None and not (isinstance(ledgers, dict) and _is_paths(list(ledgers.values()))):
            errors.append(f"{where}: ledgers is a mapping of name -> path")
        shared = entry.get("shared_ids")
        if shared is not None and not isinstance(shared, dict):
            errors.append(f"{where}: shared_ids is a mapping of id -> reason")
        for nid, reason in (shared if isinstance(shared, dict) else {}).items():
            if not isinstance(reason, str) or len(reason.strip()) < WAIVE_REASON:
                errors.append(f"{where}: shared_ids {nid!r}: a reason of {WAIVE_REASON} characters at least")
        if not isinstance(entry.get("code_index") or [], list):
            errors.append(f"{where}: code_index is a list of paths or {{path, branch}}")
        errors += [f"{where}: {k} is a mapping or a file name" for k in ("stacks", "notify", "alerts", "schedules")
                   if not isinstance(entry.get(k) or {}, (dict, str))]
        from .governor import project_limits
        errors += [f"{where}: {e}" for e in project_limits(entry)[1]]
    for p in load(root).values():
        try:
            repos_of(p)
        except RepoError as exc:
            errors.append(str(exc))
    return errors


def node_ids(store: Path) -> dict[str, str]:
    """The ids of a store's nodes, generated ones included, each with the name of the file that holds it."""
    out: dict[str, str] = {}
    for f in sorted((store / "nodes").glob("*.yaml")):
        data = graph.load_yaml_file(f)
        for n in data if isinstance(data, list) else []:
            if isinstance(n, dict) and n.get("id"):
                out.setdefault(str(n["id"]), f.name)
    return out


def collisions(projs: list[Project]) -> dict:
    """The ids found in more than one store of these projects (research_graph check sees one store at a time):
    {stores: the number read, collisions: [{id, where: [project:store/nodes/file], waived: reason or ''}], stale:
    [project: id waived but no longer shared]}. A store two entries name (a worktree's registry) is read once."""
    seen: dict[str, list[tuple[str, str]]] = {}
    read: set[str] = set()
    for p in projs:
        for store in p.stores:
            key = _norm(store.resolve())
            if key in read or not (store / "nodes").is_dir():
                continue
            read.add(key)
            rel = store.relative_to(p.root).as_posix() if store.is_relative_to(p.root) else store.as_posix()
            for nid, fname in node_ids(store).items():
                seen.setdefault(nid, []).append((p.name, f"{p.name}:{rel}/nodes/{fname}"))
    shared = {nid: where for nid, where in seen.items() if len(where) > 1}
    out = []
    for nid, where in sorted(shared.items()):
        names = {n for n, _ in where}
        reason = next((f"{p.name}: {p.shared_ids[nid]}" for p in projs if p.name in names and nid in p.shared_ids), "")
        out.append({"id": nid, "where": [w for _, w in where], "waived": reason})
    stale = sorted(f"{p.name}: {nid}" for p in projs for nid in p.shared_ids if nid not in shared)
    return {"stores": len(read), "collisions": out, "stale": stale}


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else path.as_posix()


def describe(p: Project) -> dict:
    """A project's entry, resolved, with stable keys: what brain projects prints and the views read."""
    try:
        repos = [r.name for r in repos_of(p)]
    except RepoError as exc:
        repos = [f"error: {exc}"]
    stacks = sorted(map(str, p.stacks)) if isinstance(p.stacks, dict) else ([p.stacks] if p.stacks else [])
    return {"name": p.name, "title": p.title, "root": str(p.root), "found": p.root.is_dir(),
            "stores": [_rel(s, p.root) for s in p.stores], "journals": [_rel(j, p.root) for j in p.journals],
            "decisions": [_rel(d, p.root) for d in p.decision_logs],
            "ledgers": {k: _rel(v, p.root) for k, v in p.ledgers.items()},
            "production": [os.path.relpath(x, p.root).replace(os.sep, "/") for x in p.production],
            "repos": repos,
            "code_index": [e if isinstance(e, str) else str((e or {}).get("path")) for e in p.code_index],
            "stacks": stacks, "shared_ids": sorted(map(str, p.shared_ids)), "plugin": p.plugin}
