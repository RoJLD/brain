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

An entry with ``access: read`` is a project the brain **reads and never writes** (another repo's own sessions write
it): it holds ``title`` and ``access`` only (``parent`` joins them with wi-brain-scope-tree), the shape of a mount, so
no root, store, ledger, guard or rendered rule reaches into it. :func:`load` never returns one, :func:`get` refuses one
(every ``--project``), :func:`readonly` lists them, and ``brain projects``, ``brain status --all`` and the registry's
check count them. ``access: write`` is the default, the brain writing the project by PR; any other value is an error,
and the entry is not loaded until it is one (the key narrows: a typo never opens a way in). A brain older than the one
that knows the key reads such an entry as a full project, so it lands in a registry only once every machine runs it.

**Projects that share a root.** The first project registered at a root owns it; each next one gets
``Project.shares_root_with`` (the owner's name). It spans no repo by default, and the brain runs only its stores'
passes for it: the root's own (the records and their view, the decision queue, the rendered files, the links and
FEATURES.md, the public gate, the hygiene line) stay the owner's. It declares its own stores, journal and decision log
(the defaults are the owner's files), none of them held by a project registered at the root before it, its decision
logs inside the root; until it does, it is not loaded (:func:`get` says why, :func:`check` lists it), so no command
writes the owner's files through it. Each store's board and roadmap (and its module map) sit in its parent folder,
research_graph covering the project's decision logs from its first store only; the first store of a project that owns
its root keeps research_graph's defaults (notes/, notes/decisions.md), so nothing changes for it (:func:`views_dir`,
:func:`layout`). A store whose views folder an earlier store at its root uses is not synced (:func:`view_clashes`).
``--store`` names a store of the project that lists it (:func:`lister`), so it runs with that project's layout.

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
    "access": "write (the default: the brain writes the project, by PR) or read (it reads the project and never "
              "writes it: an entry of title and access only, which no command loads, names or writes into)",
}
ACCESS = ("write", "read")
READ_ONLY_KEYS = {"title", "access"}
# the decision logs research_graph covers for a store given none (research_graph.validate.DEFAULT_DECISIONS; not
# imported: a guard reads this module on every call)
GRAPH_DECISIONS = ("notes/scientific_decisions.md", "notes/decisions.md")
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
    shares_root_with: str = ""       # the project registered first at this root, which owns it ('': this one does)


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
class ReadOnly:
    """A project the brain reads and never writes: its name and title; nothing else is declared."""
    name: str
    title: str = ""


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


def is_read_only(entry) -> bool:
    """A project the brain reads and never writes: ``access: read``, and only that value (a typo is
    :func:`bad_access`, never a deliberate read-only project)."""
    return isinstance(entry, dict) and entry.get("access") == "read"


def bad_access(entry) -> bool:
    """An entry whose ``access`` is neither read nor write: invalid, reported as such (check(), :func:`unloaded`, the
    neutral source), never loaded (the key narrows: a typo never opens a way in) and never shown as read only."""
    return isinstance(entry, dict) and "access" in entry and entry["access"] not in ACCESS


def invalid_access(root: Path | None = None) -> dict[str, object]:
    """{name: its access value} of the entries whose access is neither read nor write, in the registry's order."""
    return {str(name): entry["access"] for name, entry in raw(root).items()
            if not is_mount(entry) and bad_access(entry)}


def _skipped(entry) -> bool:
    """An entry the registry's walk never loads: a tenant mount, a read-only project, an invalid access."""
    return is_mount(entry) or is_read_only(entry) or bad_access(entry)


def load(root: Path | None = None) -> dict[str, Project]:
    """The registered projects; a tenant mount and a read-only project are not, so no command that walks them reads
    into the one or writes into the other. A project registered at a root another one holds (registered before it)
    shares it: ``shares_root_with`` names that owner; it is loaded only once it declares its own files
    (:func:`_claims`). An owner skipped for its access value still holds its root (:func:`_claimant`)."""
    return _load(root)[0]


def refused(root: Path | None = None) -> dict[str, list[str]]:
    """{a project at a shared root that is not loaded: why (:func:`_claims`)}, in the registry's order."""
    return {name: why for name, (_, why) in _load(root)[1].items()}


#: The keys of an entry that name a local path a guard protects (its root, production checkouts and repos).
GUARDED_PATH_KEYS = ("root", "production", "repos")


def guarded(root: Path | None = None) -> list[Project]:
    """Every project a guard protects (brain.guards, brain.governor): the loaded ones, those at a shared root that
    are not loaded yet, and every entry the walk skips as read only (``access: read``) or as invalid (an access value
    check() refuses, :func:`bad_access`) that still names a local path. A refusal to load never lifts a guard: a typo
    in ``access``, or ``access: read`` added to a project that has a production checkout, keeps its checkouts refused
    to edits while brain check is red. A valid read-only entry (title and access only) names no path, so it adds nothing."""
    loaded, refused = _load(root)
    out = list(loaded.values()) + [p for p, _ in refused.values()]
    f = registry_file(root)
    for name, entry in raw(root).items():
        if is_mount(entry) or not _skipped(entry) or not any(k in entry for k in GUARDED_PATH_KEYS):
            continue
        try:
            out.append(_project(str(name), entry, _resolve_root(str(entry.get("root") or "."), f.parent)))
        except (TypeError, ValueError):   # a malformed path value: check() names it; the other entries stay guarded
            continue
    return out


def _load(root: Path | None = None) -> tuple[dict[str, Project], dict[str, tuple[Project, list[str]]]]:
    """(the projects loaded, {a project at a shared root not loaded: (it, why)}), in the registry's order."""
    f = registry_file(root)
    out: dict[str, Project] = {}
    refused: dict[str, tuple[Project, list[str]]] = {}
    owners: dict[str, str] = {}
    held: dict[str, dict[str, tuple[str, str]]] = {}   # root -> normalised path -> (the project that holds it, kind)
    for name, entry in raw(root).items():
        skipped = _skipped(entry)
        p = _claimant(str(name), entry, f.parent) if skipped else None
        if skipped and p is None:
            continue
        entry = entry if isinstance(entry, dict) else {}
        p = p or _project(str(name), entry, _resolve_root(str(entry.get("root") or "."), f.parent))
        owner = owners.setdefault(_norm(p.root), p.name)
        p.shares_root_with = "" if owner == p.name else owner
        files = held.setdefault(_norm(p.root), {})
        why = _claims(p, entry, files) if p.shares_root_with and not skipped else []
        if why:
            refused[p.name] = (p, why)
            continue
        for kind, paths_ in _files(p).items():
            for x in paths_:
                files.setdefault(_norm(x), (p.name, kind))
        if not skipped:
            out[p.name] = p
    return out, refused


def _claimant(name: str, entry, base: Path) -> Project | None:
    """An entry the walk skips for its access value that still holds its root: an invalid access (a typo), or
    ``access: read`` on an entry that still names its ``root`` (both refused by check()). It is never loaded, yet it
    keeps the root it was registered at and the files it would write there, so the next project at that root stays a
    sharer and never becomes its owner (fail closed: a typo never hands another project the owner's views, records or
    rendered files). None for a tenant mount, a valid read-only entry (no root of its own) or a malformed path."""
    if not isinstance(entry, dict) or is_mount(entry) or not (bad_access(entry) or "root" in entry):
        return None
    try:
        return _project(name, entry, _resolve_root(str(entry.get("root") or "."), base))
    except (TypeError, ValueError):   # a malformed path value: check() names it
        return None


def _withheld(root: Path | None = None) -> list[Project]:
    """The entries the walk skips that still hold a root (:func:`_claimant`), in the registry's order."""
    f = registry_file(root)
    found = ((str(n), e) for n, e in raw(root).items() if _skipped(e))
    return [p for p in (_claimant(n, e, f.parent) for n, e in found) if p is not None]


def stores_of(p: Project) -> list[Path]:
    """The stores brain sync and check run for ``p``: those it lists, else its root's notes/graph (``stores: []``)."""
    return list(p.stores) or [p.root / "notes" / "graph"]


def _files(p: Project) -> dict[str, list[Path]]:
    """The files a project writes at its root, by kind (:func:`stores_of`); its decision logs are those research_graph
    covers for its first store (its defaults when it gets no option: brain.projects.layout)."""
    stores = stores_of(p)
    logs = list(p.decision_logs)
    if uses_defaults(p, stores[0]):
        logs += [p.root / d for d in GRAPH_DECISIONS]
    return {"store": stores, "journal": list(p.journals), "decision log": logs}


def _claims(p: Project, entry: dict, held: dict[str, tuple[str, str]]) -> list[str]:
    """Why ``p``, at a root a project registered before it owns, cannot be loaded: a store, journal or decision log
    it does not declare (the defaults are the owner's), or a file a project registered there before it holds, of any
    kind (a journal that is the owner's decision log), or a decision log outside the root (a decision's anchor is a
    path inside it)."""
    owner = p.shares_root_with
    errors = []
    for key, kind in (("stores", "store"), ("journal", "journal"), ("decisions", "decision log")):
        if not _paths(entry.get(key)):
            errors.append(f"project {p.name}: shares its root with {owner}: it declares no {kind} of its own (the "
                          f"default is {owner}'s: give it {key}:)")
    if errors:
        return errors
    for key, kind in (("stores", "store"), ("journal", "journal"), ("decisions", "decision log")):
        for x in _files(p)[kind]:
            holder, theirs = held.get(_norm(x), ("", ""))
            if holder:
                what = "too" if theirs == kind else f"{theirs}"
                errors.append(f"project {p.name}: shares its root with {owner}: its {kind} {_rel(x, p.root)} is "
                              f"{holder}'s {what} (give it its own: {key}:)")
    errors += [f"project {p.name}: its decision log {_rel(d, p.root)} is outside its root (a decision's anchor is a "
               "path inside it)" for d in p.decision_logs if not _inside(d, p.root)]
    return errors


def _inside(path: Path, root: Path) -> bool:
    return Path(os.path.normpath(path)).is_relative_to(Path(os.path.normpath(root)))


def readonly(root: Path | None = None) -> dict[str, ReadOnly]:
    """The projects the brain reads and never writes, in the registry's order: each one's name and title. Only
    ``access: read``: another value is a typo that check() names, never a deliberate read-only project."""
    out = {}
    for name, entry in raw(root).items():
        if is_read_only(entry):
            title = entry.get("title")
            out[str(name)] = ReadOnly(str(name), title if isinstance(title, str) else "")
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


def unloaded(name: str, root: Path | None = None) -> str:
    """Why ``name``, an entry of the registry, is not a loaded project: a tenant mount, a project the brain reads only,
    a project at a shared root that does not declare its own files; '' for any other name. :func:`get` says it, and
    so do the commands that resolve --project themselves (brain audit, its --diff)."""
    entry = raw(root).get(name)
    if is_mount(entry):
        return (f"{name!r} is a tenant mount: another brain, opaque, that the operator does not read into (its state "
                "comes from its contract export)")
    if bad_access(entry):   # a typo, named as one: brain check --all refuses it the same way
        return f"{name!r} is not loaded: access is read or write, not {entry['access']!r}"
    if is_read_only(entry):
        return f"{name!r} is read only: the brain reads it and never writes it"
    refused = _load(root)[1].get(name)
    return f"{name!r} is not loaded: {'; '.join(refused[1])}" if refused else ""


def get(name: str, root: Path | None = None) -> Project:
    """A registered project; with ``root`` (``--root``, say a worktree), the same layout at that root."""
    reg = load(root)
    if name not in reg:
        why = unloaded(name, root)
        if why:
            raise SystemExit(f"brain: {why}")
        where = registry_file(root)
        raise SystemExit(f"brain: unknown project {name!r} (registry {where or 'not found'}; known: "
                         f"{', '.join(reg) or 'none'})")
    if root is None:
        return reg[name]
    p = _project(name, raw(root).get(name) or {}, root)
    p.shares_root_with = reg[name].shares_root_with
    return p


def at_root(root: Path) -> list[Project]:
    """The registered projects at ``root``, its owner first; a worktree of a registered checkout gets them at the
    worktree. [] when none is registered there."""
    root = root.resolve()
    reg = load(root)
    here = [p for p in reg.values() if _norm(p.root) == _norm(root)]
    if here:
        return here
    main = paths.main_checkout(root)
    if main and _norm(main.resolve()) != _norm(root):
        return [get(p.name, root) for p in reg.values() if _norm(p.root) == _norm(main.resolve())]
    return []


def lister(store: Path, root: Path) -> Project | None:
    """The project registered at ``root`` (at its main checkout, for a worktree) that lists ``store``, else None:
    ``--store`` naming the store of a project that shares the root runs as that project, with its layout. Fail
    closed at a root several projects share: the store of one that is not loaded (one at a shared root without its
    own files, or an owner skipped for its access value, :func:`_claimant`) is refused with the reason
    (:func:`unloaded`), and a store none lists is refused too, never run as the owner with its defaults (the board,
    roadmap and decision stubs of the owner would be written with another store's items)."""
    key = _norm(store)
    here = at_root(root)
    hit = next((p for p in here if any(_norm(s) == key for s in stores_of(p))), None)
    if hit:
        return hit
    base = root.resolve()
    main = paths.main_checkout(base)
    homes = {_norm(base)} | ({_norm(main.resolve())} if main else set())
    refused = [p for p in [p for p, _ in _load(root)[1].values()] + _withheld(root) if _norm(p.root) in homes]
    for p in refused:
        if any(_norm(s) == key for s in stores_of(p)):
            raise SystemExit(f"brain: {unloaded(p.name, root)}")
    if len(here) + len(refused) > 1:
        raise SystemExit(f"brain: --store {store}: no registered project lists it, at a root {len(here) + len(refused)} "
                         "projects share; name one with --project")
    return None


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
    """The registered project whose root is ``root``, the first registered there when several share it (it owns the
    root), else one with the default layout named after the folder."""
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
    root alone by default; none for a project that shares its root, whose repo is its owner's). A relative path is
    read from the root, else from its main checkout (a worktree)."""
    if not isinstance(p.repos, list):
        raise RepoError(f"project {p.name}: repos is a list of paths or mappings")
    _check_audit(p)
    prod = {_norm(_resolve_root(os.path.relpath(x, p.root), p.root)) for x in p.production}
    declared = p.repos or ([] if p.shares_root_with else ["."])
    decl = list(declared)
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
            if i < len(declared):
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


def _check_read_only(where: str, entry: dict) -> list[str]:
    """A read-only project holds title and access only: a root, a store, a ledger or a guard's list would be a way to
    write or read into it."""
    errors = []
    extra = sorted(set(map(str, entry)) - READ_ONLY_KEYS)
    if extra:
        errors.append(f"{where}: a read-only project holds title and access only, not {', '.join(extra)} (each is a "
                      "way to write or read into it)")
    if "title" in entry and not isinstance(entry["title"], str):
        errors.append(f"{where}: title is a string")
    return errors


def view_clashes(projs: list[Project]) -> dict[tuple[str, str], str]:
    """The stores whose views folder (:func:`views_dir`) a store registered before them at the same root uses: brain
    sync would write one's board over the other's. {(project, the store relative to its root): what to say}."""
    out = {}
    taken: dict[str, dict[str, tuple[str, Path]]] = {}
    for p in projs:
        views = taken.setdefault(_norm(p.root), {})
        for store in stores_of(p):
            folder = views_dir(p, store)
            other, theirs = views.setdefault(_norm(folder), (p.name, store))
            if (other, _norm(theirs)) != (p.name, _norm(store)):
                out[(p.name, _rel(store, p.root))] = (
                    f"project {p.name}: its store {_rel(store, p.root)} writes its views in {_rel(folder, p.root)}, "
                    f"as {other}'s store {_rel(theirs, p.root)} does (give each store a folder of its own)")
    return out


def check(root: Path | None = None) -> list[str]:
    """What is wrong in the registry: an entry that is not a mapping, an unknown key, a value of the wrong shape, a bad
    repos: or audit: entry, a shared id without its reason, a tenant mount that holds more than its title and export,
    an access that is not read or write, a read-only project that holds more than its title, a store listed twice, a
    project at a shared root that is not loaded (:func:`_claims`), two stores that write their views in one folder.
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
        if bad_access(entry):
            errors.append(f"{where}: access is read or write, not {entry['access']!r}")   # not loaded until it is one
            continue
        if is_read_only(entry):
            errors += _check_read_only(where, entry)
            continue
        unknown = sorted(set(map(str, entry)) - set(KEYS))
        if unknown:   # read mode: a newer brain's key, noted and kept; strict (CI): an error
            errors += schema.tolerate(f"{where}: unknown key(s) {', '.join(unknown)} (brain projects --keys lists them)")
        errors += [f"{where}: {k} is a string" for k in ("root", "title") if k in entry
                   and not isinstance(entry[k], str)]
        errors += [f"{where}: {k} is a path or a list of paths" for k in ("stores", "journal", "decisions",
                                                                         "production") if k in entry
                   and not _is_paths(entry[k])]
        listed: set[str] = set()
        for s in _paths(entry.get("stores")):
            if _norm(Path(s)) in listed:
                errors.append(f"{where}: its store {s} is listed twice")
            listed.add(_norm(Path(s)))
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
    loaded, refused = _load(root)
    for _, why in refused.values():
        errors += why
    for p in loaded.values():
        try:
            repos_of(p)
        except RepoError as exc:
            errors.append(str(exc))
    return errors + list(view_clashes(list(loaded.values())).values())


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


# --- where a store's generated views go, and research_graph's options for it ---

def _later(p: Project, store: Path) -> bool:
    """A store the project lists after its first (a store it does not list, given by --store, is not one; nor is its
    first listed again, which check() refuses)."""
    return bool(p.stores) and _norm(store) != _norm(p.stores[0]) and any(_norm(store) == _norm(s)
                                                                         for s in p.stores[1:])


def uses_defaults(p: Project, store: Path) -> bool:
    """Whether research_graph runs on ``store`` with its defaults (notes/ for the views, notes/decisions.md and
    notes/scientific_decisions.md for the logs): a store of a project that owns its root, but one it lists after its
    first."""
    return not p.shares_root_with and not _later(p, store)


def views_dir(p: Project, store: Path) -> Path:
    """The folder of a store's board and roadmap (and its module map): ``notes/`` when research_graph keeps its
    defaults (:func:`uses_defaults`); else the store's parent folder (``ops/graph`` -> ``ops``)."""
    return p.root / "notes" if uses_defaults(p, store) else store.parent


def layout(p: Project, store: Path) -> list[str]:
    """research_graph's options for a store of ``p``, given before its subcommand: none when it keeps its defaults
    (nothing changes for it); else ``--views`` (:func:`views_dir`) and the decision logs it covers: the project's own
    (a project that shares its root), none from a store listed after the first."""
    if uses_defaults(p, store):
        return []
    out = ["--views", _rel(views_dir(p, store), p.root)]
    if _later(p, store):
        return out + ["--no-decisions"]
    return out + [a for d in p.decision_logs for a in ("--decisions", _rel(d, p.root))]


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
            "stacks": stacks, "shared_ids": sorted(map(str, p.shared_ids)), "plugin": p.plugin, "access": "write",
            "shares_root_with": p.shares_root_with}


def describe_read_only(r: ReadOnly) -> dict:
    """A read-only project as brain projects prints it: nothing but its name, title and access."""
    return {"name": r.name, "title": r.title, "access": "read"}
